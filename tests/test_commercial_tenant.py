import pytest

from app.commercial.repository import InMemoryCommercialRepository, ResourceNotFound
from app.commercial.tenant import Actor, CommercialPolicyError, TenantStatus


def test_tenant_state_transitions_require_authorized_actor():
    tenants = InMemoryCommercialRepository()
    tenant = tenants.create_tenant("客户 A", owner_id="owner-1")

    assert tenant.status == TenantStatus.TRIAL
    tenants.activate_tenant(tenant.id, actor=Actor("owner-1", "super_admin"))
    assert tenants.get_tenant(tenant.id).status == TenantStatus.ACTIVE

    with pytest.raises(CommercialPolicyError):
        tenants.suspend_tenant(tenant.id, actor=Actor("employee-1", "employee"))


def test_resources_are_scoped_to_tenant_and_workspace():
    tenants = InMemoryCommercialRepository()
    first = tenants.create_workspace("tenant-a", "工作区 1")
    second = tenants.create_workspace("tenant-b", "工作区 1")

    assert first.tenant_id != second.tenant_id
    with pytest.raises(ResourceNotFound):
        tenants.get_workspace(second.tenant_id, first.id)


def test_customer_admin_is_scoped_to_own_tenant():
    tenants = InMemoryCommercialRepository()
    tenant = tenants.create_tenant("客户 A", owner_id="owner-a")
    tenants.add_customer_admin(tenant.id, "admin-a")

    assert tenants.is_customer_admin(tenant.id, "admin-a") is True
    assert tenants.is_customer_admin("tenant-b", "admin-a") is False
