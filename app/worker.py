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


_outbox_publisher: OutboxPublisherProtocol | None = None
_lifecycle_runner: LifecycleRunnerProtocol | None = None
_knowledge_review_scanner: KnowledgeReviewScannerProtocol | None = None
_runtime_event_purger: RuntimeEventPurgerProtocol | None = None


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
    _, _, lifecycle = build_commercial_components(
        settings, connection=connection, migrate=False, audit=audit
    )
    # N3：知识治理到期扫描（跨租户候选 → 逐条置 needs_review，审计 actor=system:worker）。
    # 显式传 store ⇒ 复用同一连接且**不跑迁移**（`build_knowledge_governance_service` 缺省会自建池并跑迁移）。
    from .knowledge_governance.store import PostgresKnowledgeGovStore

    governance = build_knowledge_governance_service(
        settings, store=PostgresKnowledgeGovStore(connection), audit=audit
    )
    # 「运行事件有界」：复用同一连接的运行时状态仓储按保留期清理 append-only 的运行事件
    # （`purge_events_before` 只删 `workbench_runtime_events`，不碰审计）。
    from .runtime.state_postgres import PostgresRuntimeStateStore

    configure_outbox_publisher(publisher)
    configure_lifecycle(lifecycle)
    configure_knowledge_review(governance)
    configure_runtime_event_purger(PostgresRuntimeStateStore(connection))
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
            # 组 10.7：过期导出包（`expires_at = 完成时刻 + 7 天`）物理清理——导出包是租户数据副本，
            # 过期后不再可取回（GET /api/v1/commercial/exports/{package_id} ⇒ 404），此处只保留「到点即清」。
            # 间隔由 **beat** 侧读取 ⇒ 与 worker 侧必须同值。
            "export-packages-purge": {
                "task": "app.worker.purge_export_packages",
                "schedule": settings.export_package_purge_interval_seconds,
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
    if _outbox_publisher is not None or _lifecycle_runner is not None or _knowledge_review_scanner is not None or _runtime_event_purger is not None:
        return
    if get_settings().env == "development":
        return
    with _runtime_lock:
        if _outbox_publisher is not None or _lifecycle_runner is not None or _knowledge_review_scanner is not None or _runtime_event_purger is not None:
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
