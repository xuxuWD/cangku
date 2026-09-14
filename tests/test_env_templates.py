"""配置模板的静态契约：模板必须与实际配置项一一对应，且不得被 .gitignore 静默忽略。

背景：`.env.staging.example` 曾因迁移清单落后于 `migrations/` 而让预检永远 `blocked`；
同类漂移在 SSO 模板上同样会让"看起来配好了"的部署实际缺项。这里用 `Settings` 的
真实字段与别名守护模板，避免模板与实际配置再次脱节。
"""

from pathlib import Path

from app.settings import Settings

ROOT = Path(__file__).resolve().parents[1]
SSO_TEMPLATE = ROOT / ".env.sso.example"
STAGING_TEMPLATE = ROOT / ".env.staging.example"
GITIGNORE = ROOT / ".gitignore"

# 与 app/bootstrap.py 的 _RUNTIME_KEYS 同一口径：五个可外部注册的 Runtime。
RUNTIME_KEYS = ("ragflow", "agentscope", "deerflow", "codex_worker", "hermes")
# 外部云服务必须声明认证注入；本地独立进程（deerflow/codex_worker/hermes）认证可选，不强制登记。
AUTH_MARKER_KEYS = ("ragflow", "agentscope")


def template_keys(path: Path) -> set[str]:
    keys: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key, separator, _ = stripped.partition("=")
        assert separator == "=", f"模板存在无法解析的行：{stripped}"
        keys.add(key.strip())
    return keys


def declared_env_names(field_name: str) -> set[str]:
    """收集某个配置字段可被识别的全部环境变量名（别名 + WORKBENCH_ 前缀）。"""
    field = Settings.model_fields[field_name]
    names = {f"WORKBENCH_{field_name.upper()}"}
    alias = field.validation_alias
    if alias is not None:
        choices = getattr(alias, "choices", None)
        if choices is None:
            names.add(str(alias))
        else:
            names.update(str(choice) for choice in choices)
    return names


def test_sso_template_covers_every_sso_setting() -> None:
    keys = template_keys(SSO_TEMPLATE)
    sso_fields = [name for name in Settings.model_fields if name.startswith("sso_")]
    assert sso_fields, "Settings 中已无 sso_* 字段，请同步更新本测试"

    missing = [
        name for name in sso_fields if not (declared_env_names(name) & keys)
    ]

    # 判定依据：模板必须覆盖每一个 sso_* 配置项，否则部署方按模板配置仍会缺项。
    assert missing == []


def test_sso_template_states_secret_discipline() -> None:
    content = SSO_TEMPLATE.read_text(encoding="utf-8")

    # 判定依据：必须显式写明密钥由部署密钥系统注入、禁止提交真实值，并给出预检命令。
    assert "部署密钥系统" in content
    assert "禁止" in content and "client_secret" in content
    assert "py scripts/sso_preflight.py" in content
    # IdP 侧交付清单必须在模板内，联调输入才可勾对
    for item in ("issuer", "callback", "email_verified", "PKCE"):
        assert item.lower() in content.lower() or item in content


def test_sso_template_is_not_gitignored() -> None:
    entries = {
        line.strip()
        for line in GITIGNORE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }

    # 判定依据：`.env.*` 默认被忽略，模板必须显式取反，否则改完模板却提交不上去。
    assert ".env.*" in entries
    assert "!.env.sso.example" in entries


def test_staging_template_covers_every_runtime_metadata_field() -> None:
    """staging 模板必须覆盖全部可注册 Runtime 的地址、固定版本与能力白名单。

    背景：注册表与 `app/bootstrap.py` 支持五个 Runtime，但模板曾只登记 RAGFlow 与
    AgentScope，导致 DeerFlow / Codex Worker / Hermes 无"照抄"的字段形状可循，
    预检也无从发现缺项。
    """
    keys = template_keys(STAGING_TEMPLATE)

    missing = [
        f"{key}_{suffix}"
        for key in RUNTIME_KEYS
        for suffix in ("endpoint", "version", "capabilities")
        if not (declared_env_names(f"{key}_{suffix}") & keys)
    ]

    assert missing == []


def test_staging_template_declares_auth_markers_for_external_runtimes() -> None:
    """外部云服务（RAGFlow/AgentScope）必须登记认证注入标记；本地进程不强制。"""
    keys = template_keys(STAGING_TEMPLATE)

    missing = [
        f"{key}_auth_injected"
        for key in AUTH_MARKER_KEYS
        if not (declared_env_names(f"{key}_auth_injected") & keys)
    ]

    assert missing == []


def test_staging_template_states_secret_values_are_not_written() -> None:
    """模板只能登记元数据：真实令牌一律由部署密钥系统注入。"""
    content = STAGING_TEMPLATE.read_text(encoding="utf-8")

    assert "部署密钥系统注入" in content
    assert "AUTH_TOKEN" in content


# 段二（dsh 接入段）新增的 24 项配置：Settings 字段名（**甲口径**：§4 清单内字段，**不含**网关侧 `mint_secret`）。
# 口径（2026-09-14 补注）：本常量 / 规格 §4 / 门禁 §B15 = **24 项**；`.env.staging.example` = **25 项**
# （多网关侧 `WORKBENCH_MODEL_GATEWAY_MINT_SECRET`）⇒ 三处仅在**前 24 项**上同源，`.env` 模板多登记 1 项网关侧配置。
# 改一处必须三处同步。
STAGE2_SETTINGS_FIELDS = (
    "agent_runtime_backend",
    "exec_image_digest",
    "exec_workspace_root",
    "exec_trusted_roots",
    "exec_timeout_seconds",
    "exec_pids_limit",
    "exec_memory_mb",
    "exec_cpu_quota",
    "exec_orphan_limit",
    "dsh_version",
    "artifact_export_enabled",
    "body_encryption_key",
    "body_encryption_previous_keys",
    "body_cleanup_interval_seconds",
    "model_gateway_base_url",
    "model_gateway_token_ttl_seconds",
    "model_gateway_upstream_base_url",
    "model_gateway_upstream_api_key",
    "model_gateway_upstream_timeout_seconds",
    "model_gateway_max_retries",
    "exec_callback_listen_host",
    "exec_callback_listen_port",
    "exec_callback_forward_url",
    "exec_callback_shared_secret",
)


def test_stage2_settings_are_declared() -> None:
    """24 项必须真实存在于 Settings（防止清单与实现漂移）。"""
    missing = [
        name for name in STAGE2_SETTINGS_FIELDS if name not in Settings.model_fields
    ]

    assert missing == []


def test_staging_template_covers_every_stage2_setting() -> None:
    """staging 模板必须覆盖段二全部 24 项，否则部署方按模板配置仍会缺项。"""
    keys = template_keys(STAGING_TEMPLATE)

    missing = [
        name
        for name in STAGE2_SETTINGS_FIELDS
        if not (declared_env_names(name) & keys)
    ]

    assert missing == []


def test_stage2_defaults_are_pinned() -> None:
    """段二默认值必须钉死：这是规格 §8 U11 / U16「实现前必须定值」的落点。

    判定依据：把裁决值写成断言——任何一次静默改动都会让本用例变红；
    `Settings()` 不参与（避免受本机 `.env` 影响），只读字段声明的默认值。
    """
    defaults = {
        name: Settings.model_fields[name].default for name in STAGE2_SETTINGS_FIELDS
    }

    assert defaults["agent_runtime_backend"] == "mock"
    assert defaults["exec_trusted_roots"] == "/usr/bin"
    assert defaults["exec_timeout_seconds"] == 180
    assert defaults["exec_pids_limit"] == 256
    assert defaults["exec_memory_mb"] == 2048
    assert defaults["exec_cpu_quota"] == 2.0
    assert defaults["exec_orphan_limit"] == 8
    assert defaults["artifact_export_enabled"] is False
    assert defaults["body_cleanup_interval_seconds"] == 60
    assert defaults["model_gateway_token_ttl_seconds"] == 300
    assert defaults["model_gateway_upstream_timeout_seconds"] == 60.0
    assert defaults["model_gateway_max_retries"] == 0
    assert defaults["exec_callback_listen_host"] == "0.0.0.0"
    assert defaults["exec_callback_listen_port"] == 8081

    # 硬约束（规格 §4）：令牌有效期必须 ≥ 执行超时，否则执行中途令牌先过期。
    assert (
        defaults["model_gateway_token_ttl_seconds"]
        >= defaults["exec_timeout_seconds"]
    )
    # fail-closed 项：留空即"未配置"，不得给出看起来能用的默认地址或密钥。
    for name in (
        "exec_image_digest",
        "exec_workspace_root",
        "dsh_version",
        "body_encryption_key",
        "body_encryption_previous_keys",
        "model_gateway_base_url",
        "model_gateway_upstream_base_url",
        "model_gateway_upstream_api_key",
        "exec_callback_forward_url",
        "exec_callback_shared_secret",
    ):
        assert defaults[name] == ""

