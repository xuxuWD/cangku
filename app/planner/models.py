from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from app.audit.redaction import has_sensitive_key
from app.runtime.contracts import ALLOWED_PLAN_KINDS, SIDE_EFFECT_KINDS


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

    def __post_init__(self) -> None:
        if self.kind not in ALLOWED_PLAN_KINDS:
            raise ValueError(f"工具 kind 非法：{self.kind}")
        if not self.name.strip():
            raise ValueError("工具名不能为空")

    @property
    def requires_approval(self) -> bool:
        return self.kind in SIDE_EFFECT_KINDS


class ToolCatalog:
    """服务端工具白名单；kind 与审批要求只由此处决定。"""

    def __init__(self, tools: tuple[Tool, ...] = ()) -> None:
        mapping: dict[str, Tool] = {}
        for tool in tools:
            if tool.name in mapping:
                raise ValueError(f"工具白名单存在重复工具名：{tool.name}")
            mapping[tool.name] = tool
        self._tools = mapping

    @classmethod
    def from_config(cls, values: object) -> ToolCatalog:
        if values is None:
            return cls()
        if isinstance(values, str):
            text = values.strip()
            if not text:
                raise ValueError("工具白名单必须是 JSON 数组")
            try:
                values = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError("工具白名单必须是 JSON 数组") from exc
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
        if has_sensitive_key(args):
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
