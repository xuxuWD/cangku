from scripts.commercial_g0_preflight import _as_mapping, run_preflight


def valid_config() -> dict[str, object]:
    return {
        "environment": "staging",
        "storage_backend": "postgres",
        "database_url": "postgresql://workbench:secret@db/workbench",
        "auth_secret": "b" * 32,
        "backup_key": "a" * 32,
        "applied_migrations": ["001_base", "006_commercial_g0"],
        "expected_migrations": ["001_base", "006_commercial_g0"],
        "retention_policy": {"tasks": 180, "audit": 730},
        "runtime_versions": {"mock": "0.1.0", "deerflow": "2026.09.01"},
    }


def test_preflight_passes_only_when_all_private_deployment_requirements_exist():
    report = run_preflight(valid_config())
    assert report.status == "pass"
    assert all(check.status == "pass" for check in report.checks)


def test_preflight_fails_closed_for_missing_database_and_backup_key_without_leaking_values():
    config = valid_config()
    config.pop("database_url")
    config.pop("backup_key")
    report = run_preflight(config)
    assert report.status == "fail"
    text = report.to_text()
    assert "数据库地址" in text
    assert "备份加密密钥" in text
    assert "secret" not in text


def test_preflight_blocks_migration_drift_retention_gap_and_unpinned_runtime():
    config = valid_config()
    config["applied_migrations"] = ["001_base"]
    config["retention_policy"] = {}
    config["runtime_versions"] = {"mock": "latest"}
    report = run_preflight(config)
    assert report.status == "blocked"
    assert "迁移" in report.to_text()
    assert "保留策略" in report.to_text()
    assert "Runtime" in report.to_text()


def test_default_preflight_migration_inventory_includes_all_repository_migrations(monkeypatch):
    monkeypatch.delenv("WORKBENCH_APPLIED_MIGRATIONS", raising=False)
    values = _as_mapping(None)

    expected = set(values["expected_migrations"])
    assert {"001_initial", "006_commercial_g0", "007_commercial_retention"}.issubset(expected)


def test_preflight_requires_non_development_postgres_runtime_and_auth_secret():
    config = valid_config()
    config.update({"environment": "development", "storage_backend": "memory", "auth_secret": "short"})

    report = run_preflight(config)

    assert report.status == "fail"
    text = report.to_text()
    assert "运行环境" in text
    assert "存储模式" in text
    assert "认证密钥" in text
    assert "short" not in text


def test_preflight_rejects_reusing_auth_secret_as_backup_key():
    config = valid_config()
    config["backup_key"] = config["auth_secret"]

    report = run_preflight(config)

    assert report.status == "fail"
    assert "密钥隔离" in report.to_text()
