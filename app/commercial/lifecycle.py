from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from threading import RLock
from typing import Protocol
from uuid import uuid4

from .repository import InMemoryCommercialRepository, ResourceNotFound
from .tenant import Actor, CommercialPolicyError, TenantStatus, transition_tenant
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

# 导出包过期时长（用户裁决 2026-09-14 第 2 条）：`expires_at = created_at + 7 天`。
# 真源 commercial-g0-design.md:110 只要求「带过期时间」、**未给时长**；本值由裁决补齐。
EXPORT_PACKAGE_TTL = timedelta(days=7)


class DeletionNotPending(CommercialPolicyError):
    """撤销删除申请时找不到处于冷静期内、可撤销的删除作业。"""


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
    def list_pending(self, *, kind: str, limit: int = 100) -> list[LifecycleJob]: ...


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
            jobs = [job for job in self._jobs.values() if job.tenant_id == tenant_id and (kind is None or job.kind == kind)]
        # 确定性排序，口径与 `list_pending` 一致（PG 侧 = `ORDER BY created_at, id`）。
        # 依据：E2+E3 真库演练暴露——调用方按"取最近的删除作业"使用本列表，若无确定顺序
        # 则依赖字典/物理行序，同租户多条 `kind=delete` 时可能选错作业。
        jobs.sort(key=lambda job: (job.requested_at, job.id))
        return jobs

    def list_pending(self, *, kind: str, limit: int = 100) -> list[LifecycleJob]:
        with self._lock:
            pending = [
                job for job in self._jobs.values()
                if job.kind == kind and job.status not in ("completed", "cancelled")
            ]
        pending.sort(key=lambda job: (job.requested_at, job.id))
        return pending[:limit]


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
        self, tenant_id: str, job_id: str, *, expires_at: datetime, created_at: datetime | None = None
    ) -> ExportPackage:
        """把脱敏导出载荷写入 `workbench_export_packages`。

        `expires_at` 由调用方显式给出：真源只要求「带过期时间的下载包」，**未给定时长**
        ⇒ 本方法**不自造默认时长**（取值由 2026-09-14 裁决 = 7 天，见 `EXPORT_PACKAGE_TTL`）。
        `created_at` 缺省为当前时刻；给出时与 `expires_at` 同源（保证 `expires_at = created_at + 7 天`）。
        """
        self.repository.get_tenant(tenant_id)
        package = ExportPackage(
            tenant_id=tenant_id,
            job_id=job_id,
            payload=self.build_export_payload(tenant_id),
            expires_at=expires_at,
            **({} if created_at is None else {"created_at": created_at}),
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
        # 「最近的删除作业」= 按 (requested_at, id) 显式取最新（与存储层 `ORDER BY created_at, id` 同口径）。
        # 依据：E2+E3 真库演练暴露——原 `jobs[-1]` 依赖物理行序，同租户多条 `kind=delete` 时可能选错作业；
        # 这里显式取 max，即便后端返回顺序变化语义仍确定。
        job = max(jobs, key=lambda candidate: (candidate.requested_at, candidate.id), default=None)
        if job is None or job.execute_after is None:
            raise CommercialPolicyError("没有待执行的删除任务")
        if current < job.execute_after:
            raise CommercialPolicyError("删除仍在冷静期内")
        if not job.final_exported:
            raise CommercialPolicyError("删除前必须完成最终导出")
        # fail-closed：真源要求删除流程「包含……审计记录」（commercial-g0-design.md:114/:174），
        # 没有审计通道就拒绝执行删除，绝不无审计地删租户。
        if self.audit is None:
            raise CommercialPolicyError("删除执行必须写入审计（未配置审计通道）")
        tenant = self.repository.get_tenant(tenant_id)
        # 经状态机 `DELETING → DELETED`（与 `cancel_delete` 对称）：不直接改状态字段，非法边由
        # `transition_tenant` 拒绝。请求人权限已在 `request_delete` 经 `_ensure_admin` 校验；worker 代表
        # 平台执行，作业未存请求角色（`requested_by` 只有 user_id）⇒ 以平台身份（super_admin）执行状态迁移，
        # 仅为通过 `ensure_tenant_admin`，不冒充具体客户管理员；此处只强制 `DELETING → DELETED` 这一条边。
        transition_tenant(tenant, TenantStatus.DELETED, Actor(job.requested_by, "super_admin"))
        if hasattr(self.repository, "set_tenant_status"):
            self.repository.set_tenant_status(tenant_id, TenantStatus.DELETED)
        job.status = "completed"
        self.job_store.save(job)
        self.audit.record(
            AuditAction.COMMERCIAL_DELETION_EXECUTED,
            tenant_id=tenant_id,
            actor_id=job.requested_by,
            target_type="tenant",
            target_id=tenant_id,
            detail={"kind": job.kind, "status": TenantStatus.DELETED.value},
        )

    def complete_export_job(self, job_id: str, *, now: datetime | None = None) -> LifecycleJob:
        """执行一次导出作业：落库脱敏载荷 → 标记作业完成 → 按裁决 4 置「最终导出」。

        `expires_at = 完成时刻 + EXPORT_PACKAGE_TTL（7 天）`（裁决 2026-09-14 第 2 条）。
        幂等：作业已 `completed` 时直接返回，不重复落库 / 不重复置位。
        """
        current = now or datetime.now(UTC)
        job = self.job_store.get(job_id)
        if job.kind != "export":
            raise CommercialPolicyError("导出任务不存在")
        if job.status == "completed":
            return job
        self.store_export_package(
            job.tenant_id, job.id, created_at=current, expires_at=current + EXPORT_PACKAGE_TTL
        )
        job.status = "completed"
        self.job_store.save(job)
        # 裁决 4：删除申请之后**首次完成**的导出即「最终导出」。
        target = self._final_export_target(job.tenant_id)
        if target is not None:
            self.mark_final_exported(target.id)
        return job

    def _final_export_target(self, tenant_id: str) -> LifecycleJob | None:
        """返回本次导出应关联的删除作业（裁决 4），无则 None。

        判定口径（用户裁决 2026-09-14 第 4 条，用**既有字段**实现，不需新增列）：
        删除作业（`kind="delete"`）处于冷静期（`status="cooling_down"`）且尚未 `final_exported`
        时，本次导出即「删除申请之后首次完成的导出」⇒ 置位并与其关联。
        - 删除申请**之前**完成的导出：当时不存在待执行的删除作业 ⇒ 不置位；
        - 同一删除申请的**第二次及以后**完成的导出：`final_exported` 已为真 ⇒ 不重复置位。
        """
        pending = [
            job for job in self.job_store.list_for_tenant(tenant_id, kind="delete")
            if job.status == "cooling_down" and not job.final_exported
        ]
        if not pending:
            return None
        pending.sort(key=lambda job: (job.requested_at, job.id))
        return pending[-1]

    def cancel_delete(self, actor: Actor, tenant_id: str) -> LifecycleJob:
        """撤销最近的删除申请：租户经状态机 `DELETING → ACTIVE`，作业标记 `cancelled`。

        **不绕过状态机**：状态回退经 `transition_tenant`（裁决 2026-09-14 第 5 条新增允许边）。
        撤销后该删除作业不再被 worker 执行（`list_pending` 排除 `cancelled`）。
        """
        self._ensure_admin(actor, tenant_id)
        pending = [
            job for job in self.job_store.list_for_tenant(tenant_id, kind="delete")
            if job.status == "cooling_down"
        ]
        if not pending:
            raise DeletionNotPending("没有可撤销的删除申请")
        pending.sort(key=lambda job: (job.requested_at, job.id))
        job = pending[-1]
        tenant = self.repository.get_tenant(tenant_id)
        # 经状态机校验并回退；越权 / 非法边由 `transition_tenant` 拒绝。
        transition_tenant(tenant, TenantStatus.ACTIVE, actor)
        if hasattr(self.repository, "set_tenant_status"):
            self.repository.set_tenant_status(tenant_id, TenantStatus.ACTIVE)
        job.status = "cancelled"
        self.job_store.save(job)
        return job

    def run_pending_jobs(self, *, limit: int = 100, now: datetime | None = None) -> dict[str, int]:
        """worker 周期任务入口：处理待执行导出与到期删除作业。

        由 `app.worker` 的 beat 任务调用；**不在 HTTP 请求线程执行**（契约 docs/api-contract.md:148）。
        返回本次处理的作业计数（供观测）。
        """
        current = now or datetime.now(UTC)
        completed_exports = 0
        for job in self.job_store.list_pending(kind="export", limit=limit):
            self.complete_export_job(job.id, now=current)
            completed_exports += 1
        executed_deletions = 0
        for job in self.job_store.list_pending(kind="delete", limit=limit):
            if job.execute_after is None or current < job.execute_after:
                continue
            if not job.final_exported:
                continue
            self.execute_delete(job.tenant_id, now=current)
            executed_deletions += 1
        return {"exports": completed_exports, "deletions": executed_deletions}

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
                # 确定性排序，口径与 `list_pending` 一致（内存侧按 (requested_at, id)）。
                # 依据：E2+E3 真库演练暴露——调用方"取最近的删除作业"，无 `ORDER BY` 时依赖物理行序，
                # 同租户多条 `kind=delete` 时可能选错作业。
                sql += " ORDER BY created_at, id"
                cur.execute(sql, tuple(params)); rows=cur.fetchall()
        return [LifecycleJob(tenant_id=str(r[1]), kind=str(r[2]), status=str(r[3]), requested_by=str(r[5]), execute_after=r[4], id=str(r[0]), requested_at=r[6] if isinstance(r[6], datetime) else datetime.now(UTC), final_exported=bool(r[7])) for r in rows]
    def list_pending(self, *, kind: str, limit: int = 100) -> list[LifecycleJob]:
        with self._connection() as c:
            with c.cursor() as cur:
                cur.execute(
                    "SELECT id, tenant_id, kind, status, execute_after, requested_by, created_at, final_exported FROM workbench_lifecycle_jobs WHERE kind = %s AND status NOT IN ('completed', 'cancelled') ORDER BY created_at, id LIMIT %s",
                    (kind, limit),
                )
                rows=cur.fetchall()
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
