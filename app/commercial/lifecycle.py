from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from .repository import InMemoryCommercialRepository, ResourceNotFound
from .tenant import Actor, CommercialPolicyError, TenantStatus


@dataclass
class LifecycleJob:
    tenant_id: str
    kind: str
    status: str
    requested_by: str
    execute_after: datetime | None = None
    id: str = field(default_factory=lambda: f"lifecycle-{uuid4().hex[:12]}")
    requested_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    final_exported: bool = False


class CommercialLifecycleService:
    def __init__(self, repository: InMemoryCommercialRepository, *, cooldown_days: int = 7) -> None:
        if cooldown_days < 1:
            raise CommercialPolicyError("删除冷静期必须至少 1 天")
        self.repository = repository
        self.cooldown_days = cooldown_days
        self._jobs: dict[str, LifecycleJob] = {}
        self._retention: dict[str, dict[str, int]] = {}

    def _ensure_admin(self, actor: Actor, tenant_id: str) -> None:
        tenant = self.repository.get_tenant(tenant_id)
        if actor.role == "super_admin":
            return
        if actor.role != "customer_admin" or not self.repository.is_customer_admin(tenant_id, actor.user_id):
            raise CommercialPolicyError("当前账号无权管理该租户数据")
        if tenant.status == TenantStatus.DELETED:
            raise CommercialPolicyError("租户已经删除")

    def request_export(self, actor: Actor, tenant_id: str) -> LifecycleJob:
        self._ensure_admin(actor, tenant_id)
        job = LifecycleJob(tenant_id=tenant_id, kind="export", status="queued", requested_by=actor.user_id)
        self._jobs[job.id] = job
        return job

    def build_export_payload(self, tenant_id: str) -> dict[str, object]:
        self.repository.get_tenant(tenant_id)
        return {
            "tenant_id": tenant_id,
            "resources": {"users": [], "workspaces": [], "tasks": [], "runs": [], "knowledge_references": [], "usage": [], "audits": []},
            "redaction": ["password", "cookie", "验证码", "token", "api_key", "客户原文"],
        }

    def request_delete(self, actor: Actor, tenant_id: str) -> LifecycleJob:
        self._ensure_admin(actor, tenant_id)
        tenant = self.repository.get_tenant(tenant_id)
        if tenant.status == TenantStatus.DELETED:
            raise CommercialPolicyError("租户已经删除")
        tenant.status = TenantStatus.DELETING
        job = LifecycleJob(
            tenant_id=tenant_id,
            kind="delete",
            status="cooling_down",
            requested_by=actor.user_id,
            execute_after=datetime.now(UTC) + timedelta(days=self.cooldown_days),
        )
        self._jobs[job.id] = job
        return job

    def mark_final_exported(self, job_id: str) -> None:
        job = self._jobs.get(job_id)
        if job is None or job.kind != "delete":
            raise CommercialPolicyError("删除任务不存在")
        job.final_exported = True

    def execute_delete(self, tenant_id: str, *, now: datetime | None = None) -> None:
        current = now or datetime.now(UTC)
        jobs = [job for job in self._jobs.values() if job.tenant_id == tenant_id and job.kind == "delete"]
        job = jobs[-1] if jobs else None
        if job is None or job.execute_after is None:
            raise CommercialPolicyError("没有待执行的删除任务")
        if current < job.execute_after:
            raise CommercialPolicyError("删除仍在冷静期内")
        if not job.final_exported:
            raise CommercialPolicyError("删除前必须完成最终导出")
        tenant = self.repository.get_tenant(tenant_id)
        tenant.status = TenantStatus.DELETED
        job.status = "completed"

    def set_retention(self, tenant_id: str, policy: dict[str, int], actor: Actor) -> None:
        self._ensure_admin(actor, tenant_id)
        if not policy or any(not isinstance(value, int) or value < 1 for value in policy.values()):
            raise CommercialPolicyError("保留天数必须是正整数")
        self._retention[tenant_id] = dict(policy)

    def retention(self, tenant_id: str) -> dict[str, int]:
        self.repository.get_tenant(tenant_id)
        return dict(self._retention.get(tenant_id, {"tasks": 180, "audit": 730}))

    def tenant_status(self, tenant_id: str) -> TenantStatus:
        return self.repository.get_tenant(tenant_id).status

    def get_job(self, job_id: str) -> LifecycleJob:
        try:
            return self._jobs[job_id]
        except KeyError as exc:
            raise ResourceNotFound(job_id) from exc
