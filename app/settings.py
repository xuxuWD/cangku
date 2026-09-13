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

    # ---- 段二（dsh 接入段）新增配置：共 19 项 ----
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


def resolve_cors_options(settings: Settings) -> dict[str, object] | None:
    """给出 `CORSMiddleware` 参数；返回 `None` 表示不注册 CORS 中间件。"""
    if settings.env == "development":
        return {
            "allow_origins": [],
            "allow_origin_regex": DEVELOPMENT_CORS_ORIGIN_REGEX,
            "allow_credentials": False,
            "allow_methods": CORS_METHODS,
            "allow_headers": CORS_HEADERS,
        }

    origins = parse_cors_origins(settings.cors_allowed_origins)
    if not origins:
        return None

    return {
        "allow_origins": origins,
        "allow_credentials": settings.cors_allow_credentials,
        "allow_methods": CORS_METHODS,
        "allow_headers": CORS_HEADERS,
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
