from __future__ import annotations

from pathlib import Path

from .accounts.rate_limit import InMemoryLoginAttemptStore, LoginRateLimiter
from .accounts.repository import InMemoryAccountRepository
from .accounts.secrets import build_totp_cipher
from .accounts.service import AccountService
from .agent_services import ModelGateway, ProviderModel
from .audit.service import AuditService
from .audit.store import InMemoryAuditStore
from .domain import TaskStore
from .dead_letters import DeadLetterStore, PostgresDeadLetterStore
from .knowledge_policy import KnowledgeAccessRegistry, PostgresKnowledgeAccessRegistry
from .events import InMemoryEventBus, RedisStreamEventBus
from .inbox import InMemoryInboxStore, InboxService, PostgresInboxStore
from .migrations import apply_migrations
from .outbox import OutboxPublisher
from .planner.classification import PLAN_GENERATION_CAPABILITY
from .planner.generator import MockPlanGenerator
from .planner.models import ToolCatalog
from .planner.service import PlannerService
from .planner.store import InMemoryPlanProposalStore
from .repository import PostgresTaskRepository, TaskRepository
from .sessions import InMemorySessionRevocationStore
from .settings import Settings, parse_previous_body_keys, validate_runtime_settings
from .workforce.store import (
    InMemoryWorkforceDirectoryStore,
    PostgresWorkforceDirectoryStore,
)


def build_commercial_components(settings: Settings, *, connection=None, migrate: bool = True, audit: AuditService | None = None):
    """Build tenant, usage, and lifecycle persistence as one coordinated unit.

    `audit` 注入生命周期服务：真源要求「任何保留策略变化都写入审计」
    （`commercial-g0-design.md:118`）；未注入时 `set_retention` fail-closed。
    """
    validate_runtime_settings(settings)
    from .commercial.lifecycle import (
        CommercialLifecycleService,
        InMemoryExportPackageStore,
        InMemoryLifecycleJobStore,
        InMemoryRetentionPolicyStore,
        PostgresExportPackageStore,
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
            export_store=InMemoryExportPackageStore(),
            audit=audit,
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
        export_store=PostgresExportPackageStore(connection),
        audit=audit,
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


def build_content_scraper(settings: Settings):
    """按白名单装配网页抓取器；未配置域名即关闭抓取功能（不是放行）。"""
    validate_runtime_settings(settings)
    domains = frozenset(
        item.strip().lower()
        for item in settings.content_scrape_allowed_domains.split(",")
        if item.strip()
    )
    if not domains:
        return None
    from .content.scraper import ScrapePolicy, WebScraper

    policy = ScrapePolicy(
        allowed_domains=domains,
        user_agent=settings.content_scrape_user_agent,
        timeout_seconds=settings.content_scrape_timeout_seconds,
        max_bytes=settings.content_scrape_max_bytes,
        min_interval_seconds=settings.content_scrape_min_interval_seconds,
    )
    return WebScraper(policy)


def build_content_publisher(settings: Settings):
    """按配置装配公众号发布器；未配置则返回 None（发布功能关闭，fail-closed）。"""
    validate_runtime_settings(settings)
    if not (
        settings.content_publish_endpoint
        and settings.content_publish_account_id
        and settings.content_publish_access_token
    ):
        return None
    from .content.publisher import WechatMpPublisher

    return WechatMpPublisher(
        settings.content_publish_endpoint,
        settings.content_publish_account_id,
        settings.content_publish_access_token,
        timeout_seconds=settings.content_publish_timeout_seconds,
        name=settings.content_publish_target or "wechat_mp",
    )


def build_inbox_service(settings: Settings, *, audit=None, connection=None, migrate: bool = True) -> InboxService:
    """按存储模式装配站内通知（收件箱）。

    保留期取 ``WORKBENCH_INBOX_RETENTION_DAYS``（默认 90 天）；过期条目由仓储惰性清理。
    """
    validate_runtime_settings(settings)
    if settings.storage_backend == "memory":
        if settings.env != "development":
            raise ValueError("生产环境禁止使用内存收件箱")
        return InboxService(
            InMemoryInboxStore(retention_days=settings.inbox_retention_days), audit=audit
        )
    if settings.storage_backend == "postgres":
        if connection is None:
            from psycopg_pool import ConnectionPool

            database_url = settings.database_url.replace("postgresql+psycopg://", "postgresql://", 1)
            connection = ConnectionPool(database_url, min_size=1, max_size=10, open=True)
        if migrate:
            apply_migrations(connection, Path(__file__).resolve().parents[1] / "migrations")
        return InboxService(
            PostgresInboxStore(connection, retention_days=settings.inbox_retention_days), audit=audit
        )
    raise ValueError("不支持的收件箱存储类型")


def build_publication_service(
    settings: Settings,
    *,
    content_store,
    publisher=None,
    audit=None,
    inbox=None,
    connection=None,
    migrate: bool = True,
):
    """按存储模式装配内容发布编排服务。"""
    validate_runtime_settings(settings)
    from .content.publication_service import PublicationService
    from .content.publication_store import InMemoryPublicationStore, PostgresPublicationStore

    if settings.storage_backend == "memory":
        if settings.env != "development":
            raise ValueError("生产环境禁止使用内存发布记录仓储")
        store = InMemoryPublicationStore()
    elif settings.storage_backend == "postgres":
        if connection is None:
            from psycopg_pool import ConnectionPool

            database_url = settings.database_url.replace("postgresql+psycopg://", "postgresql://", 1)
            connection = ConnectionPool(database_url, min_size=1, max_size=10, open=True)
        if migrate:
            apply_migrations(connection, Path(__file__).resolve().parents[1] / "migrations")
        store = PostgresPublicationStore(connection)
    else:
        raise ValueError("不支持的发布记录存储类型")
    return PublicationService(
        content_store,
        store,
        publisher=publisher,
        audit=audit,
        inbox=inbox,
    )


def build_outbox_publisher(
    settings: Settings, *, connection=None, redis_client=None, audit=None
) -> OutboxPublisher:
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
    dead_letter_store = build_dead_letter_store(
        settings, event_bus=event_bus, connection=connection, audit=audit
    )
    return OutboxPublisher(
        connection,
        event_bus,
        max_attempts=settings.outbox_max_attempts,
        dead_letter_store=dead_letter_store,
    )


def build_dead_letter_store(settings: Settings, *, event_bus, connection=None, audit=None):
    """Select a development or durable dead-letter repository."""
    validate_runtime_settings(settings)
    if settings.storage_backend == "memory":
        if settings.env != "development":
            raise ValueError("生产环境禁止使用内存死信仓储")
        store = DeadLetterStore(event_bus)
    elif settings.storage_backend == "postgres":
        if connection is None:
            from psycopg_pool import ConnectionPool

            database_url = settings.database_url.replace("postgresql+psycopg://", "postgresql://", 1)
            connection = ConnectionPool(database_url, min_size=1, max_size=10, open=True)
        store = PostgresDeadLetterStore(connection, event_bus)
    else:
        raise ValueError("不支持的死信仓储类型")
    if not settings.dead_letter_webhook_url or audit is None:
        return store
    from .notifications import DeadLetterNotifier, WebhookNotificationChannel
    from .dead_letters import NotifyingDeadLetterStore

    channel = WebhookNotificationChannel(
        settings.dead_letter_webhook_url,
        timeout_seconds=settings.dead_letter_webhook_timeout_seconds,
    )
    return NotifyingDeadLetterStore(
        inner=store, notifier=DeadLetterNotifier(channel), audit=audit
    )


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


def build_workforce_directory_store(settings: Settings, *, connection=None, migrate: bool = True):
    """按存储模式装配岗位/数字员工目录仓储（表 `workbench_job_roles` /
    `workbench_digital_employees`，迁移 022）。"""
    validate_runtime_settings(settings)
    if settings.storage_backend == "memory":
        if settings.env != "development":
            raise ValueError("生产环境禁止使用内存岗位/数字员工目录仓储")
        return InMemoryWorkforceDirectoryStore()
    if settings.storage_backend == "postgres":
        if connection is None:
            from psycopg_pool import ConnectionPool

            database_url = settings.database_url.replace("postgresql+psycopg://", "postgresql://", 1)
            connection = ConnectionPool(database_url, min_size=1, max_size=10, open=True)
        if migrate:
            apply_migrations(connection, Path(__file__).resolve().parents[1] / "migrations")
        return PostgresWorkforceDirectoryStore(connection)
    raise ValueError("不支持的岗位/数字员工目录仓储类型")


def build_session_revocation_store(settings: Settings, *, connection=None, migrate: bool = True):
    """按存储模式装配会话撤销名单（登出立即生效）。"""
    validate_runtime_settings(settings)
    if settings.storage_backend == "memory":
        if settings.env != "development":
            raise ValueError("生产环境禁止使用内存会话撤销名单")
        return InMemorySessionRevocationStore()
    if settings.storage_backend == "postgres":
        from .sessions import PostgresSessionRevocationStore

        if connection is None:
            from psycopg_pool import ConnectionPool

            database_url = settings.database_url.replace("postgresql+psycopg://", "postgresql://", 1)
            connection = ConnectionPool(database_url, min_size=1, max_size=10, open=True)
        if migrate:
            apply_migrations(connection, Path(__file__).resolve().parents[1] / "migrations")
        return PostgresSessionRevocationStore(connection)
    raise ValueError("不支持的会话撤销存储类型")


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
        # TOTP 种子静态加密：密钥材料由备份加密密钥经 HKDF 派生（生产已强制要求该密钥）。
        repository = PostgresAccountRepository(
            connection, cipher=build_totp_cipher(settings.backup_encryption_key)
        )
    else:
        raise ValueError("不支持的账号存储类型")
    sso_config = build_sso_config(settings)
    sso_state_store = (
        build_sso_state_store(settings, connection=connection, migrate=migrate)
        if sso_config is not None
        else None
    )
    return (
        AccountService(
            repository,
            bootstrap_token=settings.bootstrap_token,
            audit=audit,
            login_limiter=login_limiter,
            require_admin_totp=settings.require_admin_totp,
            sso_config=sso_config,
            sso_state_store=sso_state_store,
            sso_provider=settings.sso_provider,
            sso_trust_idp_mfa=settings.sso_trust_idp_mfa,
            sso_state_ttl_seconds=settings.sso_state_ttl_seconds,
        ),
        repository,
    )


def build_sso_config(settings: Settings):
    """按配置装配 SSO；未启用返回 None，启用但缺必填项 fail-closed 报错。"""
    if not settings.sso_enabled:
        return None
    from .accounts.sso import SsoConfig

    required = {
        "sso_issuer": settings.sso_issuer,
        "sso_authorization_endpoint": settings.sso_authorization_endpoint,
        "sso_token_endpoint": settings.sso_token_endpoint,
        "sso_jwks_uri": settings.sso_jwks_uri,
        "sso_client_id": settings.sso_client_id,
        "sso_client_secret": settings.sso_client_secret,
        "sso_redirect_uri": settings.sso_redirect_uri,
    }
    missing = [
        name
        for name, value in required.items()
        if not (isinstance(value, str) and value.strip())
    ]
    if missing:
        raise ValueError("SSO 已启用但缺少必填配置：" + "、".join(missing))
    return SsoConfig(
        issuer=settings.sso_issuer.strip(),
        authorization_endpoint=settings.sso_authorization_endpoint.strip(),
        token_endpoint=settings.sso_token_endpoint.strip(),
        jwks_uri=settings.sso_jwks_uri.strip(),
        client_id=settings.sso_client_id.strip(),
        client_secret=settings.sso_client_secret,
        redirect_uri=settings.sso_redirect_uri.strip(),
        scopes=tuple(item for item in settings.sso_scopes.split() if item),
        timeout_seconds=settings.sso_timeout_seconds,
    )


def build_sso_state_store(settings: Settings, *, connection=None, migrate: bool = True):
    """按存储模式装配 SSO 授权 state 仓储。"""
    validate_runtime_settings(settings)
    from .accounts.sso_store import InMemorySsoStateStore, PostgresSsoStateStore

    if settings.storage_backend == "memory":
        if settings.env != "development":
            raise ValueError("生产环境禁止使用内存 SSO 状态仓储")
        return InMemorySsoStateStore()
    if settings.storage_backend == "postgres":
        if connection is None:
            from psycopg_pool import ConnectionPool

            database_url = settings.database_url.replace("postgresql+psycopg://", "postgresql://", 1)
            connection = ConnectionPool(database_url, min_size=1, max_size=10, open=True)
        if migrate:
            apply_migrations(connection, Path(__file__).resolve().parents[1] / "migrations")
        return PostgresSsoStateStore(connection)
    raise ValueError("不支持的 SSO 状态存储类型")


def build_planner_service(settings: Settings, *, audit: AuditService, task_store=None, runtime_service=None, connection=None, migrate: bool = True):
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


def build_runtime_state_store(settings: Settings, *, connection=None, migrate: bool = True):
    """按存储模式装配运行时状态仓储。

    postgres 模式强制持久化：不提供连接时自建连接池，并随启动执行迁移；
    内存实现只在 development 允许（延续「生产禁止内存仓储」的约束）。
    """
    from .runtime.state import RuntimeStateStore

    if settings.storage_backend == "memory":
        if settings.env != "development":
            raise ValueError("生产环境禁止使用内存运行时状态仓储")
        return RuntimeStateStore()
    if settings.storage_backend == "postgres":
        from .runtime.state_postgres import PostgresRuntimeStateStore

        if connection is None:
            from psycopg_pool import ConnectionPool

            database_url = settings.database_url.replace("postgresql+psycopg://", "postgresql://", 1)
            connection = ConnectionPool(database_url, min_size=1, max_size=10, open=True)
        if migrate:
            apply_migrations(connection, Path(__file__).resolve().parents[1] / "migrations")
        return PostgresRuntimeStateStore(connection)
    raise ValueError("不支持的运行时状态存储类型")


def build_runtime_service(
    settings: Settings,
    *,
    store,
    transport_factory=None,
    state_store=None,
    run_metrics=None,
    tool_actions=None,
    usage_ledger=None,
):
    """从裸名配置装配 Runtime 服务；未配置任何地址时只保留 Mock。

    `tool_actions` 为 027 待批动作仓储：必须与 `build_tool_execution` 复用**同一个实例**
    （§4.1.6-2「不得建两个实例」），由 `app/main.py` 按同一实例传入；未启用真实执行时为
    `None`（保持既有行为，仅比对运行级摘要，§4.1.7-5）。

    `usage_ledger` 为商业化追加式用量账本（`app/main.py` 传入装配期单例，与
    `GET /api/v1/commercial/usage` 读取的**同一实例**）；未传入时为 `None`（不记账）。
    """
    validate_runtime_settings(settings)
    from .runtime.registry import build_runtime_registry
    from .runtime.service import RuntimeService
    from .runtime.state import RuntimeStateStore

    shared_state_store = state_store or RuntimeStateStore()
    registry = build_runtime_registry(
        _runtime_registry_config(settings),
        transport_factory=transport_factory,
        state_store=shared_state_store,
    )
    return RuntimeService(
        store,
        registry=registry,
        state_store=shared_state_store,
        run_metrics=run_metrics,
        tool_actions=tool_actions,
        usage_ledger=usage_ledger,
    )


_UNSET = object()


def build_tool_action_store(settings: Settings, *, connection=None, migrate: bool = True):
    """公开装配 `workbench_tool_actions`（027）仓储，供 `RuntimeService` 与
    `ToolExecutionService` 共用**同一实例**（§4.1.6-2）。

    - `WORKBENCH_AGENT_RUNTIME_BACKEND != dsh`（默认 `mock`）→ `None`（真实执行未启用，无 027）；
    - 装配失败（缺件 / 配置非法）→ 记 `error` 并返回 `None`，即"拒绝启用真实执行，但不拒绝
      整个服务进程启动"（§4.1.6-3），与 `build_tool_execution` 的失败口径一致。
    """
    validate_runtime_settings(settings)
    if settings.agent_runtime_backend != "dsh":
        return None
    from .tool_execution.errors import ToolExecutionConfigError
    from .tool_execution.log import get_logger

    try:
        return _build_tool_action_store(settings, connection=connection, migrate=migrate)
    except ToolExecutionConfigError as exc:
        get_logger().error("段二真实执行装配失败，已拒绝启用：%s", exc)
        return None


def build_tool_execution(
    settings: Settings,
    *,
    run_metrics=None,
    audit=None,
    connection=None,
    migrate: bool = True,
    runtime_service=None,
    tool_actions=_UNSET,
    token_store=None,
    token_registry=None,
):
    """按 backend 装配段二工具执行服务（规格 §4.1.6-2）。

    - `WORKBENCH_AGENT_RUNTIME_BACKEND=mock`（默认）时**必须**返回 `None`；
    - 装配失败（缺件 / 配置非法）**不抛进程级异常**：记 `error` 告警并返回 `None`，
      即"拒绝启用真实执行，但不拒绝整个服务进程启动"（§4.1.6-3）；
    - `tool_actions` 由 `app/main.py` 传入与 `RuntimeService` 共用的**同一 027 仓储实例**；
      未显式传入（`_UNSET`，如单测直连）时才在内部装配；
    - `token_store` / `token_registry` 是 ②④ 的**权威状态**（§3.5 P1 第 3 条 / §8 U24）：
      由 `app/main.py` 传入**装配期单例**，与 `build_exec_callback_guard`（判定侧）**共用同一实例**。
      未传入时（单测直连）内部新建——此时 mint 侧与回调判定侧**不共享**，②④ 会恒 `403`。
    """
    validate_runtime_settings(settings)
    if settings.agent_runtime_backend != "dsh":
        return None

    from .tool_execution.body_cipher import BodyCipher
    from .tool_execution.catalog import build_tool_spec_catalog
    from .tool_execution.errors import ToolExecutionConfigError
    from .tool_execution.executor import ContainerExecutor
    from .tool_execution.log import get_logger
    from .tool_execution.service import ToolExecutionService
    from .tool_execution.startup import assert_real_execution_ready
    from .tool_execution.workspace import WorkspaceManager

    # 授权位与运行记录同库同表：直接复用运行记录仓储（§4.1.6-1）。
    run_records = getattr(run_metrics, "store", None)
    try:
        catalog = build_tool_spec_catalog()
        if tool_actions is _UNSET:
            tool_actions = _build_tool_action_store(settings, connection=connection, migrate=migrate)
        body_cipher = BodyCipher.from_base64(
            settings.body_encryption_key,
            # 旧密钥在**进程启动时**读入（§8 U22：轮换 = 改配置 + 重启，**无热轮换**）。
            # 配置缺失 / 留空 ⇒ 空列表 ⇒ 不使用旧密钥（fail-closed）。
            previous=parse_previous_body_keys(settings.body_encryption_previous_keys),
        )
        # ②④⑤ 的令牌控制面（§8 U24 收口）：mint 侧写、判定侧读，**共用同一 store/registry**。
        turn_tokens = _build_turn_token_controller(
            settings, store=token_store, registry=token_registry
        )
        # 终态同步吊销（⑤）经 `from_settings` 注入（§8 U25 A2 缺口收口）。
        executor = ContainerExecutor.from_settings(
            settings, token_revoker=turn_tokens.on_terminal
        )
        workspace = WorkspaceManager(settings.exec_workspace_root)
        tool_execution = ToolExecutionService(
            catalog=catalog,
            body_cipher=body_cipher,
            executor=executor,
            workspace=workspace,
            tool_actions=tool_actions,
            run_records=run_records,
            audit=audit,
            # ① 组装工具面过滤：`artifact.export` 默认不装配（fail-closed，§4）。
            artifact_export_enabled=settings.artifact_export_enabled,
            # ④-0 受信任可执行根来自外置配置（不使用 PATH 解析）。
            trusted_roots=settings.exec_trusted_roots,
            # ⑦ 复用既有 `RuntimeService.ensure_execution_authorized`（不另造一套）。
            authorize_execution=(
                runtime_service.ensure_execution_authorized
                if runtime_service is not None
                else None
            ),
            turn_tokens=turn_tokens,
        )
    except ToolExecutionConfigError as exc:
        get_logger().error("段二真实执行装配失败，已拒绝启用：%s", exc)
        return None

    if not assert_real_execution_ready(
        tool_execution=tool_execution,
        run_records=run_records,
        tool_actions=tool_actions,
        catalog=catalog,
        turn_tokens=turn_tokens,
    ):
        return None
    return tool_execution


def _build_turn_token_controller(settings: Settings, *, store=None, registry=None):
    """装配 §3.5 P1 第 3 条 ②④⑤ 的令牌控制面（**消费既有 `model_gateway_mint_secret`**）。

    配置项**不新增**：网关地址与网关控制面密钥分别复用 `model_gateway_base_url` /
    `model_gateway_mint_secret`（后者此前在 `app/` 内**零消费者**，本次开始消费）。
    """
    from .tool_execution.active_execution import ActiveExecutionRegistry
    from .tool_execution.token_binding import TokenBindingStore
    from .tool_execution.turn_token import TurnTokenController

    return TurnTokenController(
        store=store if store is not None else TokenBindingStore(),
        registry=registry if registry is not None else ActiveExecutionRegistry(),
        gateway_base_url=settings.model_gateway_base_url,
        mint_secret=settings.model_gateway_mint_secret,
        timeout_seconds=float(settings.model_gateway_upstream_timeout_seconds),
        # 供应商密钥：控制器只把它用于「拒绝性自检」，**绝不注入容器**（§3.5 P1）。
        vendor_api_key=settings.model_gateway_upstream_api_key,
    )


def _build_tool_action_store(settings: Settings, *, connection=None, migrate: bool = True):
    """按存储模式装配 `workbench_tool_actions` 仓储（内存实现仅 development 允许）。"""
    from .tool_execution.errors import ToolExecutionConfigError
    from .tool_execution.store import InMemoryToolActionStore, PostgresToolActionStore

    if settings.storage_backend == "memory":
        if settings.env != "development":
            raise ToolExecutionConfigError("生产环境禁止使用内存工具动作仓储")
        return InMemoryToolActionStore()
    if settings.storage_backend == "postgres":
        if connection is None:
            from psycopg_pool import ConnectionPool

            database_url = settings.database_url.replace("postgresql+psycopg://", "postgresql://", 1)
            connection = ConnectionPool(database_url, min_size=1, max_size=10, open=True)
        if migrate:
            apply_migrations(connection, Path(__file__).resolve().parents[1] / "migrations")
        return PostgresToolActionStore(connection)
    raise ToolExecutionConfigError("不支持的工具动作存储类型")


_RUNTIME_KEYS = ("ragflow", "agentscope", "deerflow", "codex_worker", "hermes")


def _runtime_registry_config(settings: Settings) -> dict[str, dict[str, object]]:
    """把 Settings 上的裸名配置翻译成 build_runtime_registry 需要的结构。"""
    config: dict[str, dict[str, object]] = {}
    for key in _RUNTIME_KEYS:
        endpoint = (getattr(settings, f"{key}_endpoint") or "").strip()
        capabilities = [
            item.strip()
            for item in (getattr(settings, f"{key}_capabilities") or "").split(",")
            if item.strip()
        ]
        config[key] = {
            "enabled": bool(endpoint),
            "endpoint": endpoint,
            "version": getattr(settings, f"{key}_version"),
            "capabilities": capabilities,
            "timeout_seconds": getattr(settings, f"{key}_timeout_seconds"),
            "auth_injected": getattr(settings, f"{key}_auth_injected"),
            "auth_token": getattr(settings, f"{key}_auth_token"),
            "auth_header": getattr(settings, f"{key}_auth_header"),
            "auth_scheme": getattr(settings, f"{key}_auth_scheme"),
        }
    return config


def build_orchestration_proposal_service(
    settings: Settings,
    *,
    metrics,
    audit: AuditService,
    connection=None,
    migrate: bool = True,
):
    """按存储模式装配编排优化提案服务。"""
    validate_runtime_settings(settings)
    from .orchestration.service import OrchestrationProposalService

    if settings.storage_backend == "memory":
        if settings.env != "development":
            raise ValueError("生产环境禁止使用内存优化提案仓储")
        from .orchestration.store import InMemoryOrchestrationProposalStore

        store = InMemoryOrchestrationProposalStore()
    elif settings.storage_backend == "postgres":
        from .orchestration.store import PostgresOrchestrationProposalStore

        if connection is None:
            from psycopg_pool import ConnectionPool

            database_url = settings.database_url.replace("postgresql+psycopg://", "postgresql://", 1)
            connection = ConnectionPool(database_url, min_size=1, max_size=10, open=True)
        if migrate:
            apply_migrations(connection, Path(__file__).resolve().parents[1] / "migrations")
        store = PostgresOrchestrationProposalStore(connection)
    else:
        raise ValueError("不支持的优化提案存储类型")

    return OrchestrationProposalService(
        store,
        metrics=metrics,
        audit=audit,
        default_runtime_key=settings.orchestration_default_runtime_key,
        min_samples=settings.orchestration_min_samples,
        improvement_threshold=settings.orchestration_improvement_threshold,
    )


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


def build_conversation_store(settings: Settings, *, connection=None, migrate: bool = True):
    """按存储模式装配对话仓储（表 `workbench_conversations` /
    `workbench_conversation_messages`，迁移 023）。"""
    validate_runtime_settings(settings)
    from .conversation.store import InMemoryConversationStore, PostgresConversationStore

    if settings.storage_backend == "memory":
        if settings.env != "development":
            raise ValueError("生产环境禁止使用内存对话仓储")
        return InMemoryConversationStore()
    if settings.storage_backend == "postgres":
        if connection is None:
            from psycopg_pool import ConnectionPool

            database_url = settings.database_url.replace("postgresql+psycopg://", "postgresql://", 1)
            connection = ConnectionPool(database_url, min_size=1, max_size=10, open=True)
        if migrate:
            apply_migrations(connection, Path(__file__).resolve().parents[1] / "migrations")
        return PostgresConversationStore(connection)
    raise ValueError("不支持的对话存储类型")


def build_conversation_service(settings: Settings, *, store, audit=None):
    """装配对话服务（P1 使用确定性桩回复，不接真实模型，D7）。"""
    validate_runtime_settings(settings)
    from .conversation.service import ConversationService

    return ConversationService(store, audit=audit)


def build_execution_idempotency_store(settings: Settings, *, connection=None, migrate: bool = True):
    """按存储模式装配执行幂等仓储（表 `workbench_execution_idempotency`，迁移 027）。"""
    validate_runtime_settings(settings)
    from .conversation.idempotency import (
        InMemoryExecutionIdempotencyStore,
        PostgresExecutionIdempotencyStore,
    )

    if settings.storage_backend == "memory":
        if settings.env != "development":
            raise ValueError("生产环境禁止使用内存执行幂等仓储")
        return InMemoryExecutionIdempotencyStore()
    if settings.storage_backend == "postgres":
        if connection is None:
            from psycopg_pool import ConnectionPool

            database_url = settings.database_url.replace("postgresql+psycopg://", "postgresql://", 1)
            connection = ConnectionPool(database_url, min_size=1, max_size=10, open=True)
        if migrate:
            apply_migrations(connection, Path(__file__).resolve().parents[1] / "migrations")
        return PostgresExecutionIdempotencyStore(connection)
    raise ValueError("不支持的执行幂等存储类型")


def build_conversation_execution_service(
    settings: Settings,
    *,
    conversations,
    conversation_store,
    task_store,
    runtime_service,
    tool_execution=None,
    idempotency=None,
    audit=None,
    directory_store=None,
    catalog=None,
):
    """装配对话入口路由（段二-4，规格 §3.7 Y2 / §3.2 第四条）。

    `tool_execution=None`（`backend=mock`）时服务仍装配，但**只走既有 `stub=true` 通路**
    （缺键语义与「未启用真实执行」同构，不创建承载任务 / 运行）。
    """
    validate_runtime_settings(settings)
    from .conversation.execution import ConversationExecutionService

    if catalog is None and tool_execution is not None:
        from .tool_execution.catalog import build_tool_spec_catalog

        catalog = build_tool_spec_catalog()
    return ConversationExecutionService(
        conversations=conversations,
        conversation_store=conversation_store,
        task_store=task_store,
        runtime_service=runtime_service,
        tool_execution=tool_execution,
        idempotency=idempotency,
        catalog=catalog,
        audit=audit,
        directory_store=directory_store,
    )


def build_exec_callback_guard(settings: Settings, *, audit=None, store=None, registry=None):
    """装配工作台侧的「执行回调接收」②④ 判定组件（规格 §3.5 P1 第 3 条 ②④ / §8 U21 裁决）。

    2026-09-14 返工（§8 U21 裁决「候选②：边车纯转发 + 判定回工作台」）：判定落点回到**工作台**
    的权威状态处——`expected` 从 `ActiveExecutionRegistry`（会话当前代次）重建、**绝不取自请求体**，
    与令牌自持绑定（`TokenBindingStore`，mint 时落）做 `constant-time` 比对。边车不再持有这些状态。

    `store` / `registry` 由 `app/main.py` 传入**装配期单例**，与 mint 侧
    （`build_tool_execution` → `TurnTokenController`）**共用同一实例**（§8 U24：不共享则 ②④ 恒 `403`）。
    未传入时（单测直连）内部新建。
    """
    validate_runtime_settings(settings)
    from .tool_execution.active_execution import ActiveExecutionRegistry
    from .tool_execution.callback_guard import WorkbenchCallbackGuard
    from .tool_execution.token_binding import TokenBindingStore

    return WorkbenchCallbackGuard(
        store=store if store is not None else TokenBindingStore(),
        registry=registry if registry is not None else ActiveExecutionRegistry(),
        audit=audit,
    )


def registered_model_keys(settings: Settings) -> frozenset[str]:
    """模型网关注册的候选键（与 `build_planner_service` 装配 `ModelGateway` 的口径一致）。"""
    keys: set[str] = set()
    if settings.planner_backend == "openai_compatible" and settings.planner_model_name.strip():
        keys.add(settings.planner_model_name.strip())
    return frozenset(keys)


def allowed_tool_names(settings: Settings) -> frozenset[str]:
    """服务端工具白名单的工具名集合（与 `build_planner_service` 同一 `ToolCatalog`）。"""
    return frozenset(ToolCatalog.from_config(settings.planner_tools).names())


def build_agent_config_service(settings: Settings, *, store, audit=None):
    """装配数字员工配置闸门：模型键与工具白名单都取自服务端已注册集合（fail-closed）。"""
    validate_runtime_settings(settings)
    from .workforce.config import AgentConfigService

    return AgentConfigService(
        store,
        audit=audit,
        allowed_model_keys=registered_model_keys(settings),
        allowed_tools=allowed_tool_names(settings),
    )
