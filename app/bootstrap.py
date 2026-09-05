from __future__ import annotations

from pathlib import Path

from .domain import TaskStore
from .migrations import apply_migrations
from .repository import PostgresTaskRepository, TaskRepository
from .settings import Settings, validate_runtime_settings


def build_task_repository(settings: Settings, *, connection=None, migrate: bool = True) -> TaskRepository:
    validate_runtime_settings(settings)
    if settings.storage_backend == "memory":
        if settings.env != "development":
            raise ValueError("生产环境禁止使用内存任务仓储")
        return TaskStore()
    if settings.storage_backend == "postgres":
        if connection is None:
            import psycopg

            database_url = settings.database_url.replace("postgresql+psycopg://", "postgresql://", 1)
            connection = psycopg.connect(database_url)
        if migrate:
            apply_migrations(connection, Path(__file__).resolve().parents[1] / "migrations")
        return PostgresTaskRepository(connection)
    raise ValueError("不支持的任务仓储类型")
