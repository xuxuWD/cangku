from __future__ import annotations

from typing import Any

from app.agent_services import ModelGateway, ModelNotAllowed
from app.audit.models import AuditAction
from app.audit.service import AuditService
from app.domain import PolicyError, Task, UserContext, ensure_can_approve

from .classification import PLAN_GENERATION_CAPABILITY, classification_for_risk
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
        audit: AuditService,
        model_gateway: ModelGateway | None = None,
    ) -> None:
        self.task_store = task_store
        self.store = store
        self.generator = generator
        self.catalog = catalog
        self.runtime_service = runtime_service
        self.max_steps = max_steps
        self.audit = audit
        self.model_gateway = model_gateway

    def propose(
        self, actor: UserContext, task_id: str, goal: str, idempotency_key: str
    ) -> PlanProposal:
        task = self._task(actor, task_id)
        classification = classification_for_risk(task.risk_level)
        normalized_goal = goal.strip() if isinstance(goal, str) else ""
        if not normalized_goal:
            raise ValueError("目标不能为空")

        if self.model_gateway is not None and self.generator.model_name:
            route = self.model_gateway.choose(
                capability=PLAN_GENERATION_CAPABILITY,
                data_classification=classification.value,
                preferred=self.generator.model_name,
            )
            if route.model_key != self.generator.model_name:
                raise ModelNotAllowed("规划模型与网关判定不一致，已拒绝")

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
        saved = self.store.add(proposal)
        self.audit.record(
            AuditAction.PLAN_PROPOSED,
            tenant_id=actor.tenant_id,
            actor_id=actor.user_id,
            target_type="plan_proposal",
            target_id=saved.proposal_id,
            detail={"step_count": len(saved.steps), "generator": saved.generator_key, "data_classification": classification.value},
        )
        return saved

    def get(self, actor: UserContext, proposal_id: str) -> PlanProposal:
        proposal = self.store.get(actor.tenant_id, proposal_id)
        self._ensure_can_view(actor, proposal)
        return proposal

    def approve(self, actor: UserContext, proposal_id: str) -> PlanProposal:
        proposal = self.store.get(actor.tenant_id, proposal_id)
        self._ensure_approver(actor, proposal)
        approved = self.store.mark_approved(proposal_id, reviewer=actor.user_id)
        self.audit.record(
            AuditAction.PLAN_APPROVED,
            tenant_id=actor.tenant_id,
            actor_id=actor.user_id,
            target_type="plan_proposal",
            target_id=approved.proposal_id,
            detail={"step_count": len(approved.steps)},
        )
        return approved

    def reject(self, actor: UserContext, proposal_id: str, reason: str) -> PlanProposal:
        proposal = self.store.get(actor.tenant_id, proposal_id)
        self._ensure_approver(actor, proposal)
        normalized_reason = reason.strip() if isinstance(reason, str) else ""
        if not normalized_reason:
            raise ValueError("驳回原因不能为空")
        rejected = self.store.mark_rejected(proposal_id, reason=normalized_reason, reviewer=actor.user_id)
        self.audit.record(
            AuditAction.PLAN_REJECTED,
            tenant_id=actor.tenant_id,
            actor_id=actor.user_id,
            target_type="plan_proposal",
            target_id=rejected.proposal_id,
            detail={"reason": normalized_reason},
        )
        return rejected

    def start_run(
        self, actor: UserContext, proposal_id: str, runtime_key: str, mode: str
    ) -> tuple[str, str, str]:
        proposal = self.store.get(actor.tenant_id, proposal_id)
        self._ensure_can_view(actor, proposal)
        if proposal.status is not PlanStatus.APPROVED:
            raise PlanProposalStateConflict("计划必须先通过审批才能执行")
        steps = [step.to_step_dict() for step in proposal.steps]
        # 运行记录的写入统一由 RuntimeService 负责；这里只透传计划关联，避免两个写入者。
        run_id, runtime_key, policy_version = self.runtime_service.start(
            actor, proposal.task_id, runtime_key, steps, mode, proposal_id=proposal.proposal_id
        )
        self.store.mark_run_started(proposal.proposal_id, run_id)
        self.audit.record(
            AuditAction.PLAN_RUN_STARTED,
            tenant_id=actor.tenant_id,
            actor_id=actor.user_id,
            target_type="plan_proposal",
            target_id=proposal.proposal_id,
            detail={"runtime_key": runtime_key, "run_id": run_id},
        )
        return run_id, runtime_key, policy_version

    def _task(self, actor: UserContext, task_id: str) -> Task:
        """取任务；可见性由仓储统一判定：跨租户、不存在、或同租户但非发起人且非高权限，一律抛 TaskNotFound。"""
        return self.task_store.get(actor, task_id)

    @staticmethod
    def _ensure_can_view(actor: UserContext, proposal: PlanProposal) -> None:
        if actor.user_id != proposal.created_by and actor.role not in _ELEVATED_ROLES:
            raise PlannerAccessDenied("当前员工无权操作此计划")

    @staticmethod
    def _ensure_approver(actor: UserContext, proposal: PlanProposal) -> None:
        ensure_can_approve(actor)
        if actor.user_id == proposal.created_by:
            raise PolicyError("发起人不能审批自己提交的计划")
