"""worker_preflight 测试：配置 fail-closed、离线/联网分支、护栏与「绝不回显令牌」。

联网分支全部通过注入的假传输层与假 Redis 探针验证，测试本身不发任何网络请求。
"""

from __future__ import annotations

import pytest

from scripts.worker_preflight import PreflightReport, _as_mapping, main, run_preflight

REDIS_URL = "redis://redis.staging.internal:6379/0"
BASE_URL = "https://workbench.staging.example"
TOKEN = "admin-token-super-secret-value"
MIGRATIONS = ["001_initial", "002_event_outbox"]


def valid_config() -> dict[str, object]:
    return {
        "environment": "staging",
        "storage_backend": "postgres",
        "redis_url": REDIS_URL,
        "outbox_max_attempts": 3,
        "dead_letter_webhook_url": "https://hooks.staging.example/dead-letters",
        "applied_migrations": list(MIGRATIONS),
        "expected_migrations": list(MIGRATIONS),
    }


class FakeResponse:
    def __init__(self, *, status_code: int = 200, payload=None) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


def ok_probe(url: str) -> str:
    return "redis.staging.internal:6379"


def ok_transport(*_args, **_kwargs):
    """默认应答：健康检查 ok、死信列表含 2 条（其中 1 条已通知）。"""
    return FakeResponse(payload=[{"event_id": "a", "notified_at": "2026-01-01T00:00:00Z"},
                                 {"event_id": "b", "notified_at": None}])


def health_transport(*args, **kwargs):
    url = args[1] if len(args) > 1 else kwargs.get("url", "")
    if url.endswith("/api/v1/health"):
        return FakeResponse(payload={"status": "ok", "service": "company-workbench"})
    return ok_transport(*args, **kwargs)


def find(report: PreflightReport, name: str) -> str:
    for check in report.checks:
        if check.name == name:
            return check.status
    raise AssertionError(f"未找到检查项：{name}")


# --- 配置层（--offline 也执行）-------------------------------------------------


def test_offline_complete_config_passes() -> None:
    report = run_preflight(valid_config(), offline=True)

    assert report.status == "pass"
    assert not any(check.status == "fail" for check in report.checks)
    assert find(report, "运行环境") == "pass"
    assert find(report, "持久化后端") == "pass"
    assert find(report, "Redis 地址协议") == "pass"
    assert find(report, "Outbox 最大尝试次数") == "pass"
    assert find(report, "迁移清单一致") == "pass"


def test_empty_config_fails_closed() -> None:
    report = run_preflight({}, offline=True)
    text = report.to_text()

    assert report.status == "fail"
    assert {
        "运行环境",
        "持久化后端",
        "Redis 地址协议",
        "Outbox 最大尝试次数",
        "迁移清单一致",
    } <= {check.name for check in report.checks}
    assert "development" in text


def test_development_environment_fails() -> None:
    config = valid_config()
    config["environment"] = "development"

    assert find(run_preflight(config, offline=True), "运行环境") == "fail"


def test_storage_backend_must_be_postgres() -> None:
    config = valid_config()
    config["storage_backend"] = "memory"

    assert find(run_preflight(config, offline=True), "持久化后端") == "fail"


def test_redis_url_requires_redis_scheme() -> None:
    for bad in ("", "http://redis.staging.internal", "redis.staging.internal:6379"):
        config = valid_config()
        config["redis_url"] = bad
        assert find(run_preflight(config, offline=True), "Redis 地址协议") == "fail"


def test_rediss_scheme_is_accepted() -> None:
    config = valid_config()
    config["redis_url"] = "rediss://redis.staging.internal:6380/0"

    assert find(run_preflight(config, offline=True), "Redis 地址协议") == "pass"


def test_outbox_max_attempts_range() -> None:
    for bad in (0, 21, "abc", None):
        config = valid_config()
        config["outbox_max_attempts"] = bad
        assert find(run_preflight(config, offline=True), "Outbox 最大尝试次数") == "fail"

    config = valid_config()
    config["outbox_max_attempts"] = "5"
    assert find(run_preflight(config, offline=True), "Outbox 最大尝试次数") == "pass"


def test_webhook_must_be_https_but_empty_is_allowed() -> None:
    config = valid_config()
    config["dead_letter_webhook_url"] = "http://hooks.staging.example/x"
    assert find(run_preflight(config, offline=True), "死信通知渠道") == "fail"

    config = valid_config()
    config["dead_letter_webhook_url"] = ""
    assert find(run_preflight(config, offline=True), "死信通知渠道") == "pass"


def test_migration_mismatch_fails_with_counts() -> None:
    config = valid_config()
    config["applied_migrations"] = ["001_initial"]
    config["expected_migrations"] = ["001_initial", "002_event_outbox"]

    check = next(
        item for item in run_preflight(config, offline=True).checks if item.name == "迁移清单一致"
    )
    assert check.status == "fail"
    assert "缺少 1" in check.message and "多出 0" in check.message


# --- 离线不触网 / 不探测 -------------------------------------------------------


def test_offline_never_touches_network_or_redis() -> None:
    report = run_preflight(
        valid_config(),
        offline=True,
        transport=lambda *_a, **_k: pytest.fail("--offline 不应发起 HTTP 请求"),
        redis_probe=lambda *_a, **_k: pytest.fail("--offline 不应探测 Redis"),
    )

    assert report.status == "pass"
    assert find(report, "联网运行态校验") == "skipped"


# --- 护栏（fail-closed）-------------------------------------------------------


def test_online_rejects_insecure_base_url() -> None:
    report = run_preflight(
        valid_config(),
        base_url="http://workbench.staging.example",
        transport=health_transport,
        redis_probe=ok_probe,
    )

    assert report.status == "fail"
    assert find(report, "目标地址护栏") == "fail"


def test_online_rejects_local_host_without_explicit_allow() -> None:
    report = run_preflight(
        valid_config(),
        base_url="https://localhost:8443",
        transport=health_transport,
        redis_probe=ok_probe,
    )

    assert report.status == "fail"
    assert find(report, "目标地址护栏") == "fail"


def test_online_allows_insecure_local_when_explicitly_allowed() -> None:
    report = run_preflight(
        valid_config(),
        base_url="http://127.0.0.1:8000",
        allow_insecure_local=True,
        transport=health_transport,
        redis_probe=ok_probe,
    )

    text = report.to_text()
    assert find(report, "目标地址护栏") == "pass"
    assert "已显式允许" in text


# --- 联网运行态 ---------------------------------------------------------------


def test_online_health_redis_and_dead_letters_pass() -> None:
    report = run_preflight(
        valid_config(),
        base_url=BASE_URL,
        token=TOKEN,
        transport=health_transport,
        redis_probe=ok_probe,
    )

    assert report.status == "pass"
    assert find(report, "应用健康检查") == "pass"
    assert find(report, "Redis 可达性") == "pass"
    assert find(report, "死信运行态") == "pass"
    text = report.to_text()
    assert "死信 2 条" in text
    assert "已通知 1 条" in text


def test_online_health_failure_fails_closed() -> None:
    report = run_preflight(
        valid_config(),
        base_url=BASE_URL,
        transport=lambda *_a, **_k: FakeResponse(status_code=503, payload={"status": "down"}),
        redis_probe=ok_probe,
    )

    assert report.status == "fail"
    assert find(report, "应用健康检查") == "fail"


def test_online_redis_probe_failure_fails_closed() -> None:
    def broken(_url: str) -> str:
        raise OSError("connect refused")

    report = run_preflight(
        valid_config(),
        base_url=BASE_URL,
        transport=health_transport,
        redis_probe=broken,
    )

    assert report.status == "fail"
    assert find(report, "Redis 可达性") == "fail"


def test_online_redis_probe_receives_configured_url() -> None:
    seen: list[str] = []

    def probe(url: str) -> str:
        seen.append(url)
        return "redis.staging.internal:6379"

    run_preflight(
        valid_config(),
        base_url=BASE_URL,
        transport=health_transport,
        redis_probe=probe,
    )

    assert seen == [REDIS_URL]


def test_dead_letters_without_token_is_skipped() -> None:
    report = run_preflight(
        valid_config(),
        base_url=BASE_URL,
        transport=health_transport,
        redis_probe=ok_probe,
    )

    assert find(report, "死信运行态") == "skipped"
    assert report.status == "pass"


def test_dead_letters_forbidden_fails() -> None:
    def transport(*args, **kwargs):
        url = args[1] if len(args) > 1 else kwargs.get("url", "")
        if url.endswith("/api/v1/dead-letters"):
            return FakeResponse(status_code=403, payload={"detail": "no"})
        return FakeResponse(payload={"status": "ok"})

    report = run_preflight(
        valid_config(),
        base_url=BASE_URL,
        token=TOKEN,
        transport=transport,
        redis_probe=ok_probe,
    )

    assert report.status == "fail"
    assert find(report, "死信运行态") == "fail"


def test_outbox_backlog_reports_missing_interface() -> None:
    report = run_preflight(
        valid_config(),
        base_url=BASE_URL,
        token=TOKEN,
        transport=health_transport,
        redis_probe=ok_probe,
    )

    check = next(item for item in report.checks if item.name == "Outbox 积压")
    assert check.status == "skipped"
    assert "接口" in check.message


def test_report_never_prints_token() -> None:
    report = run_preflight(
        valid_config(),
        base_url=BASE_URL,
        token=TOKEN,
        transport=health_transport,
        redis_probe=ok_probe,
    )

    text = report.to_text()
    assert TOKEN not in text
    assert "workbench.staging.example" in text


# --- main() 退出码与默认映射 ---------------------------------------------------


def test_main_example_exits_nonzero(capsys) -> None:
    assert main(["--example"]) == 1
    assert TOKEN not in capsys.readouterr().out


def test_main_offline_complete_config_exits_zero(monkeypatch, capsys) -> None:
    from pathlib import Path

    expected = sorted(
        path.stem for path in (Path(__file__).resolve().parents[1] / "migrations").glob("*.sql")
    )
    monkeypatch.setenv("WORKBENCH_ENV", "staging")
    monkeypatch.setenv("WORKBENCH_STORAGE_BACKEND", "postgres")
    monkeypatch.setenv("WORKBENCH_REDIS_URL", REDIS_URL)
    monkeypatch.setenv("WORKBENCH_OUTBOX_MAX_ATTEMPTS", "3")
    monkeypatch.setenv("WORKBENCH_DEAD_LETTER_WEBHOOK_URL", "")
    monkeypatch.setenv("WORKBENCH_APPLIED_MIGRATIONS", ",".join(expected))

    assert main(["--offline"]) == 0
    assert "pass" in capsys.readouterr().out


def test_default_mapping_reads_environment(monkeypatch) -> None:
    monkeypatch.setenv("WORKBENCH_ENV", "staging")
    monkeypatch.setenv("WORKBENCH_REDIS_URL", REDIS_URL)
    monkeypatch.setenv("WORKBENCH_OUTBOX_MAX_ATTEMPTS", "4")
    monkeypatch.setenv("WORKBENCH_ACCEPTANCE_TOKEN", TOKEN)

    values = _as_mapping(None)

    assert values["environment"] == "staging"
    assert values["redis_url"] == REDIS_URL
    assert values["outbox_max_attempts"] == "4"
    assert values["token"] == TOKEN
    assert values["expected_migrations"]
