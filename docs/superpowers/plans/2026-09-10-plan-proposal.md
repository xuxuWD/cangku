# 计划生成与审核闸门 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让员工用自然语言描述目标，由服务端依据工具白名单生成一份可审核的 `AgentPlan` 提案，审核通过后复用既有 Runtime 执行。

**Architecture:** 新增 `app/planner/` 领域包（工具白名单、生成器、服务、仓储），与既有控制平面解耦但复用其能力：计划挂在既有 Task 上，执行调用既有 `RuntimeService.start`，审批复用 `ensure_can_approve`，模型调用前经 `ModelGateway` 校验数据分级。`kind` 与 `requires_approval` 一律由服务端按工具推导，模型提供的值被忽略。

**Tech Stack:** Python 3.11+、FastAPI、Pydantic v2、httpx（模型后端）、pytest、PostgreSQL（psycopg3）。

**参考规格：** [`docs/superpowers/specs/2026-09-10-plan-proposal-design.md`](../specs/2026-09-10-plan-proposal-design.md)

---

## 文件结构

| 文件 | 职责 |
| --- | --- |
| `app/planner/__init__.py` | 包标记 |
| `app/planner/models.py` | 工具白名单、步骤归一化、提案模型、领域异常 |
| `app/planner/store.py` | 提案仓储协议 + 内存实现 + PostgreSQL 实现 |
| `app/planner/generator.py` | 生成器协议、Mock 生成器、OpenAI 兼容生成器 |
| `app/planner/service.py` | 生成、审批、驳回、执行编排 |
| `app/settings.py`（修改） | 新增 planner 相关配置 |
| `app/bootstrap.py`（修改） | 装配 planner 服务与仓储 |
| `app/main.py`（修改） | 5 个接口与错误映射 |
| `migrations/009_plan_proposals.sql`（新增） | 提案表 |
| `tests/test_planner_models.py` | 白名单与归一化测试 |
| `tests/test_planner_store.py` | 内存仓储测试 |
| `tests/test_planner_generator.py` | 生成器测试 |
| `tests/test_planner_service.py` | 服务测试 |
| `tests/test_planner_bootstrap.py` | 装配测试 |
| `tests/test_planner_api.py` | 接口测试 |
| `tests/test_planner_postgres.py` | PostgreSQL 仓储契约测试 |

**约定：** 本仓库测试命令用 `py -m pytest`（该机器 `python` 不在 PATH）。当前全量基线 **295 项通过**。禁止提交 `.env`、密钥、口令或模型密钥。

**迁移编号说明：** `migrations/` 现有 `001`–`008`，下一个可用编号是 `009`。

---

### Task 1: 工具白名单与领域模型

**Files:**
- Create: `app/planner/__init__.py`
- Create: `app/planner/models.py`
- Test: `tests/test_planner_models.py`

- [ ] **Step 1: 写失败测试**

```python
import pytest

from app.planner.models import (
    PlanGenerationError,
    PlanProposal,
    PlanStatus,
    PlannerNotConfigured,
    Tool,
    ToolCatalog,
    UnknownTool,
    normalize_steps,
)


def catalog() -> ToolCatalog:
    return ToolCatalog(
        (
            Tool(name="knowledge.search", kind="read", description="只读知识检索"),
            Tool(name="content.publish", kind="publish", description="对外发布"),
        )
    )


def test_catalog_resolves_known_tool_and_rejects_unknown() -> None:
    instance = catalog()

    resolved = instance.resolve("knowledge.search")

    assert resolved.name == "knowledge.search"
    assert resolved.requires_approval is False
    with pytest.raises(UnknownTool):
        instance.resolve("shell.exec")


def test_side_effect_kinds_require_approval() -> None:
    assert Tool(name="a", kind="read").requires_approval is False
    for kind in ("write", "external_send", "publish", "delete", "permission"):
        assert Tool(name="a", kind=kind).requires_approval is True


def test_normalize_ignores_model_declared_kind_and_approval() -> None:
    raw = [
        {
            "step_id": "s1",
            "tool": "content.publish",
            "kind": "read",
            "requires_approval": False,
            "args": {"channel": "wechat"},
        }
    ]

    steps = normalize_steps(raw, catalog(), max_steps=5)

    assert steps[0].kind == "publish"
    assert steps[0].requires_approval is True


def test_normalize_rejects_unknown_tool_entirely() -> None:
    raw = [
        {"step_id": "s1", "tool": "knowledge.search"},
        {"step_id": "s2", "tool": "shell.exec"},
    ]

    with pytest.raises(UnknownTool):
        normalize_steps(raw, catalog(), max_steps=5)


def test_normalize_rejects_empty_oversized_and_duplicate_steps() -> None:
    with pytest.raises(PlanGenerationError, match="至少一个步骤"):
        normalize_steps([], catalog(), max_steps=5)

    too_many = [{"step_id": f"s{i}", "tool": "knowledge.search"} for i in range(3)]
    with pytest.raises(PlanGenerationError, match="超过上限"):
        normalize_steps(too_many, catalog(), max_steps=2)

    duplicated = [
        {"step_id": "s1", "tool": "knowledge.search"},
        {"step_id": "s1", "tool": "knowledge.search"},
    ]
    with pytest.raises(PlanGenerationError, match="重复"):
        normalize_steps(duplicated, catalog(), max_steps=5)


def test_normalize_rejects_bad_args_and_sensitive_keys() -> None:
    with pytest.raises(PlanGenerationError, match="args"):
        normalize_steps([{"step_id": "s1", "tool": "knowledge.search", "args": "text"}], catalog(), max_steps=5)

    with pytest.raises(PlanGenerationError, match="敏感"):
        normalize_steps(
            [{"step_id": "s1", "tool": "knowledge.search", "args": {"api_key": "x"}}],
            catalog(),
            max_steps=5,
        )


def test_normalize_rejects_missing_fields() -> None:
    with pytest.raises(PlanGenerationError, match="step_id"):
        normalize_steps([{"tool": "knowledge.search"}], catalog(), max_steps=5)
    with pytest.raises(PlanGenerationError, match="tool"):
        normalize_steps([{"step_id": "s1"}], catalog(), max_steps=5)


def test_empty_catalog_is_reported() -> None:
    assert ToolCatalog().is_empty() is True
    assert catalog().is_empty() is False
    with pytest.raises(PlannerNotConfigured):
        ToolCatalog().require_configured()


def test_catalog_from_config_parses_json_list() -> None:
    parsed = ToolCatalog.from_config('[{"name": "knowledge.search", "kind": "read"}]')

    assert parsed.names() == ("knowledge.search",)


def test_catalog_from_config_rejects_bad_shapes() -> None:
    for bad in ("", "not-json", "{}", '[{"name": "x"}]', '[{"name": "x", "kind": ""}]', '[1]'):
        with pytest.raises(ValueError, match="工具白名单"):
            ToolCatalog.from_config(bad)


def test_catalog_from_config_accepts_empty_values() -> None:
    assert ToolCatalog.from_config(None).is_empty() is True
    assert ToolCatalog.from_config("").is_empty() is True
    assert ToolCatalog.from_config("[]").is_empty() is True


def test_proposal_defaults_to_pending_review() -> None:
    proposal = PlanProposal(
        task_id="task-1",
        tenant_id="t-1",
        goal="整理本周公众号选题",
        steps=(),
        generator_key="mock",
        generator_model=None,
        created_by="u-1",
        idempotency_key="id-1",
    )

    assert proposal.status is PlanStatus.PENDING_REVIEW
    assert proposal.proposal_id.startswith("plan-")
    assert proposal.reviewed_by is None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `py -m pytest tests/test_planner_models.py -q`
Expected: FAIL，`ModuleNotFoundError: No module named 'app.planner'`

- [ ] **Step 3: 实现包标记与模型**

`app/planner/__init__.py`：

```python
"""自然语言目标到 Agent 计划的生成与审核。"""
```

`app/planner/models.py`：

```python
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4


READ_KIND = "read"
SIDE_EFFECT_KINDS = frozenset({"write", "external_send", "publish", "delete", "permission"})
SENSITIVE_ARG_KEYS = frozenset(
    {
        "password",
        "token",
        "api_key",
        "apikey",
        "secret",
        "cookie",
        "authorization",
        "access_token",
        "refresh_token",
        "session",
    }
)


class UnknownTool(ValueError):
    """工具不在服务端白名单内。"""


class PlanGenerationError(ValueError):
    """生成结果不合法。"""


class PlannerNotConfigured(ValueError):
    """部署未配置任何可用工具。"""


class PlannerAccessDenied(ValueError):
    """当前身份无权操作该任务或提案。"""


class PlanProposalNotFound(LookupError):
    pass


class PlanProposalStateConflict(ValueError):
    pass


class PlanStatus(StrEnum):
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass(frozen=True)
class Tool:
    name: str
    kind: str
    description: str = ""

    @property
    def requires_approval(self) -> bool:
        return self.kind in SIDE_EFFECT_KINDS


class ToolCatalog:
    """服务端工具白名单；kind 与审批要求只由此处决定。"""

    def __init__(self, tools: tuple[Tool, ...] = ()) -> None:
        self._tools = {tool.name: tool for tool in tools}

    @classmethod
    def from_config(cls, values: object) -> ToolCatalog:
        if isinstance(values, str):
            text = values.strip()
            if not text:
                return cls()
            try:
                values = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError("工具白名单必须是 JSON 数组") from exc
        if values is None:
            return cls()
        if not isinstance(values, list):
            raise ValueError("工具白名单必须是 JSON 数组")
        tools: list[Tool] = []
        for item in values:
            if not isinstance(item, dict):
                raise ValueError("工具白名单的每一项都必须是对象")
            name = item.get("name")
            kind = item.get("kind")
            if not isinstance(name, str) or not name.strip():
                raise ValueError("工具白名单缺少工具名")
            if not isinstance(kind, str) or not kind.strip():
                raise ValueError("工具白名单缺少 kind")
            description = item.get("description", "")
            tools.append(
                Tool(
                    name=name.strip(),
                    kind=kind.strip(),
                    description=description if isinstance(description, str) else "",
                )
            )
        return cls(tuple(tools))

    def is_empty(self) -> bool:
        return not self._tools

    def require_configured(self) -> None:
        if self.is_empty():
            raise PlannerNotConfigured("未配置任何可用工具")

    def resolve(self, name: str) -> Tool:
        tool = self._tools.get(name)
        if tool is None:
            raise UnknownTool(name)
        return tool

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._tools))


@dataclass(frozen=True)
class PlanStepView:
    step_id: str
    tool: str
    kind: str
    requires_approval: bool
    args: dict[str, object] = field(default_factory=dict)

    def to_step_dict(self) -> dict[str, object]:
        return {"step_id": self.step_id, "tool": self.tool, "kind": self.kind}


@dataclass
class PlanProposal:
    task_id: str
    tenant_id: str
    goal: str
    steps: tuple[PlanStepView, ...]
    generator_key: str
    generator_model: str | None
    created_by: str
    idempotency_key: str
    proposal_id: str = field(default_factory=lambda: f"plan-{uuid4().hex[:12]}")
    status: PlanStatus = PlanStatus.PENDING_REVIEW
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    rejection_reason: str | None = None


def normalize_steps(raw_steps: object, catalog: ToolCatalog, *, max_steps: int) -> tuple[PlanStepView, ...]:
    """把生成器的原始输出归一化为服务端可信步骤。

    kind 与 requires_approval 一律来自工具白名单，忽略生成器提供的任何值。
    """
    if not isinstance(raw_steps, list) or not raw_steps:
        raise PlanGenerationError("计划必须包含至少一个步骤")
    if len(raw_steps) > max_steps:
        raise PlanGenerationError(f"步骤数超过上限 {max_steps}")

    seen: set[str] = set()
    normalized: list[PlanStepView] = []
    for item in raw_steps:
        if not isinstance(item, dict):
            raise PlanGenerationError("步骤必须是对象")
        step_id = item.get("step_id")
        tool_name = item.get("tool")
        if not isinstance(step_id, str) or not step_id.strip():
            raise PlanGenerationError("步骤缺少 step_id")
        if not isinstance(tool_name, str) or not tool_name.strip():
            raise PlanGenerationError("步骤缺少 tool")
        step_id = step_id.strip()
        if step_id in seen:
            raise PlanGenerationError(f"步骤号重复：{step_id}")
        seen.add(step_id)
        tool = catalog.resolve(tool_name.strip())
        args = item.get("args", {})
        if not isinstance(args, dict):
            raise PlanGenerationError("步骤 args 必须是对象")
        if {str(key).lower() for key in args} & SENSITIVE_ARG_KEYS:
            raise PlanGenerationError("步骤参数包含敏感字段")
        normalized.append(
            PlanStepView(
                step_id=step_id,
                tool=tool.name,
                kind=tool.kind,
                requires_approval=tool.requires_approval,
                args=dict(args),
            )
        )
    return tuple(normalized)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `py -m pytest tests/test_planner_models.py -q`
Expected: PASS（17 passed）

> **实现说明（审查后加固，必须遵守）**：`models.py` 在上述代码基础上还必须包含四项加固，否则代码质量审查会判为不合格：
> 1. `kind` 必须 fail-closed 校验。副作用 kind 集合提取到 `app/runtime/contracts.py` 作为单一来源（该文件的 `AgentPlan.from_steps` 也改用它），`models.py` 从那里导入 `ALLOWED_PLAN_KINDS` 与 `SIDE_EFFECT_KINDS`，不再自行定义。`Tool.__post_init__` 中校验 `kind not in ALLOWED_PLAN_KINDS` 时抛 `ValueError`，避免配置里把 `content.publish` 写成 `kind="publsh"` 或 `"READ"` 导致危险工具被当作只读而绕过审批。
> 2. `ToolCatalog.__init__` 必须检测重复工具名并抛 `ValueError`，避免同名后者覆盖前者把副作用工具降级为只读。
> 3. 敏感键检查改为**词元递归匹配**：键名小写并把 `-` 归一为 `_` 后按 `_` 切词，任一词元命中 `SENSITIVE_KEY_TOKENS`（password/passwd/pwd/token/secret/key/cookie/authorization/credential/session/bearer）即拒绝，并递归检查嵌套 dict 与 list。这样 `client_secret`、`x-api-key`、`{"headers": {"Authorization": ...}}` 都会被拦截，而 `keyword` 这类误伤被排除。
> 4. 相应地，Task 1 的测试需包含未知/大小写错误 `kind` 被拒、直接构造 `Tool` 校验、重复工具名被拒、复合与嵌套敏感键被拒、`keyword` 不被误伤这 5 个用例，合计 17 项。

- [ ] **Step 5: 提交**

```bash
git add app/planner/__init__.py app/planner/models.py tests/test_planner_models.py
git commit -m "feat: 增加计划工具白名单与领域模型"
```

---

### Task 2: 提案仓储（内存实现）

**Files:**
- Create: `app/planner/store.py`
- Test: `tests/test_planner_store.py`

- [ ] **Step 1: 写失败测试**

```python
import pytest

from app.planner.models import (
    PlanProposal,
    PlanProposalNotFound,
    PlanProposalStateConflict,
    PlanStatus,
)
from app.planner.store import InMemoryPlanProposalStore


def proposal(task_id: str = "task-1", *, idempotency_key: str = "id-1", created_by: str = "u-1") -> PlanProposal:
    return PlanProposal(
        task_id=task_id,
        tenant_id="t-1",
        goal="整理选题",
        steps=(),
        generator_key="mock",
        generator_model=None,
        created_by=created_by,
        idempotency_key=idempotency_key,
    )


def test_add_and_get_roundtrip() -> None:
    store = InMemoryPlanProposalStore()
    saved = store.add(proposal())

    assert store.get("t-1", saved.proposal_id) is saved


def test_get_rejects_other_tenant() -> None:
    store = InMemoryPlanProposalStore()
    saved = store.add(proposal())

    with pytest.raises(PlanProposalNotFound):
        store.get("t-other", saved.proposal_id)


def test_find_by_idempotency_is_scoped_to_tenant_and_task() -> None:
    store = InMemoryPlanProposalStore()
    saved = store.add(proposal())

    assert store.find_by_idempotency("t-1", "task-1", "id-1") is saved
    assert store.find_by_idempotency("t-1", "task-2", "id-1") is None
    assert store.find_by_idempotency("t-other", "task-1", "id-1") is None


def test_approve_only_from_pending_review() -> None:
    store = InMemoryPlanProposalStore()
    saved = store.add(proposal())

    approved = store.mark_approved(saved.proposal_id, reviewer="ceo-1")

    assert approved.status is PlanStatus.APPROVED
    assert approved.reviewed_by == "ceo-1"
    assert approved.reviewed_at is not None
    with pytest.raises(PlanProposalStateConflict):
        store.mark_approved(saved.proposal_id, reviewer="ceo-1")


def test_reject_records_reason_and_blocks_approval() -> None:
    store = InMemoryPlanProposalStore()
    saved = store.add(proposal())

    rejected = store.mark_rejected(saved.proposal_id, reason="步骤不完整", reviewer="ceo-1")

    assert rejected.status is PlanStatus.REJECTED
    assert rejected.rejection_reason == "步骤不完整"
    with pytest.raises(PlanProposalStateConflict):
        store.mark_approved(saved.proposal_id, reviewer="ceo-1")


def test_mark_approved_rejects_unknown_proposal() -> None:
    store = InMemoryPlanProposalStore()

    with pytest.raises(PlanProposalNotFound):
        store.mark_approved("plan-missing", reviewer="ceo-1")


def test_list_for_task_is_tenant_scoped() -> None:
    store = InMemoryPlanProposalStore()
    store.add(proposal())
    store.add(proposal(idempotency_key="id-2"))

    assert len(store.list_for_task("t-1", "task-1")) == 2
    assert store.list_for_task("t-other", "task-1") == []


def test_add_is_idempotent_for_same_key_and_returns_existing() -> None:
    store = InMemoryPlanProposalStore()
    first = store.add(proposal())
    second = store.add(proposal())

    assert second is first
    assert len(store.list_for_task("t-1", "task-1")) == 1


def test_concurrent_add_with_same_key_creates_only_one_proposal() -> None:
    from concurrent.futures import ThreadPoolExecutor

    store = InMemoryPlanProposalStore()

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _index: store.add(proposal()), range(20)))

    ids = {item.proposal_id for item in results}
    assert len(ids) == 1
    assert len(store.list_for_task("t-1", "task-1")) == 1


def test_concurrent_approval_only_succeeds_once() -> None:
    from concurrent.futures import ThreadPoolExecutor

    store = InMemoryPlanProposalStore()
    saved = store.add(proposal())

    def attempt(_index: int) -> str:
        try:
            store.mark_approved(saved.proposal_id, reviewer="ceo-1")
            return "approved"
        except PlanProposalStateConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(attempt, range(20)))

    assert results.count("approved") == 1
    assert results.count("conflict") == 19
    assert store.get("t-1", saved.proposal_id).status is PlanStatus.APPROVED
```

> 实现说明：内存实现的 `add` 必须与后续 Task 7 的 PostgreSQL 实现（`ON CONFLICT (tenant_id, task_id, idempotency_key) DO NOTHING` + 回查）**行为一致**——同一幂等键返回既有提案、不重复写入。否则并发提交同一幂等键会落两条计划并可能被重复审批执行。

- [ ] **Step 2: 运行测试确认失败**

Run: `py -m pytest tests/test_planner_store.py -q`
Expected: FAIL，`ModuleNotFoundError: No module named 'app.planner.store'`

- [ ] **Step 3: 实现仓储协议与内存实现**

`app/planner/store.py`：

```python
from __future__ import annotations

from datetime import UTC, datetime
from threading import RLock
from typing import Protocol

from .models import (
    PlanProposal,
    PlanProposalNotFound,
    PlanProposalStateConflict,
    PlanStatus,
)


class PlanProposalStore(Protocol):
    def add(self, proposal: PlanProposal) -> PlanProposal: ...
    def get(self, tenant_id: str, proposal_id: str) -> PlanProposal: ...
    def find_by_idempotency(self, tenant_id: str, task_id: str, idempotency_key: str) -> PlanProposal | None: ...
    def list_for_task(self, tenant_id: str, task_id: str) -> list[PlanProposal]: ...
    def mark_approved(self, proposal_id: str, *, reviewer: str) -> PlanProposal: ...
    def mark_rejected(self, proposal_id: str, *, reason: str, reviewer: str) -> PlanProposal: ...


class InMemoryPlanProposalStore:
    """开发期内存仓储；状态流转在锁内原子完成。"""

    def __init__(self) -> None:
        self._items: dict[str, PlanProposal] = {}
        self._idempotency: dict[tuple[str, str, str], str] = {}
        self._lock = RLock()

    def add(self, proposal: PlanProposal) -> PlanProposal:
        """写入提案；同一租户、任务与幂等键已存在时返回既有提案，不重复写入。"""
        key = (proposal.tenant_id, proposal.task_id, proposal.idempotency_key)
        with self._lock:
            existing_id = self._idempotency.get(key)
            if existing_id is not None:
                return self._items[existing_id]
            self._items[proposal.proposal_id] = proposal
            self._idempotency[key] = proposal.proposal_id
            return proposal

    def get(self, tenant_id: str, proposal_id: str) -> PlanProposal:
        with self._lock:
            return self._require(tenant_id, proposal_id)

    def find_by_idempotency(self, tenant_id: str, task_id: str, idempotency_key: str) -> PlanProposal | None:
        with self._lock:
            for item in self._items.values():
                if (
                    item.tenant_id == tenant_id
                    and item.task_id == task_id
                    and item.idempotency_key == idempotency_key
                ):
                    return item
            return None

    def list_for_task(self, tenant_id: str, task_id: str) -> list[PlanProposal]:
        with self._lock:
            return [
                item
                for item in self._items.values()
                if item.tenant_id == tenant_id and item.task_id == task_id
            ]

    def mark_approved(self, proposal_id: str, *, reviewer: str) -> PlanProposal:
        with self._lock:
            item = self._by_id(proposal_id)
            if item.status is not PlanStatus.PENDING_REVIEW:
                raise PlanProposalStateConflict("该提案当前状态不允许审批")
            item.status = PlanStatus.APPROVED
            item.reviewed_by = reviewer
            item.reviewed_at = datetime.now(UTC)
            return item

    def mark_rejected(self, proposal_id: str, *, reason: str, reviewer: str) -> PlanProposal:
        with self._lock:
            item = self._by_id(proposal_id)
            if item.status is not PlanStatus.PENDING_REVIEW:
                raise PlanProposalStateConflict("该提案当前状态不允许审批")
            item.status = PlanStatus.REJECTED
            item.reviewed_by = reviewer
            item.reviewed_at = datetime.now(UTC)
            item.rejection_reason = reason
            return item

    def _require(self, tenant_id: str, proposal_id: str) -> PlanProposal:
        item = self._items.get(proposal_id)
        if item is None or item.tenant_id != tenant_id:
            raise PlanProposalNotFound(proposal_id)
        return item

    def _by_id(self, proposal_id: str) -> PlanProposal:
        item = self._items.get(proposal_id)
        if item is None:
            raise PlanProposalNotFound(proposal_id)
        return item
```

- [ ] **Step 4: 运行测试确认通过**

Run: `py -m pytest tests/test_planner_store.py -q`
Expected: PASS（10 passed）

- [ ] **Step 5: 提交**

```bash
git add app/planner/store.py tests/test_planner_store.py
git commit -m "feat: 增加计划提案内存仓储"
```

---

### Task 3: 生成器（协议、Mock、真实模型）

**Files:**
- Create: `app/planner/generator.py`
- Test: `tests/test_planner_generator.py`

- [ ] **Step 1: 写失败测试**

```python
import json

import pytest

from app.planner.generator import MockPlanGenerator, OpenAICompatiblePlanGenerator
from app.planner.models import PlanGenerationError, PlannerNotConfigured, Tool, ToolCatalog


def catalog() -> ToolCatalog:
    return ToolCatalog(
        (
            Tool(name="knowledge.search", kind="read"),
            Tool(name="content.publish", kind="publish"),
        )
    )


def test_mock_generator_is_deterministic_and_uses_read_tools_only() -> None:
    generator = MockPlanGenerator()

    first = generator.generate("整理本周公众号选题", catalog=catalog(), max_steps=5)
    second = generator.generate("整理本周公众号选题", catalog=catalog(), max_steps=5)

    assert first == second
    assert [step["tool"] for step in first] == ["knowledge.search"]
    assert generator.key == "mock"
    assert generator.model_name is None


def test_mock_generator_requires_configured_catalog() -> None:
    generator = MockPlanGenerator()

    with pytest.raises(PlannerNotConfigured):
        generator.generate("任意目标", catalog=ToolCatalog(), max_steps=5)


def test_mock_generator_respects_max_steps() -> None:
    wide = ToolCatalog(tuple(Tool(name=f"read.tool{i}", kind="read") for i in range(5)))

    steps = MockPlanGenerator().generate("目标", catalog=wide, max_steps=2)

    assert len(steps) == 2


def test_openai_generator_parses_steps_from_model_response() -> None:
    captured: dict[str, object] = {}

    def transport(url, headers, payload, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["payload"] = payload
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "steps": [
                                    {"step_id": "s1", "tool": "knowledge.search", "args": {"query": "选题"}},
                                    {"step_id": "s2", "tool": "content.publish"},
                                ]
                            }
                        )
                    }
                }
            ]
        }

    generator = OpenAICompatiblePlanGenerator(
        base_url="https://model.example/v1",
        model_name="planner-small",
        api_key="secret-key",
        timeout_seconds=5,
        transport=transport,
    )

    steps = generator.generate("整理选题并发布", catalog=catalog(), max_steps=5)

    assert [step["tool"] for step in steps] == ["knowledge.search", "content.publish"]
    assert captured["url"] == "https://model.example/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer secret-key"
    assert generator.key == "openai_compatible"
    assert generator.model_name == "planner-small"


def test_openai_generator_does_not_dictate_kind_or_approval() -> None:
    def transport(url, headers, payload, timeout):
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "steps": [
                                    {
                                        "step_id": "s1",
                                        "tool": "content.publish",
                                        "kind": "read",
                                        "requires_approval": False,
                                    }
                                ]
                            }
                        )
                    }
                }
            ]
        }

    generator = OpenAICompatiblePlanGenerator(
        base_url="https://model.example/v1",
        model_name="planner-small",
        api_key="secret-key",
        timeout_seconds=5,
        transport=transport,
    )

    steps = generator.generate("发布", catalog=catalog(), max_steps=5)

    assert "kind" not in steps[0]
    assert "requires_approval" not in steps[0]


def test_openai_generator_raises_on_bad_payloads() -> None:
    def make(payload):
        def transport(url, headers, _payload, timeout):
            return payload

        return OpenAICompatiblePlanGenerator(
            base_url="https://model.example/v1",
            model_name="planner-small",
            api_key="secret-key",
            timeout_seconds=5,
            transport=transport,
        )

    with pytest.raises(PlanGenerationError, match="模型响应"):
        make({"choices": []}).generate("目标", catalog=catalog(), max_steps=5)

    with pytest.raises(PlanGenerationError, match="JSON"):
        make({"choices": [{"message": {"content": "not-json"}}]}).generate(
            "目标", catalog=catalog(), max_steps=5
        )

    with pytest.raises(PlanGenerationError, match="步骤列表"):
        make({"choices": [{"message": {"content": json.dumps({"steps": "text"})}}]}).generate(
            "目标", catalog=catalog(), max_steps=5
        )


def test_openai_generator_raises_on_transport_failure() -> None:
    def transport(url, headers, payload, timeout):
        raise RuntimeError("connection reset")

    generator = OpenAICompatiblePlanGenerator(
        base_url="https://model.example/v1",
        model_name="planner-small",
        api_key="secret-key",
        timeout_seconds=5,
        transport=transport,
    )

    with pytest.raises(PlanGenerationError, match="模型调用失败"):
        generator.generate("目标", catalog=catalog(), max_steps=5)


def test_openai_generator_reports_missing_configuration() -> None:
    with pytest.raises(ValueError, match="地址、模型名和 API Key"):
        OpenAICompatiblePlanGenerator(
            base_url="", model_name="", api_key="", timeout_seconds=5, transport=lambda *a: {}
        )
```

- [ ] **Step 2: 运行测试确认失败**

Run: `py -m pytest tests/test_planner_generator.py -q`
Expected: FAIL，`ModuleNotFoundError: No module named 'app.planner.generator'`

- [ ] **Step 3: 实现生成器**

`app/planner/generator.py`：

```python
from __future__ import annotations

import json
from typing import Any, Callable, Protocol

import httpx

from app.runtime.contracts import READ_KIND

from .models import (
    PlanGenerationError,
    PlannerNotConfigured,
    ToolCatalog,
)


class PlanGenerator(Protocol):
    key: str
    model_name: str | None

    def generate(self, goal: str, *, catalog: ToolCatalog, max_steps: int) -> list[dict[str, Any]]: ...


class MockPlanGenerator:
    """确定性生成器：只使用白名单里的只读工具，结果可重复。"""

    key = "mock"
    model_name = None

    def generate(self, goal: str, *, catalog: ToolCatalog, max_steps: int) -> list[dict[str, Any]]:
        catalog.require_configured()
        read_tools = [name for name in catalog.names() if catalog.resolve(name).kind == READ_KIND]
        if not read_tools:
            raise PlannerNotConfigured("未配置任何只读工具")
        selected = read_tools[:max_steps]
        return [
            {"step_id": f"step-{index + 1}", "tool": name, "args": {"goal": goal.strip()}}
            for index, name in enumerate(selected)
        ]


Transport = Callable[[str, dict[str, str], dict[str, Any], float], dict[str, Any]]


class OpenAICompatiblePlanGenerator:
    """OpenAI 兼容的规划后端；任何失败都抛出明确错误，不降级为 Mock。"""

    key = "openai_compatible"

    def __init__(
        self,
        *,
        base_url: str,
        model_name: str,
        api_key: str,
        timeout_seconds: float,
        transport: Transport | None = None,
    ) -> None:
        if not base_url or not model_name or not api_key:
            raise ValueError("真实规划模型需要配置地址、模型名和 API Key")
        self.base_url = base_url.rstrip("/")
        self.model_name = model_name
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self._transport = transport or self._http_transport

    def generate(self, goal: str, *, catalog: ToolCatalog, max_steps: int) -> list[dict[str, Any]]:
        catalog.require_configured()
        allowed = ", ".join(catalog.names())
        payload = {
            "model": self.model_name,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是执行计划生成器。只能使用这些工具："
                        f"{allowed}。只返回 JSON，形如 "
                        '{"steps": [{"step_id": "s1", "tool": "工具名", "args": {}}]}，'
                        f"步骤数不超过 {max_steps}。不要输出 kind、权限或审批字段。"
                    ),
                },
                {"role": "user", "content": goal},
            ],
            "response_format": {"type": "json_object"},
        }
        try:
            response = self._transport(
                f"{self.base_url}/chat/completions",
                {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                payload,
                self.timeout_seconds,
            )
        except Exception as exc:  # 网络、超时、HTTP 状态异常统一收敛
            raise PlanGenerationError(f"模型调用失败：{exc}") from exc
        return self._parse(response)

    @staticmethod
    def _http_transport(
        url: str, headers: dict[str, str], payload: dict[str, Any], timeout: float
    ) -> dict[str, Any]:
        response = httpx.post(url, headers=headers, json=payload, timeout=timeout)
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _parse(response: Any) -> list[dict[str, Any]]:
        try:
            content = response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise PlanGenerationError("模型响应缺少可解析内容") from exc
        if not isinstance(content, str):
            raise PlanGenerationError("模型响应缺少可解析内容")
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise PlanGenerationError("模型响应不是合法 JSON") from exc
        steps = parsed.get("steps") if isinstance(parsed, dict) else None
        if not isinstance(steps, list):
            raise PlanGenerationError("模型响应缺少步骤列表")
        cleaned: list[dict[str, Any]] = []
        for item in steps:
            if not isinstance(item, dict):
                raise PlanGenerationError("模型响应中的步骤必须是对象")
            step: dict[str, Any] = {
                "step_id": item.get("step_id"),
                "tool": item.get("tool"),
            }
            if "args" in item:
                step["args"] = item["args"]
            cleaned.append(step)
        return cleaned
```

- [ ] **Step 4: 运行测试确认通过**

Run: `py -m pytest tests/test_planner_generator.py -q`
Expected: PASS（8 passed）

- [ ] **Step 5: 提交**

```bash
git add app/planner/generator.py tests/test_planner_generator.py
git commit -m "feat: 增加计划生成器与模型后端"
```

---

### Task 4: PlannerService

**Files:**
- Create: `app/planner/service.py`
- Test: `tests/test_planner_service.py`

- [ ] **Step 1: 写失败测试**

```python
import pytest

from app.domain import PolicyError, RiskLevel, Task, TaskStatus, UserContext
from app.planner.generator import MockPlanGenerator
from app.planner.models import (
    PlanGenerationError,
    PlanProposalNotFound,
    PlanProposalStateConflict,
    PlanStatus,
    PlannerAccessDenied,
    PlannerNotConfigured,
    Tool,
    ToolCatalog,
)
from app.planner.service import PlannerService
from app.planner.store import InMemoryPlanProposalStore
from app.runtime.service import RuntimeService


class RecordingRuntimeService(RuntimeService):
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, list[dict], str]] = []

    def start(self, actor, task_id, runtime_key, steps, mode):  # type: ignore[override]
        self.calls.append((task_id, runtime_key, steps, mode))
        return "run-1", runtime_key, "policy-1"


def catalog() -> ToolCatalog:
    return ToolCatalog(
        (
            Tool(name="knowledge.search", kind="read"),
            Tool(name="content.publish", kind="publish"),
        )
    )


def make_task(task_store, *, created_by: str = "u-1") -> Task:
    task = Task(
        tenant_id="t-1",
        project_id=None,
        created_by=created_by,
        employee_key="content-operator",
        title="整理选题",
        risk_level=RiskLevel.LOW,
        budget=1,
        idempotency_key=f"id-{created_by}",
        request_fingerprint="fp",
        status=TaskStatus.QUEUED,
    )
    owner = UserContext("t-1", created_by, "employee")
    task_store.create(owner, task)
    return task


def service(task_store, runtime=None, *, tools: ToolCatalog | None = None) -> PlannerService:
    return PlannerService(
        task_store=task_store,
        store=InMemoryPlanProposalStore(),
        generator=MockPlanGenerator(),
        catalog=tools if tools is not None else catalog(),
        runtime_service=runtime or RecordingRuntimeService(),
        max_steps=5,
    )


def test_propose_generates_pending_proposal_with_server_derived_steps() -> None:
    from app.domain import TaskStore

    task_store = TaskStore()
    task = make_task(task_store)
    planner = service(task_store)

    proposal = planner.propose(
        UserContext("t-1", "u-1", "employee"), task.id, "整理本周公众号选题", "key-1"
    )

    assert proposal.status is PlanStatus.PENDING_REVIEW
    assert proposal.steps[0].tool == "knowledge.search"
    assert proposal.steps[0].requires_approval is False
    assert proposal.generator_key == "mock"


def test_propose_is_idempotent_per_task_and_key() -> None:
    from app.domain import TaskStore

    task_store = TaskStore()
    task = make_task(task_store)
    planner = service(task_store)
    actor = UserContext("t-1", "u-1", "employee")

    first = planner.propose(actor, task.id, "目标", "key-1")
    second = planner.propose(actor, task.id, "另一个目标", "key-1")

    assert first.proposal_id == second.proposal_id
    assert len(planner.store.list_for_task("t-1", task.id)) == 1


def test_propose_rejects_other_employee_on_same_task() -> None:
    from app.domain import TaskStore

    task_store = TaskStore()
    task = make_task(task_store)

    with pytest.raises(PlannerAccessDenied):
        service(task_store).propose(UserContext("t-1", "u-9", "employee"), task.id, "目标", "key-1")


def test_propose_requires_configured_tools() -> None:
    from app.domain import TaskStore

    task_store = TaskStore()
    task = make_task(task_store)

    with pytest.raises(PlannerNotConfigured, match="未配置任何可用工具"):
        service(task_store, tools=ToolCatalog()).propose(
            UserContext("t-1", "u-1", "employee"), task.id, "目标", "key-1"
        )


def test_propose_hides_cross_tenant_task() -> None:
    from app.domain import TaskStore, TaskNotFound

    task_store = TaskStore()
    task = make_task(task_store)

    with pytest.raises(TaskNotFound):
        service(task_store).propose(UserContext("t-other", "u-1", "employee"), task.id, "目标", "key-1")


def test_only_ceo_or_super_admin_can_approve_and_creator_cannot_self_approve() -> None:
    from app.domain import TaskStore

    task_store = TaskStore()
    task = make_task(task_store)
    planner = service(task_store)
    proposal = planner.propose(UserContext("t-1", "u-1", "employee"), task.id, "目标", "key-1")

    with pytest.raises(PolicyError):
        planner.approve(UserContext("t-1", "u-1", "employee"), proposal.proposal_id)
    with pytest.raises(PolicyError, match="发起人"):
        planner.approve(UserContext("t-1", "u-1", "ceo"), proposal.proposal_id)
    approved = planner.approve(UserContext("t-1", "ceo-1", "ceo"), proposal.proposal_id)

    assert approved.status is PlanStatus.APPROVED
    assert approved.reviewed_by == "ceo-1"


def test_reject_requires_ceo_and_records_reason() -> None:
    from app.domain import TaskStore

    task_store = TaskStore()
    task = make_task(task_store)
    planner = service(task_store)
    proposal = planner.propose(UserContext("t-1", "u-1", "employee"), task.id, "目标", "key-1")

    rejected = planner.reject(UserContext("t-1", "ceo-1", "ceo"), proposal.proposal_id, "步骤不完整")

    assert rejected.status is PlanStatus.REJECTED
    assert rejected.rejection_reason == "步骤不完整"


def test_run_requires_approved_status_and_uses_runtime_service() -> None:
    from app.domain import TaskStore

    task_store = TaskStore()
    task = make_task(task_store)
    runtime = RecordingRuntimeService()
    planner = service(task_store, runtime)
    proposal = planner.propose(UserContext("t-1", "u-1", "employee"), task.id, "目标", "key-1")

    with pytest.raises(PlanProposalStateConflict, match="审批"):
        planner.start_run(UserContext("t-1", "u-1", "employee"), proposal.proposal_id, "mock", "product_manager")

    planner.approve(UserContext("t-1", "ceo-1", "ceo"), proposal.proposal_id)
    run_id, runtime_key, policy_version = planner.start_run(
        UserContext("t-1", "u-1", "employee"), proposal.proposal_id, "mock", "product_manager"
    )

    assert (run_id, runtime_key, policy_version) == ("run-1", "mock", "policy-1")
    assert runtime.calls[0][0] == task.id
    assert runtime.calls[0][2] == [{"step_id": "step-1", "tool": "knowledge.search", "kind": "read"}]


def test_get_hides_other_tenant_proposal() -> None:
    from app.domain import TaskStore

    task_store = TaskStore()
    task = make_task(task_store)
    planner = service(task_store)
    proposal = planner.propose(UserContext("t-1", "u-1", "employee"), task.id, "目标", "key-1")

    with pytest.raises(PlanProposalNotFound):
        planner.get(UserContext("t-other", "u-1", "employee"), proposal.proposal_id)


def test_approval_of_unknown_proposal_is_not_found() -> None:
    from app.domain import TaskStore

    planner = service(TaskStore())

    with pytest.raises(PlanProposalNotFound):
        planner.approve(UserContext("t-1", "ceo-1", "ceo"), "plan-missing")


def test_generation_failure_does_not_persist_a_proposal() -> None:
    from app.domain import TaskStore

    class ExplodingGenerator:
        key = "mock"
        model_name = None

        def generate(self, goal, *, catalog, max_steps):
            raise PlanGenerationError("模型调用失败")

    task_store = TaskStore()
    task = make_task(task_store)
    planner = PlannerService(
        task_store=task_store,
        store=InMemoryPlanProposalStore(),
        generator=ExplodingGenerator(),
        catalog=catalog(),
        runtime_service=RecordingRuntimeService(),
        max_steps=5,
    )

    with pytest.raises(PlanGenerationError):
        planner.propose(UserContext("t-1", "u-1", "employee"), task.id, "目标", "key-1")

    assert planner.store.list_for_task("t-1", task.id) == []
```

- [ ] **Step 2: 运行测试确认失败**

Run: `py -m pytest tests/test_planner_service.py -q`
Expected: FAIL，`ModuleNotFoundError: No module named 'app.planner.service'`

- [ ] **Step 3: 实现服务**

`app/planner/service.py`：

```python
from __future__ import annotations

from typing import Any

from app.domain import PolicyError, Task, UserContext, ensure_can_approve

from .generator import PlanGenerator
from .models import (
    PlanProposal,
    PlanProposalNotFound,
    PlanProposalStateConflict,
    PlanStatus,
    PlannerAccessDenied,
    ToolCatalog,
    normalize_steps,
)
from .store import PlanProposalStore


_ELEVATED_ROLES = {"ceo", "super_admin"}


class PlannerService:
    def __init__(
        self,
        *,
        task_store: Any,
        store: PlanProposalStore,
        generator: PlanGenerator,
        catalog: ToolCatalog,
        runtime_service: Any,
        max_steps: int,
    ) -> None:
        self.task_store = task_store
        self.store = store
        self.generator = generator
        self.catalog = catalog
        self.runtime_service = runtime_service
        self.max_steps = max_steps

    def propose(
        self, actor: UserContext, task_id: str, goal: str, idempotency_key: str
    ) -> PlanProposal:
        task = self._task(actor, task_id)
        normalized_goal = goal.strip() if isinstance(goal, str) else ""
        if not normalized_goal:
            raise ValueError("目标不能为空")

        existing = self.store.find_by_idempotency(actor.tenant_id, task.id, idempotency_key)
        if existing is not None:
            return existing

        self.catalog.require_configured()
        raw_steps = self.generator.generate(normalized_goal, catalog=self.catalog, max_steps=self.max_steps)
        steps = normalize_steps(raw_steps, self.catalog, max_steps=self.max_steps)
        proposal = PlanProposal(
            task_id=task.id,
            tenant_id=actor.tenant_id,
            goal=normalized_goal,
            steps=steps,
            generator_key=self.generator.key,
            generator_model=self.generator.model_name,
            created_by=actor.user_id,
            idempotency_key=idempotency_key,
        )
        return self.store.add(proposal)

    def get(self, actor: UserContext, proposal_id: str) -> PlanProposal:
        proposal = self.store.get(actor.tenant_id, proposal_id)
        self._ensure_can_view(actor, proposal)
        return proposal

    def approve(self, actor: UserContext, proposal_id: str) -> PlanProposal:
        proposal = self.store.get(actor.tenant_id, proposal_id)
        self._ensure_approver(actor, proposal)
        return self.store.mark_approved(proposal_id, reviewer=actor.user_id)

    def reject(self, actor: UserContext, proposal_id: str, reason: str) -> PlanProposal:
        proposal = self.store.get(actor.tenant_id, proposal_id)
        self._ensure_approver(actor, proposal)
        normalized_reason = reason.strip() if isinstance(reason, str) else ""
        if not normalized_reason:
            raise ValueError("驳回原因不能为空")
        return self.store.mark_rejected(proposal_id, reason=normalized_reason, reviewer=actor.user_id)

    def start_run(
        self, actor: UserContext, proposal_id: str, runtime_key: str, mode: str
    ) -> tuple[str, str, str]:
        proposal = self.store.get(actor.tenant_id, proposal_id)
        self._ensure_can_view(actor, proposal)
        if proposal.status is not PlanStatus.APPROVED:
            raise PlanProposalStateConflict("计划必须先通过审批才能执行")
        steps = [step.to_step_dict() for step in proposal.steps]
        return self.runtime_service.start(actor, proposal.task_id, runtime_key, steps, mode)

    def _task(self, actor: UserContext, task_id: str) -> Task:
        task = self.task_store.get(actor, task_id)
        if actor.user_id != task.created_by and actor.role not in _ELEVATED_ROLES:
            raise PlannerAccessDenied("当前员工无权操作此任务")
        return task

    @staticmethod
    def _ensure_can_view(actor: UserContext, proposal: PlanProposal) -> None:
        if actor.user_id != proposal.created_by and actor.role not in _ELEVATED_ROLES:
            raise PlannerAccessDenied("当前员工无权查看此计划")

    @staticmethod
    def _ensure_approver(actor: UserContext, proposal: PlanProposal) -> None:
        ensure_can_approve(actor)
        if actor.user_id == proposal.created_by:
            raise PolicyError("发起人不能审批自己提交的计划")
```

- [ ] **Step 4: 运行测试确认通过**

Run: `py -m pytest tests/test_planner_service.py -q`
Expected: PASS（11 passed）

- [ ] **Step 5: 跑全量测试确认无回归**

Run: `py -m pytest -o addopts=""`
Expected: 全部通过（295 + 新增用例）

- [ ] **Step 6: 提交**

```bash
git add app/planner/service.py tests/test_planner_service.py
git commit -m "feat: 增加计划生成与审批服务"
```

---

### Task 5: 配置与装配

**Files:**
- Modify: `app/settings.py`
- Modify: `app/bootstrap.py`
- Test: `tests/test_planner_bootstrap.py`

- [ ] **Step 1: 写失败测试**

```python
import pytest
from pydantic import ValidationError

from app.bootstrap import build_planner_service
from app.planner.generator import MockPlanGenerator, OpenAICompatiblePlanGenerator
from app.planner.models import ToolCatalog
from app.planner.store import InMemoryPlanProposalStore
from app.settings import Settings


def memory_settings(**overrides) -> Settings:
    base = {
        "env": "development",
        "storage_backend": "memory",
        "planner_backend": "mock",
        "planner_tools": '[{"name": "knowledge.search", "kind": "read"}]',
        "planner_max_steps": 5,
    }
    base.update(overrides)
    return Settings(**base)


def test_memory_backend_builds_mock_planner() -> None:
    service, store = build_planner_service(memory_settings())

    assert isinstance(store, InMemoryPlanProposalStore)
    assert isinstance(service.generator, MockPlanGenerator)
    assert service.catalog.names() == ("knowledge.search",)
    assert service.max_steps == 5


def test_openai_backend_requires_connection_settings() -> None:
    with pytest.raises(ValueError, match="地址、模型名和 API Key"):
        build_planner_service(
            memory_settings(
                planner_backend="openai_compatible",
                planner_model_base_url="",
                planner_model_name="",
                planner_model_api_key="",
            )
        )


def test_openai_backend_builds_model_generator() -> None:
    service, _store = build_planner_service(
        memory_settings(
            planner_backend="openai_compatible",
            planner_model_base_url="https://model.example/v1",
            planner_model_name="planner-small",
            planner_model_api_key="secret-key",
        )
    )

    assert isinstance(service.generator, OpenAICompatiblePlanGenerator)
    assert service.generator.model_name == "planner-small"


def test_unsupported_backend_and_bad_tools_are_rejected() -> None:
    with pytest.raises(ValueError, match="规划生成后端"):
        build_planner_service(memory_settings(planner_backend="other"))

    with pytest.raises(ValueError, match="工具白名单"):
        build_planner_service(memory_settings(planner_tools="not-json"))


def test_planner_max_steps_bounds() -> None:
    assert Settings().planner_max_steps == 10

    with pytest.raises(ValidationError):
        Settings(planner_max_steps=0)
    with pytest.raises(ValidationError):
        Settings(planner_max_steps=99)


def test_default_catalog_is_empty_and_config_parses() -> None:
    assert Settings().planner_tools == "[]"
    assert ToolCatalog.from_config(Settings().planner_tools).is_empty() is True
```

- [ ] **Step 2: 运行测试确认失败**

Run: `py -m pytest tests/test_planner_bootstrap.py -q`
Expected: FAIL，`ImportError: cannot import name 'build_planner_service'`

- [ ] **Step 3: 新增配置项**

在 `app/settings.py` 的 `Settings` 类中、`session_ttl_seconds` 之后追加：

```python
    planner_backend: str = Field(
        default="mock",
        validation_alias=AliasChoices("PLANNER_BACKEND", "WORKBENCH_PLANNER_BACKEND"),
    )
    planner_tools: str = Field(
        default="[]",
        validation_alias=AliasChoices("PLANNER_TOOLS", "WORKBENCH_PLANNER_TOOLS"),
    )
    planner_max_steps: int = Field(
        default=10,
        ge=1,
        le=50,
        validation_alias=AliasChoices("PLANNER_MAX_STEPS", "WORKBENCH_PLANNER_MAX_STEPS"),
    )
    planner_model_base_url: str = Field(
        default="",
        validation_alias=AliasChoices("PLANNER_MODEL_BASE_URL", "WORKBENCH_PLANNER_MODEL_BASE_URL"),
    )
    planner_model_name: str = Field(
        default="",
        validation_alias=AliasChoices("PLANNER_MODEL_NAME", "WORKBENCH_PLANNER_MODEL_NAME"),
    )
    planner_model_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("PLANNER_MODEL_API_KEY", "WORKBENCH_PLANNER_MODEL_API_KEY"),
    )
    planner_model_timeout_seconds: float = Field(
        default=30.0,
        ge=1,
        le=120,
        validation_alias=AliasChoices("PLANNER_MODEL_TIMEOUT_SECONDS", "WORKBENCH_PLANNER_MODEL_TIMEOUT_SECONDS"),
    )
```

在 `validate_runtime_settings` 中、`content_generation_backend` 校验之后追加：

```python
    if settings.planner_backend not in {"mock", "openai_compatible"}:
        raise ValueError("不支持的规划生成后端")
```

- [ ] **Step 4: 实现装配函数**

在 `app/bootstrap.py` 顶部 import 区加入：

```python
from .planner.generator import MockPlanGenerator
from .planner.models import ToolCatalog
from .planner.store import InMemoryPlanProposalStore
from .planner.service import PlannerService
```

在文件末尾追加：

```python
def build_planner_service(settings: Settings, *, task_store=None, runtime_service=None, connection=None, migrate: bool = True):
    """按存储模式装配计划生成服务。"""
    validate_runtime_settings(settings)
    catalog = ToolCatalog.from_config(settings.planner_tools)
    if settings.planner_backend == "mock":
        generator = MockPlanGenerator()
    elif settings.planner_backend == "openai_compatible":
        from .planner.generator import OpenAICompatiblePlanGenerator

        generator = OpenAICompatiblePlanGenerator(
            base_url=settings.planner_model_base_url,
            model_name=settings.planner_model_name,
            api_key=settings.planner_model_api_key,
            timeout_seconds=settings.planner_model_timeout_seconds,
        )
    else:
        raise ValueError("不支持的规划生成后端")

    if settings.storage_backend == "memory":
        if settings.env != "development":
            raise ValueError("生产环境禁止使用内存计划提案仓储")
        store = InMemoryPlanProposalStore()
    elif settings.storage_backend == "postgres":
        from .planner.store import PostgresPlanProposalStore

        if connection is None:
            from psycopg_pool import ConnectionPool

            database_url = settings.database_url.replace("postgresql+psycopg://", "postgresql://", 1)
            connection = ConnectionPool(database_url, min_size=1, max_size=10, open=True)
        if migrate:
            apply_migrations(connection, Path(__file__).resolve().parents[1] / "migrations")
        store = PostgresPlanProposalStore(connection)
    else:
        raise ValueError("不支持的计划提案存储类型")

    service = PlannerService(
        task_store=task_store,
        store=store,
        generator=generator,
        catalog=catalog,
        runtime_service=runtime_service,
        max_steps=settings.planner_max_steps,
    )
    return service, store
```

> 说明：`PostgresPlanProposalStore` 在 Task 7 创建，因此本任务只覆盖 Mock 后端与内存仓储；postgres 分支的装配测试放在 Task 7。

- [ ] **Step 5: 运行测试确认通过**

Run: `py -m pytest tests/test_planner_bootstrap.py -q`
Expected: PASS（6 passed）

- [ ] **Step 6: 跑全量测试确认无回归**

Run: `py -m pytest -o addopts=""`
Expected: 全部通过

- [ ] **Step 7: 提交**

```bash
git add app/settings.py app/bootstrap.py tests/test_planner_bootstrap.py
git commit -m "feat: 增加计划生成的配置与装配"
```

---

### Task 6: HTTP 接口

**Files:**
- Modify: `app/main.py`
- Test: `tests/test_planner_api.py`

- [ ] **Step 1: 写失败测试**

```python
import pytest
from fastapi.testclient import TestClient

from app import main
from app.domain import RiskLevel, Task, TaskStatus, UserContext
from app.main import app
from app.planner.generator import MockPlanGenerator
from app.planner.models import Tool, ToolCatalog
from app.planner.service import PlannerService
from app.planner.store import InMemoryPlanProposalStore

client = TestClient(app)


def headers(role: str = "employee", user_id: str = "u-1", tenant_id: str = "t-1") -> dict[str, str]:
    return {"X-Tenant-Id": tenant_id, "X-User-Id": user_id, "X-User-Role": role}


@pytest.fixture
def planner(monkeypatch) -> PlannerService:
    catalog = ToolCatalog(
        (
            Tool(name="knowledge.search", kind="read"),
            Tool(name="content.publish", kind="publish"),
        )
    )
    service = PlannerService(
        task_store=main.store,
        store=InMemoryPlanProposalStore(),
        generator=MockPlanGenerator(),
        catalog=catalog,
        runtime_service=main.runtime_service,
        max_steps=5,
    )
    monkeypatch.setattr(main, "planner_service", service)
    return service


def create_task(created_by: str = "u-1") -> str:
    task = Task(
        tenant_id="t-1",
        project_id=None,
        created_by=created_by,
        employee_key="content-operator",
        title="整理选题",
        risk_level=RiskLevel.LOW,
        budget=1,
        idempotency_key=f"api-{created_by}",
        request_fingerprint="fp",
        status=TaskStatus.QUEUED,
    )
    main.store.create(UserContext("t-1", created_by, "employee"), task)
    return task.id


def propose(task_id: str, *, key: str = "key-1", actor: str = "u-1") -> dict[str, object]:
    response = client.post(
        f"/api/v1/tasks/{task_id}/plan-proposals",
        headers=headers(user_id=actor),
        json={"goal": "整理本周公众号选题", "idempotency_key": key},
    )
    assert response.status_code == 201
    return response.json()


def test_propose_returns_server_derived_steps(planner: PlannerService) -> None:
    task_id = create_task()

    body = propose(task_id)

    assert body["status"] == "pending_review"
    assert body["steps"][0]["tool"] == "knowledge.search"
    assert body["steps"][0]["kind"] == "read"
    assert body["steps"][0]["requires_approval"] is False
    assert "generator" in body


def test_propose_is_idempotent(planner: PlannerService) -> None:
    task_id = create_task()

    first = propose(task_id, key="same-key")
    second = propose(task_id, key="same-key")

    assert first["proposal_id"] == second["proposal_id"]


def test_propose_requires_goal_and_idempotency_key(planner: PlannerService) -> None:
    task_id = create_task()

    missing_goal = client.post(
        f"/api/v1/tasks/{task_id}/plan-proposals",
        headers=headers(),
        json={"idempotency_key": "k"},
    )
    missing_key = client.post(
        f"/api/v1/tasks/{task_id}/plan-proposals",
        headers=headers(),
        json={"goal": "目标"},
    )

    assert missing_goal.status_code == 422
    assert missing_key.status_code == 422


def test_employee_cannot_approve_and_ceo_cannot_approve_own_proposal(planner: PlannerService) -> None:
    task_id = create_task()
    proposal_id = propose(task_id)["proposal_id"]

    assert (
        client.post(f"/api/v1/plan-proposals/{proposal_id}/approval", headers=headers()).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/v1/plan-proposals/{proposal_id}/approval", headers=headers(role="ceo", user_id="u-1")
        ).status_code
        == 403
    )


def test_ceo_approves_then_execution_starts(planner: PlannerService) -> None:
    task_id = create_task()
    proposal_id = propose(task_id)["proposal_id"]

    approved = client.post(
        f"/api/v1/plan-proposals/{proposal_id}/approval",
        headers=headers(role="ceo", user_id="ceo-1"),
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"

    blocked = client.post(
        f"/api/v1/plan-proposals/{proposal_id}/runs",
        headers=headers(user_id="u-9"),
        json={"runtime_key": "mock", "mode": "product_manager"},
    )
    assert blocked.status_code == 404

    started = client.post(
        f"/api/v1/plan-proposals/{proposal_id}/runs",
        headers=headers(),
        json={"runtime_key": "mock", "mode": "product_manager"},
    )
    assert started.status_code == 201
    assert started.json()["status"] == "running"


def test_execution_before_approval_conflicts(planner: PlannerService) -> None:
    task_id = create_task()
    proposal_id = propose(task_id)["proposal_id"]

    response = client.post(
        f"/api/v1/plan-proposals/{proposal_id}/runs",
        headers=headers(),
        json={"runtime_key": "mock", "mode": "product_manager"},
    )

    assert response.status_code == 409


def test_rejection_records_reason(planner: PlannerService) -> None:
    task_id = create_task()
    proposal_id = propose(task_id)["proposal_id"]

    response = client.post(
        f"/api/v1/plan-proposals/{proposal_id}/rejection",
        headers=headers(role="ceo", user_id="ceo-1"),
        json={"reason": "步骤不完整"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "rejected"
    assert response.json()["rejection_reason"] == "步骤不完整"


def test_get_hides_cross_tenant_proposal(planner: PlannerService) -> None:
    task_id = create_task()
    proposal_id = propose(task_id)["proposal_id"]

    hidden = client.get(
        f"/api/v1/plan-proposals/{proposal_id}",
        headers=headers(tenant_id="t-other"),
    )

    assert hidden.status_code == 404


def test_approval_of_unknown_proposal_is_not_found(planner: PlannerService) -> None:
    response = client.post(
        "/api/v1/plan-proposals/plan-missing/approval",
        headers=headers(role="ceo", user_id="ceo-1"),
    )

    assert response.status_code == 404


def test_proposal_view_does_not_leak_model_secrets(planner: PlannerService) -> None:
    task_id = create_task()

    body = propose(task_id)

    rendered = str(body).lower()
    for leaked in ("api_key", "authorization", "secret-key", "password", "token"):
        assert leaked not in rendered
    assert set(body) == {
        "proposal_id",
        "task_id",
        "goal",
        "status",
        "steps",
        "generator",
        "created_by",
        "created_at",
        "reviewed_by",
        "reviewed_at",
        "rejection_reason",
    }
```

- [ ] **Step 2: 运行测试确认失败**

Run: `py -m pytest tests/test_planner_api.py -q`
Expected: FAIL（接口未注册，大量 404）

- [ ] **Step 3: 实现接口**

在 `app/main.py` 的 import 区加入：

```python
from .planner.models import (
    PlanGenerationError,
    PlanProposalNotFound,
    PlanProposalStateConflict,
    PlannerAccessDenied,
    PlannerNotConfigured,
    UnknownTool,
)
```

把 `from .bootstrap import ...` 一行补上 `build_planner_service`（按字母序放在最前）。

在 `account_service, _ = build_account_service(settings)` 之后加入：

```python
planner_service, planner_store = build_planner_service(
    settings, task_store=store, runtime_service=runtime_service
)
```

在文件末尾追加请求模型、视图与 5 个接口：

```python
class PlanProposalCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal: str = Field(min_length=1, max_length=2_000)
    idempotency_key: str = Field(min_length=1, max_length=200)


class PlanProposalRejection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=500)


class PlanRunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    runtime_key: str = Field(default="mock", min_length=1, max_length=80)
    mode: str = Field(default="product_manager", pattern="^(product_manager|fde)$")


def _plan_view(proposal) -> dict[str, object]:
    return {
        "proposal_id": proposal.proposal_id,
        "task_id": proposal.task_id,
        "goal": proposal.goal,
        "status": proposal.status.value,
        "steps": [
            {
                "step_id": step.step_id,
                "tool": step.tool,
                "kind": step.kind,
                "requires_approval": step.requires_approval,
            }
            for step in proposal.steps
        ],
        "generator": {
            "key": proposal.generator_key,
            "model": proposal.generator_model,
        },
        "created_by": proposal.created_by,
        "created_at": proposal.created_at,
        "reviewed_by": proposal.reviewed_by,
        "reviewed_at": proposal.reviewed_at,
        "rejection_reason": proposal.rejection_reason,
    }


@app.post("/api/v1/tasks/{task_id}/plan-proposals", status_code=status.HTTP_201_CREATED)
def create_plan_proposal(
    task_id: str, payload: PlanProposalCreate, context: UserContext = Depends(current_user)
) -> dict[str, object]:
    try:
        proposal = planner_service.propose(
            context, task_id, payload.goal, payload.idempotency_key
        )
    except TaskNotFound as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc
    except PlannerAccessDenied as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc
    except PlannerNotConfigured as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (UnknownTool, PlanGenerationError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _plan_view(proposal)


@app.get("/api/v1/plan-proposals/{proposal_id}")
def get_plan_proposal(proposal_id: str, context: UserContext = Depends(current_user)) -> dict[str, object]:
    try:
        proposal = planner_service.get(context, proposal_id)
    except PlanProposalNotFound as exc:
        raise HTTPException(status_code=404, detail="计划提案不存在") from exc
    except PlannerAccessDenied as exc:
        raise HTTPException(status_code=404, detail="计划提案不存在") from exc
    return _plan_view(proposal)


@app.post("/api/v1/plan-proposals/{proposal_id}/approval")
def approve_plan_proposal(proposal_id: str, context: UserContext = Depends(current_user)) -> dict[str, object]:
    try:
        proposal = planner_service.approve(context, proposal_id)
    except PlanProposalNotFound as exc:
        raise HTTPException(status_code=404, detail="计划提案不存在") from exc
    except PlanProposalStateConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PolicyError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return _plan_view(proposal)


@app.post("/api/v1/plan-proposals/{proposal_id}/rejection")
def reject_plan_proposal(
    proposal_id: str, payload: PlanProposalRejection, context: UserContext = Depends(current_user)
) -> dict[str, object]:
    try:
        proposal = planner_service.reject(context, proposal_id, payload.reason)
    except PlanProposalNotFound as exc:
        raise HTTPException(status_code=404, detail="计划提案不存在") from exc
    except PlanProposalStateConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PolicyError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _plan_view(proposal)


@app.post("/api/v1/plan-proposals/{proposal_id}/runs", status_code=status.HTTP_201_CREATED)
def start_plan_run(
    proposal_id: str, payload: PlanRunCreate, context: UserContext = Depends(current_user)
) -> dict[str, object]:
    try:
        run_id, runtime_key, policy_version = planner_service.start_run(
            context, proposal_id, payload.runtime_key, payload.mode
        )
    except PlanProposalNotFound as exc:
        raise HTTPException(status_code=404, detail="计划提案不存在") from exc
    except PlannerAccessDenied as exc:
        raise HTTPException(status_code=404, detail="计划提案不存在") from exc
    except PlanProposalStateConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RunAccessDenied as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc
    except (PolicyDenied, ApprovalRequired) as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=400, detail="运行时不可用") from exc
    return {
        "run_id": run_id,
        "runtime_key": runtime_key,
        "policy_version": policy_version,
        "status": "running",
    }
```

同时把 `PlannerNotConfigured` 加入上面第一条 import 块的符号列表。

- [ ] **Step 4: 运行测试确认通过**

Run: `py -m pytest tests/test_planner_api.py -q`
Expected: PASS（10 passed）

- [ ] **Step 5: 跑全量测试确认无回归**

Run: `py -m pytest -o addopts=""`
Expected: 全部通过

- [ ] **Step 6: 提交**

```bash
git add app/main.py tests/test_planner_api.py
git commit -m "feat: 增加计划提案接口"
```

---

### Task 7: PostgreSQL 迁移与仓储

**Files:**
- Create: `migrations/009_plan_proposals.sql`
- Modify: `app/planner/store.py`
- Modify: `tests/test_planner_bootstrap.py`
- Test: `tests/test_planner_postgres.py`

- [ ] **Step 1: 写失败测试**

新建 `tests/test_planner_postgres.py`：

```python
from datetime import UTC, datetime

import pytest

from app.bootstrap import build_planner_service
from app.planner.models import (
    PlanProposal,
    PlanProposalNotFound,
    PlanProposalStateConflict,
    PlanStatus,
)
from app.planner.store import PostgresPlanProposalStore
from app.settings import Settings


def postgres_settings() -> Settings:
    return Settings(
        env="production",
        storage_backend="postgres",
        database_url="postgresql://workbench:pw@pg.internal:5432/workbench",
        auth_secret="a" * 32,
        backup_encryption_key="b" * 32,
        content_store_backend="sqlite",
        planner_backend="mock",
        planner_tools='[{"name": "knowledge.search", "kind": "read"}]',
    )


def test_postgres_backend_uses_injected_connection() -> None:
    service, store = build_planner_service(postgres_settings(), connection=object(), migrate=False)

    assert isinstance(store, PostgresPlanProposalStore)
    assert service.store is store


class RecordingCursor:
    def __init__(self, rows: list[object]) -> None:
        self.rows = rows
        self.statements: list[tuple[str, tuple]] = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, statement: str, params: tuple = ()) -> None:
        self.statements.append((statement, params))

    def fetchone(self):
        return self.rows.pop(0)

    def fetchall(self):
        return self.rows.pop(0)


class RecordingTransaction:
    def __init__(self, connection) -> None:
        self.connection = connection

    def __enter__(self):
        self.connection.transaction_count += 1
        return self

    def __exit__(self, *_args):
        return False


class RecordingConnection:
    def __init__(self, rows: list[object]) -> None:
        self.cursor_instance = RecordingCursor(rows)
        self.transaction_count = 0

    def transaction(self):
        return RecordingTransaction(self)

    def cursor(self):
        return self.cursor_instance


def proposal_row(status: str = "pending_review") -> tuple:
    return (
        "plan-1",
        "task-1",
        "t-1",
        "整理选题",
        '[{"step_id": "s1", "tool": "knowledge.search", "kind": "read", "requires_approval": false, "args": {}}]',
        "mock",
        None,
        "u-1",
        "key-1",
        status,
        datetime(2026, 9, 10, tzinfo=UTC),
        None,
        None,
        None,
    )


def make_proposal() -> PlanProposal:
    return PlanProposal(
        task_id="task-1",
        tenant_id="t-1",
        goal="整理选题",
        steps=(),
        generator_key="mock",
        generator_model=None,
        created_by="u-1",
        idempotency_key="key-1",
    )


def test_postgres_add_uses_transaction_and_returns_hydrated_proposal() -> None:
    connection = RecordingConnection([proposal_row()])
    store = PostgresPlanProposalStore(connection)

    saved = store.add(make_proposal())

    assert saved.proposal_id == "plan-1"
    assert saved.status is PlanStatus.PENDING_REVIEW
    assert connection.transaction_count == 1
    statement = connection.cursor_instance.statements[0][0]
    assert "INSERT INTO workbench_plan_proposals" in statement


def test_postgres_add_passes_parameters_in_column_order() -> None:
    connection = RecordingConnection([proposal_row()])
    store = PostgresPlanProposalStore(connection)
    draft = make_proposal()

    store.add(draft)

    _statement, params = connection.cursor_instance.statements[0]
    assert len(params) == 14
    assert params[0] == draft.proposal_id
    assert params[1] == "task-1"
    assert params[2] == "t-1"


def test_postgres_get_hides_other_tenant() -> None:
    connection = RecordingConnection([None])
    store = PostgresPlanProposalStore(connection)

    with pytest.raises(PlanProposalNotFound):
        store.get("t-other", "plan-1")


def test_postgres_mark_approved_guards_pending_state() -> None:
    connection = RecordingConnection([proposal_row("approved")])
    store = PostgresPlanProposalStore(connection)

    approved = store.mark_approved("plan-1", reviewer="ceo-1")

    assert approved.status is PlanStatus.APPROVED
    statement = connection.cursor_instance.statements[0][0]
    assert "status = 'pending_review'" in statement


def test_postgres_mark_approved_conflicts_when_not_pending() -> None:
    connection = RecordingConnection([None, ("plan-1",)])
    store = PostgresPlanProposalStore(connection)

    with pytest.raises(PlanProposalStateConflict):
        store.mark_approved("plan-1", reviewer="ceo-1")


def test_postgres_mark_approved_not_found() -> None:
    connection = RecordingConnection([None, None])
    store = PostgresPlanProposalStore(connection)

    with pytest.raises(PlanProposalNotFound):
        store.mark_approved("plan-1", reviewer="ceo-1")


def test_postgres_find_by_idempotency_returns_none_when_absent() -> None:
    connection = RecordingConnection([None])
    store = PostgresPlanProposalStore(connection)

    assert store.find_by_idempotency("t-1", "task-1", "key-1") is None


def test_migration_009_defines_status_check_and_unique_idempotency() -> None:
    from pathlib import Path

    migration = Path("migrations/009_plan_proposals.sql").read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS workbench_plan_proposals" in migration
    assert "CHECK (status IN ('pending_review', 'approved', 'rejected'))" in migration
    assert "UNIQUE (tenant_id, task_id, idempotency_key)" in migration
```

在 `tests/test_planner_bootstrap.py` 中把 `test_unsupported_backend_and_bad_tools_are_rejected` 之后追加：

```python
def test_postgres_backend_requires_postgres_storage() -> None:
    with pytest.raises(ValueError, match="计划提案存储类型"):
        build_planner_service(memory_settings(storage_backend="sqlite"))
```

- [ ] **Step 2: 运行测试确认失败**

Run: `py -m pytest tests/test_planner_postgres.py -q`
Expected: FAIL，`ImportError: cannot import name 'PostgresPlanProposalStore'` 与 `FileNotFoundError`（迁移文件不存在）

- [ ] **Step 3: 写迁移文件**

`migrations/009_plan_proposals.sql`：

```sql
CREATE TABLE IF NOT EXISTS workbench_plan_proposals (
    proposal_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    goal TEXT NOT NULL,
    steps JSONB NOT NULL DEFAULT '[]'::jsonb,
    generator_key TEXT NOT NULL,
    generator_model TEXT,
    created_by TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending_review', 'approved', 'rejected')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    reviewed_by TEXT,
    reviewed_at TIMESTAMPTZ,
    rejection_reason TEXT,
    UNIQUE (tenant_id, task_id, idempotency_key)
);

CREATE INDEX IF NOT EXISTS idx_workbench_plan_proposals_task
    ON workbench_plan_proposals (tenant_id, task_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_workbench_plan_proposals_status
    ON workbench_plan_proposals (tenant_id, status);
```

- [ ] **Step 4: 实现 PostgreSQL 仓储**

在 `app/planner/store.py` 的 import 区补充：

```python
import json
from contextlib import contextmanager, nullcontext

from .models import PlanStepView
```

在文件末尾追加：

```python
class PostgresPlanProposalStore:
    """计划提案持久化；审批使用条件更新保证并发安全。"""

    _COLUMNS = (
        "proposal_id, task_id, tenant_id, goal, steps, generator_key, generator_model, "
        "created_by, idempotency_key, status, created_at, reviewed_by, reviewed_at, rejection_reason"
    )

    def __init__(self, connection_or_pool) -> None:
        self.connection = connection_or_pool

    @contextmanager
    def _connection(self):
        if hasattr(self.connection, "connection") and callable(self.connection.connection):
            with self.connection.connection() as connection:
                yield connection
        else:
            with nullcontext(self.connection) as connection:
                yield connection

    @staticmethod
    def _hydrate(row: tuple) -> PlanProposal:
        raw_steps = row[4]
        if isinstance(raw_steps, str):
            raw_steps = json.loads(raw_steps)
        steps = tuple(
            PlanStepView(
                step_id=str(item["step_id"]),
                tool=str(item["tool"]),
                kind=str(item["kind"]),
                requires_approval=bool(item["requires_approval"]),
                args=dict(item.get("args") or {}),
            )
            for item in raw_steps
        )
        return PlanProposal(
            proposal_id=str(row[0]),
            task_id=str(row[1]),
            tenant_id=str(row[2]),
            goal=str(row[3]),
            steps=steps,
            generator_key=str(row[5]),
            generator_model=row[6],
            created_by=str(row[7]),
            idempotency_key=str(row[8]),
            status=PlanStatus(str(row[9])),
            created_at=row[10] if isinstance(row[10], datetime) else datetime.now(UTC),
            reviewed_by=row[11],
            reviewed_at=row[12],
            rejection_reason=row[13],
        )

    @staticmethod
    def _serialize(steps: tuple[PlanStepView, ...]) -> str:
        return json.dumps(
            [
                {
                    "step_id": step.step_id,
                    "tool": step.tool,
                    "kind": step.kind,
                    "requires_approval": step.requires_approval,
                    "args": step.args,
                }
                for step in steps
            ],
            ensure_ascii=False,
        )

    def add(self, proposal: PlanProposal) -> PlanProposal:
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""
                        INSERT INTO workbench_plan_proposals ({self._COLUMNS})
                        VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (tenant_id, task_id, idempotency_key) DO NOTHING
                        RETURNING {self._COLUMNS}
                        """,
                        (
                            proposal.proposal_id,
                            proposal.task_id,
                            proposal.tenant_id,
                            proposal.goal,
                            self._serialize(proposal.steps),
                            proposal.generator_key,
                            proposal.generator_model,
                            proposal.created_by,
                            proposal.idempotency_key,
                            proposal.status.value,
                            proposal.created_at,
                            proposal.reviewed_by,
                            proposal.reviewed_at,
                            proposal.rejection_reason,
                        ),
                    )
                    row = cursor.fetchone()
                    if row is None:
                        cursor.execute(
                            f"""
                            SELECT {self._COLUMNS} FROM workbench_plan_proposals
                            WHERE tenant_id = %s AND task_id = %s AND idempotency_key = %s
                            """,
                            (proposal.tenant_id, proposal.task_id, proposal.idempotency_key),
                        )
                        row = cursor.fetchone()
        if row is None:
            raise PlanProposalNotFound(proposal.proposal_id)
        return self._hydrate(row)

    def get(self, tenant_id: str, proposal_id: str) -> PlanProposal:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT {self._COLUMNS} FROM workbench_plan_proposals
                    WHERE proposal_id = %s AND tenant_id = %s
                    """,
                    (proposal_id, tenant_id),
                )
                row = cursor.fetchone()
        if row is None:
            raise PlanProposalNotFound(proposal_id)
        return self._hydrate(row)

    def find_by_idempotency(self, tenant_id: str, task_id: str, idempotency_key: str) -> PlanProposal | None:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT {self._COLUMNS} FROM workbench_plan_proposals
                    WHERE tenant_id = %s AND task_id = %s AND idempotency_key = %s
                    """,
                    (tenant_id, task_id, idempotency_key),
                )
                row = cursor.fetchone()
        return self._hydrate(row) if row is not None else None

    def list_for_task(self, tenant_id: str, task_id: str) -> list[PlanProposal]:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT {self._COLUMNS} FROM workbench_plan_proposals
                    WHERE tenant_id = %s AND task_id = %s ORDER BY created_at
                    """,
                    (tenant_id, task_id),
                )
                rows = cursor.fetchall()
        return [self._hydrate(row) for row in rows]

    def mark_approved(self, proposal_id: str, *, reviewer: str) -> PlanProposal:
        return self._review(proposal_id, reviewer=reviewer, status="approved", reason=None)

    def mark_rejected(self, proposal_id: str, *, reason: str, reviewer: str) -> PlanProposal:
        return self._review(proposal_id, reviewer=reviewer, status="rejected", reason=reason)

    def _review(self, proposal_id: str, *, reviewer: str, status: str, reason: str | None) -> PlanProposal:
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""
                        UPDATE workbench_plan_proposals
                        SET status = %s, reviewed_by = %s, reviewed_at = now(), rejection_reason = %s
                        WHERE proposal_id = %s AND status = 'pending_review'
                        RETURNING {self._COLUMNS}
                        """,
                        (status, reviewer, reason, proposal_id),
                    )
                    row = cursor.fetchone()
                    if row is None:
                        cursor.execute(
                            "SELECT proposal_id FROM workbench_plan_proposals WHERE proposal_id = %s",
                            (proposal_id,),
                        )
                        if cursor.fetchone() is None:
                            raise PlanProposalNotFound(proposal_id)
                        raise PlanProposalStateConflict("该提案当前状态不允许审批")
        return self._hydrate(row)
```

- [ ] **Step 5: 运行测试确认通过**

Run: `py -m pytest tests/test_planner_postgres.py tests/test_planner_bootstrap.py -q`
Expected: PASS

- [ ] **Step 6: 跑全量测试与编译检查**

Run: `py -m pytest -o addopts=""`
Expected: 全部通过

Run: `py -m compileall -q app tests extract_pdf.py scripts`
Expected: 退出码 0

- [ ] **Step 7: 提交**

```bash
git add migrations/009_plan_proposals.sql app/planner/store.py tests/test_planner_postgres.py tests/test_planner_bootstrap.py
git commit -m "feat: 增加计划提案 PostgreSQL 迁移与仓储"
```

---

### Task 8: 文档同步

**Files:**
- Modify: `docs/api-contract.md`
- Modify: `.env.example`
- Modify: `.env.staging.example`
- Modify: `docs/private-deployment-runbook.md`
- Modify: `docs/delivery-gates.md`

- [ ] **Step 1: 更新接口契约**

在 `docs/api-contract.md` 的「## Agent Runtime 运行」小节之前插入：

```markdown
## 计划生成与审核

员工用自然语言描述目标，服务端依据工具白名单生成一份可审核的 Agent 计划。计划的步骤、`kind` 与是否需要审批**一律由服务端按工具白名单推导**，生成器（含真实模型）提供的同类字段被忽略；未知工具会导致整份计划被拒绝。计划挂在既有任务上，审核通过后复用既有 Runtime 执行。

`POST /api/v1/tasks/{task_id}/plan-proposals`

在指定任务下提交目标并生成计划提案。请求体为 `{ "goal": "...", "idempotency_key": "..." }`。首次创建返回 `201` 与提案视图；相同租户、任务与幂等键重放返回既有提案。未配置任何可用工具返回 `422`；生成结果不合法（未知工具、步骤数超限、参数含敏感字段）返回 `422`；跨租户或无权任务返回 `404`。

`GET /api/v1/plan-proposals/{proposal_id}`

查看提案与服务端推导后的步骤。跨租户或不存在统一返回 `404`。

`POST /api/v1/plan-proposals/{proposal_id}/approval`

仅 CEO 或超级管理员可调用，且**发起人不能审批自己提交的计划**；否则返回 `403`。只允许 `pending_review` 状态，重复审批返回 `409`。

`POST /api/v1/plan-proposals/{proposal_id}/rejection`

仅 CEO 或超级管理员可调用。请求体为 `{ "reason": "..." }`，只允许 `pending_review` 状态。

`POST /api/v1/plan-proposals/{proposal_id}/runs`

审核通过后启动运行。请求体为 `{ "runtime_key": "...", "mode": "..." }`。未通过审批返回 `409`；跨租户返回 `404`；运行时不可用返回 `400`。执行时由服务端从任务快照重建租户、岗位、预算与策略版本，客户端不能覆盖。

提案视图包含提案号、任务号、目标、步骤（含服务端推导的 `kind` 与 `requires_approval`）、状态、生成器标识与时间；不包含模型密钥、原始模型响应或内部提示词。
```

- [ ] **Step 2: 更新环境示例**

在 `.env.example` 末尾追加：

```dotenv
WORKBENCH_PLANNER_BACKEND=mock
WORKBENCH_PLANNER_TOOLS=[]
WORKBENCH_PLANNER_MAX_STEPS=10
WORKBENCH_PLANNER_MODEL_BASE_URL=
WORKBENCH_PLANNER_MODEL_NAME=
WORKBENCH_PLANNER_MODEL_API_KEY=
WORKBENCH_PLANNER_MODEL_TIMEOUT_SECONDS=30
```

并在该行组上方加一行注释说明工具白名单的 JSON 形状：

```dotenv
# 工具白名单示例（部署必须显式声明已接通的工具，默认空表示不启用计划生成）：
# WORKBENCH_PLANNER_TOOLS=[{"name":"knowledge.search","kind":"read"}]
```

- [ ] **Step 3: 同步迁移清单**

把 `.env.staging.example` 的 `WORKBENCH_APPLIED_MIGRATIONS` 行末尾追加 `,009_plan_proposals`，即：

```dotenv
WORKBENCH_APPLIED_MIGRATIONS=001_initial,002_event_outbox,003_dead_letters,004_knowledge_access_bindings,005_knowledge_access_audit,006_commercial_g0,007_commercial_retention,008_accounts,009_plan_proposals
```

把 `docs/private-deployment-runbook.md` 中的迁移范围 `001` 至 `008` 更新为 `001` 至 `009`。

- [ ] **Step 4: 更新交付门禁**

在 `docs/delivery-gates.md` 的当前阶段列表中追加：

```markdown
- [x] 计划生成与审核闸门：目标到 AgentPlan 提案、服务端风险推导、审批后复用既有 Runtime（开发期接口验证）
- [ ] 计划执行的反馈与指标采集（子项目②）
- [ ] 基于指标的编排优化提案（子项目③）
```

- [ ] **Step 5: 验证**

Run: `py -m pytest -o addopts=""`
Expected: 全部通过

Run: `py -m compileall -q app tests extract_pdf.py scripts`
Expected: 退出码 0

Run: `py -c "from pathlib import Path; from scripts.commercial_g0_preflight import run_preflight; expected=sorted(p.stem for p in Path('migrations').glob('*.sql')); v={'environment':'staging','storage_backend':'postgres','database_url':'postgresql://u:p@h/db','auth_secret':'a'*32,'backup_key':'b'*32,'applied_migrations':expected,'expected_migrations':expected,'retention_policy':{'tasks':180},'runtime_versions':{'mock':'0.1.0'}}; print([(c.name,c.status) for c in run_preflight(v).checks if '迁移' in c.name])"`
Expected: `[('迁移状态', 'pass')]`

Run: `git diff --check`
Expected: 无输出

- [ ] **Step 6: 提交**

```bash
git add docs/api-contract.md .env.example .env.staging.example docs/private-deployment-runbook.md docs/delivery-gates.md
git commit -m "docs: 同步计划提案接口契约与配置"
```

---

## 验收对照

| 规格要求 | 对应任务 |
| --- | --- |
| 工具白名单与 kind 映射 | Task 1 |
| 步骤归一化、忽略模型自证的 kind/审批 | Task 1 |
| 未知工具拒绝整份计划 | Task 1、Task 3 |
| 提案状态机与租户隔离 | Task 2 |
| Mock 生成器确定性 | Task 3 |
| 真实模型后端、失败不降级 | Task 3 |
| 生成、审批、驳回、执行编排 | Task 4 |
| 发起人不能自审、仅 CEO/超管可审批 | Task 4、Task 6 |
| 未审批不可执行、执行复用 RuntimeService | Task 4、Task 6 |
| 可切换生成后端与配置校验 | Task 5 |
| 5 个接口与错误码 | Task 6 |
| PostgreSQL 持久化与迁移 | Task 7 |
| 接口契约、环境示例、迁移清单、交付门禁 | Task 8 |

## 明确不做

反馈驱动的自动优化（子项目③）、指标采集（子项目②）、自动执行、可视化编排编辑器、新建独立工作流领域对象、允许模型决定工具白名单与风险等级。真实模型效果与工具真实执行能力仍需单独验收，不得据此宣称已上线。
