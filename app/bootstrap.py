from __future__ import annotations

from pathlib import Path

from .accounts.rate_limit import InMemoryLoginAttemptStore, LoginRateLimiter
from .accounts.repository import InMemoryAccountRepository
from .accounts.service import AccountService
from .agent_services import ModelGateway, ProviderModel
from .audit.service import AuditService
from .audit.store import InMemoryAuditStore
from .domain import TaskStore
from .dead_letters import DeadLetterStore, PostgresDeadLetterStore
from .knowledge_policy import KnowledgeAccessRegistry, PostgresKnowledgeAccessRegistry
from .events import InMemoryEventBus, RedisStreamEventBus
from .migrations import apply_migrations
from .outbox import OutboxPublisher
from .planner.classification import PLAN_GENERATION_CAPABILITY
from .planner.generator import MockPlanGenerator
from .planner.models import ToolCatalog
from .planner.service import PlannerService
from .planner.store import InMemoryPlanProposalStore
from .repository import PostgresTaskRepository, TaskRepository
from .settings import Settings, validate_runtime_settings


def build_commercial_components(settings: Settings, *, connection=None, migrate: bool = True):
    """Build tenant, usage, and lifecycle persistence as one coordinated unit."""
    validate_runtime_settings(settings)
    from .commercial.lifecycle import (
        CommercialLifecycleService,
        InMemoryLifecycleJobStore,
        InMemoryRetentionPolicyStore,
        PostgresLifecycleJobStore,
        PostgresRetentionPolicyStore,
    )
    from .commercial.repository import InMemoryCommercialRepository, PostgresCommercialRepository
    from .commercial.usage import InMemoryUsageLedger, PostgresUsageLedger

    if settings.storage_backend == "memory":
        if settings.env != "development":
            raise ValueError("生产环境禁止使用内存商业化仓储")
        repository = InMemoryCommercialRepository()
        usage = InMemoryUsageLedger()
        lifecycle = CommercialLifecycleService(
            repository,
            job_store=InMemoryLifecycleJobStore(),
            retention_store=InMemoryRetentionPolicyStore(),
        )
        return repository, usage, lifecycle
    if settings.storage_backend != "postgres":
        raise ValueError("不支持的商业化存储类型")
    if connection is None:
        from psycopg_pool import ConnectionPool

        database_url = settings.database_url.replace("postgresql+psycopg://", "postgresql://", 1)
        connection = ConnectionPool(database_url, min_size=1, max_size=10, open=True)
    if migrate:
        apply_migrations(connection, Path(__file__).resolve().parents[1] / "migrations")
    repository = PostgresCommercialRepository(connection)
    usage = PostgresUsageLedger(connection)
    lifecycle = CommercialLifecycleService(
        repository,
        job_store=PostgresLifecycleJobStore(connection),
        retention_store=PostgresRetentionPolicyStore(connection),
    )
    return repository, usage, lifecycle


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


def build_content_store(settings: Settings):
    validate_runtime_settings(settings)
    if settings.content_store_backend == "memory":
        if settings.env != "development":
            raise ValueError("生产环境禁止使用内存内容仓储")
        from .content.store import ContentStore

        return ContentStore()
    if settings.content_store_backend == "sqlite":
        from .content.sqlite_store import SQLiteContentStore

        path = Path(settings.content_store_path)
        if not path.is_absolute():
            path = Path(__file__).resolve().parents[1] / path
        return SQLiteContentStore(path)
    raise ValueError("不支持的内容仓储类型")


def build_content_generator(settings: Settings):
    validate_runtime_settings(settings)
    from .content.generator import MockContentGenerator

    if settings.content_generation_backend == "mock":
        return MockContentGenerator()
    if settings.content_generation_backend == "openai_compatible":
        if not settings.content_model_base_url or not settings.content_model_name or not settings.content_model_api_key:
            raise ValueError("真实内容模型需要配置地址、模型名和 API Key")
        from .content.openai_compatible import OpenAICompatibleContentGenerator

        return OpenAICompatibleContentGenerator(
            base_url=settings.content_model_base_url,
            model_name=settings.content_model_name,
            api_key=settings.content_model_api_key,
            timeout_seconds=settings.content_model_timeout_seconds,
            max_retries=settings.content_model_max_retries,
        )
    raise ValueError("不支持的内容生成后端")


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
    event_bus = RedisStreamEventBus(redis_client)
    dead_letter_store = build_dead_letter_store(settings, event_bus=event_bus, connection=connection)
    return OutboxPublisher(
        connection,
        event_bus,
        max_attempts=settings.outbox_max_attempts,
        dead_letter_store=dead_letter_store,
    )


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


def build_knowledge_access_registry(settings: Settings, *, connection=None):
    """Select the tenant-scoped knowledge access repository."""
    validate_runtime_settings(settings)
    if settings.storage_backend == "memory":
        if settings.env != "development":
            raise ValueError("生产环境禁止使用内存知识范围仓储")
        return KnowledgeAccessRegistry()
    if settings.storage_backend == "postgres":
        if connection is None:
            from psycopg_pool import ConnectionPool

            database_url = settings.database_url.replace("postgresql+psycopg://", "postgresql://", 1)
            connection = ConnectionPool(database_url, min_size=1, max_size=10, open=True)
        return PostgresKnowledgeAccessRegistry(connection)
    raise ValueError("不支持的知识范围仓储类型")


def build_account_service(
    settings: Settings,
    *,
    audit: AuditService,
    login_limiter: LoginRateLimiter,
    connection=None,
    migrate: bool = True,
) -> tuple[AccountService, object]:
    """按存储模式装配账号仓储与服务。"""
    validate_runtime_settings(settings)
    if settings.storage_backend == "memory":
        if settings.env != "development":
            raise ValueError("生产环境禁止使用内存账号仓储")
        repository = InMemoryAccountRepository()
    elif settings.storage_backend == "postgres":
        from .accounts.repository import PostgresAccountRepository

        if connection is None:
            from psycopg_pool import ConnectionPool

            database_url = settings.database_url.replace("postgresql+psycopg://", "postgresql://", 1)
            connection = ConnectionPool(database_url, min_size=1, max_size=10, open=True)
        if migrate:
            apply_migrations(connection, Path(__file__).resolve().parents[1] / "migrations")
        repository = PostgresAccountRepository(connection)
    else:
        raise ValueError("不支持的账号存储类型")
    return (
        AccountService(
            repository,
            bootstrap_token=settings.bootstrap_token,
            audit=audit,
            login_limiter=login_limiter,
            require_admin_totp=settings.require_admin_totp,
        ),
        repository,
    )


def build_planner_service(settings: Settings, *, audit: AuditService, task_store=None, runtime_service=None, run_metrics=None, connection=None, migrate: bool = True):
    """按存储模式装配计划生成服务。"""
    validate_runtime_settings(settings)
    catalog = ToolCatalog.from_config(settings.planner_tools)
    if settings.planner_backend == "mock":
        generator = MockPlanGenerator()
        model_gateway = None
    elif settings.planner_backend == "openai_compatible":
        from .planner.generator import OpenAICompatiblePlanGenerator

        generator = OpenAICompatiblePlanGenerator(
            base_url=settings.planner_model_base_url,
            model_name=settings.planner_model_name,
            api_key=settings.planner_model_api_key,
            timeout_seconds=settings.planner_model_timeout_seconds,
        )
        model_gateway = ModelGateway(
            [
                ProviderModel(
                    model_key=settings.planner_model_name,
                    capabilities=frozenset({PLAN_GENERATION_CAPABILITY}),
                    sensitive_data=settings.planner_model_sensitive_data,
                )
            ]
        )
    else:
        raise ValueError("不支持的规划生成后端")

    if settings.storage_backend == "memory":
        if settings.env != "development":
            raise ValueError("生产环境禁止使用内存计划提案仓储")
        store = InMemoryPlanProposalStore()
    elif settings.storage_backend == "postgres":
        from .planner.store import PostgresPlanProposalStore

        if connection is None:
            from psycopg_pool import ConnectionPool

            database_url = settings.database_url.replace("postgresql+psycopg://", "postgresql://", 1)
            connection = ConnectionPool(database_url, min_size=1, max_size=10, open=True)
        if migrate:
            apply_migrations(connection, Path(__file__).resolve().parents[1] / "migrations")
        store = PostgresPlanProposalStore(connection)
    else:
        raise ValueError("不支持的计划提案存储类型")

    service = PlannerService(
        task_store=task_store,
        store=store,
        generator=generator,
        catalog=catalog,
        runtime_service=runtime_service,
        max_steps=settings.planner_max_steps,
        audit=audit,
        model_gateway=model_gateway,
        run_metrics=run_metrics,
    )
    return service, store


def build_run_metrics(settings: Settings, *, connection=None, migrate: bool = True):
    """按存储模式装配运行记录指标服务。"""
    validate_runtime_settings(settings)
    from .runtime.records import InMemoryRunRecordStore, PostgresRunRecordStore
    from .runtime.run_metrics import RunMetricsService

    if settings.storage_backend == "memory":
        if settings.env != "development":
            raise ValueError("生产环境禁止使用内存运行记录仓储")
        return RunMetricsService(InMemoryRunRecordStore())
    if settings.storage_backend == "postgres":
        if connection is None:
            from psycopg_pool import ConnectionPool

            database_url = settings.database_url.replace("postgresql+psycopg://", "postgresql://", 1)
            connection = ConnectionPool(database_url, min_size=1, max_size=10, open=True)
        if migrate:
            apply_migrations(connection, Path(__file__).resolve().parents[1] / "migrations")
        return RunMetricsService(PostgresRunRecordStore(connection))
    raise ValueError("不支持的运行记录存储类型")


def build_audit_service(settings: Settings, *, connection=None, migrate: bool = True) -> AuditService:
    """按存储模式装配审计仓储。"""
    validate_runtime_settings(settings)
    if settings.storage_backend == "memory":
        if settings.env != "development":
            raise ValueError("生产环境禁止使用内存审计仓储")
        return AuditService(InMemoryAuditStore())
    if settings.storage_backend == "postgres":
        from .audit.store import PostgresAuditStore

        if connection is None:
            from psycopg_pool import ConnectionPool

            database_url = settings.database_url.replace("postgresql+psycopg://", "postgresql://", 1)
            connection = ConnectionPool(database_url, min_size=1, max_size=10, open=True)
        if migrate:
            apply_migrations(connection, Path(__file__).resolve().parents[1] / "migrations")
        return AuditService(PostgresAuditStore(connection))
    raise ValueError("不支持的审计存储类型")


def build_login_rate_limiter(settings: Settings, *, connection=None, migrate: bool = True) -> LoginRateLimiter:
    """按存储模式装配登录限流。"""
    validate_runtime_settings(settings)
    if settings.storage_backend == "memory":
        if settings.env != "development":
            raise ValueError("生产环境禁止使用内存登录限流仓储")
        store = InMemoryLoginAttemptStore()
    elif settings.storage_backend == "postgres":
        from .accounts.rate_limit import PostgresLoginAttemptStore

        if connection is None:
            from psycopg_pool import ConnectionPool

            database_url = settings.database_url.replace("postgresql+psycopg://", "postgresql://", 1)
            connection = ConnectionPool(database_url, min_size=1, max_size=10, open=True)
        if migrate:
            apply_migrations(connection, Path(__file__).resolve().parents[1] / "migrations")
        store = PostgresLoginAttemptStore(connection)
    else:
        raise ValueError("不支持的登录限流存储类型")
    return LoginRateLimiter(
        store,
        secret=settings.auth_secret,
        max_failures=settings.login_max_failures,
        window_seconds=settings.login_window_seconds,
        lock_seconds=settings.login_lock_seconds,
    )
