from __future__ import annotations

from datetime import UTC, datetime, timedelta
from threading import Lock
from typing import Protocol

from celery import Celery

from .settings import get_settings


class OutboxPublisherProtocol(Protocol):
    def publish_pending(self, *, limit: int = 100) -> int:
        ...


class LifecycleRunnerProtocol(Protocol):
    def run_pending_jobs(self, *, limit: int = 100) -> dict[str, int]:
        ...


class KnowledgeReviewScannerProtocol(Protocol):
    def scan_review_due_across_tenants(self, *, now=None, limit: int = 500) -> dict[str, int]:
        ...


class RuntimeEventPurgerProtocol(Protocol):
    def purge_events_before(self, cutoff: datetime) -> int:
        ...


class ConversationStreamPurgerProtocol(Protocol):
    """P2b 流帧清理器（`PostgresStreamStore` 满足该协议）：悬挂兜底 + 到期清理。"""

    def mark_stalled(self, *, cutoff: datetime, expires_at: datetime) -> int:
        ...

    def purge_expired(self, *, cutoff: datetime) -> int:
        ...


class RunArtifactPurgerProtocol(Protocol):
    """P2c-3 产物登记清理器（`PostgresRunArtifactStore` 满足该协议）：按保留期逐租户删除。"""

    def purge_expired(self, *, cutoff: datetime) -> int:
        ...


class CrmServiceProtocol(Protocol):
    """P5a CRM 服务在 worker 侧的最小接口（避免 worker 依赖 CRM 全量模块）。"""

    store: object

    def recompute_health_for_tenant(self, tenant_id: str) -> int:
        ...


class CrmNotifierProtocol(Protocol):
    def notify(self, *, tenant_id: str, recipient_id: str, kind, target_type=None, target_id=None) -> None:
        ...


_outbox_publisher: OutboxPublisherProtocol | None = None
_lifecycle_runner: LifecycleRunnerProtocol | None = None
_knowledge_review_scanner: KnowledgeReviewScannerProtocol | None = None
_runtime_event_purger: RuntimeEventPurgerProtocol | None = None
_conversation_stream_purger: ConversationStreamPurgerProtocol | None = None
_run_artifact_purger: RunArtifactPurgerProtocol | None = None
_crm_service: CrmServiceProtocol | None = None
_crm_notifier: CrmNotifierProtocol | None = None


def configure_outbox_publisher(publisher: OutboxPublisherProtocol | None) -> None:
    """Inject the process-local publisher during worker startup or tests."""
    global _outbox_publisher
    _outbox_publisher = publisher


def configure_lifecycle(runner: LifecycleRunnerProtocol | None) -> None:
    """Inject the process-local commercial lifecycle runner during worker startup or tests."""
    global _lifecycle_runner
    _lifecycle_runner = runner


def configure_knowledge_review(scanner: KnowledgeReviewScannerProtocol | None) -> None:
    """注入知识治理到期扫描器（`KnowledgeGovernanceService` 满足该协议）；测试可置 None。"""
    global _knowledge_review_scanner
    _knowledge_review_scanner = scanner


def configure_runtime_event_purger(purger: RuntimeEventPurgerProtocol | None) -> None:
    """注入运行事件保留期清理器（`PostgresRuntimeStateStore` 满足该协议）；测试可置 None。"""
    global _runtime_event_purger
    _runtime_event_purger = purger


def configure_conversation_stream_purger(purger: ConversationStreamPurgerProtocol | None) -> None:
    """注入流帧清理器（P2b §2.6；`PostgresStreamStore` 满足该协议）；测试可置 None。"""
    global _conversation_stream_purger
    _conversation_stream_purger = purger


def configure_run_artifact_purger(purger: RunArtifactPurgerProtocol | None) -> None:
    """注入产物登记清理器（P2c-3 §2.7；`PostgresRunArtifactStore` 满足该协议）；测试可置 None。"""
    global _run_artifact_purger
    _run_artifact_purger = purger


def configure_crm(*, service: CrmServiceProtocol | None, notifier: CrmNotifierProtocol | None) -> None:
    """注入 P5a CRM 服务与站内通知（`CrmService` / `InboxService` 满足协议）；测试可置 None。

    **未接线时 3 个 CRM 周期任务一律返回零值**（不伪造扫描结果，沿用既有周期任务口径）。
    """
    global _crm_service, _crm_notifier
    _crm_service = service
    _crm_notifier = notifier


def configure_runtime(*, settings=None, connection=None, redis_client=None, audit=None) -> OutboxPublisherProtocol:
    """Wire a production Outbox publisher and lifecycle runner into this Celery process."""
    if settings is None:
        settings = get_settings()
    if settings.storage_backend != "postgres":
        raise ValueError("Worker 必须使用 PostgreSQL")
    from .bootstrap import build_commercial_components, build_knowledge_governance_service, build_outbox_publisher

    if connection is None:
        from psycopg_pool import ConnectionPool

        database_url = settings.database_url.replace("postgresql+psycopg://", "postgresql://", 1)
        connection = ConnectionPool(database_url, min_size=1, max_size=10, open=True)
    publisher = build_outbox_publisher(
        settings, connection=connection, redis_client=redis_client, audit=audit
    )
    # E2/E3：商业化生命周期执行层复用同一连接；worker **不跑迁移**（迁移由 API 进程负责）。
    # B-2（2026-09-19）：**导出作业正是在本进程执行** ⇒ 必须注入类别读取器与记忆层仓储，
    # 否则生产里生成的导出包会是「所有类别皆空」的假包（API 进程注入不覆盖本进程）。
    # 读取器与 API 进程同源（`build_export_readers`），存储实现按本进程连接构造。
    from .bootstrap import build_memory_store, build_skills_service, build_task_repository
    from .accounts.repository import PostgresAccountRepository
    from .audit.store import PostgresAuditStore
    from .commercial.export_readers import build_export_readers
    from .knowledge_governance.store import PostgresKnowledgeGovStore
    from .runtime.artifacts import PostgresRunArtifactStore
    from .runtime.records import PostgresRunRecordStore
    from .runtime.state_postgres import PostgresRuntimeStateStore
    from .skills.store import PostgresSkillStore
    from .workforce.store import PostgresWorkforceDirectoryStore

    # 记忆层仓储**一次构造、两处复用**：导出读取器（memories 类别）与生命周期清场（删除租户时清记忆层）。
    # 2026-09-19 真机验证抓到：此前它只传给 `export_readers`，**没传给 `build_commercial_components`**
    # ⇒ 生命周期服务 `memory_store=None` ⇒ **生产删除租户时记忆层完全不清场**（审计 `cleared_categories`
    # 只列出 skills / knowledge_governance 两面，暴露了这一点）。导出包能出 memories 数据、删除却不清它，
    # 属"两面不一致"的真缺陷。
    memory_store = build_memory_store(settings, connection=connection, migrate=False)
    export_readers = build_export_readers(
        memory_store=memory_store,
        workforce=PostgresWorkforceDirectoryStore(connection),
        knowledge=PostgresKnowledgeGovStore(connection),
        audits=PostgresAuditStore(connection),
        runs=PostgresRunRecordStore(connection),
        accounts=PostgresAccountRepository(connection),
        tasks=build_task_repository(settings, connection=connection, migrate=False),
        artifacts=PostgresRunArtifactStore(connection, retention_days=settings.run_artifact_retention_days),
        steps=PostgresRuntimeStateStore(connection),
        # `usage` 由 `build_commercial_components` 用本进程的账本实例自行接线（账本归它持有）。
    )
    _, _, lifecycle = build_commercial_components(
        settings,
        connection=connection,
        migrate=False,
        audit=audit,
        export_readers=export_readers,
        # B-3 清场扩围 + 2026-09-19 补漏：worker 是**执行删除的进程** ⇒ 三面清场通道都必须在这里注入
        # （与 API 侧同源）。**只注入部分**的后果由审计 `cleared_categories` 如实暴露，但数据已经漏清。
        # 技能仓储用共享连接显式构造（`build_skills_service(store=...)` 缺省会自建池并跑迁移 ⇒ 违反
        # 「worker 不跑迁移」）。
        memory_store=memory_store,
        skills_store=build_skills_service(
            settings, store=PostgresSkillStore(connection), audit=audit
        ).store,
        knowledge_store=PostgresKnowledgeGovStore(connection),
    )
    # N3：知识治理到期扫描（跨租户候选 → 逐条置 needs_review，审计 actor=system:worker）。
    # 显式传 store ⇒ 复用同一连接且**不跑迁移**（`build_knowledge_governance_service` 缺省会自建池并跑迁移）。
    governance = build_knowledge_governance_service(
        settings, store=PostgresKnowledgeGovStore(connection), audit=audit
    )
    # 「运行事件有界」：复用同一连接的运行时状态仓储按保留期清理 append-only 的运行事件
    # （`purge_events_before` 只删 `workbench_runtime_events`，不碰审计）。
    configure_outbox_publisher(publisher)
    configure_lifecycle(lifecycle)
    configure_knowledge_review(governance)
    configure_runtime_event_purger(PostgresRuntimeStateStore(connection))
    # P2b 流帧清理（§2.6）：先悬挂兜底（未终态且久无更新 ⇒ unavailable('stalled') + expires_at），
    # 再按 expires_at 删除到期 run 的帧与状态行；**只清流帧**（消息表 / 审计 / 运行事件不受影响）。
    from .conversation.stream import PostgresStreamStore

    configure_conversation_stream_purger(
        PostgresStreamStore(
            connection,
            max_frames=settings.stream_max_frames,
            max_bytes=settings.stream_max_bytes,
        )
    )
    # P2c-3 产物登记清理（§2.7）：按保留期**逐租户**删除到期行；**只清登记表**
    # （帧 / 消息 / 审计 / 运行记录不受影响）；保留期与写端同源（同一 settings）。
    from .runtime.artifacts import PostgresRunArtifactStore

    configure_run_artifact_purger(
        PostgresRunArtifactStore(connection, retention_days=settings.run_artifact_retention_days)
    )
    # P5a CRM（crm-p5a-design §2.11）：健康度重算 / 活动到期提醒 / 续约窗口三个周期任务，
    # 共用同一连接与审计；收件箱复用既有装配（`migrate=False`——迁移归 API 进程）。
    from .bootstrap import build_inbox_service
    from .crm.service import CrmService
    from .crm.store_postgres import PostgresCrmStore

    configure_crm(
        service=CrmService(PostgresCrmStore(connection), audit=audit),
        notifier=build_inbox_service(settings, audit=audit, connection=connection, migrate=False),
    )
    return publisher


def create_celery_app() -> Celery:
    settings = get_settings()
    celery = Celery("company_workbench", broker=settings.redis_url, backend=settings.redis_url)
    celery.conf.update(
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        task_track_started=True,
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        worker_prefetch_multiplier=1,
        beat_schedule={
            "outbox-publisher": {
                "task": "app.worker.publish_outbox",
                "schedule": 15.0,
            },
            # E2/E3：导出作业与到期删除作业不在 HTTP 请求线程执行（docs/api-contract.md:148）。
            "lifecycle-jobs": {
                "task": "app.worker.run_lifecycle_jobs",
                "schedule": 30.0,
            },
            # N3：知识治理到期扫描（默认 1h，可由 WORKBENCH_KNOWLEDGE_REVIEW_SCAN_INTERVAL_SECONDS 外置覆盖）。
            # 只在 worker 进程接线后生效；未接线时任务返回零值，不伪造扫描结果。
            "knowledge-review-scan": {
                "task": "app.worker.scan_knowledge_review_due",
                "schedule": settings.knowledge_review_scan_interval_seconds,
            },
            # 「运行事件有界」：按保留期清理 append-only 的运行事件
            # （默认 1h 一次；保留期 WORKBENCH_RUNTIME_EVENTS_RETENTION_DAYS，默认 30 天）。
            # 间隔由 **beat** 侧读取 ⇒ 与 worker 侧必须同值，否则配置只在一边生效（见 docker-compose.app.yml）。
            "runtime-events-purge": {
                "task": "app.worker.purge_runtime_events",
                "schedule": settings.runtime_events_purge_interval_seconds,
            },
            # P2b 实时流（§2.6）：悬挂兜底 + 按 `expires_at` 清理到期流帧（**只清流帧**）。
            # 间隔由 **beat** 侧读取 ⇒ 与 worker 侧必须同值（口径同既有条目）。
            "conversation-stream-purge": {
                "task": "app.worker.purge_conversation_stream",
                "schedule": settings.stream_purge_interval_seconds,
            },
            # P2c-3 产物登记（§2.7）：按保留期清理到期元数据行（**只清登记表**）。
            # 间隔由 **beat** 侧读取 ⇒ 与 worker 侧必须同值（口径同既有条目）。
            "run-artifacts-purge": {
                "task": "app.worker.purge_run_artifacts",
                "schedule": settings.run_artifact_purge_interval_seconds,
            },
            # 组 10.7：过期导出包（`expires_at = 完成时刻 + 7 天`）物理清理——导出包是租户数据副本，
            # 过期后不再可取回（GET /api/v1/commercial/exports/{package_id} ⇒ 404），此处只保留「到点即清」。
            # 间隔由 **beat** 侧读取 ⇒ 与 worker 侧必须同值。
            "export-packages-purge": {
                "task": "app.worker.purge_export_packages",
                "schedule": settings.export_package_purge_interval_seconds,
            },
            # P5a CRM（crm-p5a-design §2.11）：健康度重算 / 活动到期提醒（幂等）/ 续约窗口。
            # 间隔由 **beat** 侧读取 ⇒ 与 worker 侧必须同值（口径同既有条目）。
            "crm-health-recompute": {
                "task": "app.worker.recompute_crm_health",
                "schedule": settings.crm_health_recompute_interval_seconds,
            },
            "crm-activity-reminder": {
                "task": "app.worker.remind_crm_activities",
                "schedule": settings.crm_activity_reminder_interval_seconds,
            },
            "crm-renewal-window": {
                "task": "app.worker.remind_crm_renewals",
                "schedule": settings.crm_renewal_window_interval_seconds,
            },
        },
    )
    return celery


celery_app = create_celery_app()

# ------------------------------------------------------------ 运行时装配（fork 安全）
#
# **为什么不在模块导入期装配**（2026-09-15 容器演练发现的既有缺陷）：
# 导入期装配会在 **worker 主进程**里创建 psycopg 连接池，而 Celery 默认使用 prefork 池
# （Linux 默认；Windows 上 Celery 拒绝 `-B` 但 worker 仍可用 solo/threads）。fork 出的子进程
# 继承的是父进程的池对象，**psycopg_pool 明确不支持跨 fork 共享**，表现为周期任务全部抛
# `PoolTimeout("couldn't get a connection after 30.00 sec")`——文档被静默卡住、只有日志可见。
#
# 因此改为：**在真正执行任务的进程里**惰性装配（首次任务调用时装配一次）：
#   - prefork：每个子进程各自建池（父进程不建）⇒ 无跨 fork 共享；
#   - threads / solo：进程内首次调用时建一次（`_runtime_lock` 防并发重复）；
#   - development：**不自动装配**，保持「未接线 ⇒ 任务返回零值」，不偷偷连库。
_runtime_lock = Lock()
# 测试注入点：替换装配动作（默认 `_build_production_runtime`），用于断言「什么时候装配」。
_runtime_builder = None


def _build_production_runtime() -> None:
    """按当前进程的 settings 装配运行时（仅由 `_ensure_runtime` 调用；`migrate=False`——迁移归 API 进程）。"""
    settings = get_settings()
    from .bootstrap import build_audit_service

    # E2/E3：删除执行必须写审计（真源 commercial-g0-design.md:114/:174）⇒ worker 恒建审计连接。
    configure_runtime(
        settings=settings,
        audit=build_audit_service(settings, migrate=False),
    )


def _ensure_runtime() -> None:
    """任务进程内惰性装配（见上方「fork 安全」段）；**完全未接线时**才自动装配。

    刻意不覆盖「显式只配了一部分」的场景：只要任一运行时已注入（测试 / 运维脚本 / 显式
    `configure_*`），就视为已接线、不再自动装配（避免把显式注入悄悄替换掉）。
    装配失败**不吞**：直接向上抛（任务 FAILURE、日志可见），不做「静默零值」。
    """
    if (
        _outbox_publisher is not None
        or _lifecycle_runner is not None
        or _knowledge_review_scanner is not None
        or _runtime_event_purger is not None
        or _conversation_stream_purger is not None
        or _run_artifact_purger is not None
        or _crm_service is not None
        or _crm_notifier is not None
    ):
        return
    if get_settings().env == "development":
        return
    with _runtime_lock:
        if (
        _outbox_publisher is not None
        or _lifecycle_runner is not None
        or _knowledge_review_scanner is not None
        or _runtime_event_purger is not None
        or _conversation_stream_purger is not None
        or _run_artifact_purger is not None
        or _crm_service is not None
        or _crm_notifier is not None
    ):
            return
        builder = _runtime_builder or _build_production_runtime
        builder()


@celery_app.task(bind=True, autoretry_for=(TimeoutError,), retry_backoff=True, max_retries=3)
def dispatch_event(self, event_json: str) -> str:
    """Queue boundary for event delivery; handlers remain idempotent downstream."""
    del self
    return event_json


@celery_app.task
def publish_outbox() -> int:
    """Publish pending rows when the worker has been wired to a publisher."""
    _ensure_runtime()
    publisher = _outbox_publisher
    if publisher is None:
        return 0
    return publisher.publish_pending(limit=100)


@celery_app.task
def run_lifecycle_jobs() -> dict[str, int]:
    """Process queued exports and due tenant deletions when the worker has been wired."""
    _ensure_runtime()
    runner = _lifecycle_runner
    if runner is None:
        return {"exports": 0, "deletions": 0}
    return runner.run_pending_jobs(limit=100)


@celery_app.task
def scan_knowledge_review_due() -> dict[str, int]:
    """知识治理到期扫描（§4 N3）：跨租户把 published 且过 `review_due_at` 的文档置 needs_review。

    与 `publish_outbox` / `run_lifecycle_jobs` 同口径：**未接线即返回零值**，绝不伪造扫描结果。
    ⚠️ **已接线但未注入 audit** 时**不返回零值**：服务层按 N7 裁决 B（2026-09-15）fail-closed 抛错
    （无人值守路径不得静默不留痕）⇒ 任务显式失败、日志可见——这是刻意行为，不要「修」成静默跳过。
    """
    _ensure_runtime()
    scanner = _knowledge_review_scanner
    if scanner is None:
        return {"candidates": 0, "flipped": 0}
    return scanner.scan_review_due_across_tenants(limit=500)


@celery_app.task
def purge_runtime_events() -> int:
    """运行事件保留期清理（「运行事件有界」）：删除早于保留期的运行事件，返回删除条数。

    - 保留期 = `WORKBENCH_RUNTIME_EVENTS_RETENTION_DAYS`（默认 30 天），截止时刻取**任务执行时刻**；
    - 只清理 append-only 的 `workbench_runtime_events`：**审计不可删除**，
      清理器（`purge_events_before`）不触碰任何审计数据；
    - 与 `publish_outbox` / `run_lifecycle_jobs` 同口径：**未接线即返回 0**，绝不伪造清理结果。
    """
    _ensure_runtime()
    purger = _runtime_event_purger
    if purger is None:
        return 0
    cutoff = datetime.now(UTC) - timedelta(days=get_settings().runtime_events_retention_days)
    return purger.purge_events_before(cutoff)


@celery_app.task
def purge_conversation_stream() -> dict[str, int]:
    """流帧保留期清理（P2b §2.6）：先**悬挂兜底**置 `unavailable('stalled')`，再删到期 run 的帧与状态行。

    - 悬挂兜底：`status='streaming'` 且 `updated_at < now - WORKBENCH_STREAM_STALLED_HOURS`（默认 6h）
      ⇒ 置 `unavailable` + `is_terminal` + `expires_at = now + WORKBENCH_STREAM_RETENTION_DAYS`（默认 7 天）；
    - 到期清理：删除 `expires_at < now` 的 run 的**全部帧行 + 状态行**；**只清流帧**——
      消息表 / 审计 / 运行事件**不受影响**（清理**不写审计**，与运行事件清理同口径）；
    - 与既有周期任务同口径：**未接线即返回零值**，绝不伪造清理结果；development 下不自动装配。
    """
    _ensure_runtime()
    purger = _conversation_stream_purger
    if purger is None:
        return {"stalled": 0, "purged": 0}
    settings = get_settings()
    reference = datetime.now(UTC)
    stalled = purger.mark_stalled(
        cutoff=reference - timedelta(hours=settings.stream_stalled_hours),
        expires_at=reference + timedelta(days=settings.stream_retention_days),
    )
    purged = purger.purge_expired(cutoff=reference)
    return {"stalled": stalled, "purged": purged}


@celery_app.task
def purge_run_artifacts() -> int:
    """产物登记保留期清理（P2c-3 §2.7）：**逐租户**删除 `expires_at < 任务执行时刻` 的登记行。

    - 保留期在**写端**已按 `WORKBENCH_RUN_ARTIFACT_RETENTION_DAYS`（默认 30 天）落到 `expires_at`
      ⇒ 本任务只按该时刻执行，不重复计算保留期；
    - **只清登记表**：帧、消息、审计、运行记录**不受影响**；清理**不写审计**（例行维护，
      与流帧 / 运行事件清理同口径）；
    - 与既有周期任务同口径：**未接线即返回 0**，绝不伪造清理结果（development 下不自动装配）。
    """
    _ensure_runtime()
    purger = _run_artifact_purger
    if purger is None:
        return 0
    return purger.purge_expired(cutoff=datetime.now(UTC))


@celery_app.task
def purge_export_packages() -> int:
    """导出包过期清理（组 10.7）：物理删除 `expires_at <= 任务执行时刻` 的导出包，返回删除条数。

    - 过期时刻由包自身 `expires_at`（= 导出完成时刻 + 7 天）决定 ⇒ **无独立保留期配置**，
      只由 beat 间隔 `WORKBENCH_EXPORT_PACKAGE_PURGE_INTERVAL_SECONDS` 控制扫描频率；
    - 与 `run_lifecycle_jobs` 共用既有 `_lifecycle_runner` 注入点（导出包仓储归生命周期服务持有）：
      **未接线即返回 0**，绝不伪造清理结果；development 下不自动装配（同 `_ensure_runtime` 口径）；
    - 只清理导出包；**生命周期作业记录与审计不随之删除**。
    """
    _ensure_runtime()
    runner = _lifecycle_runner
    if runner is None:
        return 0
    return runner.purge_expired_export_packages()


@celery_app.task
def recompute_crm_health() -> dict[str, int]:
    """CRM 健康度逐租户重算（crm-p5a-design §2.11）：返回 {tenants, accounts}。

    - 逐租户全量重算（批量收集，避免 N+1）；审计为**每租户一行汇总**（`crm.health.recomputed`）；
    - 与既有周期任务同口径：**未接线即返回零值**，绝不伪造扫描结果。
    """
    _ensure_runtime()
    service = _crm_service
    if service is None:
        return {"tenants": 0, "accounts": 0}
    tenant_ids = service.store.list_tenant_ids()
    accounts = 0
    for tenant_id in tenant_ids:
        accounts += service.recompute_health_for_tenant(tenant_id)
    return {"tenants": len(tenant_ids), "accounts": accounts}


@celery_app.task
def remind_crm_activities() -> dict[str, int]:
    """CRM 活动到期提醒（§2.11）：扫描 `kind=task` 且 `planned` 且 `due_at ≤ now+1d` 的活动。

    **幂等**：同一活动同一天只投递一次（`reminded_on` 回写；重复扫描不重复投递）。
    未接线即返回零值（不伪造）。
    """
    _ensure_runtime()
    service = _crm_service
    notifier = _crm_notifier
    if service is None or notifier is None:
        return {"scanned": 0, "delivered": 0}
    from .inbox import InboxKind  # 延迟导入：worker 不因此在顶层耦合收件箱实现

    reference = datetime.now(UTC)
    today = reference.date()
    due_before = reference + timedelta(days=1)
    scanned = 0
    delivered = 0
    for tenant_id in service.store.list_tenant_ids():
        for activity in service.store.list_due_activities(tenant_id, due_before=due_before):
            scanned += 1
            if activity.reminded_on == today:
                continue
            notifier.notify(
                tenant_id=tenant_id,
                recipient_id=activity.owner_id,
                kind=InboxKind.CRM_ACTIVITY_DUE,
                target_type="crm_activity",
                target_id=activity.activity_id,
            )
            activity.reminded_on = today
            service.store.update_activity(activity)
            delivered += 1
    return {"scanned": scanned, "delivered": delivered}


@celery_app.task
def remind_crm_renewals() -> dict[str, int]:
    """CRM 续约窗口提醒 + 过期翻转（§2.11）：窗口内 `signed` 合同通知 `owner_id`；到期未续 ⇒ `expired`。

    ⚠️ 本段按规格字面实现「扫描即提醒」（每日一次；**跨日幂等未做**——规格未要求，如需可加字段）。
    未接线即返回零值（不伪造）。
    """
    _ensure_runtime()
    service = _crm_service
    notifier = _crm_notifier
    if service is None or notifier is None:
        return {"reminded": 0, "expired": 0}
    from .crm.models import RENEWAL_WINDOW_DAYS
    from .inbox import InboxKind

    reference = datetime.now(UTC)
    today = reference.date()
    until = today + timedelta(days=RENEWAL_WINDOW_DAYS)
    reminded = 0
    expired = 0
    for tenant_id in service.store.list_tenant_ids():
        for contract in service.store.list_contracts_in_renewal_window(tenant_id, from_date=today, until=until):
            notifier.notify(
                tenant_id=tenant_id,
                recipient_id=contract.owner_id,
                kind=InboxKind.CRM_RENEWAL_WINDOW,
                target_type="crm_contract",
                target_id=contract.contract_id,
            )
            reminded += 1
        for contract in service.store.list_expired_contracts(tenant_id, today=today):
            contract.status = "expired"
            contract.updated_at = reference
            service.store.update_contract(contract)
            expired += 1
    return {"reminded": reminded, "expired": expired}
