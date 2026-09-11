from __future__ import annotations

from typing import Any

from app.audit.models import AuditAction
from app.audit.service import AuditService
from app.domain import PolicyError, UserContext, ensure_can_approve

from .models import (
    OrchestrationProposal,
    OrchestrationProposalKind,
)
from .store import OrchestrationProposalStore


class OrchestrationProposalService:
    """基于运行指标生成默认运行时切换提案；提案只做建议，绝不自动改配置。"""

    def __init__(
        self,
        store: OrchestrationProposalStore,
        *,
        metrics: Any,
        audit: AuditService,
        default_runtime_key: str,
        min_samples: int,
        improvement_threshold: float,
    ) -> None:
        self.store = store
        self.metrics = metrics
        self.audit = audit
        self.default_runtime_key = default_runtime_key
        self.min_samples = min_samples
        self.improvement_threshold = improvement_threshold

    def generate(
        self,
        actor: UserContext,
        *,
        kind: OrchestrationProposalKind | str = OrchestrationProposalKind.RUNTIME_DEFAULT,
    ) -> tuple[OrchestrationProposal | None, str]:
        try:
            resolved_kind = OrchestrationProposalKind(kind)
        except ValueError as exc:
            raise ValueError("不支持的优化提案类型") from exc
        if resolved_kind is not OrchestrationProposalKind.RUNTIME_DEFAULT:
            raise ValueError("不支持的优化提案类型")

        summary = self.metrics.summary(actor.tenant_id)
        by_runtime = summary.get("by_runtime") or []
        qualified = [
            item for item in by_runtime if int(item.get("run_count", 0)) >= self.min_samples
        ]
        if len(qualified) < 2:
            return (
                None,
                f"可用于比较的运行时不足（需至少 2 个且各自样本数不少于 {self.min_samples}）",
            )

        best = min(qualified, key=self._rank)
        if best["runtime_key"] == self.default_runtime_key:
            return None, "当前默认运行时已是表现最好的运行时，无需调整"

        current = next(
            (item for item in qualified if item["runtime_key"] == self.default_runtime_key), None
        )
        if current is None:
            return None, "当前默认运行时样本不足，暂不比较"

        improvement = float(best["task_completion_rate"]) - float(current["task_completion_rate"])
        if improvement < self.improvement_threshold:
            return None, "最优运行时的完成任务率提升未达到阈值，暂不建议切换"

        existing = self.store.find_pending(
            actor.tenant_id, resolved_kind, str(best["runtime_key"])
        )
        if existing is not None:
            return existing, existing.rationale

        rationale = (
            f"运行时 {best['runtime_key']} 的任务完成率 {float(best['task_completion_rate']):.2f}"
            f"（样本 {int(best['run_count'])}）高于当前默认 {self.default_runtime_key} 的"
            f" {float(current['task_completion_rate']):.2f}（样本 {int(current['run_count'])}），"
            f"建议将默认运行时切换为 {best['runtime_key']}。"
        )
        proposal = OrchestrationProposal(
            tenant_id=actor.tenant_id,
            kind=resolved_kind,
            current_value=self.default_runtime_key,
            proposed_value=str(best["runtime_key"]),
            rationale=rationale,
            metrics_snapshot={"current": dict(current), "proposed": dict(best)},
            created_by=actor.user_id,
        )
        saved = self.store.add(proposal)
        self.audit.record(
            AuditAction.ORCHESTRATION_PROPOSED,
            tenant_id=actor.tenant_id,
            actor_id=actor.user_id,
            target_type="orchestration_proposal",
            target_id=saved.proposal_id,
            detail={
                "kind": resolved_kind.value,
                "current_value": saved.current_value,
                "proposed_value": saved.proposed_value,
                "run_count": int(best["run_count"]),
            },
        )
        return saved, rationale

    def list(self, actor: UserContext, *, limit: int) -> list[OrchestrationProposal]:
        return self.store.list_for_tenant(actor.tenant_id, limit=limit)

    def get(self, actor: UserContext, proposal_id: str) -> OrchestrationProposal:
        return self.store.get(actor.tenant_id, proposal_id)

    def approve(self, actor: UserContext, proposal_id: str) -> OrchestrationProposal:
        proposal = self.store.get(actor.tenant_id, proposal_id)
        self._ensure_approver(actor, proposal)
        approved = self.store.mark_approved(proposal_id, reviewer=actor.user_id)
        self.audit.record(
            AuditAction.ORCHESTRATION_APPROVED,
            tenant_id=actor.tenant_id,
            actor_id=actor.user_id,
            target_type="orchestration_proposal",
            target_id=approved.proposal_id,
            detail={"kind": approved.kind.value, "proposed_value": approved.proposed_value},
        )
        return approved

    def reject(self, actor: UserContext, proposal_id: str, reason: str) -> OrchestrationProposal:
        proposal = self.store.get(actor.tenant_id, proposal_id)
        self._ensure_approver(actor, proposal)
        normalized_reason = reason.strip() if isinstance(reason, str) else ""
        if not normalized_reason:
            raise ValueError("驳回原因不能为空")
        rejected = self.store.mark_rejected(
            proposal_id, reason=normalized_reason, reviewer=actor.user_id
        )
        self.audit.record(
            AuditAction.ORCHESTRATION_REJECTED,
            tenant_id=actor.tenant_id,
            actor_id=actor.user_id,
            target_type="orchestration_proposal",
            target_id=rejected.proposal_id,
            detail={"reason": normalized_reason},
        )
        return rejected

    @staticmethod
    def _rank(item: dict[str, Any]) -> tuple[float, float, int, str]:
        return (
            -float(item.get("task_completion_rate", 0.0)),
            -float(item.get("tool_success_rate", 0.0)),
            -int(item.get("run_count", 0)),
            str(item["runtime_key"]),
        )

    @staticmethod
    def _ensure_approver(actor: UserContext, proposal: OrchestrationProposal) -> None:
        ensure_can_approve(actor)
        if actor.user_id == proposal.created_by:
            raise PolicyError("发起人不能审批自己提交的优化提案")
