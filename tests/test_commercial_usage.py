import pytest

from datetime import UTC, datetime

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


# ---------------------------------------------------------------------------
# B-2b（2026-09-19）：用量账本按租户列出（导出包 `usage` 类别的读取通道）
# ---------------------------------------------------------------------------


def test_in_memory_ledger_list_for_tenant_scopes_orders_and_counts():
    ledger = InMemoryUsageLedger()
    ledger.append(
        UsageEntry(
            idempotency_key="old", tenant_id="t1", units=1, cost_cents=10,
            occurred_at=datetime(2026, 9, 1, tzinfo=UTC),
        )
    )
    ledger.append(
        UsageEntry(
            idempotency_key="new", tenant_id="t1", units=2, cost_cents=20,
            occurred_at=datetime(2026, 9, 2, tzinfo=UTC),
        )
    )
    ledger.append(
        UsageEntry(
            idempotency_key="other", tenant_id="t2", units=5, cost_cents=50,
            occurred_at=datetime(2026, 9, 3, tzinfo=UTC),
        )
    )

    rows, total = ledger.list_for_tenant("t1", limit=10, offset=0)

    assert total == 2  # 计数按租户过滤，不含他租户
    assert [row.idempotency_key for row in rows] == ["old", "new"]  # 按发生时间升序
    assert all(row.tenant_id == "t1" for row in rows)

    page, same_total = ledger.list_for_tenant("t1", limit=1, offset=1)

    assert same_total == 2
    assert [row.idempotency_key for row in page] == ["new"]
