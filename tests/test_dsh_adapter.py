"""dsh 适配器（`app/runtime/adapters/dsh.py`）单元验收 —— 规格 §3.5 / §3.6。

覆盖：
    - **剖面锁死断言**：`DSH_PERMISSION_MODE=read-only`、禁用清单（含 `tool-bash` /
      `tool-pwsh` / `subprocess-local` / `web_*` / `skill` / `subagent*` / `workflow` / `ralph`
      / 遥测）、`restrict` 非空工具面、遥测开关；
    - **断言失败 = 拒绝启用真实执行并告警，不拒绝整个进程启动**；
    - 容器内 `baseURL` → 网关、`apiKeyEnv` = **短期令牌**；**供应商密钥不得进入容器**；
    - **令牌六条**中可离线判定的项（① 每 turn 新铸 / ② 绑定标签 / ③ 服务端为准 / ⑤ 终态吊销）。
"""

from __future__ import annotations

import logging

import pytest

from app.runtime.adapters.dsh import (
    DISABLED_PLUGINS,
    ENV_API_KEY,
    ENV_BASE_URL,
    ENV_PERMISSION_MODE,
    ENV_TELEMETRY_DISABLED,
    PROFILE_PERMISSION_MODE,
    RESTRICT_TOOLS,
    DisabledPlugin,
    DshAdapter,
    DshAdapterConfig,
    DshProfileLock,
    DshProfileLockError,
    assert_profile_locked,
    build_dsh_adapter,
)
from app.runtime.contracts import AgentPlan, RuntimeContext, PlanStep

from datetime import UTC, datetime

LOGGER_NAME = "company_workbench.tool_execution"
VENDOR_KEY = "sk-vendor-canary-0123456789abcdef"  # 假供应商密钥（非真实凭据）
GATEWAY_URL = "http://gw:8080"
DIGEST = "registry.local/dsh@sha256:abc"


# --------------------------------------------------------------- 脚手架

class FakeTokenClient:
    def __init__(self) -> None:
        self.minted: list[tuple[str, str]] = []
        self.revoked: list[str] = []

    def mint(self, bound: str) -> str:
        token = f"gw-token-{len(self.minted) + 1}"
        self.minted.append((token, bound))
        return token

    def revoke(self, bound: str) -> int:
        self.revoked.append(bound)
        return 1


class FakeTurnRunner:
    def __init__(self) -> None:
        self.specs = []

    def __call__(self, spec) -> None:
        self.specs.append(spec)


def _context() -> RuntimeContext:
    return RuntimeContext(
        tenant_id="t-1",
        user_id="u-1",
        role_key="employee",
        mode="auto",
        project_id=None,
        task_id="task-9",
        device_id="web",
        knowledge_scope=(),
        file_scope=(),
        budget_cents=0,
        risk_level="low",
        policy_version="v1",
        expires_at=datetime(2030, 1, 1, tzinfo=UTC),
    )


def _plan() -> AgentPlan:
    return AgentPlan.from_steps([{"step_id": "s1", "kind": "read", "tool": "read"}])


def _config(**overrides) -> DshAdapterConfig:
    base = dict(
        gateway_base_url=GATEWAY_URL,
        exec_image_digest=DIGEST,
        dsh_version="0.1.5-rc.1",
        vendor_api_key=VENDOR_KEY,
    )
    base.update(overrides)
    return DshAdapterConfig(**base)


def _scanner_hits(secret: str, values) -> list[str]:
    """明文扫描器（最小实现）：返回命中的字段名。"""
    if not secret:
        return []
    return [name for name, value in values.items() if isinstance(value, str) and secret in value]


# --------------------------------------------------------------- 剖面锁死断言

def test_default_profile_is_locked() -> None:
    profile = DshProfileLock()
    assert profile.problems() == []
    assert assert_profile_locked(profile) is True
    assert profile.permission_mode == PROFILE_PERMISSION_MODE == "read-only"
    assert profile.restrict_tools == RESTRICT_TOOLS and profile.restrict_tools


def test_assert_profile_rejects_non_read_only(caplog) -> None:
    """反假 ② 的判据面：去掉 `read-only` 断言 → 本用例变红。"""
    profile = DshProfileLock(permission_mode="workspace-write")
    with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
        assert assert_profile_locked(profile) is False
    assert any(ENV_PERMISSION_MODE in record.getMessage() for record in caplog.records)


def test_assert_profile_rejects_missing_disabled_plugin() -> None:
    reduced = tuple(item for item in DISABLED_PLUGINS if item.plugin_id != "subprocess-local")
    problems = DshProfileLock(disabled_plugins=reduced).problems()
    assert any("subprocess-local" in problem for problem in problems)


def test_disable_list_covers_required_packages() -> None:
    """用例 24 口径：禁用清单须含 `dsh-subprocess-local` 与 `dsh-session-telemetry-otel`。"""
    packages = set(DshProfileLock().disabled_packages)
    assert "@deepseek-ai/dsh-subprocess-local" in packages
    assert "@deepseek-ai/dsh-session-telemetry-otel" in packages
    assert "@deepseek-ai/dsh-tool-bash" in packages
    assert "@deepseek-ai/dsh-tool-pwsh" in packages


def test_assert_profile_rejects_empty_restrict() -> None:
    problems = DshProfileLock(restrict_tools=()).problems()
    assert any("restrict" in problem for problem in problems)


def test_assert_profile_rejects_telemetry_enabled() -> None:
    problems = DshProfileLock(telemetry_disabled=False).problems()
    assert any(ENV_TELEMETRY_DISABLED in problem for problem in problems)


def test_patch_yaml_disables_every_listed_plugin() -> None:
    content = DshProfileLock().patch_yaml()
    for item in DISABLED_PLUGINS:
        assert f"- id: {item.plugin_id}" in content
    assert content.count("disabled: true") == len(DISABLED_PLUGINS)


def test_disabled_plugin_shape_is_stable() -> None:
    assert isinstance(DISABLED_PLUGINS[0], DisabledPlugin)


# --------------------------------------------------------------- 适配器装配

def test_adapter_enabled_when_profile_and_config_ok() -> None:
    adapter = build_dsh_adapter(_config(), token_client=FakeTokenClient(), turn_runner=FakeTurnRunner())
    assert adapter.real_execution_enabled is True


def test_adapter_disabled_on_bad_profile_without_raising(caplog) -> None:
    """§3.6：断言失败 = 拒绝启用真实执行 + 记 error，**不抛进程级异常**。"""
    with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
        adapter = DshAdapter(
            _config(),
            token_client=FakeTokenClient(),
            turn_runner=FakeTurnRunner(),
            profile=DshProfileLock(permission_mode="danger-full-access"),
        )
    assert adapter.real_execution_enabled is False
    assert any(record.levelno == logging.ERROR for record in caplog.records)
    with pytest.raises(DshProfileLockError):
        adapter.start_run(_context(), _plan())


def test_adapter_disabled_when_gateway_url_or_digest_missing() -> None:
    for bad in (_config(gateway_base_url=""), _config(exec_image_digest=""), _config(exec_image_digest="dsh:latest")):
        adapter = DshAdapter(bad, token_client=FakeTokenClient(), turn_runner=FakeTurnRunner())
        assert adapter.real_execution_enabled is False


def test_from_settings_maps_fields() -> None:
    from app.settings import Settings

    settings = Settings(
        env="development",
        storage_backend="memory",
        model_gateway_base_url=GATEWAY_URL,
        exec_image_digest=DIGEST,
        dsh_version="0.1.5-rc.1",
        model_gateway_token_ttl_seconds=300,
        exec_timeout_seconds=180,
        model_gateway_upstream_api_key=VENDOR_KEY,
    )
    config = DshAdapterConfig.from_settings(settings)
    assert config.gateway_base_url == GATEWAY_URL
    assert config.dsh_version == "0.1.5-rc.1"
    assert config.vendor_api_key == VENDOR_KEY


# --------------------------------------------------------------- 容器内注入物

def test_turn_env_points_at_gateway_and_holds_short_term_token() -> None:
    client = FakeTokenClient()
    runner = FakeTurnRunner()
    adapter = build_dsh_adapter(_config(), token_client=client, turn_runner=runner)
    run_id = adapter.start_run(_context(), _plan())

    assert run_id and client.minted
    token, bound = client.minted[0]
    env = runner.specs[0].env
    assert env[ENV_BASE_URL] == GATEWAY_URL  # baseURL → 网关内网地址
    assert env[ENV_API_KEY] == token  # apiKeyEnv = 短期令牌
    assert env[ENV_PERMISSION_MODE] == "read-only"
    assert env[ENV_TELEMETRY_DISABLED] == "1"
    # 绑定标签 = 租户:会话:代次（审计元数据）
    assert bound == "t-1:task-9:1"
    assert runner.specs[0].bound == bound


def test_turn_env_never_contains_vendor_secret() -> None:
    """反假 ① 的判据面：把供应商密钥注入容器 env → 本用例（明文扫描）必须变红。"""
    adapter = build_dsh_adapter(_config(), token_client=FakeTokenClient(), turn_runner=FakeTurnRunner())
    env = adapter.build_turn_env(token="gw-token-1")
    assert _scanner_hits(VENDOR_KEY, env) == []
    # 阴性对照：扫描器对真实存在的密钥确实会命中（证明扫描器有效，不是恒空）
    assert _scanner_hits(VENDOR_KEY, {**env, "LEAKED": f"x{VENDOR_KEY}y"}) == ["LEAKED"]


# --------------------------------------------------------------- 令牌六条（可离线项）

def test_per_turn_new_mint_and_bound_encodes_identity() -> None:
    client = FakeTokenClient()
    adapter = build_dsh_adapter(_config(), token_client=client, turn_runner=FakeTurnRunner())
    adapter.start_run(_context(), _plan())
    adapter.start_run(_context(), _plan())
    tokens = [token for token, _bound in client.minted]
    bounds = [bound for _token, bound in client.minted]
    assert tokens[0] != tokens[1]  # ① 每 turn 新铸
    assert bounds == ["t-1:task-9:1", "t-1:task-9:2"]  # ② 绑死租户/会话/代次


def test_cancel_run_revokes_token() -> None:
    client = FakeTokenClient()
    adapter = build_dsh_adapter(_config(), token_client=client, turn_runner=FakeTurnRunner())
    run_id = adapter.start_run(_context(), _plan())
    adapter.cancel_run(run_id, "user_cancel")
    adapter.terminal_revoke(run_id)  # 终态同步吊销入口（供 token_revoker 复用）
    assert client.revoked == ["t-1:task-9:1", "t-1:task-9:1"]  # ⑤ 吊销落到同一 bound


def test_start_run_requires_token_client_and_runner() -> None:
    aware = build_dsh_adapter(_config())  # 无 token_client / runner
    assert aware.real_execution_enabled is True
    with pytest.raises(DshProfileLockError):
        aware.start_run(_context(), _plan())


def test_health_reports_sandbox_and_tool_face() -> None:
    adapter = build_dsh_adapter(_config(), token_client=FakeTokenClient(), turn_runner=FakeTurnRunner())
    health = adapter.health()
    assert health["sandbox"] == "read-only"
    assert health["capabilities"] == list(RESTRICT_TOOLS)
    assert health["status"] == "ok"
