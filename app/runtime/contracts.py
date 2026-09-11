from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol


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


@dataclass(frozen=True)
class RuntimeEvent:
    run_id: str
    sequence: int
    event_type: RuntimeEventType
    payload: dict[str, Any] = field(default_factory=dict)

    def to_public_dict(self) -> dict[str, Any]:
        sensitive_keys = {
            "password",
            "cookie",
            "api_key",
            "secret",
            "token",
            "authorization",
            "access_token",
            "refresh_token",
            "session",
            "验证码",
        }

        def redact(value: Any) -> Any:
            if isinstance(value, dict):
                return {
                    key: "[已隐藏]" if key.lower() in sensitive_keys else redact(item)
                    for key, item in value.items()
                }
            if isinstance(value, list):
                return [redact(item) for item in value]
            return value

        return {
            "cursor": f"{self.run_id}:{self.sequence}",
            "run_id": self.run_id,
            "sequence": self.sequence,
            "event_type": self.event_type.value,
            "payload": redact(self.payload),
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
