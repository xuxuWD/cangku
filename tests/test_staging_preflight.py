from scripts.staging_preflight import _as_mapping, run_preflight


def valid_config() -> dict[str, object]:
    return {
        "environment": "staging",
        "storage_backend": "postgres",
        "database_url": "postgresql+psycopg://workbench:pg-secret@pg.staging.internal:5432/workbench",
        "auth_secret": "b" * 32,
        "backup_key": "a" * 32,
        "applied_migrations": ["001_initial", "006_commercial_g0"],
        "expected_migrations": ["001_initial", "006_commercial_g0"],
        "retention_policy": {"tasks": 180, "audit": 730},
        "runtime_versions": {"mock": "0.1.0", "ragflow": "v0.19.0"},
        "staging_id": "customer-a-isolated",
        "ragflow_endpoint": "https://ragflow.staging.example",
        "ragflow_version": "v0.19.0",
        "ragflow_capabilities": "knowledge_search",
        "ragflow_auth_injected": "true",
        "agentscope_endpoint": "https://agentscope.staging.example",
        "agentscope_version": "v1.2.3",
        "agentscope_capabilities": "run",
        "agentscope_auth_injected": "true",
        "runtime_network": "ragflow.staging.example,agentscope.staging.example",
        "redis_url": "redis://redis.staging.internal:6379/0",
        "object_storage_url": "https://objects.staging.internal",
        "staging_tenant_id": "tenant-staging-a",
        "object_namespace": "staging-customer-a",
        "ragflow_test_account_ready": "true",
        "agentscope_test_account_ready": "true",
    }


def test_staging_preflight_passes_when_isolation_and_metadata_are_complete() -> None:
    report = run_preflight(valid_config())

    assert report.status == "pass"
    assert all(check.status == "pass" for check in report.checks)


def test_staging_preflight_fails_closed_without_isolation_metadata() -> None:
    report = run_preflight({})

    assert report.status == "fail"
    assert {check.name for check in report.checks} >= {
        "PostgreSQL 独立主机",
        "Redis 独立主机",
        "对象存储独立主机",
        "Staging 租户隔离",
        "对象存储命名空间",
        "RAGFlow 测试账号",
        "AgentScope 测试账号",
    }


def test_staging_preflight_rejects_local_default_hosts() -> None:
    config = valid_config()
    config.update(
        {
            "database_url": "postgresql://workbench:secret@localhost:5432/workbench",
            "redis_url": "redis://127.0.0.1:6379/0",
            "object_storage_url": "http://localhost:9000",
        }
    )

    report = run_preflight(config)
    text = report.to_text()

    assert report.status == "fail"
    assert "PostgreSQL 独立主机" in text
    assert "Redis 独立主机" in text
    assert "对象存储独立主机" in text


def test_staging_preflight_requires_isolation_markers_and_test_accounts() -> None:
    config = valid_config()
    for key in (
        "staging_tenant_id",
        "object_namespace",
        "ragflow_test_account_ready",
        "agentscope_test_account_ready",
    ):
        config.pop(key)

    report = run_preflight(config)
    text = report.to_text()

    assert report.status == "fail"
    assert "Staging 租户隔离" in text
    assert "对象存储命名空间" in text
    assert "RAGFlow 测试账号" in text
    assert "AgentScope 测试账号" in text


def test_staging_preflight_aggregates_commercial_and_runtime_checks() -> None:
    config = valid_config()
    config["backup_key"] = "short"
    config["agentscope_version"] = "latest"

    report = run_preflight(config)
    text = report.to_text()

    assert report.status == "fail"
    assert "商业化：" in text
    assert "外部 Runtime：" in text


def test_staging_preflight_does_not_leak_secret_values() -> None:
    config = valid_config()
    config["database_url"] = "postgresql://workbench:super-secret-password@pg.staging.internal:5432/workbench"
    config["auth_secret"] = "leaky-auth-secret-value-000000000000"

    text = run_preflight(config).to_text()

    assert "super-secret-password" not in text
    assert "leaky-auth-secret-value" not in text


def test_default_mapping_reads_staging_isolation_environment(monkeypatch) -> None:
    monkeypatch.setenv("WORKBENCH_REDIS_URL", "redis://redis.staging.internal:6379/0")
    monkeypatch.setenv("WORKBENCH_OBJECT_NAMESPACE", "staging-customer-a")
    monkeypatch.setenv("AGENTSCOPE_TEST_ACCOUNT_READY", "true")

    values = _as_mapping(None)

    assert values["redis_url"] == "redis://redis.staging.internal:6379/0"
    assert values["object_namespace"] == "staging-customer-a"
    assert values["agentscope_test_account_ready"] == "true"
