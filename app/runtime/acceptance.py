"""运行**结构判定**（P2c-4 §2.5「自动验收」）；口径源 `docs/api-contract.md`「运行结构判定」。

三条件**全满足** ⇒ `met`：

1. **步骤全部完成**：`completed_step_count >= step_count`（`step_count = 0` 视为满足——沿用既有展示口径）；
2. **无未决审批**：运行审批状态中无 `pending`；
3. **正常终态**：`finish_reason == run_completed`（`cancelled_by_user` / `step_failed` / `approval_rejected`
   与「尚未终态（`finish_reason` 为空）」一律**不算**）。

**不调模型、不写库、不改运行状态**：本模块是纯函数 + 一次只读组装（端点侧），
不做任何模型调用、不做任何状态回写（改接 LLM 或回写状态都会让 `tests/test_run_acceptance_api.py` 变红）。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable

from .records import FinishReason

# 唯一「正常终态」：由运行状态单向推导的受控枚举（不另写字面量，防两处漂移）。
NORMAL_FINISH_REASON = FinishReason.RUN_COMPLETED.value

PENDING_APPROVAL_STATUS = "pending"


class AcceptanceVerdict(StrEnum):
    MET = "met"
    UNMET = "unmet"


@dataclass(frozen=True)
class AcceptanceResult:
    """结构判定结论 + 三个分项（前端按分项解释「差在哪一条」）。"""

    verdict: AcceptanceVerdict
    steps_complete: bool
    no_pending_approvals: bool
    finish_reason_ok: bool
    completed_steps: int
    total_steps: int
    pending_approvals: int
    finish_reason: str | None
    status: str


def evaluate_acceptance(
    *,
    status: str,
    step_count: int,
    completed_step_count: int,
    finish_reason: str | None,
    approval_statuses: Iterable[str] = (),
) -> AcceptanceResult:
    """结构判定（纯函数）：只看运行已有字段，**不调模型、不改状态**。"""
    total = max(0, int(step_count))
    completed = max(0, int(completed_step_count))
    steps_complete = completed >= total
    pending = sum(1 for item in approval_statuses if str(item) == PENDING_APPROVAL_STATUS)
    no_pending_approvals = pending == 0
    finish_reason_ok = finish_reason == NORMAL_FINISH_REASON
    verdict = (
        AcceptanceVerdict.MET
        if steps_complete and no_pending_approvals and finish_reason_ok
        else AcceptanceVerdict.UNMET
    )
    return AcceptanceResult(
        verdict=verdict,
        steps_complete=steps_complete,
        no_pending_approvals=no_pending_approvals,
        finish_reason_ok=finish_reason_ok,
        completed_steps=completed,
        total_steps=total,
        pending_approvals=pending,
        finish_reason=finish_reason,
        status=str(status),
    )