from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .domain import PolicyError, UserContext


class CapabilityState(StrEnum):
    ALLOWED = "allowed"
    REVIEW_REQUIRED = "review_required"
    DENIED = "denied"


@dataclass(frozen=True)
class CapabilityDecision:
    capability: str
    state: CapabilityState
    reason: str


HIGH_RISK_CAPABILITIES = frozenset(
    {
        "third_party_skill_install",
        "shell_execution",
        "privileged_sandbox",
        "knowledge_write",
        "prompt_update",
        "workflow_update",
    }
)


class CapabilityPolicy:
    """Central policy for capabilities that can change data or runtime behavior."""

    def authorize(
        self,
        context: UserContext,
        capability: str,
        *,
        environment: str = "development",
        approved: bool = False,
        scope: str | None = None,
    ) -> CapabilityDecision:
        if capability not in HIGH_RISK_CAPABILITIES:
            raise PolicyError("未知能力，已拒绝执行")
        if context.role not in {"ceo", "super_admin"}:
            raise PolicyError("当前岗位无权申请高风险能力")
        if not approved:
            return CapabilityDecision(capability, CapabilityState.REVIEW_REQUIRED, "需要管理员审核")

        if capability == "knowledge_write" and environment == "staging" and scope == "draft":
            return CapabilityDecision(capability, CapabilityState.ALLOWED, "仅允许在 staging 写入草稿")

        raise PolicyError("该能力必须经过专用灰度流程，不能直接启用")
