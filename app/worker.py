from __future__ import annotations

from celery import Celery

from .settings import get_settings


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


@celery_app.task(bind=True, autoretry_for=(TimeoutError,), retry_backoff=True, max_retries=3)
def dispatch_event(self, event_json: str) -> str:
    """Queue boundary for event delivery; handlers remain idempotent downstream."""
    del self
    return event_json


@celery_app.task
def publish_outbox() -> int:
    """Periodic hook; production wiring injects the pool and Redis stream bus."""
    return 0
