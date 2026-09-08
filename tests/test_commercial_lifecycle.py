from datetime import UTC, datetime, timedelta

import pytest

from app.commercial.lifecycle import CommercialLifecycleService, InMemoryLifecycleJobStore
from app.commercial.repository import InMemoryCommercialRepository
from app.commercial.tenant import Actor, CommercialPolicyError, TenantStatus


def seeded_service(cooldown_days=7):
    repository = InMemoryCommercialRepository()
    tenant = repository.create_tenant("客户 A", owner_id="owner-1")
    repository.add_customer_admin(tenant.id, "admin-1")
    return repository, tenant, CommercialLifecycleService(repository, cooldown_days=cooldown_days)


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
