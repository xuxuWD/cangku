from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="WORKBENCH_", env_file=".env", extra="ignore", populate_by_name=True,
    )

    env: str = "development"
    database_url: str = "sqlite:///./workbench.dev.db"
    redis_url: str = "redis://localhost:6379/0"
    object_storage_url: str = "http://localhost:9000"
    log_level: str = "INFO"
    auth_secret: str = ""
    backup_encryption_key: str = Field(
        default="",
        validation_alias=AliasChoices(
            "BACKUP_ENCRYPTION_KEY", "WORKBENCH_BACKUP_ENCRYPTION_KEY"
        ),
    )
    outbox_max_attempts: int = Field(
        default=3,
        ge=1,
        le=20,
        validation_alias=AliasChoices("OUTBOX_MAX_ATTEMPTS", "WORKBENCH_OUTBOX_MAX_ATTEMPTS"),
    )
    dead_letter_webhook_url: str = Field(
        default="",
        validation_alias=AliasChoices(
            "DEAD_LETTER_WEBHOOK_URL", "WORKBENCH_DEAD_LETTER_WEBHOOK_URL"
        ),
    )
    dead_letter_webhook_timeout_seconds: float = Field(
        default=5.0,
        ge=1,
        le=30,
        validation_alias=AliasChoices(
            "DEAD_LETTER_WEBHOOK_TIMEOUT_SECONDS",
            "WORKBENCH_DEAD_LETTER_WEBHOOK_TIMEOUT_SECONDS",
        ),
    )
    storage_backend: str = "memory"
    content_store_backend: str = Field(
        default="sqlite",
        validation_alias=AliasChoices("CONTENT_STORE_BACKEND", "WORKBENCH_CONTENT_STORE_BACKEND"),
    )
    content_store_path: str = Field(
        default="data/content-workbench.sqlite3",
        validation_alias=AliasChoices("CONTENT_STORE_PATH", "WORKBENCH_CONTENT_STORE_PATH"),
    )
    content_generation_backend: str = Field(
        default="mock",
        validation_alias=AliasChoices("CONTENT_GENERATION_BACKEND", "WORKBENCH_CONTENT_GENERATION_BACKEND"),
    )
    content_model_base_url: str = Field(
        default="",
        validation_alias=AliasChoices("CONTENT_MODEL_BASE_URL", "WORKBENCH_CONTENT_MODEL_BASE_URL"),
    )
    content_model_name: str = Field(
        default="",
        validation_alias=AliasChoices("CONTENT_MODEL_NAME", "WORKBENCH_CONTENT_MODEL_NAME"),
    )
    content_model_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("CONTENT_MODEL_API_KEY", "WORKBENCH_CONTENT_MODEL_API_KEY"),
    )
    content_model_timeout_seconds: float = Field(
        default=30.0, ge=1, le=120,
        validation_alias=AliasChoices("CONTENT_MODEL_TIMEOUT_SECONDS", "WORKBENCH_CONTENT_MODEL_TIMEOUT_SECONDS"),
    )
    content_model_max_retries: int = Field(
        default=2, ge=0, le=5,
        validation_alias=AliasChoices("CONTENT_MODEL_MAX_RETRIES", "WORKBENCH_CONTENT_MODEL_MAX_RETRIES"),
    )
    content_scrape_allowed_domains: str = Field(
        default="",
        validation_alias=AliasChoices("CONTENT_SCRAPE_ALLOWED_DOMAINS", "WORKBENCH_CONTENT_SCRAPE_ALLOWED_DOMAINS"),
    )
    content_scrape_timeout_seconds: float = Field(
        default=10.0, ge=1, le=60,
        validation_alias=AliasChoices("CONTENT_SCRAPE_TIMEOUT_SECONDS", "WORKBENCH_CONTENT_SCRAPE_TIMEOUT_SECONDS"),
    )
    content_scrape_max_bytes: int = Field(
        default=2_000_000, ge=1_000, le=20_000_000,
        validation_alias=AliasChoices("CONTENT_SCRAPE_MAX_BYTES", "WORKBENCH_CONTENT_SCRAPE_MAX_BYTES"),
    )
    content_scrape_min_interval_seconds: float = Field(
        default=1.0, ge=0, le=60,
        validation_alias=AliasChoices("CONTENT_SCRAPE_MIN_INTERVAL_SECONDS", "WORKBENCH_CONTENT_SCRAPE_MIN_INTERVAL_SECONDS"),
    )
    content_scrape_user_agent: str = Field(
        default="CompanyWorkbenchBot/0.1",
        validation_alias=AliasChoices("CONTENT_SCRAPE_USER_AGENT", "WORKBENCH_CONTENT_SCRAPE_USER_AGENT"),
    )
    bootstrap_token: str = Field(
        default="",
        validation_alias=AliasChoices("BOOTSTRAP_TOKEN", "WORKBENCH_BOOTSTRAP_TOKEN"),
    )
    session_ttl_seconds: int = Field(
        default=900,
        ge=60,
        le=3600,
        validation_alias=AliasChoices("SESSION_TTL_SECONDS", "WORKBENCH_SESSION_TTL_SECONDS"),
    )
    planner_backend: str = Field(
        default="mock",
        validation_alias=AliasChoices("PLANNER_BACKEND", "WORKBENCH_PLANNER_BACKEND"),
    )
    planner_tools: str = Field(
        default="[]",
        validation_alias=AliasChoices("PLANNER_TOOLS", "WORKBENCH_PLANNER_TOOLS"),
    )
    planner_max_steps: int = Field(
        default=10,
        ge=1,
        le=50,
        validation_alias=AliasChoices("PLANNER_MAX_STEPS", "WORKBENCH_PLANNER_MAX_STEPS"),
    )
    planner_model_base_url: str = Field(
        default="",
        validation_alias=AliasChoices("PLANNER_MODEL_BASE_URL", "WORKBENCH_PLANNER_MODEL_BASE_URL"),
    )
    planner_model_name: str = Field(
        default="",
        validation_alias=AliasChoices("PLANNER_MODEL_NAME", "WORKBENCH_PLANNER_MODEL_NAME"),
    )
    planner_model_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("PLANNER_MODEL_API_KEY", "WORKBENCH_PLANNER_MODEL_API_KEY"),
    )
    planner_model_timeout_seconds: float = Field(
        default=30.0,
        ge=1,
        le=120,
        validation_alias=AliasChoices("PLANNER_MODEL_TIMEOUT_SECONDS", "WORKBENCH_PLANNER_MODEL_TIMEOUT_SECONDS"),
    )
    planner_model_sensitive_data: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "PLANNER_MODEL_SENSITIVE_DATA", "WORKBENCH_PLANNER_MODEL_SENSITIVE_DATA"
        ),
    )
    login_max_failures: int = Field(
        default=5,
        ge=1,
        le=20,
        validation_alias=AliasChoices("LOGIN_MAX_FAILURES", "WORKBENCH_LOGIN_MAX_FAILURES"),
    )
    login_window_seconds: int = Field(
        default=300,
        ge=30,
        le=3600,
        validation_alias=AliasChoices("LOGIN_WINDOW_SECONDS", "WORKBENCH_LOGIN_WINDOW_SECONDS"),
    )
    login_lock_seconds: int = Field(
        default=900,
        ge=30,
        le=86400,
        validation_alias=AliasChoices("LOGIN_LOCK_SECONDS", "WORKBENCH_LOGIN_LOCK_SECONDS"),
    )
    require_admin_totp: bool = Field(
        default=True,
        validation_alias=AliasChoices("REQUIRE_ADMIN_TOTP", "WORKBENCH_REQUIRE_ADMIN_TOTP"),
    )
    totp_enrollment_ttl_seconds: int = Field(
        default=300,
        ge=60,
        le=900,
        validation_alias=AliasChoices(
            "TOTP_ENROLLMENT_TTL_SECONDS", "WORKBENCH_TOTP_ENROLLMENT_TTL_SECONDS"
        ),
    )
    orchestration_default_runtime_key: str = Field(
        default="mock",
        validation_alias=AliasChoices(
            "ORCHESTRATION_DEFAULT_RUNTIME_KEY", "WORKBENCH_ORCHESTRATION_DEFAULT_RUNTIME_KEY"
        ),
    )
    orchestration_min_samples: int = Field(
        default=5,
        ge=1,
        le=1000,
        validation_alias=AliasChoices(
            "ORCHESTRATION_MIN_SAMPLES", "WORKBENCH_ORCHESTRATION_MIN_SAMPLES"
        ),
    )
    orchestration_improvement_threshold: float = Field(
        default=0.1,
        ge=0.0,
        le=1.0,
        validation_alias=AliasChoices(
            "ORCHESTRATION_IMPROVEMENT_THRESHOLD", "WORKBENCH_ORCHESTRATION_IMPROVEMENT_THRESHOLD"
        ),
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


def validate_runtime_settings(settings: Settings) -> None:
    if settings.content_store_backend not in {"memory", "sqlite"}:
        raise ValueError("不支持的内容仓储类型")
    if settings.content_generation_backend not in {"mock", "openai_compatible"}:
        raise ValueError("不支持的内容生成后端")
    if settings.planner_backend not in {"mock", "openai_compatible"}:
        raise ValueError("不支持的规划生成后端")
    if settings.env == "development":
        return
    if settings.storage_backend != "postgres":
        raise ValueError("生产环境必须使用 PostgreSQL 持久化仓储")
    if settings.content_store_backend == "memory":
        raise ValueError("生产环境禁止使用内存内容仓储")
    if not settings.database_url.startswith(("postgresql://", "postgresql+psycopg://")):
        raise ValueError("生产环境数据库地址必须是 PostgreSQL")
    if len(settings.auth_secret) < 32:
        raise ValueError("认证密钥至少需要 32 个字符")
    if len(settings.backup_encryption_key) < 32:
        raise ValueError("备份加密密钥至少需要 32 个字符")
    if settings.auth_secret == settings.backup_encryption_key:
        raise ValueError("认证密钥和备份加密密钥必须不同")
