from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4


class TenantStatus(StrEnum):
    TRIAL = "trial"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    EXPORTING = "exporting"
    DELETING = "deleting"
    DELETED = "deleted"


class CommercialPolicyError(ValueError):
    pass


@dataclass(frozen=True)
class Actor:
    user_id: str
    role: str


@dataclass
class Tenant:
    name: str
    owner_id: str
    id: str = field(default_factory=lambda: f"tenant-{uuid4().hex[:12]}")
    status: TenantStatus = TenantStatus.TRIAL
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class Workspace:
    tenant_id: str
    name: str
    id: str = field(default_factory=lambda: f"workspace-{uuid4().hex[:12]}")
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class CustomerAdmin:
    tenant_id: str
    user_id: str
    granted_at: datetime = field(default_factory=lambda: datetime.now(UTC))


def ensure_tenant_admin(actor: Actor, tenant: Tenant) -> None:
    if actor.role not in {"super_admin", "customer_admin"} or (
        actor.role == "customer_admin" and actor.user_id != tenant.owner_id
    ):
        raise CommercialPolicyError("当前账号无权管理该租户")


def transition_tenant(tenant: Tenant, target: TenantStatus, actor: Actor) -> Tenant:
    ensure_tenant_admin(actor, tenant)
    allowed = {
        TenantStatus.TRIAL: {TenantStatus.ACTIVE, TenantStatus.DELETING},
        TenantStatus.ACTIVE: {TenantStatus.SUSPENDED, TenantStatus.EXPORTING, TenantStatus.DELETING},
        TenantStatus.SUSPENDED: {TenantStatus.ACTIVE, TenantStatus.DELETING},
        TenantStatus.EXPORTING: {TenantStatus.ACTIVE},
        # 裁决 2026-09-14 第 5 条：撤销删除申请后回到 `ACTIVE`（`DELETING → ACTIVE` 允许边）。
        TenantStatus.DELETING: {TenantStatus.DELETED, TenantStatus.ACTIVE},
        TenantStatus.DELETED: set(),
    }
    if target not in allowed[tenant.status]:
        raise CommercialPolicyError(f"租户不能从 {tenant.status.value} 变更为 {target.value}")
    tenant.status = target
    return tenant
