"""P6a 评测集基础设施的领域模型、错误类型与访问权限判定。

口径见 `docs/superpowers/specs/2026-09-16-self-evolution-p6-design.md` §2.2/§2.3（A2 裁决：
P6a = 评测集基础设施与采集器；**零生产行为变更**——候选生成 / 指针灰度 / 回滚属 P6b，不在本模块）。

设计要点：
- **用例**（`workbench_eval_cases`）：状态机 `draft → published → archived`（any → archived；
  不物理删；已发布用例的变更走 `supersede` 软链到新条目）。
- **运行**（`workbench_eval_runs`）与**逐例结果**（`workbench_eval_case_results`）：只落判定与计数，
  **不落正文**；`suite_digest` = 当次评测所用用例集指纹（事后可验证「到底考了什么」）。
- **发布闸门**：期望（expectation）必须是**可执行**的（受评对象已注册 + 输入形状可消费），
  否则一律拒绝——不得把空用例放行成「默认为通过」。
- 权限：评测集与评测运行的**全部操作仅 `super_admin`**（规格 §2.5；读接口同样收紧，最小权限）。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Mapping, Sequence
from uuid import uuid4

from ..audit.redaction import key_tokens
from ..domain import PolicyError, UserContext

# 标识与体积上限（服务端校验；沿用 P4 skill_key 风格的小写稳定标识）。
MAX_SUITE_KEY_LENGTH = 64
MAX_CASE_ID_LENGTH = 64
SUITE_KEY_PATTERN = r"^[a-z0-9][a-z0-9._-]{0,63}$"
CASE_ID_PATTERN = r"^[a-z0-9][a-z0-9._-]{0,63}$"
# 输入快照：dict、可 JSON 序列化、UTF-8 字节 ≤ 16 KiB、**不得含敏感键**（任意层级）。
MAX_SNAPSHOT_BYTES = 16 * 1024
# 期望：受控键集（probe / expect），体积 ≤ 2 KiB。
MAX_EXPECTATION_BYTES = 2 * 1024
# 期望的判定取值（受评对象返回的结论枚举）。
EXPECTATION_VERDICTS = ("pass", "blocked")
EXPECTATION_KEYS = frozenset({"probe", "expect"})


class EvalCaseSource(StrEnum):
    """用例来源（规格 §2.3：三种来源）。"""

    RUN_TRACE = "run_trace"      # 真实运行轨迹（采集器生成草稿，期望由专家补全）
    MANUAL = "manual"            # 人工专家编写
    REGRESSION = "regression"    # 回归锁定基线（只增不减，永不回退）


class EvalCaseStatus(StrEnum):
    """用例状态机（规格 §2.3：draft → published → archived）。"""

    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class EvalRunStatus(StrEnum):
    """评测运行状态：completed = 正常完成；aborted = fail-closed 中止（如费用超限）。"""

    COMPLETED = "completed"
    ABORTED = "aborted"


class EvalError(ValueError):
    """评测域失败基类；接口层按子类映射到 4xx。"""


class InvalidEvalCase(EvalError):
    """用例 / 期望 / 快照校验不通过，或运行参数非法 → 422。"""


class EvalSuiteTooLarge(InvalidEvalCase):
    """单次运行的用例数超出上限 → 422（显式失败，不静默截断）。"""


class EvalCaseStateConflict(EvalError):
    """状态机冲突（对 archived 发布、非草稿补全期望等）→ 409。"""


class EvalSuiteEmpty(EvalError):
    """套件没有已发布用例 → 422（fail-closed，不默认为通过）。"""


class UnknownEvalSubject(EvalError):
    """受评对象未注册 → 422。"""


class EvalCostExceeded(EvalError):
    """评测费用超出配置上限 → 422（fail-closed 中止并留痕）。"""


class EvalDisabled(EvalError):
    """自进化评测组件未启用（`WORKBENCH_EVOLUTION_ENABLED=false`）→ 503。"""


class EvalCaseNotFound(LookupError):
    """用例 / 运行不存在或跨租户 → 404（不泄露存在性，沿用记忆层口径）。"""


def now() -> datetime:
    return datetime.now(UTC)


def new_case_id() -> str:
    return f"case-{uuid4().hex[:16]}"


def new_eval_run_id() -> str:
    return f"eval-{uuid4().hex[:16]}"


@dataclass(frozen=True)
class EvalCase:
    """评测用例（`workbench_eval_cases` 一行）。"""

    tenant_id: str
    case_id: str
    suite_key: str
    source: EvalCaseSource
    status: EvalCaseStatus
    input_snapshot: dict
    input_digest: str
    created_by: str
    expectation: dict = field(default_factory=dict)
    superseded_by: str | None = None
    created_at: datetime | None = field(default_factory=now)
    updated_at: datetime | None = field(default_factory=now)


@dataclass(frozen=True)
class EvalRun:
    """评测运行（`workbench_eval_runs` 一行；只落计数与指纹，不落正文）。"""

    tenant_id: str
    eval_run_id: str
    subject: str
    suite_key: str
    suite_digest: str
    case_count: int
    pass_count: int
    cost_cents: int
    status: EvalRunStatus
    created_by: str
    created_at: datetime | None = field(default_factory=now)


@dataclass(frozen=True)
class EvalCaseResult:
    """逐例结果（`workbench_eval_case_results` 一行；detail 只放判定与计数）。"""

    tenant_id: str
    eval_run_id: str
    case_id: str
    passed: bool
    detail: dict = field(default_factory=dict)
    created_at: datetime | None = field(default_factory=now)


@dataclass(frozen=True)
class CaseSpec:
    """待登记用例（导入 / 采集共用；`case_id=None` 时服务端生成）。"""

    suite_key: str
    source: EvalCaseSource
    input_snapshot: dict
    expectation: dict | None = None
    case_id: str | None = None


# ------------------------------------------------------------ 访问权限（跨层共用）


def can_manage(context: UserContext) -> bool:
    """是否可管理评测集与评测运行（规格 §2.5：仅超级管理员）。"""
    return context.role == "super_admin"


def ensure_can_manage(context: UserContext) -> None:
    if not can_manage(context):
        raise PolicyError("只有超级管理员可以管理评测集与评测运行")


# ------------------------------------------------------------ 输入归一化与指纹


def normalize_suite_key(value: str) -> str:
    """归一套件键；非法（空 / 大写 / 超长 / 非 ASCII 字符集）抛 422。"""
    if not isinstance(value, str):
        raise InvalidEvalCase("suite_key 必须是字符串")
    normalized = value.strip().lower()
    if not normalized:
        raise InvalidEvalCase("suite_key 不能为空")
    if len(normalized) > MAX_SUITE_KEY_LENGTH or not _matches(SUITE_KEY_PATTERN, normalized):
        raise InvalidEvalCase(
            "suite_key 只能含小写字母、数字、点、下划线与短横线，且以字母或数字开头（最长 64）"
        )
    return normalized


def normalize_case_id(value: str) -> str:
    if not isinstance(value, str):
        raise InvalidEvalCase("case_id 必须是字符串")
    normalized = value.strip().lower()
    if not normalized or len(normalized) > MAX_CASE_ID_LENGTH or not _matches(CASE_ID_PATTERN, normalized):
        raise InvalidEvalCase("case_id 只能含小写字母、数字、点、下划线与短横线，且以字母或数字开头（最长 64）")
    return normalized


def _matches(pattern: str, value: str) -> bool:
    import re

    return re.match(pattern, value) is not None


def normalize_source(value: str | EvalCaseSource) -> EvalCaseSource:
    try:
        return EvalCaseSource(value)
    except ValueError as exc:
        raise InvalidEvalCase(f"source 只能是 {' / '.join(s.value for s in EvalCaseSource)}") from exc


def normalize_case_status(value: str | EvalCaseStatus) -> EvalCaseStatus:
    try:
        return EvalCaseStatus(value)
    except ValueError as exc:
        raise InvalidEvalCase(f"status 只能是 {' / '.join(s.value for s in EvalCaseStatus)}") from exc


def normalize_snapshot(value: Mapping | object) -> dict:
    """归一输入快照（fail-closed）。

    - 必须是 dict（不接受字符串 / 数组 / 标量）；
    - 可 JSON 序列化；UTF-8 字节 ≤ `MAX_SNAPSHOT_BYTES`；
    - **任何层级出现敏感键一律拒绝**——快照不得成为第二份密钥副本。
    """
    if not isinstance(value, dict):
        raise InvalidEvalCase("input_snapshot 必须是对象（dict）")
    if _has_sensitive_snapshot_key(value):
        raise InvalidEvalCase("input_snapshot 不得包含敏感键（如 api_key / token / password）")
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise InvalidEvalCase(f"input_snapshot 必须是可 JSON 序列化的对象：{exc}") from exc
    if len(encoded.encode("utf-8")) > MAX_SNAPSHOT_BYTES:
        raise InvalidEvalCase(f"input_snapshot 超过体积上限（{MAX_SNAPSHOT_BYTES} 字节）")
    return value


# 快照敏感键判定：沿用审计层的词元口径，但**不把泛化的 `key` 词元一律视为敏感**
# （`tool_key` / `agent_key` / `role_key` 等受控标识必须可用）；仅当 `key` 带限定前缀
# （api_/access_/secret_/...）或键名就是裸 `key` 时判敏感。
_SENSITIVE_TOKENS = frozenset(
    {"password", "passwd", "pwd", "token", "secret", "cookie", "authorization", "credential", "bearer", "session"}
)
_QUALIFIED_KEY_PREFIXES = frozenset(
    {"api", "access", "secret", "private", "signing", "encryption", "master", "auth"}
)


def _has_sensitive_snapshot_key(value: object) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            tokens = key_tokens(key)
            if tokens & _SENSITIVE_TOKENS:
                return True
            if "key" in tokens and (tokens & _QUALIFIED_KEY_PREFIXES or tokens == {"key"}):
                return True
            if _has_sensitive_snapshot_key(item):
                return True
        return False
    if isinstance(value, list):
        return any(_has_sensitive_snapshot_key(item) for item in value)
    return False


def compute_input_digest(snapshot: Mapping) -> str:
    """快照指纹（规范 JSON 派生；用于去重与套件指纹）。"""
    encoded = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def normalize_expectation(value: object, *, supported_probes: frozenset[str]) -> dict:
    """归一期望（fail-closed）。

    v1 形状：``{"probe": <受评对象名>, "expect": "pass"|"blocked"}``；
    键集**恰好**为 probe/expect（多余键一律拒），probe 必须已注册。
    """
    if not isinstance(value, dict):
        raise InvalidEvalCase("expectation 必须是对象")
    if set(value) != EXPECTATION_KEYS:
        raise InvalidEvalCase("expectation 只能包含 probe 与 expect 两个字段")
    probe = value.get("probe")
    if not isinstance(probe, str) or probe not in supported_probes:
        raise InvalidEvalCase(f"expectation.probe 必须是已注册的受评对象（当前：{sorted(supported_probes)}）")
    expect = value.get("expect")
    if expect not in EXPECTATION_VERDICTS:
        raise InvalidEvalCase(f"expectation.expect 只能是 {' / '.join(EXPECTATION_VERDICTS)}")
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > MAX_EXPECTATION_BYTES:
        raise InvalidEvalCase(f"expectation 超过体积上限（{MAX_EXPECTATION_BYTES} 字节）")
    return {"probe": probe, "expect": expect}


def expectation_digest(expectation: Mapping) -> str:
    encoded = json.dumps(expectation, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def compute_suite_digest(cases: Sequence[EvalCase]) -> str:
    """用例集指纹 = 对 (case_id, 快照指纹, 期望指纹) 排序后派生。

    语义：**当次评测到底考了哪些题、题目是什么**——换题（增删改用例）必然改变指纹；
    同题面重复运行指纹稳定（顺序无关）。
    """
    parts = sorted(
        f"{case.case_id}:{case.input_digest}:{expectation_digest(case.expectation)}" for case in cases
    )
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()