from __future__ import annotations

from typing import Protocol

from celery import Celery

from .settings import get_settings


class OutboxPublisherProtocol(Protocol):
    def publish_pending(self, *, limit: int = 100) -> int:
        ...


class LifecycleRunnerProtocol(Protocol):
    def run_pending_jobs(self, *, limit: int = 100) -> dict[str, int]:
        ...


_outbox_publisher: OutboxPublisherProtocol | None = None
_lifecycle_runner: LifecycleRunnerProtocol | None = None


def configure_outbox_publisher(publisher: OutboxPublisherProtocol | None) -> None:
    """Inject the process-local publisher during worker startup or tests."""
    global _outbox_publisher
    _outbox_publisher = publisher


def configure_lifecycle(runner: LifecycleRunnerProtocol | None) -> None:
    """Inject the process-local commercial lifecycle runner during worker startup or tests."""
    global _lifecycle_runner
    _lifecycle_runner = runner


def configure_runtime(*, settings=None, connection=None, redis_client=None, audit=None) -> OutboxPublisherProtocol:
    """Wire a production Outbox publisher and lifecycle runner into this Celery process."""
    if settings is None:
        settings = get_settings()
    if settings.storage_backend != "postgres":
        raise ValueError("Worker 必须使用 PostgreSQL")
    from .bootstrap import build_commercial_components, build_outbox_publisher

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
    configure_outbox_publisher(publisher)
    configure_lifecycle(lifecycle)
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
        },
    )
    return celery


celery_app = create_celery_app()

_worker_settings = get_settings()
if _worker_settings.env != "development":
    from .bootstrap import build_audit_service

    configure_runtime(
        settings=_worker_settings,
        # E2/E3：删除执行必须写审计（真源 commercial-g0-design.md:114/:174）⇒ worker 恒建审计连接；
        # migrate=False：迁移由 API 进程负责，避免在导入期触发迁移。
        audit=build_audit_service(_worker_settings, migrate=False),
    )


@celery_app.task(bind=True, autoretry_for=(TimeoutError,), retry_backoff=True, max_retries=3)
def dispatch_event(self, event_json: str) -> str:
    """Queue boundary for event delivery; handlers remain idempotent downstream."""
    del self
    return event_json


@celery_app.task
def publish_outbox() -> int:
    """Publish pending rows when the worker has been wired to a publisher."""
    publisher = _outbox_publisher
    if publisher is None:
        return 0
    return publisher.publish_pending(limit=100)


@celery_app.task
def run_lifecycle_jobs() -> dict[str, int]:
    """Process queued exports and due tenant deletions when the worker has been wired."""
    runner = _lifecycle_runner
    if runner is None:
        return {"exports": 0, "deletions": 0}
    return runner.run_pending_jobs(limit=100)
