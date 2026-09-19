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
    content_publish_target: str = Field(
        default="",
        validation_alias=AliasChoices("CONTENT_PUBLISH_TARGET", "WORKBENCH_CONTENT_PUBLISH_TARGET"),
    )
    content_publish_endpoint: str = Field(
        default="",
        validation_alias=AliasChoices("CONTENT_PUBLISH_ENDPOINT", "WORKBENCH_CONTENT_PUBLISH_ENDPOINT"),
    )
    content_publish_account_id: str = Field(
        default="",
        validation_alias=AliasChoices("CONTENT_PUBLISH_ACCOUNT_ID", "WORKBENCH_CONTENT_PUBLISH_ACCOUNT_ID"),
    )
    content_publish_access_token: str = Field(
        default="",
        validation_alias=AliasChoices("CONTENT_PUBLISH_ACCESS_TOKEN", "WORKBENCH_CONTENT_PUBLISH_ACCESS_TOKEN"),
    )
    content_publish_timeout_seconds: float = Field(
        default=15.0, ge=1, le=60,
        validation_alias=AliasChoices("CONTENT_PUBLISH_TIMEOUT_SECONDS", "WORKBENCH_CONTENT_PUBLISH_TIMEOUT_SECONDS"),
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
    sso_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices("SSO_ENABLED", "WORKBENCH_SSO_ENABLED"),
    )
    sso_provider: str = Field(
        default="generic_oidc",
        validation_alias=AliasChoices("SSO_PROVIDER", "WORKBENCH_SSO_PROVIDER"),
    )
    sso_issuer: str = Field(
        default="",
        validation_alias=AliasChoices("SSO_ISSUER", "WORKBENCH_SSO_ISSUER"),
    )
    sso_authorization_endpoint: str = Field(
        default="",
        validation_alias=AliasChoices(
            "SSO_AUTHORIZATION_ENDPOINT", "WORKBENCH_SSO_AUTHORIZATION_ENDPOINT"
        ),
    )
    sso_token_endpoint: str = Field(
        default="",
        validation_alias=AliasChoices("SSO_TOKEN_ENDPOINT", "WORKBENCH_SSO_TOKEN_ENDPOINT"),
    )
    sso_jwks_uri: str = Field(
        default="",
        validation_alias=AliasChoices("SSO_JWKS_URI", "WORKBENCH_SSO_JWKS_URI"),
    )
    sso_client_id: str = Field(
        default="",
        validation_alias=AliasChoices("SSO_CLIENT_ID", "WORKBENCH_SSO_CLIENT_ID"),
    )
    sso_client_secret: str = Field(
        default="",
        validation_alias=AliasChoices("SSO_CLIENT_SECRET", "WORKBENCH_SSO_CLIENT_SECRET"),
    )
    sso_redirect_uri: str = Field(
        default="",
        validation_alias=AliasChoices("SSO_REDIRECT_URI", "WORKBENCH_SSO_REDIRECT_URI"),
    )
    sso_scopes: str = Field(
        default="openid email profile",
        validation_alias=AliasChoices("SSO_SCOPES", "WORKBENCH_SSO_SCOPES"),
    )
    sso_trust_idp_mfa: bool = Field(
        default=False,
        validation_alias=AliasChoices("SSO_TRUST_IDP_MFA", "WORKBENCH_SSO_TRUST_IDP_MFA"),
    )
    sso_state_ttl_seconds: int = Field(
        default=300,
        ge=60,
        le=900,
        validation_alias=AliasChoices("SSO_STATE_TTL_SECONDS", "WORKBENCH_SSO_STATE_TTL_SECONDS"),
    )
    sso_timeout_seconds: float = Field(
        default=10.0,
        ge=1,
        le=60,
        validation_alias=AliasChoices("SSO_TIMEOUT_SECONDS", "WORKBENCH_SSO_TIMEOUT_SECONDS"),
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
    # 外部 Runtime 裸名配置：与 staging 模板及预检脚本共用同一套变量名。
    # ENDPOINT 非空即启用；VERSION 必须是固定版本；CAPABILITIES 为空即 fail-closed。
    # AUTH_INJECTED=true 时必须有 AUTH_TOKEN，声明了注入却无凭据一律报错。
    ragflow_endpoint: str = Field(
        default="", validation_alias=AliasChoices("RAGFLOW_ENDPOINT", "WORKBENCH_RAGFLOW_ENDPOINT")
    )
    ragflow_version: str = Field(
        default="", validation_alias=AliasChoices("RAGFLOW_VERSION", "WORKBENCH_RAGFLOW_VERSION")
    )
    ragflow_capabilities: str = Field(
        default="",
        validation_alias=AliasChoices("RAGFLOW_CAPABILITIES", "WORKBENCH_RAGFLOW_CAPABILITIES"),
    )
    ragflow_auth_injected: bool = Field(
        default=False,
        validation_alias=AliasChoices("RAGFLOW_AUTH_INJECTED", "WORKBENCH_RAGFLOW_AUTH_INJECTED"),
    )
    ragflow_auth_token: str = Field(
        default="", validation_alias=AliasChoices("RAGFLOW_AUTH_TOKEN", "WORKBENCH_RAGFLOW_AUTH_TOKEN")
    )
    ragflow_auth_header: str = Field(
        default="Authorization",
        validation_alias=AliasChoices("RAGFLOW_AUTH_HEADER", "WORKBENCH_RAGFLOW_AUTH_HEADER"),
    )
    ragflow_auth_scheme: str = Field(
        default="Bearer", validation_alias=AliasChoices("RAGFLOW_AUTH_SCHEME", "WORKBENCH_RAGFLOW_AUTH_SCHEME")
    )
    ragflow_timeout_seconds: float = Field(
        default=30.0,
        validation_alias=AliasChoices("RAGFLOW_TIMEOUT_SECONDS", "WORKBENCH_RAGFLOW_TIMEOUT_SECONDS"),
    )
    agentscope_endpoint: str = Field(
        default="", validation_alias=AliasChoices("AGENTSCOPE_ENDPOINT", "WORKBENCH_AGENTSCOPE_ENDPOINT")
    )
    agentscope_version: str = Field(
        default="", validation_alias=AliasChoices("AGENTSCOPE_VERSION", "WORKBENCH_AGENTSCOPE_VERSION")
    )
    agentscope_capabilities: str = Field(
        default="",
        validation_alias=AliasChoices("AGENTSCOPE_CAPABILITIES", "WORKBENCH_AGENTSCOPE_CAPABILITIES"),
    )
    agentscope_auth_injected: bool = Field(
        default=False,
        validation_alias=AliasChoices("AGENTSCOPE_AUTH_INJECTED", "WORKBENCH_AGENTSCOPE_AUTH_INJECTED"),
    )
    agentscope_auth_token: str = Field(
        default="",
        validation_alias=AliasChoices("AGENTSCOPE_AUTH_TOKEN", "WORKBENCH_AGENTSCOPE_AUTH_TOKEN"),
    )
    agentscope_auth_header: str = Field(
        default="Authorization",
        validation_alias=AliasChoices("AGENTSCOPE_AUTH_HEADER", "WORKBENCH_AGENTSCOPE_AUTH_HEADER"),
    )
    agentscope_auth_scheme: str = Field(
        default="Bearer",
        validation_alias=AliasChoices("AGENTSCOPE_AUTH_SCHEME", "WORKBENCH_AGENTSCOPE_AUTH_SCHEME"),
    )
    agentscope_timeout_seconds: float = Field(
        default=30.0,
        validation_alias=AliasChoices("AGENTSCOPE_TIMEOUT_SECONDS", "WORKBENCH_AGENTSCOPE_TIMEOUT_SECONDS"),
    )
    deerflow_endpoint: str = Field(
        default="", validation_alias=AliasChoices("DEERFLOW_ENDPOINT", "WORKBENCH_DEERFLOW_ENDPOINT")
    )
    deerflow_version: str = Field(
        default="", validation_alias=AliasChoices("DEERFLOW_VERSION", "WORKBENCH_DEERFLOW_VERSION")
    )
    deerflow_capabilities: str = Field(
        default="",
        validation_alias=AliasChoices("DEERFLOW_CAPABILITIES", "WORKBENCH_DEERFLOW_CAPABILITIES"),
    )
    deerflow_auth_injected: bool = Field(
        default=False,
        validation_alias=AliasChoices("DEERFLOW_AUTH_INJECTED", "WORKBENCH_DEERFLOW_AUTH_INJECTED"),
    )
    deerflow_auth_token: str = Field(
        default="", validation_alias=AliasChoices("DEERFLOW_AUTH_TOKEN", "WORKBENCH_DEERFLOW_AUTH_TOKEN")
    )
    deerflow_auth_header: str = Field(
        default="Authorization",
        validation_alias=AliasChoices("DEERFLOW_AUTH_HEADER", "WORKBENCH_DEERFLOW_AUTH_HEADER"),
    )
    deerflow_auth_scheme: str = Field(
        default="Bearer", validation_alias=AliasChoices("DEERFLOW_AUTH_SCHEME", "WORKBENCH_DEERFLOW_AUTH_SCHEME")
    )
    deerflow_timeout_seconds: float = Field(
        default=30.0,
        validation_alias=AliasChoices("DEERFLOW_TIMEOUT_SECONDS", "WORKBENCH_DEERFLOW_TIMEOUT_SECONDS"),
    )
    codex_worker_endpoint: str = Field(
        default="", validation_alias=AliasChoices("CODEX_WORKER_ENDPOINT", "WORKBENCH_CODEX_WORKER_ENDPOINT")
    )
    codex_worker_version: str = Field(
        default="", validation_alias=AliasChoices("CODEX_WORKER_VERSION", "WORKBENCH_CODEX_WORKER_VERSION")
    )
    codex_worker_capabilities: str = Field(
        default="",
        validation_alias=AliasChoices("CODEX_WORKER_CAPABILITIES", "WORKBENCH_CODEX_WORKER_CAPABILITIES"),
    )
    codex_worker_auth_injected: bool = Field(
        default=False,
        validation_alias=AliasChoices("CODEX_WORKER_AUTH_INJECTED", "WORKBENCH_CODEX_WORKER_AUTH_INJECTED"),
    )
    codex_worker_auth_token: str = Field(
        default="",
        validation_alias=AliasChoices("CODEX_WORKER_AUTH_TOKEN", "WORKBENCH_CODEX_WORKER_AUTH_TOKEN"),
    )
    codex_worker_auth_header: str = Field(
        default="Authorization",
        validation_alias=AliasChoices("CODEX_WORKER_AUTH_HEADER", "WORKBENCH_CODEX_WORKER_AUTH_HEADER"),
    )
    codex_worker_auth_scheme: str = Field(
        default="Bearer",
        validation_alias=AliasChoices("CODEX_WORKER_AUTH_SCHEME", "WORKBENCH_CODEX_WORKER_AUTH_SCHEME"),
    )
    codex_worker_timeout_seconds: float = Field(
        default=30.0,
        validation_alias=AliasChoices("CODEX_WORKER_TIMEOUT_SECONDS", "WORKBENCH_CODEX_WORKER_TIMEOUT_SECONDS"),
    )
    hermes_endpoint: str = Field(
        default="", validation_alias=AliasChoices("HERMES_ENDPOINT", "WORKBENCH_HERMES_ENDPOINT")
    )
    hermes_version: str = Field(
        default="", validation_alias=AliasChoices("HERMES_VERSION", "WORKBENCH_HERMES_VERSION")
    )
    hermes_capabilities: str = Field(
        default="", validation_alias=AliasChoices("HERMES_CAPABILITIES", "WORKBENCH_HERMES_CAPABILITIES")
    )
    hermes_auth_injected: bool = Field(
        default=False,
        validation_alias=AliasChoices("HERMES_AUTH_INJECTED", "WORKBENCH_HERMES_AUTH_INJECTED"),
    )
    hermes_auth_token: str = Field(
        default="", validation_alias=AliasChoices("HERMES_AUTH_TOKEN", "WORKBENCH_HERMES_AUTH_TOKEN")
    )
    hermes_auth_header: str = Field(
        default="Authorization",
        validation_alias=AliasChoices("HERMES_AUTH_HEADER", "WORKBENCH_HERMES_AUTH_HEADER"),
    )
    hermes_auth_scheme: str = Field(
        default="Bearer", validation_alias=AliasChoices("HERMES_AUTH_SCHEME", "WORKBENCH_HERMES_AUTH_SCHEME")
    )
    hermes_timeout_seconds: float = Field(
        default=30.0, validation_alias=AliasChoices("HERMES_TIMEOUT_SECONDS", "WORKBENCH_HERMES_TIMEOUT_SECONDS"),
    )
    # ---- P3 记忆层（embedding / 记忆写入）新增配置 ----
    # 口径见 docs/superpowers/specs/2026-09-15-memory-layer-p3-design.md §2.5 / §2.8：
    # 本地 embedding 服务（Qwen3-Embedding-0.6B 或同协议实现）地址；**缺失即拒绝启动**（fail-closed）。
    embedding_base_url: str = Field(
        default="", validation_alias=AliasChoices("EMBEDDING_BASE_URL", "WORKBENCH_EMBEDDING_BASE_URL")
    )
    embedding_timeout_seconds: float = Field(
        default=10.0, ge=1, le=60,
        validation_alias=AliasChoices("EMBEDDING_TIMEOUT_SECONDS", "WORKBENCH_EMBEDDING_TIMEOUT_SECONDS"),
    )
    embedding_max_tokens: int = Field(
        default=8192, ge=1, le=32768,
        validation_alias=AliasChoices("EMBEDDING_MAX_TOKENS", "WORKBENCH_EMBEDDING_MAX_TOKENS"),
    )
    # 记忆写入每日成本熔断（整数分）：0 = 走员工 daily_budget_cents 语义（本期只做实例内近似累计，
    # 见规格 §2.9.3；生产真实口径走「用量账本」，未接线时以本实例累计作为每日预算闸门）。
    memory_daily_budget_cents: int = Field(
        default=0, ge=0,
        validation_alias=AliasChoices("MEMORY_DAILY_BUDGET_CENTS", "WORKBENCH_MEMORY_DAILY_BUDGET_CENTS"),
    )
    # P4 技能层（口径见 docs/superpowers/specs/2026-09-15-skill-layer-p4-design.md §2.7）：
    # 技能来源白名单（逗号分隔）。**空 = 技能层关闭**（可登记、不可启用，fail-closed）。
    skill_source_allowlist: str = Field(
        default="", validation_alias=AliasChoices("SKILL_SOURCE_ALLOWLIST", "WORKBENCH_SKILL_SOURCE_ALLOWLIST"),
    )
    # 技能包正文体积上限（字节；M5 裁决 2026-09-15 库内落库，服务端校验）。默认 64 KiB。
    skill_content_max_bytes: int = Field(
        default=64 * 1024, ge=256, le=1024 * 1024,
        validation_alias=AliasChoices("SKILL_CONTENT_MAX_BYTES", "WORKBENCH_SKILL_CONTENT_MAX_BYTES"),
    )
    # 知识治理层（口径见 docs/superpowers/specs/2026-09-15-knowledge-governance-design.md §2.6）：
    # 总开关（fail-closed：关闭时不作文档级过滤，保持既有检索行为）；复核到期宽限（天）。
    knowledge_governance_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices("KNOWLEDGE_GOVERNANCE_ENABLED", "WORKBENCH_KNOWLEDGE_GOVERNANCE_ENABLED"),
    )
    knowledge_review_grace_days: int = Field(
        default=30, ge=1, le=3650,
        validation_alias=AliasChoices("KNOWLEDGE_REVIEW_GRACE_DAYS", "WORKBENCH_KNOWLEDGE_REVIEW_GRACE_DAYS"),
    )
    # 到期扫描 beat 间隔（秒；§4 N3）：worker 的 `knowledge-review-scan` 周期任务用。
    # 下限 30s 防止把 beat 打成忙轮询；上限 7 天（更长等于事实停用，应显式关任务而非拉长间隔）。
    knowledge_review_scan_interval_seconds: int = Field(
        default=3600, ge=30, le=7 * 24 * 3600,
        validation_alias=AliasChoices(
            "KNOWLEDGE_REVIEW_SCAN_INTERVAL_SECONDS",
            "WORKBENCH_KNOWLEDGE_REVIEW_SCAN_INTERVAL_SECONDS",
        ),
    )
    # 知识检索入口（`POST /api/v1/knowledge/search`，规格 §2.3 接线）：
    # WeKnora 只读检索服务地址与凭据。**两者皆空 = 未配置 ⇒ 该端点 503**（不返回空结果，
    # 以免把「服务没接」读成「没查到」）；**只配一半 ⇒ 启动即失败**（明显配置错误，
    # 与 P3 `embedding_base_url` 同口径）。环境变量名与运维脚本（N1 导入）保持一致。
    weknora_base_url: str = Field(
        default="", validation_alias=AliasChoices("WEKNORA_BASE_URL", "WORKBENCH_WEKNORA_BASE_URL")
    )
    weknora_api_key: str = Field(
        default="", validation_alias=AliasChoices("WEKNORA_API_KEY", "WORKBENCH_WEKNORA_API_KEY")
    )
    weknora_timeout_seconds: float = Field(
        default=10.0, ge=1, le=60,
        validation_alias=AliasChoices("WEKNORA_TIMEOUT_SECONDS", "WORKBENCH_WEKNORA_TIMEOUT_SECONDS"),
    )
    # P6a 自进化·评测集（口径见 docs/superpowers/specs/2026-09-16-self-evolution-p6-design.md §2.8）：
    # 总开关默认 false（fail-closed）——关闭时**不装配任何评测组件**，管理端点 503、CLI 拒绝执行；
    # 评测费用上限（整数分）：单次评测运行预计费用超过该值即中止并留痕（v1 内置探针为 0，接入模型类受评对象后收紧）。
    evolution_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices("EVOLUTION_ENABLED", "WORKBENCH_EVOLUTION_ENABLED"),
    )
    evolution_eval_max_cost_cents: int = Field(
        default=500, ge=0, le=10_000_000,
        validation_alias=AliasChoices("EVOLUTION_EVAL_MAX_COST_CENTS", "WORKBENCH_EVOLUTION_EVAL_MAX_COST_CENTS"),
    )
    # 跨源部署（桌面端远程模式 / PWA 伴侣端）：非 development 环境只在显式配置来源后
    # 才注册 CORS；留空即视为「不允许任何跨源」（fail-closed）。
    cors_allowed_origins: str = Field(
        default="",
        validation_alias=AliasChoices("CORS_ALLOWED_ORIGINS", "WORKBENCH_CORS_ALLOWED_ORIGINS"),
    )
    cors_allow_credentials: bool = Field(
        default=False,
        validation_alias=AliasChoices("CORS_ALLOW_CREDENTIALS", "WORKBENCH_CORS_ALLOW_CREDENTIALS"),
    )
    # 站内通知（收件箱）保留期：过期条目在写入/读取时惰性清理。
    inbox_retention_days: int = Field(
        default=90,
        ge=1,
        le=3650,
        validation_alias=AliasChoices("INBOX_RETENTION_DAYS", "WORKBENCH_INBOX_RETENTION_DAYS"),
    )
    # 运行事件保留期（天）：事件存 append-only 的 `workbench_runtime_events`（migrations/034），
    # 超出保留期的行由 worker 周期任务 `runtime-events-purge` 按 `occurred_at` 清理（运行事件有界）。
    # 只清理运行事件；审计表不可删除。
    runtime_events_retention_days: int = Field(
        default=30,
        ge=1,
        le=3650,
        validation_alias=AliasChoices(
            "RUNTIME_EVENTS_RETENTION_DAYS", "WORKBENCH_RUNTIME_EVENTS_RETENTION_DAYS"
        ),
    )
    # 运行事件清理任务的 beat 间隔（秒；命名口径同 `knowledge_review_scan_interval_seconds`）。
    # 下限 30s 防止把 beat 打成忙轮询；上限 7 天（更长等于事实停用，应显式关任务而非拉长间隔）。
    runtime_events_purge_interval_seconds: int = Field(
        default=3600,
        ge=30,
        le=7 * 24 * 3600,
        validation_alias=AliasChoices(
            "RUNTIME_EVENTS_PURGE_INTERVAL_SECONDS",
            "WORKBENCH_RUNTIME_EVENTS_PURGE_INTERVAL_SECONDS",
        ),
    )
    # 导出包（`workbench_export_packages`，迁移 028）过期清理任务的 beat 间隔（秒）。
    # 过期口径由包自身 `expires_at`（= 导出完成时刻 + 7 天，2026-09-14 裁决）决定 ⇒
    # **本项只控「多久扫一次」，不设独立保留期**；命名与区间口径同 `runtime_events_purge_interval_seconds`。
    # 组 10.7：导出包是租户数据副本，过期后既不可取回（404）也不再留存（物理删除）。
    export_package_purge_interval_seconds: int = Field(
        default=3600,
        ge=30,
        le=7 * 24 * 3600,
        validation_alias=AliasChoices(
            "EXPORT_PACKAGE_PURGE_INTERVAL_SECONDS",
            "WORKBENCH_EXPORT_PACKAGE_PURGE_INTERVAL_SECONDS",
        ),
    )
    # 保留策略**执行器**（B-4 选项 C，迁移零新增）的 beat 间隔（秒）。保留期本身按租户取自
    # `workbench_retention_policies`（缺省 = `DEFAULT_RETENTION_POLICY`：tasks/runs 180、usage 365 天），
    # 本项只控「多久执行一轮」；执行顺序（账本结转 → 运行域先子后父 → 提案域 → 任务域）与各面语义
    # 见 `app/commercial/lifecycle.py::purge_expired_data_for_tenant` 与契约「保留策略执行口径」。
    # 命名与区间口径同 `export_package_purge_interval_seconds`。
    retention_purge_interval_seconds: int = Field(
        default=3600,
        ge=30,
        le=7 * 24 * 3600,
        validation_alias=AliasChoices(
            "RETENTION_PURGE_INTERVAL_SECONDS",
            "WORKBENCH_RETENTION_PURGE_INTERVAL_SECONDS",
        ),
    )

    # ---- P5a CRM 周期任务（crm-p5a-design §2.11）：3 个 beat 间隔，命名与区间口径同上一节 ----
    # 健康度重算：默认每日一次（逐租户全量重算，批量收集避免 N+1）。
    crm_health_recompute_interval_seconds: int = Field(
        default=86400,
        ge=300,
        le=7 * 24 * 3600,
        validation_alias=AliasChoices(
            "CRM_HEALTH_RECOMPUTE_INTERVAL_SECONDS",
            "WORKBENCH_CRM_HEALTH_RECOMPUTE_INTERVAL_SECONDS",
        ),
    )
    # 活动到期提醒：默认每小时扫一次（幂等：同任务同日只投递一次）。
    crm_activity_reminder_interval_seconds: int = Field(
        default=3600,
        ge=60,
        le=7 * 24 * 3600,
        validation_alias=AliasChoices(
            "CRM_ACTIVITY_REMINDER_INTERVAL_SECONDS",
            "WORKBENCH_CRM_ACTIVITY_REMINDER_INTERVAL_SECONDS",
        ),
    )
    # 续约窗口提醒 + 过期翻转：默认每日一次。
    crm_renewal_window_interval_seconds: int = Field(
        default=86400,
        ge=300,
        le=7 * 24 * 3600,
        validation_alias=AliasChoices(
            "CRM_RENEWAL_WINDOW_INTERVAL_SECONDS",
            "WORKBENCH_CRM_RENEWAL_WINDOW_INTERVAL_SECONDS",
        ),
    )

    # ---- P2b 实时流（realtime-stream-p2b-design §2.2）：7 项，均有安全缺省 ----
    # 保留期：流是体感数据、帧量大 ⇒ 比运行事件（30 天）短。
    stream_retention_days: int = Field(
        default=7,
        ge=1,
        le=90,
        validation_alias=AliasChoices("STREAM_RETENTION_DAYS", "WORKBENCH_STREAM_RETENTION_DAYS"),
    )
    # 熔断：每 run 帧数与 payload 累计字节双上限（超限置 unavailable 并显式告知，不静默丢帧）。
    stream_max_frames: int = Field(
        default=2000,
        ge=100,
        le=20000,
        validation_alias=AliasChoices("STREAM_MAX_FRAMES", "WORKBENCH_STREAM_MAX_FRAMES"),
    )
    stream_max_bytes: int = Field(
        default=4 * 1024 * 1024,
        ge=256 * 1024,
        le=64 * 1024 * 1024,
        validation_alias=AliasChoices("STREAM_MAX_BYTES", "WORKBENCH_STREAM_MAX_BYTES"),
    )
    # SSE 连接最长生命周期（到点关流，客户端自动重连续播）。
    stream_max_connection_seconds: int = Field(
        default=1800,
        ge=60,
        le=7200,
        validation_alias=AliasChoices(
            "STREAM_MAX_CONNECTION_SECONDS", "WORKBENCH_STREAM_MAX_CONNECTION_SECONDS"
        ),
    )
    # 读端轮询增量间隔（毫秒）。
    stream_poll_interval_ms: int = Field(
        default=500,
        ge=200,
        le=5000,
        validation_alias=AliasChoices("STREAM_POLL_INTERVAL_MS", "WORKBENCH_STREAM_POLL_INTERVAL_MS"),
    )
    # 悬挂兜底：未终态且 updated_at 超此值 ⇒ 置 unavailable('stalled') 并设 expires_at。
    stream_stalled_hours: int = Field(
        default=6,
        ge=1,
        le=72,
        validation_alias=AliasChoices("STREAM_STALLED_HOURS", "WORKBENCH_STREAM_STALLED_HOURS"),
    )
    # 清理任务 beat 间隔。
    stream_purge_interval_seconds: int = Field(
        default=3600,
        ge=60,
        le=86400,
        validation_alias=AliasChoices(
            "STREAM_PURGE_INTERVAL_SECONDS", "WORKBENCH_STREAM_PURGE_INTERVAL_SECONDS"
        ),
    )

    # ---- P2c-2 内容级回传（有界摘录）：执行输出文本摘录上限（字节）----
    # `0` = 关闭回传（**不读容器日志**）；上限只影响回传，不影响执行结果（流是视图）。
    output_excerpt_max_bytes: int = Field(
        default=16384,
        ge=0,
        le=262144,
        validation_alias=AliasChoices(
            "OUTPUT_EXCERPT_MAX_BYTES", "WORKBENCH_OUTPUT_EXCERPT_MAX_BYTES"
        ),
    )

    # ---- P2c-3 文件变更通道（有界）：单文件 diff 摘录上限（字节）/ 每次执行最多变更条数 ----
    # `0` = 关闭该通道（不产出 `diff_excerpt` / 不产出变更记录且**不登记产物**）；
    # 与输出回传同为「视图」：任何截断 / 失败都不影响执行结果。
    file_diff_excerpt_max_bytes: int = Field(
        default=8192,
        ge=0,
        le=65536,
        validation_alias=AliasChoices(
            "FILE_DIFF_EXCERPT_MAX_BYTES", "WORKBENCH_FILE_DIFF_EXCERPT_MAX_BYTES"
        ),
    )
    file_changes_max: int = Field(
        default=50,
        ge=0,
        le=200,
        validation_alias=AliasChoices("FILE_CHANGES_MAX", "WORKBENCH_FILE_CHANGES_MAX"),
    )

    # ---- P2c-3 产物登记（运行级元数据）：保留期（天）+ 清理任务 beat 间隔（秒）----
    run_artifact_retention_days: int = Field(
        default=30,
        ge=1,
        le=365,
        validation_alias=AliasChoices(
            "RUN_ARTIFACT_RETENTION_DAYS", "WORKBENCH_RUN_ARTIFACT_RETENTION_DAYS"
        ),
    )
    run_artifact_purge_interval_seconds: int = Field(
        default=3600,
        ge=60,
        le=86400,
        validation_alias=AliasChoices(
            "RUN_ARTIFACT_PURGE_INTERVAL_SECONDS",
            "WORKBENCH_RUN_ARTIFACT_PURGE_INTERVAL_SECONDS",
        ),
    )

    # ---- 段二（dsh 接入段）新增配置：共 25 项（= 规格 §4 清单 24 项 + 网关侧 `mint_secret`）----
    # 口径见 docs/superpowers/specs/2026-09-12-dsh-integration-design.md §4；
    # 门禁 §B15 要求「实现前必须全部进 app/settings.py + `.env.staging.example` + 守护测试」。
    # 命名口径：只认 `WORKBENCH_` 前缀（由 env_prefix 自动派生），**不设裸名别名** ——
    # 裸名（如 `EXEC_TIMEOUT_SECONDS`）过于通用，易被无关环境变量误拾。
    # 默认值取舍：能 fail-closed 的一律留空或关闭；数值口径见各项注释（2026-09-13 用户裁决）。
    agent_runtime_backend: str = "mock"  # 总开关：mock（默认）| dsh，仅显式 dsh 才启用真实执行
    exec_image_digest: str = ""  # 执行镜像 digest（非 tag）；留空 = 未配置
    exec_workspace_root: str = ""  # 执行工作卷根；留空 = 未配置
    exec_trusted_roots: str = "/usr/bin"  # 受信任且不可写的可执行根
    # 单次执行硬上限（秒）：须覆盖 dsh initialize 冷启动（实测 53.2s / 78.9s），
    # 否则会把"初始化慢"误判为执行超时；超时语义 = 拒绝并终止容器（fail-closed）。
    exec_timeout_seconds: int = Field(default=180, ge=10, le=3600)
    exec_pids_limit: int = Field(default=256, ge=16, le=4096)  # 对应 docker --pids-limit
    exec_memory_mb: int = Field(default=2048, ge=128, le=32768)  # 对应 docker --memory
    exec_cpu_quota: float = Field(default=2.0, ge=0.1, le=16.0)  # 对应 docker --cpus
    # 孤儿容器上限（§8 U17 ⑥，保守 fail-closed）：超限 → 拒绝新执行并告警，不打挂进程；
    # 默认 8。清扫时机 = 启动时 + 按 body_cleanup_interval_seconds 周期（同批）。
    exec_orphan_limit: int = Field(default=8, ge=0, le=64)
    dsh_version: str = ""  # dsh 精确版本；留空 = 未配置（禁止 latest/main 一类浮动值）
    artifact_export_enabled: bool = False  # fail-closed：关闭时 artifact.export 不装配
    # 正文密文密钥：32 字节原始密钥的 base64；必填非空、不进仓库、不复用备份加密密钥。
    body_encryption_key: str = ""
    # 旧正文密文密钥（多值；§8 U22 裁决）：轮换期**仅用于解密**，且**进程启动时读入** ——
    # 轮换 = 改配置 + 重启（**无热轮换**）；窗口结束后由运维从配置移除 + 重启（进程不再持有）。
    # 格式与主密钥同口径（base64(32 字节原始密钥)），**多值以逗号分隔**（见 parse_previous_body_keys）。
    # fail-closed：缺失 / 留空 ⇒ 不使用旧密钥；解不开一律抛 `BodyCipherError`，绝不静默降级。
    body_encryption_previous_keys: str = ""
    # 正文密文 TTL 清理周期（秒）：清理在启动时 + 按此周期执行，决定密钥轮换窗口长度。
    body_cleanup_interval_seconds: int = Field(default=60, ge=10, le=86400)
    model_gateway_base_url: str = ""  # 容器内 baseURL 指向的网关地址；供应商域名不得出现在本项
    # 短期网关令牌有效期（秒）：每 turn 新铸、终态吊销；
    # 硬约束 = 必须 ≥ exec_timeout_seconds，否则执行中途令牌先过期。
    model_gateway_token_ttl_seconds: int = Field(default=300, ge=30, le=3600)
    model_gateway_upstream_base_url: str = ""  # 上游供应商端点：只在网关侧出现，不得进容器
    model_gateway_upstream_api_key: str = ""  # 上游供应商密钥：必填非空、不进仓库、不进容器
    # 网关 → 上游单次请求超时（秒）：与 exec_timeout_seconds 耦合，
    # 须与冷启动上限（79s）相加后仍落在执行超时内，两级超时才不会相互架空。
    model_gateway_upstream_timeout_seconds: float = Field(default=60.0, ge=1, le=600)
    model_gateway_max_retries: int = Field(default=0, ge=0, le=5)  # fail-closed：默认不隐式重试
    # 网关控制面密钥（mint / revoke 鉴权）：由部署密钥系统注入、不进仓库、不进容器；
    # 与 UPSTREAM_API_KEY（供应商密钥）职责分离。留空 = 未配置（网关侧 fail-closed 拒绝启动）。
    model_gateway_mint_secret: str = ""
    # 执行回调边车三项（§3.5 P1 第 3 条 ②④ / §8 U20 方案 b-1）：
    # 边车是**独立进程**，**只监听一个端口、只挂 workbench-exec-internal**（门禁 §B14 判据 E）；
    # 其自身从同名环境变量读取（`app/exec_callback/config.py`），本处与模板同批登记以守台账。
    # 唯一监听地址：对外可达性由「只挂内网」限定；不得双宿到工作台默认网络。
    exec_callback_listen_host: str = "0.0.0.0"
    # 唯一监听端口：不得再开第二个端口 / 第二条路由。
    exec_callback_listen_port: int = Field(default=8081, ge=1, le=65535)
    # 边车 → 工作台的**受控出向**调用目标（工作台侧回调接收端点）；**留空 = 拒绝启用**（fail-closed）。
    # **不得把回调地址烤进镜像**：只能由部署配置注入（本项默认留空即不启用边车）。
    exec_callback_forward_url: str = ""
    # 「边车 → 工作台」的**预共享密钥**（对称鉴权，§8 U21 裁决）：边车转发随行附带，
    # 工作台接收端点做 `constant-time` 比对；**留空 = 未配置 ⇒ 拒绝请求（fail-closed）**。
    # **不得烤进镜像 / 不进仓库**：只能由部署密钥系统外置注入（两侧同值）。
    exec_callback_shared_secret: str = ""


CORS_METHODS = ["GET", "POST", "PUT", "DELETE", "OPTIONS"]
CORS_HEADERS = [
    "Authorization",
    "Accept",
    "Content-Type",
    "X-Tenant-Id",
    "X-User-Id",
    "X-User-Role",
    "Idempotency-Key",
]
# **响应头**白名单（不是请求头白名单）：跨源时 JS 只允许读到被 expose 的响应头。
# `X-Stream-Run-Id` 是 SSE 读端「该会话最新运行」的权威来源（契约「实时流」）——
# 不 expose 的话 `response.headers.get(...)` 恒为 `null`，前端会据此误判「服务端没有 run」
# 并提前关流，导致历史会话解析不到运行与审批（通知深链落不到卡上）。
CORS_EXPOSE_HEADERS = ["X-Stream-Run-Id"]
DEVELOPMENT_CORS_ORIGIN_REGEX = r"https?://(localhost|127\.0\.0\.1):\d+"


def parse_cors_origins(raw: str) -> list[str]:
    """解析并校验允许来源清单。

    只接受 `scheme://host[:port]` 形式的**裸来源**：拒绝通配符 `*`、非 http(s) 协议，
    以及带路径/查询/结尾斜杠的地址（这类写法不会与浏览器的 `Origin` 头相等，属于配错）。
    """
    origins = [item.strip() for item in (raw or "").split(",") if item.strip()]
    for origin in origins:
        if origin == "*":
            raise ValueError("CORS 允许来源不能使用通配符 *")
        if not origin.startswith(("http://", "https://")):
            raise ValueError(f"CORS 允许来源必须是 http(s) 绝对来源：{origin}")
        remainder = origin.split("://", 1)[1]
        if not remainder or any(mark in remainder for mark in ("/", "?", "#")):
            raise ValueError(f"CORS 允许来源不能包含路径或查询：{origin}")
    return origins


def parse_previous_body_keys(raw: str) -> list[str]:
    """解析旧正文密文密钥（多值；§8 U22 裁决）：**逗号分隔**，逐项去空白，空项忽略。

    真源（§3.4 R3）只把**单值**主密钥 `WORKBENCH_BODY_ENCRYPTION_KEY` 定死为「32 字节原始密钥的
    `base64`」，**未规定多值格式**。此处取既有配置风格里最贴近的一种 —— **逗号分隔**（与
    `cors_allowed_origins` / `content_scrape_allowed_domains` 的分隔方式一致），且 **base64
    字符集不含逗号**，故分隔无歧义。每个非空项仍是「`base64`(32 字节原始密钥)」，格式与长度
    校验交给 `BodyCipher.from_base64`（非法即抛 `ToolExecutionConfigError`，拒绝启用真实执行）。

    **缺失 / 留空 ⇒ 返回空列表**（= 不使用旧密钥，fail-closed）。
    """
    return [item.strip() for item in (raw or "").split(",") if item.strip()]


def resolve_cors_options(settings: Settings) -> dict[str, object] | None:
    """给出 `CORSMiddleware` 参数；返回 `None` 表示不注册 CORS 中间件。"""
    if settings.env == "development":
        return {
            "allow_origins": [],
            "allow_origin_regex": DEVELOPMENT_CORS_ORIGIN_REGEX,
            "allow_credentials": False,
            "allow_methods": CORS_METHODS,
            "allow_headers": CORS_HEADERS,
            "expose_headers": CORS_EXPOSE_HEADERS,
        }

    origins = parse_cors_origins(settings.cors_allowed_origins)
    if not origins:
        return None

    return {
        "allow_origins": origins,
        "allow_credentials": settings.cors_allow_credentials,
        "allow_methods": CORS_METHODS,
        "allow_headers": CORS_HEADERS,
        "expose_headers": CORS_EXPOSE_HEADERS,
    }


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
    # 跨源来源配置错误必须在启动期暴露（例如通配符或带路径的地址）。
    parse_cors_origins(settings.cors_allowed_origins)
