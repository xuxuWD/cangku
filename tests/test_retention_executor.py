"""保留策略执行器（B-4 选项 C，2026-09-19）的单元与装配守护。

覆盖范围（**真库删除语义**另见 `tests/test_retention_executor_postgres.py`）：
  - 账本**结转恒等式**：总额逐分不变（含冲正对）、同 `cutoff` 重放不双算、后到的过期行并入净额、
    无过期行时不写零额行；
  - 服务层编排：保留期取值（默认 / 自定义）、逐租户遍历、审计只记受控键且**空转不落审计**、
    删除通道 / 账本 / 审计三者缺一 **fail-closed**；
  - worker 装配：beat 条目与间隔、未接线返回零值（不伪造）、委派调用、
    `configure_runtime` 的**静态钉住**（漏注入即红 —— 沿用 2026-09-19 的教训：静默少注入一面 =
    生产漏清一面）；
  - 导出包 `usage` 类别含 `reason`（结转行在包内可识别）。
"""

from __future__ import annotations

import inspect
import re
from datetime import UTC, datetime, timedelta

import pytest

from app import worker
from app.audit.models import ALLOWED_DETAIL_KEYS, AuditAction
from app.audit.service import AuditService
from app.audit.store import InMemoryAuditStore
from app.commercial.lifecycle import DEFAULT_RETENTION_POLICY, CommercialLifecycleService
from app.commercial.repository import InMemoryCommercialRepository
from app.commercial.retention import RETENTION_PURGE_LIMIT
from app.commercial.usage import (
    CARRYOVER_REASON,
    InMemoryUsageLedger,
    UsageEntry,
    carryover_idempotency_key,
)
from app.settings import Settings

TENANT = "tenant-retention"
OTHER_TENANT = "tenant-retention-other"
NOW = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _clean_wiring(monkeypatch):
    """清空接线状态（`_ensure_runtime` 的判定读这些模块级全局，必须逐个列全）。"""
    for name in (
        "_outbox_publisher",
        "_lifecycle_runner",
        "_knowledge_review_scanner",
        "_runtime_event_purger",
        "_conversation_stream_purger",
        "_run_artifact_purger",
        "_crm_service",
        "_crm_notifier",
        "_runtime_builder",
    ):
        monkeypatch.setattr(worker, name, None)
    monkeypatch.setattr(worker, "_ensure_runtime", lambda: None)
    yield


class _PurgeStoreStub:
    """删除原语替身：记录调用参数 + 返回可控计数。

    **真库语义（先子后父 / 防孤儿谓词 / 审计面不删）由 PG 用例覆盖** —— 这里只验服务层编排
    （取哪个保留期、传哪个 cutoff、计数怎么汇总、审计怎么落）。
    """

    def __init__(self, counts: dict[str, int] | None = None) -> None:
        self.calls: list[dict[str, object]] = []
        self.counts = dict(counts or {})

    def purge_expired_for_tenant(
        self, tenant_id: str, *, cutoff: datetime, limit: int = RETENTION_PURGE_LIMIT
    ) -> dict[str, int]:
        self.calls.append({"tenant_id": tenant_id, "cutoff": cutoff, "limit": limit})
        return dict(self.counts)


# 服务层辅助：`audit` 缺省 = 新建一个内存审计（便于断言），显式传 None 才表示「未配置审计通道」。
_DEFAULT_AUDIT = object()


def _service(
    *,
    policy: dict[str, int] | None = None,
    purge: _PurgeStoreStub | None = None,
    ledger: InMemoryUsageLedger | None = None,
    audit: object = _DEFAULT_AUDIT,
    tenant: str = TENANT,
) -> CommercialLifecycleService:
    repository = InMemoryCommercialRepository()
    repository.ensure_test_tenant(tenant, owner_id="owner", admins=set())
    service = CommercialLifecycleService(
        repository,
        usage_ledger=ledger,
        retention_purge_store=purge,
        audit=AuditService(InMemoryAuditStore()) if audit is _DEFAULT_AUDIT else audit,
    )
    if policy is not None:
        service.retention_store.set(tenant, policy, actor_id="admin")
    return service


# ---------------------------------------------------------------- 账本结转恒等式


def test_carry_over_keeps_totals_cent_exact_with_misaligned_reversal() -> None:
    """过期窗口内只有**原件**、冲正行在窗口内（错位情形）时，`SUM` 前后仍**逐分不变**。"""
    ledger = InMemoryUsageLedger()
    expired_at = NOW - timedelta(days=500)
    fresh_at = NOW - timedelta(days=10)
    ledger.append(UsageEntry(idempotency_key="a", tenant_id=TENANT, units=100, cost_cents=250, occurred_at=expired_at))
    ledger.append(UsageEntry(idempotency_key="b", tenant_id=TENANT, units=50, cost_cents=125, occurred_at=expired_at))
    original = ledger.append(UsageEntry(idempotency_key="c", tenant_id=TENANT, units=30, cost_cents=75, occurred_at=expired_at))
    reversal = ledger.reverse(original.id, reason="误计费", actor_id="admin")  # 冲正发生在当前时刻（窗口内）
    ledger.append(UsageEntry(idempotency_key="d", tenant_id=TENANT, units=7, cost_cents=3, occurred_at=fresh_at))

    units_before, cents_before = ledger.total(TENANT), ledger.total_cost_cents(TENANT)
    cutoff = NOW - timedelta(days=365)

    result = ledger.carry_over_before(TENANT, cutoff=cutoff)

    # 3 行过期明细（原件 + 两条普通）⇒ 净额 100+50+30 = 180、250+125+75 = 450；
    # 冲正行（-30 / -75）留在窗口内 ⇒ 总额不变（**与是否含冲正对无关**，这里是最容易算错的错位情形）。
    assert result == {"rows": 3, "units": 180, "cost_cents": 450}
    assert ledger.total(TENANT) == units_before
    assert ledger.total_cost_cents(TENANT) == cents_before
    assert reversal.occurred_at >= cutoff

    rows, total = ledger.list_for_tenant(TENANT, limit=100, offset=0)
    carry = [row for row in rows if row.reason == CARRYOVER_REASON]
    assert total == 3, "结转后应剩「结转行 + 窗口内明细（冲正行 / 新行）」三行"
    assert len(carry) == 1
    assert carry[0].idempotency_key == carryover_idempotency_key(cutoff)
    assert (carry[0].units, carry[0].cost_cents) == (180, 450)
    assert carry[0].occurred_at == cutoff, "结转行的 occurred_at 必须落在截止时刻（下一轮据此前滚）"
    assert carry[0].reversal_of is None


def test_carry_over_replay_with_same_cutoff_is_idempotent() -> None:
    """同一 `cutoff` 重放：不重复结转、不重复删、总额不变（幂等键由确定性时刻派生）。"""
    ledger = InMemoryUsageLedger()
    ledger.append(
        UsageEntry(
            idempotency_key="a",
            tenant_id=TENANT,
            units=9,
            cost_cents=11,
            occurred_at=NOW - timedelta(days=400),
        )
    )
    cutoff = NOW - timedelta(days=365)
    units_before, cents_before = ledger.total(TENANT), ledger.total_cost_cents(TENANT)

    first = ledger.carry_over_before(TENANT, cutoff=cutoff)
    second = ledger.carry_over_before(TENANT, cutoff=cutoff)

    assert first == {"rows": 1, "units": 9, "cost_cents": 11}
    assert second == {"rows": 0, "units": 0, "cost_cents": 0}
    assert (ledger.total(TENANT), ledger.total_cost_cents(TENANT)) == (units_before, cents_before)
    rows, total = ledger.list_for_tenant(TENANT, limit=100, offset=0)
    assert total == 1 and rows[0].units == 9


def test_carry_over_absorbs_late_rows_written_after_first_pass() -> None:
    """首轮之后**迟到**的过期明细（同 `cutoff`）：并入既有结转行，总额仍逐分不变、不重复删。"""
    ledger = InMemoryUsageLedger()
    cutoff = NOW - timedelta(days=365)
    ledger.append(
        UsageEntry(
            idempotency_key="a",
            tenant_id=TENANT,
            units=9,
            cost_cents=11,
            occurred_at=NOW - timedelta(days=400),
        )
    )
    ledger.carry_over_before(TENANT, cutoff=cutoff)
    units_before, cents_before = ledger.total(TENANT), ledger.total_cost_cents(TENANT)

    # 迟到行：写入时刻晚于首轮，但业务时间落在截止时刻之前（例：补录/回填）。
    ledger.append(
        UsageEntry(
            idempotency_key="late",
            tenant_id=TENANT,
            units=4,
            cost_cents=6,
            occurred_at=cutoff - timedelta(days=1),
        )
    )
    units_before, cents_before = ledger.total(TENANT), ledger.total_cost_cents(TENANT)

    result = ledger.carry_over_before(TENANT, cutoff=cutoff)

    assert result == {"rows": 1, "units": 4, "cost_cents": 6}
    assert (ledger.total(TENANT), ledger.total_cost_cents(TENANT)) == (units_before, cents_before)
    rows, total = ledger.list_for_tenant(TENANT, limit=100, offset=0)
    assert total == 1, "迟到行应被并入结转行，而不是保留成第二行"
    assert (rows[0].units, rows[0].cost_cents) == (13, 17)


def test_carry_over_writes_no_zero_row_when_nothing_expired() -> None:
    """无过期明细时不写结转行（避免每轮空转都往账本塞一行零额）。"""
    ledger = InMemoryUsageLedger()
    ledger.append(
        UsageEntry(
            idempotency_key="fresh",
            tenant_id=TENANT,
            units=5,
            cost_cents=5,
            occurred_at=NOW - timedelta(days=1),
        )
    )

    result = ledger.carry_over_before(TENANT, cutoff=NOW - timedelta(days=365))

    assert result == {"rows": 0, "units": 0, "cost_cents": 0}
    rows, total = ledger.list_for_tenant(TENANT, limit=100, offset=0)
    assert total == 1 and rows[0].idempotency_key == "fresh"


def test_carry_over_leftovers_are_isolated_per_tenant() -> None:
    """结转只作用于本租户：他租户的过期明细不动。"""
    ledger = InMemoryUsageLedger()
    old = NOW - timedelta(days=400)
    ledger.append(UsageEntry(idempotency_key="a", tenant_id=TENANT, units=3, cost_cents=3, occurred_at=old))
    ledger.append(UsageEntry(idempotency_key="b", tenant_id=OTHER_TENANT, units=8, cost_cents=8, occurred_at=old))

    ledger.carry_over_before(TENANT, cutoff=NOW - timedelta(days=365))

    assert ledger.total(TENANT) == 3
    assert ledger.total(OTHER_TENANT) == 8
    other_rows, _total = ledger.list_for_tenant(OTHER_TENANT, limit=100, offset=0)
    assert [row.idempotency_key for row in other_rows] == ["b"]


# ---------------------------------------------------------------- 服务层编排


def test_service_uses_default_policy_for_tenants_without_custom_policy() -> None:
    """未自定义策略的租户按 `DEFAULT_RETENTION_POLICY` 清理（默认保留期是平台声明）。"""
    ledger = InMemoryUsageLedger()
    ledger.append(
        UsageEntry(
            idempotency_key="old",
            tenant_id=TENANT,
            units=1,
            cost_cents=1,
            occurred_at=NOW - timedelta(days=400),
        )
    )
    purge = _PurgeStoreStub()
    service = _service(purge=purge, ledger=ledger)

    service.purge_expired_data_for_tenant(TENANT, now=NOW)

    assert purge.calls[0]["cutoff"] == NOW - timedelta(days=DEFAULT_RETENTION_POLICY["tasks"])
    rows, _total = ledger.list_for_tenant(TENANT, limit=100, offset=0)
    assert rows[0].occurred_at == NOW - timedelta(days=DEFAULT_RETENTION_POLICY["usage"])


def test_service_honours_custom_policy_and_propagates_limit() -> None:
    ledger = InMemoryUsageLedger()
    purge = _PurgeStoreStub()
    service = _service(policy={"tasks": 10, "usage": 20}, purge=purge, ledger=ledger)

    service.purge_expired_data_for_tenant(TENANT, now=NOW, limit=7)

    assert purge.calls == [{"tenant_id": TENANT, "cutoff": NOW - timedelta(days=10), "limit": 7}]


def test_service_writes_audit_only_when_something_changed() -> None:
    """空转不落审计；有清理时审计只记受控键。"""
    audit_store = InMemoryAuditStore()
    quiet = _service(purge=_PurgeStoreStub(), ledger=InMemoryUsageLedger(), audit=AuditService(audit_store))

    quiet.purge_expired_data_for_tenant(TENANT, now=NOW)

    assert audit_store.query(TENANT, actions=[AuditAction.COMMERCIAL_RETENTION_PURGED]) == ([], 0)

    busy = _service(
        purge=_PurgeStoreStub(
            {"runs": 3, "run_artifacts": 4, "tool_actions": 5, "plan_proposals": 2, "orchestration_proposals": 1, "tasks": 6}
        ),
        ledger=InMemoryUsageLedger(),
        audit=AuditService(audit_store),
    )
    busy.purge_expired_data_for_tenant(TENANT, now=NOW)

    records, total = audit_store.query(TENANT, actions=[AuditAction.COMMERCIAL_RETENTION_PURGED])
    assert total == 1
    record = records[0]
    assert record.actor_id == "system:worker"
    assert record.target_type == "retention_policy"
    assert set(record.detail) <= ALLOWED_DETAIL_KEYS, "审计明细必须全在受控键白名单内"
    assert record.detail["runs_deleted"] == 3
    assert record.detail["tasks_deleted"] == 6
    assert record.detail["proposals_deleted"] == 3
    assert record.detail["cutoff"] == (NOW - timedelta(days=DEFAULT_RETENTION_POLICY["tasks"])).isoformat()


def test_service_counts_run_domain_across_child_tables() -> None:
    """`run_domain_deleted` 必须把**子表**也算进去（只数父表会低报清理量）。"""
    audit_store = InMemoryAuditStore()
    service = _service(
        purge=_PurgeStoreStub({"runs": 1, "run_artifacts": 2, "run_acceptance_decisions": 3, "runtime_states": 4}),
        ledger=InMemoryUsageLedger(),
        audit=AuditService(audit_store),
    )

    result = service.purge_expired_data_for_tenant(TENANT, now=NOW)

    assert result["runs_deleted"] == 1
    assert result["run_domain_deleted"] == 10


@pytest.mark.parametrize("missing", ["purge", "ledger", "audit"])
def test_service_fails_closed_when_any_channel_is_missing(missing: str) -> None:
    """三者缺一即拒绝执行 —— 既不「假装清过」返回零值，也不在无审计时销毁数据。"""
    service = _service(
        purge=None if missing == "purge" else _PurgeStoreStub(),
        ledger=None if missing == "ledger" else InMemoryUsageLedger(),
        audit=None if missing == "audit" else AuditService(InMemoryAuditStore()),
    )

    with pytest.raises(Exception) as excinfo:
        service.purge_expired_data_for_tenant(TENANT, now=NOW)

    assert "保留清理" in str(excinfo.value)


def test_across_tenants_iterates_every_tenant_and_sums_counts() -> None:
    """逐租户 = 全部登记租户（含未自定义策略者与 `deleted` 租户），计数求和、逐个调用。"""
    repository = InMemoryCommercialRepository()
    repository.ensure_test_tenant(TENANT, owner_id="owner", admins=set())
    other = repository.create_tenant("客户乙", owner_id="owner-2")
    purge = _PurgeStoreStub({"runs": 2, "tasks": 1})
    service = CommercialLifecycleService(
        repository,
        usage_ledger=InMemoryUsageLedger(),
        retention_purge_store=purge,
        audit=AuditService(InMemoryAuditStore()),
    )

    totals = service.purge_expired_data_across_tenants(now=NOW, limit=50)

    assert totals["tenants"] == 2
    assert totals["runs_deleted"] == 4
    assert totals["tasks_deleted"] == 2
    assert [call["tenant_id"] for call in purge.calls] == sorted([TENANT, other.id])
    assert all(call["limit"] == 50 for call in purge.calls)


# ---------------------------------------------------------------- worker 装配


def test_retention_purge_task_is_scheduled_alongside_existing_periodic_tasks() -> None:
    entry = worker.celery_app.conf.beat_schedule["retention-purge"]

    assert entry["task"] == "app.worker.purge_expired_tenant_data"
    assert entry["schedule"] == Settings().retention_purge_interval_seconds


def test_retention_purge_interval_defaults_and_bounds() -> None:
    field = Settings.model_fields["retention_purge_interval_seconds"]

    assert field.default == 3600
    assert Settings(retention_purge_interval_seconds=30).retention_purge_interval_seconds == 30
    assert (
        Settings(retention_purge_interval_seconds=7 * 24 * 3600).retention_purge_interval_seconds
        == 7 * 24 * 3600
    )
    for invalid in (29, 7 * 24 * 3600 + 1):
        with pytest.raises(Exception):
            Settings(retention_purge_interval_seconds=invalid)


def test_retention_purge_returns_zero_when_worker_is_not_wired() -> None:
    result = worker.purge_expired_tenant_data()

    assert result == {
        "tenants": 0,
        "runs_deleted": 0,
        "run_domain_deleted": 0,
        "tasks_deleted": 0,
        "proposals_deleted": 0,
        "usage_rows_deleted": 0,
        "usage_carried_units": 0,
        "usage_carried_cents": 0,
    }


def test_retention_purge_delegates_to_the_wired_lifecycle_runner() -> None:
    calls: list[dict[str, object]] = []

    class _Runner:
        def run_pending_jobs(self, *, limit: int = 100) -> dict[str, int]:
            return {"exports": 0, "deletions": 0}

        def purge_expired_data_across_tenants(self, **kwargs) -> dict[str, int]:
            calls.append(kwargs)
            return {"tenants": 2, "runs_deleted": 1, "run_domain_deleted": 3, "tasks_deleted": 0,
                    "proposals_deleted": 0, "usage_rows_deleted": 0, "usage_carried_units": 0,
                    "usage_carried_cents": 0}

    worker.configure_lifecycle(_Runner())

    result = worker.purge_expired_tenant_data()

    assert calls == [{}]
    assert result["tenants"] == 2 and result["run_domain_deleted"] == 3


def test_production_runtime_wires_both_retention_channels_non_none() -> None:
    """`build_commercial_components` 的 PG 分支**静态钉住**：账本与删除通道都必须非 None 注入。

    钉点的选择依据：两个通道由 `build_commercial_components`（bootstrap）内部构造并注入生命周期服务，
    worker 侧无需再传（`configure_runtime` 只传清场三面与读取器）。风险在于该函数里「漏注入 / 传 None」——
    那会让保留策略执行器**看起来在跑、实际不清理**（fail-closed 抛错或整面漏清），
    故用源码级断言把两个参数钉住：既排除「漏参数」也排除「传了 `None` 假装注入」。
    """
    from app import bootstrap

    source = inspect.getsource(bootstrap.build_commercial_components)
    # 只取 **PG 分支**（生产路径）：内存分支不装配删除通道是刻意行为（内存 `Task` 无创建时间）。
    marker = "repository = PostgresCommercialRepository(connection)"
    assert marker in source, "未找到 PG 分支（结构变了？请同步本用例）"
    pg_branch = source.split(marker, 1)[1]

    for param in ("usage_ledger", "retention_purge_store"):
        assert re.search(rf"{param}\s*=\s*(?!None\b)\S", pg_branch), (
            f"PG 分支的 {param} 缺失或传了 None ⇒ 保留策略执行器不会真正清理"
        )


# ---------------------------------------------------------------- 导出包口径


def test_usage_export_rows_carry_reason_so_carryover_is_recognizable() -> None:
    from app.commercial.export_readers import usage_export_reader

    ledger = InMemoryUsageLedger()
    ledger.append(
        UsageEntry(
            idempotency_key="a",
            tenant_id=TENANT,
            units=3,
            cost_cents=4,
            occurred_at=NOW - timedelta(days=400),
        )
    )
    ledger.carry_over_before(TENANT, cutoff=NOW - timedelta(days=365))
    ledger.append(
        UsageEntry(
            idempotency_key="b",
            tenant_id=TENANT,
            units=1,
            cost_cents=1,
            occurred_at=NOW - timedelta(days=1),
        )
    )

    rows, total = usage_export_reader(ledger)(TENANT, limit=100)

    assert total == 2
    reasons = {row["reason"] for row in rows}
    assert reasons == {CARRYOVER_REASON, None}, "结转行与普通明细必须可在包内区分"