from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from threading import RLock
from typing import Protocol
from uuid import uuid4

from .repository import InMemoryCommercialRepository, ResourceNotFound
from .tenant import Actor, CommercialPolicyError, TenantStatus
from ..audit.models import AuditAction
from ..audit.service import AuditService


# 保留策略默认值（真源 commercial-g0-design.md:118）：任务和运行 180 天、事件和用量 365 天、审计 730 天。
# 保留口径以 DB 表 `workbench_retention_policies`（服务侧）为准；env `WORKBENCH_RETENTION_POLICY`
# 仅由 `scripts/commercial_g0_preflight.py` 的部署预检读取，**不被服务侧消费**
# （两者之间无写入方 ⇒ 预检 pass ≠ 服务侧生效）。
DEFAULT_RETENTION_POLICY: dict[str, int] = {"tasks": 180, "events": 365, "usage": 365, "audit": 730}

# 真源 commercial-g0-design.md:102-108（§6.1）的导出类别清单。
# 当前商业化服务**没有任何跨模块读取通道**（不持有 users/roles/agents/tasks/runs/steps/artifacts/
# knowledge_*/memories/growth_proposals/approvals/usage/audits 的读取器）⇒ 每一类**均无现成读取方法**，
# 一律返回空数组（**未实现**）。**不臆造字段、不假装有数据**。
EXPORT_RESOURCE_CATEGORIES: tuple[str, ...] = (
    "users",                  # 用户配置
    "roles",                  # 岗位配置
    "agents",                 # 数字员工配置
    "tasks",                  # 任务元数据
    "runs",                   # 运行元数据
    "steps",                  # 步骤元数据
    "artifacts",              # 产物元数据
    "knowledge_documents",    # 知识文档元数据
    "knowledge_versions",     # 知识文档版本
    "knowledge_references",   # 知识引用关系
    "memories",               # 记忆
    "growth_proposals",       # 成长提案
    "approvals",              # 审核记录
    "usage",                  # 用量账本
    "audits",                 # 审计记录
)
# 无现成读取方法、因而**未实现**（返回空数组）的类别集合。
UNIMPLEMENTED_EXPORT_CATEGORIES: frozenset[str] = frozenset(EXPORT_RESOURCE_CATEGORIES)

# 导出脱敏契约（docs/api-contract.md:144）：以下内容**一律不导出**。
EXPORT_REDACTED_FIELDS: tuple[str, ...] = ("密码", "Cookie", "验证码", "令牌", "原始 API 密钥", "客户原文")


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


@dataclass
class ExportPackage:
    """租户导出载荷落点（表 `workbench_export_packages`）。

    `expires_at` 由写入方显式给出：真源（commercial-g0-design.md:110）只要求「带过期时间」，
    **未给定时长** ⇒ 本模块**不自造默认时长**。
    """

    tenant_id: str
    payload: dict[str, object]
    expires_at: datetime
    job_id: str | None = None
    id: str = field(default_factory=lambda: f"export-{uuid4().hex[:12]}")
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class LifecycleJobStore(Protocol):
    def create(self, job: LifecycleJob) -> LifecycleJob: ...
    def get(self, job_id: str, *, tenant_id: str | None = None) -> LifecycleJob: ...
    def save(self, job: LifecycleJob) -> LifecycleJob: ...
    def list_for_tenant(self, tenant_id: str, *, kind: str | None = None) -> list[LifecycleJob]: ...


class RetentionPolicyStore(Protocol):
    def set(self, tenant_id: str, policy: dict[str, int], *, actor_id: str) -> None: ...
    def get(self, tenant_id: str) -> dict[str, int] | None: ...


class ExportPackageStore(Protocol):
    def save(self, package: ExportPackage) -> ExportPackage: ...
    def get(self, package_id: str, *, tenant_id: str | None = None) -> ExportPackage: ...


class InMemoryLifecycleJobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, LifecycleJob] = {}
        self._lock = RLock()

    def create(self, job: LifecycleJob) -> LifecycleJob:
        with self._lock:
            self._jobs[job.id] = job
            return job

    def get(self, job_id: str, *, tenant_id: str | None = None) -> LifecycleJob:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or (tenant_id is not None and job.tenant_id != tenant_id):
                raise ResourceNotFound(job_id)
            return job

    def save(self, job: LifecycleJob) -> LifecycleJob:
        with self._lock:
            if job.id not in self._jobs:
                raise ResourceNotFound(job.id)
            self._jobs[job.id] = job
            return job

    def list_for_tenant(self, tenant_id: str, *, kind: str | None = None) -> list[LifecycleJob]:
        with self._lock:
            return [job for job in self._jobs.values() if job.tenant_id == tenant_id and (kind is None or job.kind == kind)]


class InMemoryRetentionPolicyStore:
    def __init__(self) -> None:
        self._policies: dict[str, dict[str, int]] = {}
        self._lock = RLock()

    def set(self, tenant_id: str, policy: dict[str, int], *, actor_id: str) -> None:
        del actor_id
        with self._lock:
            self._policies[tenant_id] = dict(policy)

    def get(self, tenant_id: str) -> dict[str, int] | None:
        with self._lock:
            value = self._policies.get(tenant_id)
            return dict(value) if value is not None else None


class InMemoryExportPackageStore:
    def __init__(self) -> None:
        self._packages: dict[str, ExportPackage] = {}
        self._lock = RLock()

    def save(self, package: ExportPackage) -> ExportPackage:
        with self._lock:
            self._packages[package.id] = package
            return package

    def get(self, package_id: str, *, tenant_id: str | None = None) -> ExportPackage:
        with self._lock:
            package = self._packages.get(package_id)
            if package is None or (tenant_id is not None and package.tenant_id != tenant_id):
                raise ResourceNotFound(package_id)
            return package


class CommercialLifecycleService:
    def __init__(
        self,
        repository: InMemoryCommercialRepository,
        *,
        cooldown_days: int = 7,
        job_store: LifecycleJobStore | None = None,
        retention_store: RetentionPolicyStore | None = None,
        export_store: ExportPackageStore | None = None,
        audit: AuditService | None = None,
    ) -> None:
        if cooldown_days < 1:
            raise CommercialPolicyError("删除冷静期必须至少 1 天")
        self.repository = repository
        self.cooldown_days = cooldown_days
        self.job_store = job_store or InMemoryLifecycleJobStore()
        self.retention_store = retention_store or InMemoryRetentionPolicyStore()
        self.export_store = export_store or InMemoryExportPackageStore()
        # 保留策略变更必须写入审计（真源 commercial-g0-design.md:118）。
        # 未配置审计通道时 `set_retention` 会 fail-closed（见下），不静默跳过。
        self.audit = audit

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
        return self.job_store.create(job)

    def build_export_payload(self, tenant_id: str) -> dict[str, object]:
        """构造租户导出载荷（真源 commercial-g0-design.md §6.1）。

        结构按真源类别清单产出；**当前每一类都没有现成读取方法**（商业化服务不持有
        users/roles/agents/tasks/runs/steps/artifacts/knowledge_*/memories/growth_proposals/
        approvals/usage/audits 的读取通道）⇒ 一律为空数组（**未实现**，见
        `UNIMPLEMENTED_EXPORT_CATEGORIES`）；**不臆造字段、不假装有数据**。
        载荷只承载元数据/脱敏字段（契约 docs/api-contract.md:144）。
        """
        self.repository.get_tenant(tenant_id)
        return {
            "tenant_id": tenant_id,
            "resources": {category: [] for category in EXPORT_RESOURCE_CATEGORIES},
            "unimplemented_categories": sorted(UNIMPLEMENTED_EXPORT_CATEGORIES),
            "redaction": list(EXPORT_REDACTED_FIELDS),
        }

    def store_export_package(
        self, tenant_id: str, job_id: str, *, expires_at: datetime
    ) -> ExportPackage:
        """把脱敏导出载荷写入 `workbench_export_packages`。

        `expires_at` 由调用方显式给出：真源只要求「带过期时间的下载包」，**未给定时长**
        ⇒ 本方法**不自造默认时长**（取值需先裁决）。
        """
        self.repository.get_tenant(tenant_id)
        package = ExportPackage(
            tenant_id=tenant_id,
            job_id=job_id,
            payload=self.build_export_payload(tenant_id),
            expires_at=expires_at,
        )
        return self.export_store.save(package)

    def request_delete(self, actor: Actor, tenant_id: str) -> LifecycleJob:
        self._ensure_admin(actor, tenant_id)
        tenant = self.repository.get_tenant(tenant_id)
        if tenant.status == TenantStatus.DELETED:
            raise CommercialPolicyError("租户已经删除")
        if hasattr(self.repository, "set_tenant_status"):
            tenant = self.repository.set_tenant_status(tenant_id, TenantStatus.DELETING)
        else:
            tenant.status = TenantStatus.DELETING
        job = LifecycleJob(
            tenant_id=tenant_id,
            kind="delete",
            status="cooling_down",
            requested_by=actor.user_id,
            execute_after=datetime.now(UTC) + timedelta(days=self.cooldown_days),
        )
        return self.job_store.create(job)

    def mark_final_exported(self, job_id: str) -> None:
        try:
            job = self.job_store.get(job_id)
        except ResourceNotFound as exc:
            raise CommercialPolicyError("删除任务不存在") from exc
        if job.kind != "delete":
            raise CommercialPolicyError("删除任务不存在")
        job.final_exported = True
        self.job_store.save(job)

    def execute_delete(self, tenant_id: str, *, now: datetime | None = None) -> None:
        current = now or datetime.now(UTC)
        jobs = self.job_store.list_for_tenant(tenant_id, kind="delete")
        job = jobs[-1] if jobs else None
        if job is None or job.execute_after is None:
            raise CommercialPolicyError("没有待执行的删除任务")
        if current < job.execute_after:
            raise CommercialPolicyError("删除仍在冷静期内")
        if not job.final_exported:
            raise CommercialPolicyError("删除前必须完成最终导出")
        tenant = self.repository.get_tenant(tenant_id)
        if hasattr(self.repository, "set_tenant_status"):
            self.repository.set_tenant_status(tenant_id, TenantStatus.DELETED)
        else:
            tenant.status = TenantStatus.DELETED
        job.status = "completed"
        self.job_store.save(job)

    def set_retention(self, tenant_id: str, policy: dict[str, int], actor: Actor) -> None:
        self._ensure_admin(actor, tenant_id)
        if not policy or any(not isinstance(value, int) or value < 1 for value in policy.values()):
            raise CommercialPolicyError("保留天数必须是正整数")
        # fail-closed：真源要求「任何保留策略变化都写入审计」（commercial-g0-design.md:118），
        # 没有审计通道就拒绝变更，绝不静默跳过审计。
        if self.audit is None:
            raise CommercialPolicyError("保留策略变更必须写入审计（未配置审计通道）")
        self.retention_store.set(tenant_id, policy, actor_id=actor.user_id)
        self.audit.record(
            AuditAction.COMMERCIAL_RETENTION_UPDATED,
            tenant_id=tenant_id,
            actor_id=actor.user_id,
            target_type="retention_policy",
            target_id=tenant_id,
            # 只记「哪些类别被改动」的服务端声明键，不含自由文本。
            detail={"changed_fields": sorted(policy)},
        )

    def retention(self, tenant_id: str) -> dict[str, int]:
        self.repository.get_tenant(tenant_id)
        stored = self.retention_store.get(tenant_id)
        return dict(stored) if stored is not None else dict(DEFAULT_RETENTION_POLICY)

    def tenant_status(self, tenant_id: str) -> TenantStatus:
        return self.repository.get_tenant(tenant_id).status

    def get_job(self, job_id: str) -> LifecycleJob:
        return self.job_store.get(job_id)


class PostgresLifecycleJobStore:
    def __init__(self, connection_or_pool) -> None: self.connection = connection_or_pool
    def _connection(self):
        from contextlib import nullcontext
        return self.connection.connection() if hasattr(self.connection, "connection") and callable(self.connection.connection) else nullcontext(self.connection)
    def create(self, job: LifecycleJob) -> LifecycleJob:
        with self._connection() as c:
            with c.transaction():
                with c.cursor() as cur:
                    cur.execute("INSERT INTO workbench_lifecycle_jobs (id, tenant_id, kind, status, execute_after, requested_by, created_at, final_exported) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)", (job.id,job.tenant_id,job.kind,job.status,job.execute_after,job.requested_by,job.requested_at,job.final_exported))
        return job
    def get(self, job_id: str, *, tenant_id: str | None = None) -> LifecycleJob:
        with self._connection() as c:
            with c.cursor() as cur:
                sql="SELECT id, tenant_id, kind, status, execute_after, requested_by, created_at, final_exported FROM workbench_lifecycle_jobs WHERE id = %s"; params=[job_id]
                if tenant_id is not None: sql += " AND tenant_id = %s"; params.append(tenant_id)
                cur.execute(sql, tuple(params)); row=cur.fetchone()
        if row is None: raise ResourceNotFound(job_id)
        return LifecycleJob(tenant_id=str(row[1]), kind=str(row[2]), status=str(row[3]), requested_by=str(row[5]), execute_after=row[4], id=str(row[0]), requested_at=row[6] if isinstance(row[6], datetime) else datetime.now(UTC), final_exported=bool(row[7]))
    def save(self, job: LifecycleJob) -> LifecycleJob:
        with self._connection() as c:
            with c.transaction():
                with c.cursor() as cur:
                    cur.execute("UPDATE workbench_lifecycle_jobs SET status = %s, execute_after = %s, final_exported = %s WHERE id = %s AND tenant_id = %s", (job.status,job.execute_after,job.final_exported,job.id,job.tenant_id))
        return job
    def list_for_tenant(self, tenant_id: str, *, kind: str | None = None) -> list[LifecycleJob]:
        with self._connection() as c:
            with c.cursor() as cur:
                sql="SELECT id, tenant_id, kind, status, execute_after, requested_by, created_at, final_exported FROM workbench_lifecycle_jobs WHERE tenant_id = %s"; params=[tenant_id]
                if kind is not None: sql += " AND kind = %s"; params.append(kind)
                cur.execute(sql, tuple(params)); rows=cur.fetchall()
        return [LifecycleJob(tenant_id=str(r[1]), kind=str(r[2]), status=str(r[3]), requested_by=str(r[5]), execute_after=r[4], id=str(r[0]), requested_at=r[6] if isinstance(r[6], datetime) else datetime.now(UTC), final_exported=bool(r[7])) for r in rows]

class PostgresRetentionPolicyStore:
    def __init__(self, connection_or_pool) -> None: self.connection = connection_or_pool
    def _connection(self):
        from contextlib import nullcontext
        return self.connection.connection() if hasattr(self.connection, "connection") and callable(self.connection.connection) else nullcontext(self.connection)
    def set(self, tenant_id: str, policy: dict[str,int], *, actor_id: str) -> None:
        import json
        with self._connection() as c:
            with c.transaction():
                with c.cursor() as cur:
                    cur.execute("INSERT INTO workbench_retention_policies (tenant_id, policy, updated_by) VALUES (%s,%s,%s) ON CONFLICT (tenant_id) DO UPDATE SET policy = EXCLUDED.policy, updated_by = EXCLUDED.updated_by", (tenant_id, json.dumps(policy), actor_id))
    def get(self, tenant_id: str) -> dict[str,int] | None:
        import json
        with self._connection() as c:
            with c.cursor() as cur:
                cur.execute("SELECT policy FROM workbench_retention_policies WHERE tenant_id = %s", (tenant_id,)); row=cur.fetchone()
        if row is None: return None
        return dict(json.loads(row[0]) if isinstance(row[0], str) else row[0])


class PostgresExportPackageStore:
    def __init__(self, connection_or_pool) -> None: self.connection = connection_or_pool
    def _connection(self):
        from contextlib import nullcontext
        return self.connection.connection() if hasattr(self.connection, "connection") and callable(self.connection.connection) else nullcontext(self.connection)
    def save(self, package: ExportPackage) -> ExportPackage:
        import json
        with self._connection() as c:
            with c.transaction():
                with c.cursor() as cur:
                    cur.execute("INSERT INTO workbench_export_packages (id, tenant_id, job_id, payload, created_at, expires_at) VALUES (%s,%s,%s,%s,%s,%s)", (package.id, package.tenant_id, package.job_id, json.dumps(package.payload, ensure_ascii=False), package.created_at, package.expires_at))
        return package
    def get(self, package_id: str, *, tenant_id: str | None = None) -> ExportPackage:
        import json
        with self._connection() as c:
            with c.cursor() as cur:
                sql="SELECT id, tenant_id, job_id, payload, created_at, expires_at FROM workbench_export_packages WHERE id = %s"; params=[package_id]
                if tenant_id is not None: sql += " AND tenant_id = %s"; params.append(tenant_id)
                cur.execute(sql, tuple(params)); row=cur.fetchone()
        if row is None: raise ResourceNotFound(package_id)
        return ExportPackage(tenant_id=str(row[1]), job_id=row[2], payload=dict(json.loads(row[3]) if isinstance(row[3], str) else row[3]), expires_at=row[5], id=str(row[0]), created_at=row[4] if isinstance(row[4], datetime) else datetime.now(UTC))
