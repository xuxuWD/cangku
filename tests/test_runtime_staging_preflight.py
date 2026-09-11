from scripts.runtime_staging_preflight import run_preflight


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
        "runtime_network": "ragflow.staging.example,agentscope.staging.example",
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
        "RAGFlow 能力白名单", "AgentScope 能力白名单",
    }
    assert all(check.status == "pass" for check in capability_checks)
