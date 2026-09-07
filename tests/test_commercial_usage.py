import pytest

from app.commercial.plan import PlanVersion, QuotaService
from app.commercial.usage import InMemoryUsageLedger, UsageEntry, UsageLedgerError


def test_usage_is_idempotent_and_corrections_are_reversals():
    ledger = InMemoryUsageLedger()
    entry = ledger.append(
        UsageEntry(idempotency_key="run-1", tenant_id="t1", units=10, cost_cents=50)
    )

    assert ledger.append(entry) == entry
    correction = ledger.reverse(entry.id, reason="供应商回调重复", actor_id="admin-1")
    assert correction.reversal_of == entry.id
    assert ledger.total("t1") == 0
    with pytest.raises(UsageLedgerError):
        ledger.reverse(entry.id, reason="重复冲正", actor_id="admin-1")


def test_quota_policy_blocks_or_requires_approval_when_exceeded():
    plan = PlanVersion("pro-private", limits={"task_runs": 2, "model_cost_cents": 100})
    quota = QuotaService(plan)
    quota.consume("task_runs", 2)
    assert quota.check("task_runs", 1).action == "block"
    quota.set_overage_policy("model_cost_cents", "approval")
    assert quota.check("model_cost_cents", 101).action == "approval"


def test_plan_version_is_immutable_after_creation():
    limits = {"task_runs": 2}
    plan = PlanVersion("internal", limits=limits)
    limits["task_runs"] = 999
    assert plan.limits["task_runs"] == 2
