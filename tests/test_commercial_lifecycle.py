import json
from datetime import UTC, datetime, timedelta

import pytest

from app.audit.models import AuditAction
from app.audit.redaction import has_sensitive_key
from app.audit.service import AuditService
from app.audit.store import InMemoryAuditStore
from app.commercial.lifecycle import (
    EXPORT_PACKAGE_TTL,
    EXPORT_RESOURCE_CATEGORIES,
    UNIMPLEMENTED_EXPORT_CATEGORIES,
    CommercialLifecycleService,
    DeletionNotPending,
    InMemoryExportPackageStore,
    InMemoryLifecycleJobStore,
)
from app.commercial.repository import InMemoryCommercialRepository, ResourceNotFound
from app.commercial.tenant import Actor, CommercialPolicyError, TenantStatus


def seeded_service(cooldown_days=7):
    repository = InMemoryCommercialRepository()
    tenant = repository.create_tenant("客户 A", owner_id="owner-1")
    repository.add_customer_admin(tenant.id, "admin-1")
    service = CommercialLifecycleService(
        repository,
        cooldown_days=cooldown_days,
        audit=AuditService(InMemoryAuditStore()),
    )
    return repository, tenant, service


def test_export_is_async_and_never_contains_secrets():
    repository, tenant, service = seeded_service()
    job = service.request_export(Actor("admin-1", "customer_admin"), tenant.id)

    assert job.status == "queued"
    payload = service.build_export_payload(tenant.id)
    assert "api_key" not in payload
    assert "cookie" not in payload


def test_delete_requires_cooldown_and_final_export():
    repository, tenant, service = seeded_service(cooldown_days=7)
    job = service.request_delete(Actor("admin-1", "customer_admin"), tenant.id)

    assert job.status == "cooling_down"
    with pytest.raises(CommercialPolicyError):
        service.execute_delete(tenant.id, now=job.execute_after)
    service.mark_final_exported(job.id)
    service.execute_delete(tenant.id, now=job.execute_after)
    assert service.tenant_status(tenant.id) == TenantStatus.DELETED


def test_retention_policy_has_positive_days_and_is_audited():
    repository, tenant, service = seeded_service()
    service.set_retention(tenant.id, {"tasks": 180, "audit": 730}, Actor("admin-1", "customer_admin"))
    assert service.retention(tenant.id)["tasks"] == 180
    with pytest.raises(CommercialPolicyError):
        service.set_retention(tenant.id, {"tasks": 0}, Actor("admin-1", "customer_admin"))


def test_lifecycle_service_uses_injected_job_store():
    repository = InMemoryCommercialRepository()
    tenant = repository.create_tenant("客户 A", owner_id="owner-1")
    repository.add_customer_admin(tenant.id, "admin-1")
    jobs = InMemoryLifecycleJobStore()
    service = CommercialLifecycleService(repository, job_store=jobs)

    job = service.request_delete(Actor("admin-1", "customer_admin"), tenant.id)

    assert jobs.get(job.id).id == job.id
    assert service.get_job(job.id).tenant_id == tenant.id


# ---------------------------------------------------------------------------
# E4：导出载荷落地（真源 commercial-g0-design.md §6.1 + api-contract.md:144）
# ---------------------------------------------------------------------------


def test_export_payload_lists_source_categories_as_metadata_only():
    """载荷结构必须与真源类别清单一致；无读取方法的类别一律为空数组（未实现）。"""
    repository, tenant, service = seeded_service()

    payload = service.build_export_payload(tenant.id)
    resources = payload["resources"]

    assert set(resources) == set(EXPORT_RESOURCE_CATEGORIES)
    # 商业化服务未持有任何跨模块读取通道 ⇒ 每一类**未实现**，必须是空数组（不臆造数据）。
    for category in EXPORT_RESOURCE_CATEGORIES:
        assert resources[category] == [], f"{category} 未实现，必须为空数组"
    assert set(payload["unimplemented_categories"]) == set(UNIMPLEMENTED_EXPORT_CATEGORIES)
    assert set(UNIMPLEMENTED_EXPORT_CATEGORIES) == set(EXPORT_RESOURCE_CATEGORIES)


def test_export_payload_never_contains_secrets_or_original_content():
    """逐条断言：载荷数据面不含密码/Cookie/验证码/令牌/原始密钥/客户原文。"""
    repository, tenant, service = seeded_service()

    payload = service.build_export_payload(tenant.id)
    # 数据面（resources）序列化后不得出现任何敏感词元。
    resources_text = json.dumps(payload["resources"], ensure_ascii=False).lower()
    for forbidden in ("password", "cookie", "验证码", "token", "api key", "api_key", "客户原文"):
        assert forbidden not in resources_text
    # 递归：全载荷不得出现敏感键名。
    from app.audit.redaction import has_sensitive_key

    assert has_sensitive_key(payload) is False
    # 顶层不得出现凭据类键。
    for key in ("password", "cookie", "token", "api_key", "verification_code"):
        assert key not in payload


def test_export_package_lands_with_explicit_expiry():
    """载荷写入新表；expires_at 由调用方显式给出（真源未给时长，不自造默认）。"""
    repository, tenant, service = seeded_service()
    expires_at = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)

    package = service.store_export_package(tenant.id, "job-1", expires_at=expires_at)

    stored = service.export_store.get(package.id, tenant_id=tenant.id)
    assert stored.tenant_id == tenant.id
    assert stored.job_id == "job-1"
    assert stored.expires_at == expires_at
    assert stored.payload["tenant_id"] == tenant.id
    assert stored.payload["resources"]["users"] == []
    with pytest.raises(ResourceNotFound):
        service.export_store.get(package.id, tenant_id="other-tenant")


# ---------------------------------------------------------------------------
# E4：保留策略接线（真源 commercial-g0-design.md:118）
# ---------------------------------------------------------------------------


def test_retention_defaults_match_source_three_tiers():
    """默认值必须与真源三档一致：任务/运行 180、事件/用量 365、审计 730。"""
    repository, tenant, service = seeded_service()

    assert service.retention(tenant.id) == {"tasks": 180, "events": 365, "usage": 365, "audit": 730}


def test_set_retention_persists_and_writes_audit():
    """保留策略写入 DB（服务侧口径）且**写入审计**（真源 :118）。"""
    repository, tenant, service = seeded_service()

    service.set_retention(
        tenant.id,
        {"tasks": 90, "events": 365, "usage": 365, "audit": 730},
        Actor("admin-1", "customer_admin"),
    )

    assert service.retention(tenant.id)["tasks"] == 90
    records = service.audit.store.list_recent(tenant.id)
    assert [record.action for record in records] == [AuditAction.COMMERCIAL_RETENTION_UPDATED]
    assert records[0].actor_id == "admin-1"
    assert records[0].target_type == "retention_policy"


def test_set_retention_fails_closed_without_audit_channel():
    """没有审计通道就拒绝变更，绝不静默跳过审计。"""
    repository = InMemoryCommercialRepository()
    tenant = repository.create_tenant("客户 A", owner_id="owner-1")
    repository.add_customer_admin(tenant.id, "admin-1")
    service = CommercialLifecycleService(repository)

    with pytest.raises(CommercialPolicyError):
        service.set_retention(tenant.id, {"tasks": 90}, Actor("admin-1", "customer_admin"))


# ---------------------------------------------------------------------------
# E2/E3：worker 执行层（导出落库 / 删除执行 / 撤销）
# ---------------------------------------------------------------------------


class _RecordingExportStore(InMemoryExportPackageStore):
    """记录写入的导出包，供断言 payload 与过期时刻。"""

    def __init__(self):
        super().__init__()
        self.saved: list = []

    def save(self, package):  # type: ignore[override]
        self.saved.append(package)
        return super().save(package)


def worker_service(cooldown_days=7):
    repository = InMemoryCommercialRepository()
    tenant = repository.create_tenant("客户 A", owner_id="owner-1")
    repository.add_customer_admin(tenant.id, "admin-1")
    exports = _RecordingExportStore()
    service = CommercialLifecycleService(
        repository,
        cooldown_days=cooldown_days,
        export_store=exports,
        audit=AuditService(InMemoryAuditStore()),
    )
    return repository, tenant, service, exports


def test_export_package_ttl_ruling_is_seven_days():
    assert EXPORT_PACKAGE_TTL == timedelta(days=7)


def test_worker_completes_export_and_lands_package_with_seven_day_expiry():
    repository, tenant, service, exports = worker_service()
    now = datetime(2026, 9, 14, 8, 0, tzinfo=UTC)
    job = service.request_export(Actor("admin-1", "customer_admin"), tenant.id)

    counts = service.run_pending_jobs(now=now)

    assert counts == {"exports": 1, "deletions": 0}
    assert service.get_job(job.id).status == "completed"
    package = exports.saved[0]
    # 裁决 2：expires_at = created_at + 7 天（断言到天）。
    assert package.created_at == now
    assert package.expires_at == now + timedelta(days=7)
    assert (package.expires_at.date() - package.created_at.date()).days == 7
    # 脱敏 + 类别结构为空数组（裁决 3：数据面本期不建）。
    assert has_sensitive_key(package.payload) is False
    assert package.payload["resources"]["users"] == []
    # 数据面（resources）序列化后不得出现任何敏感词元（redaction 列是「排除声明」不是数据）。
    text = json.dumps(package.payload["resources"], ensure_ascii=False).lower()
    for forbidden in ("password", "cookie", "token", "api_key", "客户原文"):
        assert forbidden not in text


def test_worker_export_is_idempotent():
    repository, tenant, service, exports = worker_service()
    job = service.request_export(Actor("admin-1", "customer_admin"), tenant.id)
    service.run_pending_jobs(now=datetime(2026, 9, 14, tzinfo=UTC))

    counts = service.run_pending_jobs(now=datetime(2026, 9, 15, tzinfo=UTC))

    assert counts == {"exports": 0, "deletions": 0}
    assert service.get_job(job.id).status == "completed"
    assert len(exports.saved) == 1  # 不重复落库


def test_final_export_marks_first_export_after_delete_request_only():
    """裁决 4：删除申请之前完成的不置；之后首次完成置；再次完成不重复置。"""
    repository, tenant, service, _ = worker_service()
    actor = Actor("admin-1", "customer_admin")
    now = datetime(2026, 9, 14, tzinfo=UTC)
    # 删除申请之前完成的导出 ⇒ 不置 final_exported
    service.request_export(actor, tenant.id)
    service.run_pending_jobs(now=now)
    delete_job = service.request_delete(actor, tenant.id)
    assert service.get_job(delete_job.id).final_exported is False
    # 删除申请之后首次完成 ⇒ 置
    service.request_export(actor, tenant.id)
    service.run_pending_jobs(now=now)
    assert service.get_job(delete_job.id).final_exported is True
    # 之后再次完成 ⇒ 不重复置（mark_final_exported 不再被调用）
    calls: list[str] = []
    original = service.mark_final_exported

    def spy(job_id):
        calls.append(job_id)
        return original(job_id)

    service.mark_final_exported = spy  # type: ignore[method-assign]
    service.request_export(actor, tenant.id)
    service.run_pending_jobs(now=now)
    assert calls == []
    assert service.get_job(delete_job.id).final_exported is True


def test_worker_does_not_delete_before_cooldown():
    repository, tenant, service, _ = worker_service(cooldown_days=7)
    actor = Actor("admin-1", "customer_admin")
    delete_job = service.request_delete(actor, tenant.id)
    service.request_export(actor, tenant.id)

    service.run_pending_jobs(now=delete_job.execute_after - timedelta(seconds=1))

    assert service.get_job(delete_job.id).final_exported is True
    assert service.tenant_status(tenant.id) == TenantStatus.DELETING


def test_worker_does_not_delete_without_final_export():
    repository, tenant, service, _ = worker_service(cooldown_days=7)
    actor = Actor("admin-1", "customer_admin")
    delete_job = service.request_delete(actor, tenant.id)

    counts = service.run_pending_jobs(now=delete_job.execute_after)

    assert counts["deletions"] == 0
    assert service.tenant_status(tenant.id) == TenantStatus.DELETING
    actions = [record.action for record in service.audit.store.list_recent(tenant.id)]
    assert AuditAction.COMMERCIAL_DELETION_EXECUTED not in actions


def test_worker_deletes_after_cooldown_and_final_export_with_audit():
    repository, tenant, service, _ = worker_service(cooldown_days=7)
    actor = Actor("admin-1", "customer_admin")
    delete_job = service.request_delete(actor, tenant.id)
    service.request_export(actor, tenant.id)

    counts = service.run_pending_jobs(now=delete_job.execute_after)

    assert counts == {"exports": 1, "deletions": 1}
    assert service.tenant_status(tenant.id) == TenantStatus.DELETED
    assert service.get_job(delete_job.id).status == "completed"
    records = service.audit.store.list_recent(tenant.id)
    executed = [r for r in records if r.action == AuditAction.COMMERCIAL_DELETION_EXECUTED]
    assert len(executed) == 1
    assert executed[0].target_type == "tenant"
    assert executed[0].target_id == tenant.id


def test_delete_execution_fails_closed_without_audit_channel():
    repository = InMemoryCommercialRepository()
    tenant = repository.create_tenant("客户 A", owner_id="owner-1")
    repository.add_customer_admin(tenant.id, "admin-1")
    service = CommercialLifecycleService(repository)
    actor = Actor("admin-1", "customer_admin")
    delete_job = service.request_delete(actor, tenant.id)
    service.mark_final_exported(delete_job.id)

    with pytest.raises(CommercialPolicyError, match="审计"):
        service.execute_delete(tenant.id, now=delete_job.execute_after)


def test_cancel_delete_returns_tenant_to_active_and_blocks_worker():
    """裁决 5：撤销后租户回 ACTIVE，且后续 worker 不再执行删除。"""
    repository, tenant, service, _ = worker_service(cooldown_days=7)
    actor = Actor("owner-1", "customer_admin")
    delete_job = service.request_delete(actor, tenant.id)

    cancelled = service.cancel_delete(actor, tenant.id)

    assert cancelled.status == "cancelled"
    assert service.tenant_status(tenant.id) == TenantStatus.ACTIVE
    counts = service.run_pending_jobs(now=delete_job.execute_after)
    assert counts["deletions"] == 0
    assert service.tenant_status(tenant.id) == TenantStatus.ACTIVE


def test_cancel_delete_goes_through_state_machine(monkeypatch):
    from app.commercial import lifecycle as lifecycle_module

    repository, tenant, service, _ = worker_service(cooldown_days=7)
    actor = Actor("owner-1", "customer_admin")
    service.request_delete(actor, tenant.id)
    seen: list[TenantStatus] = []
    real = lifecycle_module.transition_tenant

    def spy(tenant_obj, target, spy_actor):
        seen.append(target)
        return real(tenant_obj, target, spy_actor)

    monkeypatch.setattr(lifecycle_module, "transition_tenant", spy)

    service.cancel_delete(actor, tenant.id)

    # 断言：撤销经 `transition_tenant`（状态机）而非直接改状态字段。
    assert seen == [TenantStatus.ACTIVE]


def test_cancel_without_pending_delete_raises():
    repository, tenant, service, _ = worker_service()

    with pytest.raises(DeletionNotPending):
        service.cancel_delete(Actor("owner-1", "customer_admin"), tenant.id)
