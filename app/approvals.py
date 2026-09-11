from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.audit.redaction import mask_phone
from app.domain import TaskNotFound, UserContext

KIND_TASK_APPROVAL = "task_approval"
KIND_PLAN_PROPOSAL = "plan_proposal"
KIND_ACCOUNT_REGISTRATION = "account_registration"
KIND_RUN_APPROVAL = "run_approval"

_APPROVER_ROLES = frozenset({"ceo", "super_admin"})
_SUPER_ADMIN_ROLE = "super_admin"

# 任务数据类没有 created_at：统一用可比较的最早时间兜底，保证排序不抛异常且稳定。
_FALLBACK_CREATED_AT = datetime.min.replace(tzinfo=UTC)
_FALLBACK_RUN_TITLE = "运行审批"
_COUNT_KEYS = (KIND_TASK_APPROVAL, KIND_PLAN_PROPOSAL, KIND_ACCOUNT_REGISTRATION, KIND_RUN_APPROVAL)


@dataclass(frozen=True)
class PendingApproval:
    kind: str
    target_id: str
    title: str
    requested_by: str | None
    created_at: datetime
    detail: dict[str, object]


def _as_utc(value: object) -> datetime:
    """把仓储返回的时间戳归一为带时区的 UTC；缺失或类型异常时退回兜底值。"""
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return _FALLBACK_CREATED_AT


class ApprovalsService:
    """聚合四类待审批事项：任务审批、计划提案、账号注册、运行内审批。

    权限按角色过滤：任务、计划提案与运行审批仅 ceo/super_admin；账号注册仅 super_admin。
    非审批角色返回空列表与全 0 计数，便于客户端轮询展示「暂无待办」。
    """

    def __init__(
        self, *, task_store: Any, proposal_store: Any, account_service: Any, run_approvals: Any = None
    ) -> None:
        self.task_store = task_store
        self.proposal_store = proposal_store
        self.account_service = account_service
        # 运行审批的来源（RuntimeService）；未注入时该类不参与聚合。
        self.run_approvals = run_approvals

    def pending(
        self, actor: UserContext, *, limit: int
    ) -> tuple[list[PendingApproval], dict[str, int]]:
        counts = {key: 0 for key in _COUNT_KEYS}
        counts["total"] = 0
        items: list[PendingApproval] = []

        if actor.role in _APPROVER_ROLES:
            tasks = self.task_store.list_pending_approval(actor.tenant_id, limit=limit)
            items.extend(self._task_item(task) for task in tasks)
            proposals = [
                proposal
                for proposal in self.proposal_store.list_pending_review(actor.tenant_id, limit=limit)
                # 审批动作禁止发起人自审，列表同样剔除，避免展示无法操作的事项。
                if proposal.created_by != actor.user_id
            ]
            items.extend(self._proposal_item(proposal) for proposal in proposals)
            # 运行内审批：只列非终态运行里仍待决议的项，并剔除发起人自审（与计划提案同一逻辑）。
            if self.run_approvals is not None:
                items.extend(
                    self._run_item(actor, item)
                    for item in self.run_approvals.list_pending_approvals(actor, limit=limit)
                    if item.requested_by != actor.user_id
                )

        if actor.role == _SUPER_ADMIN_ROLE:
            registrations = self.account_service.list_requests(actor)
            items.extend(self._registration_item(account) for account in registrations[:limit])

        items.sort(key=lambda item: item.created_at, reverse=True)
        for item in items:
            counts[item.kind] += 1
        counts["total"] = len(items)
        return items, counts

    @staticmethod
    def _task_item(task: Any) -> PendingApproval:
        return PendingApproval(
            kind=KIND_TASK_APPROVAL,
            target_id=task.id,
            title=task.title,
            requested_by=task.created_by,
            created_at=_FALLBACK_CREATED_AT,
            detail={"risk_level": task.risk_level.value, "employee_key": task.employee_key},
        )

    @staticmethod
    def _proposal_item(proposal: Any) -> PendingApproval:
        return PendingApproval(
            kind=KIND_PLAN_PROPOSAL,
            target_id=proposal.proposal_id,
            title=proposal.goal,
            requested_by=proposal.created_by,
            created_at=_as_utc(proposal.created_at),
            detail={"step_count": len(proposal.steps)},
        )

    @staticmethod
    def _registration_item(account: Any) -> PendingApproval:
        return PendingApproval(
            kind=KIND_ACCOUNT_REGISTRATION,
            target_id=account.account_id,
            title=mask_phone(account.phone),
            requested_by=None,
            created_at=_as_utc(account.requested_at),
            detail={"position": account.position},
        )

    def _run_item(self, actor: UserContext, item: Any) -> PendingApproval:
        return PendingApproval(
            kind=KIND_RUN_APPROVAL,
            target_id=item.run_id,
            title=self._run_title(actor, item.task_id),
            requested_by=item.requested_by,
            created_at=_as_utc(item.created_at),
            detail={
                "run_id": item.run_id,
                "approval_id": item.approval_id,
                "step_id": item.step_id,
                "tool": item.tool,
            },
        )

    def _run_title(self, actor: UserContext, task_id: str) -> str:
        """运行审批的标题取任务标题；任务不可见或已不存在时回落为通用文案。"""
        try:
            return str(self.task_store.get(actor, task_id).title)
        except TaskNotFound:
            return _FALLBACK_RUN_TITLE
