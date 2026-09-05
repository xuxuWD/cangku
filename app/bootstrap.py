from __future__ import annotations

from pathlib import Path

from .domain import TaskStore
from .dead_letters import DeadLetterStore, PostgresDeadLetterStore
from .events import InMemoryEventBus, RedisStreamEventBus
from .migrations import apply_migrations
from .outbox import OutboxPublisher
from .repository import PostgresTaskRepository, TaskRepository
from .settings import Settings, validate_runtime_settings


def build_event_bus(settings: Settings, *, redis_client=None):
    """Select the local development bus or the Redis Streams production bus."""
    validate_runtime_settings(settings)
    if settings.storage_backend == "memory":
        if settings.env != "development":
            raise ValueError("生产环境禁止使用内存事件总线")
        return InMemoryEventBus()
    if settings.storage_backend == "postgres":
        if redis_client is None:
            from redis import Redis

            redis_client = Redis.from_url(settings.redis_url, decode_responses=False)
        if redis_client is None:
            raise ValueError("生产事件总线需要 Redis")
        return RedisStreamEventBus(redis_client)
    raise ValueError("不支持的事件总线类型")


def build_task_repository(settings: Settings, *, connection=None, migrate: bool = True) -> TaskRepository:
    validate_runtime_settings(settings)
    if settings.storage_backend == "memory":
        if settings.env != "development":
            raise ValueError("生产环境禁止使用内存任务仓储")
        return TaskStore()
    if settings.storage_backend == "postgres":
        if connection is None:
            from psycopg_pool import ConnectionPool

            database_url = settings.database_url.replace("postgresql+psycopg://", "postgresql://", 1)
            connection = ConnectionPool(database_url, min_size=1, max_size=10, open=True)
        if migrate:
            apply_migrations(connection, Path(__file__).resolve().parents[1] / "migrations")
        return PostgresTaskRepository(connection)
    raise ValueError("不支持的任务仓储类型")


def build_outbox_publisher(settings: Settings, *, connection=None, redis_client=None) -> OutboxPublisher:
    """Build the production Outbox publisher from deployment-owned clients."""
    validate_runtime_settings(settings)
    if settings.storage_backend != "postgres":
        raise ValueError("Outbox 发布器需要 PostgreSQL")
    if connection is None:
        from psycopg_pool import ConnectionPool

        database_url = settings.database_url.replace("postgresql+psycopg://", "postgresql://", 1)
        connection = ConnectionPool(database_url, min_size=1, max_size=10, open=True)
    if redis_client is None:
        from redis import Redis

        redis_client = Redis.from_url(settings.redis_url, decode_responses=False)
    return OutboxPublisher(connection, RedisStreamEventBus(redis_client))


def build_dead_letter_store(settings: Settings, *, event_bus, connection=None):
    """Select a development or durable dead-letter repository."""
    validate_runtime_settings(settings)
    if settings.storage_backend == "memory":
        if settings.env != "development":
            raise ValueError("生产环境禁止使用内存死信仓储")
        return DeadLetterStore(event_bus)
    if settings.storage_backend == "postgres":
        if connection is None:
            from psycopg_pool import ConnectionPool

            database_url = settings.database_url.replace("postgresql+psycopg://", "postgresql://", 1)
            connection = ConnectionPool(database_url, min_size=1, max_size=10, open=True)
        return PostgresDeadLetterStore(connection, event_bus)
    raise ValueError("不支持的死信仓储类型")
