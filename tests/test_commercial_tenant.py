import pytest

from app.commercial.repository import InMemoryCommercialRepository, ResourceNotFound
from app.commercial.tenant import Actor, CommercialPolicyError, Tenant, TenantStatus, transition_tenant


def test_tenant_state_transitions_require_authorized_actor():
    tenants = InMemoryCommercialRepository()
    tenant = tenants.create_tenant("客户 A", owner_id="owner-1")

    assert tenant.status == TenantStatus.TRIAL
    tenants.activate_tenant(tenant.id, actor=Actor("owner-1", "super_admin"))
    assert tenants.get_tenant(tenant.id).status == TenantStatus.ACTIVE

    with pytest.raises(CommercialPolicyError):
        tenants.suspend_tenant(tenant.id, actor=Actor("employee-1", "employee"))


def test_deleting_tenant_can_return_to_active_via_state_machine():
    """裁决 5：`DELETING → ACTIVE` 允许边；非法边仍被拒绝。"""
    tenant = Tenant(name="客户 A", owner_id="owner-1", status=TenantStatus.DELETING)

    transition_tenant(tenant, TenantStatus.ACTIVE, Actor("owner-1", "customer_admin"))
    assert tenant.status == TenantStatus.ACTIVE

    deleting = Tenant(name="客户 A", owner_id="owner-1", status=TenantStatus.DELETING)
    with pytest.raises(CommercialPolicyError):
        transition_tenant(deleting, TenantStatus.EXPORTING, Actor("owner-1", "customer_admin"))


def test_execute_delete_edge_deleting_to_deleted_allowed_others_rejected():
    """`DELETING → DELETED` 允许边（`execute_delete` 经状态机走此边）；其它非法边仍被拒。"""
    tenant = Tenant(name="客户 A", owner_id="owner-1", status=TenantStatus.DELETING)

    transition_tenant(tenant, TenantStatus.DELETED, Actor("owner-1", "customer_admin"))
    assert tenant.status == TenantStatus.DELETED

    # 不得给其它非法边开口子：只有「处于 DELETING」才可到 DELETED。
    for status in (TenantStatus.TRIAL, TenantStatus.ACTIVE, TenantStatus.SUSPENDED, TenantStatus.EXPORTING):
        with pytest.raises(CommercialPolicyError):
            transition_tenant(
                Tenant(name="客户 A", owner_id="owner-1", status=status),
                TenantStatus.DELETED,
                Actor("owner-1", "customer_admin"),
            )
    # DELETED 为终态：不得回流。
    with pytest.raises(CommercialPolicyError):
        transition_tenant(
            Tenant(name="客户 A", owner_id="owner-1", status=TenantStatus.DELETED),
            TenantStatus.ACTIVE,
            Actor("owner-1", "customer_admin"),
        )


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
