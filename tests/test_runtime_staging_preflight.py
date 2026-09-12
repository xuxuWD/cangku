import pytest

from scripts.runtime_staging_preflight import _as_mapping, run_preflight


def valid_config() -> dict[str, object]:
    return {
        "environment": "staging",
        "staging_id": "customer-a-isolated",
        "ragflow_endpoint": "https://ragflow.staging.example",
        "ragflow_version": "v0.19.0",
        "ragflow_capabilities": "knowledge_search",
        "ragflow_auth_injected": "true",
        "agentscope_endpoint": "https://agentscope.staging.example",
        "agentscope_version": "v1.2.3",
        "agentscope_capabilities": "run, pause, resume, cancel, approvals, replay, usage",
        "agentscope_auth_injected": "true",
        "deerflow_endpoint": "http://127.0.0.1:9101",
        "deerflow_version": "pinned",
        "deerflow_capabilities": "research, content_plan",
        "codex_worker_endpoint": "http://127.0.0.1:9102",
        "codex_worker_version": "pinned",
        "codex_worker_capabilities": "fde_file_read, sandbox_check",
        "hermes_endpoint": "http://127.0.0.1:9103",
        "hermes_version": "pinned",
        "hermes_capabilities": "memory_proposal, skill_proposal",
        "runtime_network": "ragflow.staging.example,agentscope.staging.example,127.0.0.1",
    }


def test_runtime_staging_preflight_passes_with_complete_non_secret_metadata() -> None:
    report = run_preflight(valid_config())

    assert report.status == "pass"
    assert all(check.status == "pass" for check in report.checks)


def test_runtime_staging_preflight_fails_closed_without_required_metadata() -> None:
    report = run_preflight({})

    assert report.status == "fail"
    assert {check.name for check in report.checks} >= {
        "运行环境", "Staging 标识", "RAGFlow 地址", "AgentScope 地址", "网络白名单",
    }


def test_runtime_staging_preflight_rejects_insecure_or_unpinned_runtimes() -> None:
    config = valid_config()
    config["ragflow_endpoint"] = "http://ragflow.staging.example"
    config["agentscope_version"] = "latest"

    report = run_preflight(config)

    assert report.status == "fail"
    assert "RAGFlow 地址" in report.to_text()
    assert "AgentScope 版本" in report.to_text()


def test_runtime_staging_preflight_requires_deployment_auth_markers_without_leaking_values() -> None:
    config = valid_config()
    config["ragflow_auth_injected"] = "false"
    config["agentscope_auth_injected"] = "Bearer secret-value"

    report = run_preflight(config)
    text = report.to_text()

    assert report.status == "fail"
    assert "认证注入" in text
    assert "secret-value" not in text


def test_runtime_staging_preflight_fails_closed_without_capability_whitelist() -> None:
    config = valid_config()
    config["ragflow_capabilities"] = ""
    config["agentscope_capabilities"] = "  ,  "

    report = run_preflight(config)
    text = report.to_text()

    assert report.status == "fail"
    assert any(
        check.name == "RAGFlow 能力白名单" and check.status == "fail"
        for check in report.checks
    )
    assert any(
        check.name == "AgentScope 能力白名单" and check.status == "fail"
        for check in report.checks
    )
    assert "fail-closed" in text


def test_runtime_staging_preflight_passes_with_capability_whitelist() -> None:
    report = run_preflight(valid_config())

    capability_checks = [check for check in report.checks if check.name.endswith("能力白名单")]
    assert {check.name for check in capability_checks} == {
        "RAGFlow 能力白名单",
        "AgentScope 能力白名单",
        "DeerFlow 能力白名单",
        "Codex Worker 能力白名单",
        "Hermes 能力白名单",
    }
    assert all(check.status == "pass" for check in capability_checks)


def test_runtime_staging_preflight_accepts_local_process_http_endpoints() -> None:
    """本地独立进程（DeerFlow / Codex Worker / Hermes）允许 http，且不强制认证注入。"""
    report = run_preflight(valid_config())

    assert report.status == "pass"
    local_checks = [
        check
        for check in report.checks
        if check.name.startswith(("DeerFlow", "Codex Worker", "Hermes"))
    ]
    assert local_checks
    assert all(check.status == "pass" for check in local_checks)
    assert not any("认证注入" in check.name for check in local_checks)


def test_runtime_staging_preflight_rejects_local_process_without_fixed_version_or_whitelist() -> None:
    config = valid_config()
    config["hermes_version"] = ""
    config["codex_worker_capabilities"] = "  ,  "

    report = run_preflight(config)
    text = report.to_text()

    assert report.status == "fail"
    assert "Hermes 版本" in text
    assert any(
        check.name == "Codex Worker 能力白名单" and check.status == "fail"
        for check in report.checks
    )


_NON_RUNTIME_ENV_NAMES = {
    "environment": "WORKBENCH_ENV",
    "staging_id": "WORKBENCH_STAGING_ID",
    "runtime_network": "WORKBENCH_RUNTIME_NETWORK",
}
_RUNTIME_PREFIXES = ("ragflow", "agentscope", "deerflow", "codex_worker", "hermes")


def _set_prefix_only_env(monkeypatch, config: dict[str, object]) -> None:
    """只写 `WORKBENCH_<KEY>_*` 形式，并清掉裸名，模拟"带前缀部署"这一种合法写法。"""
    for key in config:
        if key in _NON_RUNTIME_ENV_NAMES:
            monkeypatch.setenv(_NON_RUNTIME_ENV_NAMES[key], str(config[key]))
            continue
        prefix, _, field = key.rpartition("_")
        monkeypatch.setenv(f"WORKBENCH_{prefix.upper()}_{field.upper()}", str(config[key]))
    for prefix in _RUNTIME_PREFIXES:
        for field in ("ENDPOINT", "VERSION", "CAPABILITIES", "AUTH_INJECTED"):
            monkeypatch.delenv(f"{prefix}_{field}", raising=False)


def test_default_mapping_reads_workbench_prefixed_runtime_names(monkeypatch) -> None:
    """应用同时接受裸名与 `WORKBENCH_` 前缀名，预检必须同样认，否则会"假失败"。"""
    monkeypatch.setenv("WORKBENCH_RAGFLOW_ENDPOINT", "https://ragflow.staging.example")
    monkeypatch.setenv("WORKBENCH_HERMES_CAPABILITIES", "memory_proposal")
    monkeypatch.delenv("RAGFLOW_ENDPOINT", raising=False)

    values = _as_mapping(None)

    assert values["ragflow_endpoint"] == "https://ragflow.staging.example"
    assert values["hermes_capabilities"] == "memory_proposal"


def test_default_mapping_prefers_bare_name_over_prefixed(monkeypatch) -> None:
    """与 Settings 的 AliasChoices 顺序一致：裸名优先。"""
    monkeypatch.setenv("RAGFLOW_ENDPOINT", "https://bare.example")
    monkeypatch.setenv("WORKBENCH_RAGFLOW_ENDPOINT", "https://prefixed.example")

    assert _as_mapping(None)["ragflow_endpoint"] == "https://bare.example"


def test_runtime_staging_preflight_passes_with_prefixed_names_only(monkeypatch) -> None:
    """整份配置都写成带前缀名时，预检必须与实际启动口径一致地判 pass。"""
    _set_prefix_only_env(monkeypatch, valid_config())

    report = run_preflight()

    assert report.status == "pass"
    assert all(check.status == "pass" for check in report.checks)


@pytest.mark.parametrize("spelling", ["true", "TRUE", "1", "yes", "on", "t"])
def test_runtime_staging_preflight_accepts_boolean_spellings_of_auth_marker(spelling) -> None:
    """与 pydantic 的 bool 解析同口径，这些写法都表示"已注入"。"""
    config = valid_config()
    config["ragflow_auth_injected"] = spelling
    config["agentscope_auth_injected"] = spelling

    assert run_preflight(config).status == "pass"


