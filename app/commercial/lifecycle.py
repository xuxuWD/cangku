from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from threading import RLock
from typing import Mapping, Protocol
from uuid import uuid4

from .repository import InMemoryCommercialRepository, ResourceNotFound
from .tenant import Actor, CommercialPolicyError, TenantStatus, transition_tenant
from ..audit.models import AuditAction
from ..audit.service import AuditService
from ..runtime.contracts import redact_payload

logger = logging.getLogger(__name__)


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
# B-2（2026-09-19）：接线后**未接线的类别**由 `build_export_readers` 决定 ⇒ 运行时口径 =
# `set(EXPORT_RESOURCE_CATEGORIES) - set(export_readers)`；本常量保留为「一个都没接」时的默认值
# （服务未注入读取器时的既有行为，契约与既有测试不变）。
UNIMPLEMENTED_EXPORT_CATEGORIES: frozenset[str] = frozenset(EXPORT_RESOURCE_CATEGORIES)

# 单类导出行数上限（B-2）：导出包整体落在 JSONB 一行里，必须有界；
# 超出时**不静默截断**——服务层在 `truncated_categories` 里给出「取了多少 / 共多少」。
EXPORT_CATEGORY_MAX_ROWS = 5000

# 导出脱敏契约（docs/api-contract.md:144）：以下内容**一律不导出**。
EXPORT_REDACTED_FIELDS: tuple[str, ...] = ("密码", "Cookie", "验证码", "令牌", "原始 API 密钥", "客户原文")

# 导出包过期时长（用户裁决 2026-09-14 第 2 条）：`expires_at = created_at + 7 天`。
# 真源 commercial-g0-design.md:110 只要求「带过期时间」、**未给时长**；本值由裁决补齐。
EXPORT_PACKAGE_TTL = timedelta(days=7)


class DeletionNotPending(CommercialPolicyError):
    """撤销删除申请时找不到处于冷静期内、可撤销的删除作业。"""


class DeletionPreconditionMissing(CommercialPolicyError):
    """删除确认的前置未满足（尚未完成最终导出）。

    **归属与 HTTP 语义**：继承 `CommercialPolicyError` 只为复用异常族，
    其对外语义**不是 403**——路由必须**先于** `CommercialPolicyError` 捕获本异常并映射 `409`
    （先例：`DeletionNotPending` → `409`、`ExportPackageExpired` → `404`）。
    与「无权限（403）」区分开：这是**业务前置未满足**，不是调用方没资格。
    """


class ExportPackageExpired(CommercialPolicyError):
    """取回时导出包已过期（`expires_at <= 当前时刻`）。

    **归属与 HTTP 语义**：继承 `CommercialPolicyError` 只为复用异常族，
    其对外语义**不是 403**——路由必须**先于** `CommercialPolicyError` 捕获本异常并映射 `404`
    （先例：`DeletionNotPending` → `409` 同为「先捕获再落到通用 403」）。全仓未使用 `410`
    （改造前核查：`app/` 无命中）⇒ 过期与不存在对客户端同为 `404`，仅文案区分。
    """


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
    # B-3：删除确认人 / 确认时刻（迁移 043）。存量行两列均为此默认值（未确认）。
    confirmed_by: str | None = None
    confirmed_at: datetime | None = None


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


@dataclass
class ExportPackageSummary:
    """导出包**元数据**（列表面）：不含载荷。

    列表只回元数据（`package_id` / 租户 / 所属作业 / 生成与过期时刻），载荷按 `package_id`
    单独取回（契约「GET /api/v1/commercial/exports」）：列表可能一次几十上百条，带上载荷
    会把「看有哪些包」变成大体积传输。
    """

    id: str
    tenant_id: str
    created_at: datetime
    expires_at: datetime
    job_id: str | None = None


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
    def list_for_tenant(
        self, tenant_id: str, *, limit: int, offset: int
    ) -> tuple[list[ExportPackageSummary], int]: ...
    def purge_expired(self, *, now: datetime | None = None) -> int: ...


def _summarize_package(package: ExportPackage) -> ExportPackageSummary:
    """导出包 → 列表面条目（丢弃载荷）。"""
    return ExportPackageSummary(
        id=package.id,
        tenant_id=package.tenant_id,
        job_id=package.job_id,
        created_at=package.created_at,
        expires_at=package.expires_at,
    )


class TenantPurgeStore(Protocol):
    """租户级**物理清场**接口（B-3 清场扩围）。

    实现 = `app/skills/store.py` / `app/knowledge_governance/store.py` 的仓储（与 `MemoryExportStore`
    同款最小面）。语义是**租户整体删除**：删除流程按租户物理清场，避免孤儿数据残留
    （软删语义只留给正常业务）。

    ⚠️ **「整层」= 该层在迁移里的全部租户级表**（技能层 = 技能包 + 数字员工绑定），
    不是只清「主表」：2026-09-19 真机验证实测到只清主表的后果——审计 `cleared_categories`
    报得出面名、面上却仍有整租户行残留（清单 10.7 该条留痕）。
    """

    def delete_all_for_tenant(self, tenant_id: str) -> int: ...


class MemoryExportStore(Protocol):
    """P3 记忆层的生命周期读取/清理接口（N2 接线；实现 = `app.memory.store` 的
    `PostgresMemoryStore`/`InMemoryMemoryStore`，仅使用与商业化握手的最小面）。

    注：`delete_all_for_tenant` 是**租户整体删除**语义（生命周期 CLI/worker 专用），
    与业务侧「事实类 supersede 软删」不冲突——软删留给正常业务，删除流程物理清场。

    ⚠️ **「整层」= 三张表一起清**（事实 / 规则 / 身份类画像；见 `029` 迁移），不是只清事实表：
    2026-09-19 真机验证实测到只清事实表的后果——租户已 `deleted`、审计报 `memories`，
    规则表与画像表行数原样不动（口径同 `TenantPurgeStore`）。
    """

    def list_all_for_tenant(self, tenant_id: str, *, since=None) -> list[object]: ...
    def delete_all_for_tenant(self, tenant_id: str) -> int: ...


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

    def list_for_tenant(
        self, tenant_id: str, *, limit: int, offset: int
    ) -> tuple[list[ExportPackageSummary], int]:
        """列出本租户导出包元数据：生成时间倒序，同刻按包号倒序 ⇒ 顺序确定。

        返回 `(本页条目, 过滤后总数)`；越界分页返回空页（总数不变）。
        """
        with self._lock:
            rows = [package for package in self._packages.values() if package.tenant_id == tenant_id]
        rows.sort(key=lambda package: (package.created_at, package.id), reverse=True)
        total = len(rows)
        return [_summarize_package(package) for package in rows[offset : offset + limit]], total

    def purge_expired(self, *, now: datetime | None = None) -> int:
        """物理删除 `expires_at <= now` 的导出包，返回删除条数（与 PG 实现同语义）。"""
        cutoff = now or datetime.now(UTC)
        with self._lock:
            expired = [pid for pid, package in self._packages.items() if package.expires_at <= cutoff]
            for pid in expired:
                del self._packages[pid]
        return len(expired)


class CommercialLifecycleService:
    def __init__(
        self,
        repository: InMemoryCommercialRepository,
        *,
        cooldown_days: int = 7,
        job_store: LifecycleJobStore | None = None,
        retention_store: RetentionPolicyStore | None = None,
        export_store: ExportPackageStore | None = None,
        memory_store: MemoryExportStore | None = None,
        skills_store: TenantPurgeStore | None = None,
        knowledge_store: TenantPurgeStore | None = None,
        export_readers: Mapping[str, object] | None = None,
        export_category_max_rows: int = EXPORT_CATEGORY_MAX_ROWS,
        audit: AuditService | None = None,
    ) -> None:
        if cooldown_days < 1:
            raise CommercialPolicyError("删除冷静期必须至少 1 天")
        if export_category_max_rows < 1:
            raise CommercialPolicyError("导出行数上限必须是正整数")
        self.repository = repository
        self.cooldown_days = cooldown_days
        self.job_store = job_store or InMemoryLifecycleJobStore()
        self.retention_store = retention_store or InMemoryRetentionPolicyStore()
        self.export_store = export_store or InMemoryExportPackageStore()
        self.export_category_max_rows = export_category_max_rows
        # B-2 接线：类别 → 读取器（`app/commercial/export_readers.py`，签名
        # `reader(tenant_id, *, limit) -> (rows, total)`）。缺哪一类就不接哪一类
        # （该类仍留在 `unimplemented_categories`，**不假装有数据**）。
        self.export_readers: dict[str, object] = dict(export_readers or {})
        # P3 记忆层生命周期通道（N2）：注入后导出载荷含 memories 数据、删除流程物理清场；
        # 未注入时保持「memories 未实现（空数组）」现状（既有契约与测试不变）。
        # B-2：等价于往 `export_readers` 里补一个 memories 读取器（同一实现，两条注入路径归一）。
        if memory_store is not None:
            from .export_readers import memory_export_reader

            self.export_readers.setdefault("memories", memory_export_reader(memory_store))
        self.memory_store = memory_store
        # B-3 清场扩围：技能层 / 知识治理层也按租户物理清场（真源「业务数据、对象存储文件、向量索引
        # 和缓存按策略清理」）。未注入的仓储**不参与清场**（`cleared_categories` 只列真正清到的一侧）。
        self.skills_store = skills_store
        self.knowledge_store = knowledge_store
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

        结构按真源类别清单产出；**未注入读取通道的类别一律为空数组**（**未实现**，
        见 `unimplemented_categories`）；**不臆造字段、不假装有数据**。
        B-2（2026-09-19）起支持注入 `export_readers`：接了读取器的类别填真实行（字段口径见
        `app/commercial/export_readers.py` 与 `docs/api-contract.md`），并：

        - 每类**行数上限** `export_category_max_rows`，超出时在 `truncated_categories` 里给出
          `{"exported": 行数, "total": 总数}`（**不静默截断**）；
        - 读取器运行期报错的类别进 `unavailable_categories` 且**不写入 `resources`**
          （与「读了但是空」区分开：前者是读不到，后者是真的没有），其余类别照常导出；
        - 所有行统一过 `redact_payload`（既有脱敏器：敏感键名 + 值内凭据形态）。
        """
        self.repository.get_tenant(tenant_id)
        resources: dict[str, object] = {category: [] for category in EXPORT_RESOURCE_CATEGORIES}
        unimplemented = set(EXPORT_RESOURCE_CATEGORIES) - set(self.export_readers)
        truncated: dict[str, dict[str, int]] = {}
        unavailable: list[str] = []
        for category, reader in self.export_readers.items():
            if category not in resources:
                continue  # 未知类别名：忽略，不往载荷里塞计划外字段
            try:
                rows, total = reader(tenant_id, limit=self.export_category_max_rows)  # type: ignore[operator]
            except Exception as exc:  # noqa: BLE001 — 单类读取失败不毒化整包：如实标注 + 记日志
                logger.warning("导出类别 %s 读取失败（租户 %s）：%s", category, tenant_id, exc)
                resources.pop(category, None)
                unavailable.append(category)
                continue
            resources[category] = redact_payload(rows)
            if total > len(rows):
                truncated[category] = {"exported": len(rows), "total": int(total)}
        return {
            "tenant_id": tenant_id,
            "resources": resources,
            "unimplemented_categories": sorted(unimplemented),
            "unavailable_categories": sorted(unavailable),
            "truncated_categories": truncated,
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

    def get_export_package(
        self, actor: Actor, tenant_id: str, package_id: str, *, now: datetime | None = None
    ) -> ExportPackage:
        """取回本租户的导出包（**admin-only**，契约「GET /api/v1/commercial/exports/{package_id}」）。

        权限与归属都在**服务端**判定：先 `_ensure_admin`，再以 `tenant_id` 限定取包
        （跨租户与不存在统一 `ResourceNotFound`，不泄露他租户资源是否存在）；
        `expires_at <= now` 视为过期 ⇒ `ExportPackageExpired`（路由映射 `404`）。
        取回端点与过期清理（`purge_expired_export_packages`）**同一时刻口径**：正点即过期。
        """
        self._ensure_admin(actor, tenant_id)
        package = self.export_store.get(package_id, tenant_id=tenant_id)
        if package.expires_at <= (now or datetime.now(UTC)):
            raise ExportPackageExpired("导出包已过期")
        return package

    def list_export_packages(
        self, actor: Actor, tenant_id: str, *, limit: int = 50, offset: int = 0
    ) -> tuple[list[ExportPackageSummary], int]:
        """列出本租户**已生成**导出包的元数据（契约「GET /api/v1/commercial/exports」）。

        为什么需要它（2026-09-19 B-1 补链）：取回端点要 `package_id`，而申请响应与作业视图
        都不携带 ⇒ 没有本方法客户端**无法发现包号**，取回能力实际不可用。
        权限与租户口径同 `get_export_package`：admin-only + 以 `tenant_id` 限定（永不列他租户）；
        列表**如实包含已过期但尚未被清理的包**（客户端按 `expires_at` 标注，取回仍 `404`）。
        """
        self._ensure_admin(actor, tenant_id)
        return self.export_store.list_for_tenant(tenant_id, limit=limit, offset=offset)

    def purge_expired_export_packages(self, *, now: datetime | None = None) -> int:
        """清理过期导出包（物理删除），返回删除条数；供 worker 周期任务调用。

        与 `run_pending_jobs` 同口径：**跨租户**、**不在请求线程执行**。只按包自身
        `expires_at` 判定；**不触碰**生命周期作业记录（作业是生命周期事实，导出包才是数据副本）。
        """
        return self.export_store.purge_expired(now=now)

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

    def confirm_deletion(self, actor: Actor, tenant_id: str, *, now: datetime | None = None) -> LifecycleJob:
        """记录删除确认人（真源 commercial-g0-design.md:114「删除前必须生成最终导出包**并记录确认人**」）。

        这是一次**显式确认动作**（admin-only），与「申请删除」分开：
        - 必须已完成**最终导出**（`final_exported`）——真源把两者并列要求；
        - **不改作业状态**（确认只是记录「谁确认了」；执行仍由冷静期闸门与 worker 排程决定）；
        - 与删除执行同口径 **fail-closed**：没有审计通道就拒绝确认，绝不留下不可追的确认人。
        """
        self._ensure_admin(actor, tenant_id)
        job = self._latest_delete_job(tenant_id)
        if job.status != "cooling_down":
            raise DeletionNotPending("没有处于冷静期内、可确认的删除申请")
        if not job.final_exported:
            raise DeletionPreconditionMissing("删除前必须完成最终导出，再记录确认人")
        if self.audit is None:
            raise CommercialPolicyError("删除确认必须写入审计（未配置审计通道）")
        job.confirmed_by = actor.user_id
        job.confirmed_at = now or datetime.now(UTC)
        self.job_store.save(job)
        self.audit.record(
            AuditAction.COMMERCIAL_DELETION_CONFIRMED,
            tenant_id=tenant_id,
            actor_id=actor.user_id,
            target_type="tenant",
            target_id=tenant_id,
            # 只记受控值：作业种类与状态；确认人由 `actor_id` 承载，不重复落自由文本。
            detail={"kind": job.kind, "status": job.status},
        )
        return job

    def _latest_delete_job(self, tenant_id: str) -> LifecycleJob:
        """「最近的删除作业」= 按 `(requested_at, id)` 显式取最新（与存储层 `ORDER BY created_at, id` 同口径）。

        依据：E2+E3 真库演练暴露——原 `jobs[-1]` 依赖物理行序，同租户多条 `kind=delete` 时可能选错作业；
        这里显式取 max，即便后端返回顺序变化语义仍确定。
        """
        jobs = self.job_store.list_for_tenant(tenant_id, kind="delete")
        job = max(jobs, key=lambda candidate: (candidate.requested_at, candidate.id), default=None)
        if job is None:
            raise CommercialPolicyError("没有待执行的删除任务")
        return job

    def execute_delete(self, tenant_id: str, *, now: datetime | None = None) -> None:
        current = now or datetime.now(UTC)
        job = self._latest_delete_job(tenant_id)
        if job.execute_after is None:
            raise CommercialPolicyError("没有待执行的删除任务")
        if current < job.execute_after:
            raise CommercialPolicyError("删除仍在冷静期内")
        if not job.final_exported:
            raise CommercialPolicyError("删除前必须完成最终导出")
        # B-3：确认人必须已记录（真源把「最终导出」与「记录确认人」并列作为删除前的前置）。
        if not job.confirmed_by:
            raise CommercialPolicyError("删除前必须记录确认人")
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
        # N2 + B-3：租户删除 = 物理清场（各层生命周期方法）。软删语义只留给正常业务；
        # 删除流程按租户整体销毁数据，避免孤儿数据残留。**逐面记录实际清到哪些面**（未注入的不列）。
        cleared: list[str] = []
        for name, store in (
            ("memories", self.memory_store),
            ("skills", self.skills_store),
            ("knowledge_governance", self.knowledge_store),
        ):
            if store is None:
                continue
            store.delete_all_for_tenant(tenant_id)
            cleared.append(name)
        job.status = "completed"
        self.job_store.save(job)
        self.audit.record(
            AuditAction.COMMERCIAL_DELETION_EXECUTED,
            tenant_id=tenant_id,
            actor_id=job.requested_by,
            target_type="tenant",
            target_id=tenant_id,
            detail={
                "kind": job.kind,
                "status": TenantStatus.DELETED.value,
                "confirmed_by": job.confirmed_by,
                "cleared_categories": sorted(cleared),
            },
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
            # B-3：确认人由**管理员显式确认**（`confirm_deletion`）。但冷静期本身可能长达数十天，
            # 管理员常遗忘最后一步 ⇒ 到期且已完成最终导出时，由 worker 代表平台**按申请自动确认**
            # （确认人 = 请求人，即代表租户决策的那个管理员），保证删除不会因遗漏而静默卡死；
            # 自动确认**写与手动确认同一审计动作**（`commercial.deletion.confirmed`），可追。
            if not job.confirmed_by:
                job.confirmed_by = job.requested_by
                job.confirmed_at = current
                self.job_store.save(job)
                if self.audit is not None:
                    self.audit.record(
                        AuditAction.COMMERCIAL_DELETION_CONFIRMED,
                        tenant_id=job.tenant_id,
                        actor_id=job.requested_by,
                        target_type="tenant",
                        target_id=job.tenant_id,
                        detail={"kind": job.kind, "status": job.status},
                    )
                logger.info(
                    "删除作业 %s 到期未显式确认，worker 按申请自动确认（确认人 = 请求人 %s）",
                    job.id, job.requested_by,
                )
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
    # B-3：列清单与行水合集中到一处——此前三处 SELECT + 三处位置水合各写一遍，
    # 加列时极易漏改（真库演练已暴露过排序类同源问题）。
    _COLUMNS = "id, tenant_id, kind, status, execute_after, requested_by, created_at, final_exported, confirmed_by, confirmed_at"

    def __init__(self, connection_or_pool) -> None: self.connection = connection_or_pool
    def _connection(self):
        from contextlib import nullcontext
        return self.connection.connection() if hasattr(self.connection, "connection") and callable(self.connection.connection) else nullcontext(self.connection)

    @staticmethod
    def _hydrate(row) -> LifecycleJob:
        return LifecycleJob(
            tenant_id=str(row[1]), kind=str(row[2]), status=str(row[3]), requested_by=str(row[5]),
            execute_after=row[4], id=str(row[0]),
            requested_at=row[6] if isinstance(row[6], datetime) else datetime.now(UTC),
            final_exported=bool(row[7]),
            confirmed_by=row[8], confirmed_at=row[9],
        )
    def create(self, job: LifecycleJob) -> LifecycleJob:
        with self._connection() as c:
            with c.transaction():
                with c.cursor() as cur:
                    cur.execute("INSERT INTO workbench_lifecycle_jobs (id, tenant_id, kind, status, execute_after, requested_by, created_at, final_exported, confirmed_by, confirmed_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", (job.id,job.tenant_id,job.kind,job.status,job.execute_after,job.requested_by,job.requested_at,job.final_exported,job.confirmed_by,job.confirmed_at))
        return job
    def get(self, job_id: str, *, tenant_id: str | None = None) -> LifecycleJob:
        with self._connection() as c:
            with c.cursor() as cur:
                sql=f"SELECT {self._COLUMNS} FROM workbench_lifecycle_jobs WHERE id = %s"; params=[job_id]
                if tenant_id is not None: sql += " AND tenant_id = %s"; params.append(tenant_id)
                cur.execute(sql, tuple(params)); row=cur.fetchone()
        if row is None: raise ResourceNotFound(job_id)
        return self._hydrate(row)
    def save(self, job: LifecycleJob) -> LifecycleJob:
        with self._connection() as c:
            with c.transaction():
                with c.cursor() as cur:
                    cur.execute("UPDATE workbench_lifecycle_jobs SET status = %s, execute_after = %s, final_exported = %s, confirmed_by = %s, confirmed_at = %s WHERE id = %s AND tenant_id = %s", (job.status,job.execute_after,job.final_exported,job.confirmed_by,job.confirmed_at,job.id,job.tenant_id))
        return job
    def list_for_tenant(self, tenant_id: str, *, kind: str | None = None) -> list[LifecycleJob]:
        with self._connection() as c:
            with c.cursor() as cur:
                sql=f"SELECT {self._COLUMNS} FROM workbench_lifecycle_jobs WHERE tenant_id = %s"; params=[tenant_id]
                if kind is not None: sql += " AND kind = %s"; params.append(kind)
                # 确定性排序，口径与 `list_pending` 一致（内存侧按 (requested_at, id)）。
                # 依据：E2+E3 真库演练暴露——调用方"取最近的删除作业"，无 `ORDER BY` 时依赖物理行序，
                # 同租户多条 `kind=delete` 时可能选错作业。
                sql += " ORDER BY created_at, id"
                cur.execute(sql, tuple(params)); rows=cur.fetchall()
        return [self._hydrate(r) for r in rows]
    def list_pending(self, *, kind: str, limit: int = 100) -> list[LifecycleJob]:
        with self._connection() as c:
            with c.cursor() as cur:
                cur.execute(
                    f"SELECT {self._COLUMNS} FROM workbench_lifecycle_jobs WHERE kind = %s AND status NOT IN ('completed', 'cancelled') ORDER BY created_at, id LIMIT %s",
                    (kind, limit),
                )
                rows=cur.fetchall()
        return [self._hydrate(r) for r in rows]

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
    def list_for_tenant(
        self, tenant_id: str, *, limit: int, offset: int
    ) -> tuple[list[ExportPackageSummary], int]:
        """真库口径同内存实现：租户限定 + 生成时间倒序（同刻按包号倒序）+ 计数与分页。

        **SELECT 不含 `payload` 列**：列表是元数据面（载荷按包号单独取回）。
        `created_at DESC, id DESC` + `LIMIT/OFFSET`；计数为**过滤后总数**，不受分页影响。
        """
        with self._connection() as c:
            with c.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM workbench_export_packages WHERE tenant_id = %s",
                    (tenant_id,),
                )
                total = int(cur.fetchone()[0])
                cur.execute(
                    "SELECT id, tenant_id, job_id, created_at, expires_at FROM workbench_export_packages "
                    "WHERE tenant_id = %s ORDER BY created_at DESC, id DESC LIMIT %s OFFSET %s",
                    (tenant_id, limit, offset),
                )
                rows = cur.fetchall()
        return [
            ExportPackageSummary(
                id=str(row[0]),
                tenant_id=str(row[1]),
                job_id=row[2],
                created_at=row[3] if isinstance(row[3], datetime) else datetime.now(UTC),
                expires_at=row[4] if isinstance(row[4], datetime) else datetime.now(UTC),
            )
            for row in rows
        ], total
    def purge_expired(self, *, now: datetime | None = None) -> int:
        """物理删除过期导出包（`expires_at <= cutoff`，正点即过期），返回删除条数。

        清理**跨租户**、不经 HTTP（worker 周期任务）；迁移 028 已有
        `idx_workbench_export_packages_expires (expires_at)` 支撑本 DELETE。
        """
        cutoff = now or datetime.now(UTC)
        with self._connection() as c:
            with c.transaction():
                with c.cursor() as cur:
                    cur.execute("DELETE FROM workbench_export_packages WHERE expires_at <= %s", (cutoff,))
                    removed = cur.rowcount
        return removed
