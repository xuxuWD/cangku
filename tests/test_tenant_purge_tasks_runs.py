"""B2+B3 任务与运行层租户清场：面名上报 + 全龄原语语义（真库见 `..._postgres.py`）。

背景：`docs/superpowers/specs/2026-09-19-tenant-purge-expansion-design.md` §4.1 的 B2（任务域）与 B3（运行域）
在本轮**合为一面** `tasks_and_runs`：任务删除以「其运行已全部删除」为前提（`run_records.task_id` **无外键**），
拆成两面会留下「面名齐全、任务却按谓词被跳过」的假清场空间。本文件钉住两件事：
  1. 该面**只在注入时**上报（未注入必须如实不列 —— 不假装清过）；
  2. 上报即真调用同一删除原语（`delete_all_for_tenant`），且 `ALL_AGES_CUTOFF` 是「全龄」语义。
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.audit.models import AuditAction
from app.audit.service import AuditService
from app.audit.store import InMemoryAuditStore
from app.commercial.lifecycle import CommercialLifecycleService
from app.commercial.repository import InMemoryCommercialRepository
from app.commercial.retention import ALL_AGES_CUTOFF, RETENTION_PURGE_LIMIT
from app.commercial.tenant import Actor

TENANT_POLICY_KEYS = ("tasks_and_runs",)


class _PurgeStub:
    """删除原语替身：只记录调用（真库语义由 PG 用例覆盖）。"""

    def __init__(self, deleted: int = 7) -> None:
        self.calls: list[str] = []
        self.deleted = deleted

    def delete_all_for_tenant(self, tenant_id: str) -> int:
        self.calls.append(tenant_id)
        return self.deleted


def test_all_ages_cutoff_is_the_timestamptz_safe_maximum() -> None:
    """「全龄」= `datetime.max`（带时区）⇒ `started_at/created_at < cutoff` 恒真，且落在 TIMESTAMPTZ 取值域内。"""
    assert ALL_AGES_CUTOFF.tzinfo is UTC
    assert ALL_AGES_CUTOFF == datetime.max.replace(tzinfo=UTC)
    assert ALL_AGES_CUTOFF.year < 294276  # PostgreSQL TIMESTAMPTZ 上界（不溢出）
    assert RETENTION_PURGE_LIMIT >= 1


def _service(*, with_purge: bool) -> tuple[CommercialLifecycleService, str, AuditService, _PurgeStub]:
    repository = InMemoryCommercialRepository()
    tenant = repository.create_tenant("客户B2", owner_id="admin-1")
    repository.add_customer_admin(tenant.id, "admin-1")
    audit = AuditService(InMemoryAuditStore())
    stub = _PurgeStub()
    service = CommercialLifecycleService(
        repository,
        cooldown_days=7,
        audit=audit,
        retention_purge_store=stub if with_purge else None,
    )
    return service, tenant.id, audit, stub


def test_face_is_reported_only_when_the_purge_store_is_wired() -> None:
    for with_purge, expected, calls in (
        (True, ["tasks_and_runs"], 1),
        (False, [], 0),
    ):
        service, tenant_id, audit, stub = _service(with_purge=with_purge)
        actor = Actor("admin-1", "customer_admin")
        job = service.request_delete(actor, tenant_id)
        service.mark_final_exported(job.id)
        service.confirm_deletion(actor, tenant_id)

        service.execute_delete(tenant_id, now=job.execute_after)

        executed = [
            record
            for record in audit.store.list_recent(tenant_id)
            if record.action == AuditAction.COMMERCIAL_DELETION_EXECUTED
        ]
        assert executed[0].detail["cleared_categories"] == expected
        # 面名与真实调用必须同步：报了就要真调（否则是「面名齐全、实际没清」）。
        assert len(stub.calls) == calls