from __future__ import annotations

from typing import Protocol

from celery import Celery

from .settings import get_settings


class OutboxPublisherProtocol(Protocol):
    def publish_pending(self, *, limit: int = 100) -> int:
        ...


_outbox_publisher: OutboxPublisherProtocol | None = None


def configure_outbox_publisher(publisher: OutboxPublisherProtocol | None) -> None:
    """Inject the process-local publisher during worker startup or tests."""
    global _outbox_publisher
    _outbox_publisher = publisher


def configure_runtime(*, settings=None, connection=None, redis_client=None) -> OutboxPublisherProtocol:
    """Wire a production Outbox publisher into this Celery process."""
    if settings is None:
        settings = get_settings()
    if settings.storage_backend != "postgres":
        raise ValueError("Worker 必须使用 PostgreSQL")
    from .bootstrap import build_outbox_publisher

    publisher = build_outbox_publisher(settings, connection=connection, redis_client=redis_client)
    configure_outbox_publisher(publisher)
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
            }
        },
    )
    return celery


celery_app = create_celery_app()

if get_settings().env != "development":
    configure_runtime()


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
