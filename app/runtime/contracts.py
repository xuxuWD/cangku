from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol

from ..audit.redaction import key_tokens


READ_KIND = "read"
SIDE_EFFECT_KINDS = frozenset({"write", "external_send", "publish", "delete", "permission"})
ALLOWED_PLAN_KINDS = SIDE_EFFECT_KINDS | {READ_KIND}


class RuntimeEventType(StrEnum):
    PLAN_CREATED = "plan.created"
    STEP_STARTED = "step.started"
    TOOL_CALL = "tool.call"
    TOOL_RESULT = "tool.result"
    APPROVAL_REQUESTED = "approval.requested"
    APPROVAL_DECIDED = "approval.decided"
    CHECKPOINT_SAVED = "checkpoint.saved"
    RUN_PAUSED = "run.paused"
    RUN_FAILED = "run.failed"
    RUN_COMPLETED = "run.completed"


class ApprovalNotFound(LookupError):
    """审批项不存在，或不属于该次运行（接口层按 404 处理）。"""


class ApprovalAlreadyDecided(ValueError):
    """审批项已决议过，不允许重复改判（接口层按 409 处理）。"""


class RunNotDecidable(ValueError):
    """运行已进入终态，任何审批都不再可决议（接口层按 409 处理）。"""


class RunNotActionable(ValueError):
    """运行已进入终态，暂停 / 恢复 / 取消一律拒绝（接口层按 409 处理）。

    「终态即终态」与 `RunNotDecidable` 同一原则：不允许用干预动作把已结束的运行复活
    （把 `completed` 置回 `running`、或把 `cancelled` 再暂停，都会让指标与审计口径失真）。
    """


@dataclass(frozen=True)
class KnowledgeCitation:
    document_id: str
    knowledge_base_id: str
    title: str
    snippet: str
    score: float | None = None


@dataclass(frozen=True)
class RuntimeContext:
    tenant_id: str
    user_id: str
    role_key: str
    mode: str
    project_id: str | None
    task_id: str
    device_id: str
    knowledge_scope: tuple[str, ...]
    file_scope: tuple[str, ...]
    budget_cents: int
    risk_level: str
    policy_version: str
    expires_at: datetime

    def is_valid_at(self, now: datetime) -> bool:
        if now.tzinfo is None or self.expires_at.tzinfo is None:
            return False
        return now < self.expires_at


@dataclass(frozen=True)
class PlanStep:
    step_id: str
    kind: str
    tool: str
    requires_approval: bool = False


@dataclass(frozen=True)
class AgentPlan:
    steps: tuple[PlanStep, ...]

    @classmethod
    def from_steps(cls, values: list[dict[str, Any]]) -> AgentPlan:
        steps: list[PlanStep] = []
        for value in values:
            item = dict(value)
            item["requires_approval"] = item.get("requires_approval", item.get("kind") in SIDE_EFFECT_KINDS)
            steps.append(PlanStep(**item))
        return cls(tuple(steps))


# 运行时事件 payload 脱敏（10.4 自查扩展，2026-09-16）。
#
# 判据①「值的形态」：不只看键名 —— 工具标题 / 命令摘要 / 回复正文里同样可能夹带凭据，
# 字符串值另做**有限模式集**扫描；键名侧按**词元归一**比对（复用审计侧 `key_tokens` 口径），
# 覆盖 `apiKey` / `X-Api-Key` / `authToken` 等形态。
# 判据②「掩码幂等」：掩码产物为 `[已隐藏]`，值模式字符类**排除 `[` `]`** ⇒ 重复脱敏时
# 已掩码片段不再被任一模式命中，payload 逐字节不变（hash 自然不变）。
#
# 键名侧**裸 `key` 不纳入**判定（`{"key": "plan-42"}` 是正常业务字段，误伤代价高于收益），
# `api` + `key` 组合（`apiKey` / `X-Api-Key` / `api-key`）另行命中。
_RUNTIME_SENSITIVE_KEY_TOKENS = frozenset(
    {
        "password",
        "passwd",
        "pwd",
        "token",
        "secret",
        "cookie",
        "authorization",
        "credential",
        "session",
        "bearer",
        "验证码",
    }
)
_REDACTED = "[已隐藏]"
# 值正文的取值字符类：取到分隔符为止；**排除 `[` `]`** ⇒ 掩码产物不再被匹配（幂等的实现手法）。
_VALUE_CHARS = r"[^\s,;\"'&\[\]]{4,}"


def _is_sensitive_payload_key(key: object) -> bool:
    """键名是否敏感：词元归一后比对强词元集；`api` + `key` 组合另行命中。"""
    tokens = key_tokens(key)
    if tokens & _RUNTIME_SENSITIVE_KEY_TOKENS:
        return True
    return "api" in tokens and "key" in tokens


# 值正文模式集（三类，全部替换为统一占位符）：
# ① `Bearer <token>`；② 敏感词 `k[:=]v`（含引号包裹的 JSON 形态；负向断言 `(?!Bearer\b)`
# 避免与①重复替换）；③ 已知凭据前缀。
_BEARER_IN_TEXT = re.compile(rf"(?i)\bBearer\s+{_VALUE_CHARS}")
_CREDENTIAL_IN_TEXT = re.compile(
    rf"(?i)\b((?:api[_-]?key|access[_-]?token|refresh[_-]?token|auth[_-]?token"
    rf"|authorization|password|passwd|pwd|token|secret|cookie|credential|session)"
    rf"[\"']?(\s*[:=]\s*)[\"']?)(?!Bearer\b){_VALUE_CHARS}"
)
_CREDENTIAL_PREFIX = re.compile(
    r"(?i)\b(?:sk-[A-Za-z0-9_-]{6,}|ghp_[A-Za-z0-9]{10,}|glpat-[A-Za-z0-9_-]{6,}"
    r"|xox[baprs]-[A-Za-z0-9-]{6,}|AKIA[0-9A-Z]{12})"
)


def _redact_text(value: str) -> str:
    """有限模式集的值正文脱敏；不匹配的文本原样返回（掩码产物不再被匹配 ⇒ 幂等）。"""
    text = _BEARER_IN_TEXT.sub(f"Bearer {_REDACTED}", value)
    text = _CREDENTIAL_IN_TEXT.sub(rf"\g<1>{_REDACTED}", text)
    return _CREDENTIAL_PREFIX.sub(_REDACTED, text)


def redact_payload(value: Any) -> Any:
    """递归把敏感键的值替换为占位符，并对字符串值做有限模式集扫描。

    读取输出（`RuntimeEvent.to_public_dict`）与**持久化写入**共用这一套规则：
    事件一旦落库就是长期留存，凭据类内容不应写进数据库。
    """
    if isinstance(value, dict):
        return {
            key: _REDACTED if _is_sensitive_payload_key(key) else redact_payload(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_payload(item) for item in value]
    if isinstance(value, str):
        return _redact_text(value)
    return value


@dataclass(frozen=True)
class RuntimeEvent:
    run_id: str
    sequence: int
    event_type: RuntimeEventType
    payload: dict[str, Any] = field(default_factory=dict)

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "cursor": f"{self.run_id}:{self.sequence}",
            "run_id": self.run_id,
            "sequence": self.sequence,
            "event_type": self.event_type.value,
            "payload": redact_payload(self.payload),
        }


class AgentRuntimeAdapter(Protocol):
    def start_run(self, context: RuntimeContext, plan: AgentPlan) -> str: ...
    def stream_events(self, run_id: str, cursor: str | None = None) -> list[RuntimeEvent]: ...
    def pause_run(self, run_id: str, reason: str) -> None: ...
    def resume_run(self, run_id: str) -> None: ...
    def cancel_run(self, run_id: str, reason: str) -> None: ...
    def request_approval(self, run_id: str, action: dict[str, Any]) -> str: ...
    def decide_approval(self, run_id: str, approval_id: str, approved: bool) -> None: ...
    def get_checkpoint(self, run_id: str) -> dict[str, Any] | None: ...
    def replay_run(self, run_id: str, from_step: str | None = None) -> str: ...
    def get_usage(self, run_id: str) -> dict[str, Any]: ...
    def health(self) -> dict[str, Any]: ...
