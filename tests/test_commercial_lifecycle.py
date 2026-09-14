import json
from datetime import UTC, datetime

import pytest

from app.audit.models import AuditAction
from app.audit.service import AuditService
from app.audit.store import InMemoryAuditStore
from app.commercial.lifecycle import (
    EXPORT_RESOURCE_CATEGORIES,
    UNIMPLEMENTED_EXPORT_CATEGORIES,
    CommercialLifecycleService,
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
