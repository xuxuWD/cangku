"""客户侧交付验收只读探针的离线测试。

全部使用**注入的假 docker 执行器 / 假 HTTP GET / 假 SQL 查询**：
不发任何真实网络请求、不连任何数据库、不调用 docker（CI 与开发机通常都没有 docker 守护进程）。

覆盖：
- 镜像引用（禁止 latest / 无标签）与 5 个 OCI 标签（缺失、默认值 ``dev`` / ``unknown``）；
- 三服务容器日志上限（正确 / 缺失）；
- health 200 与非 200；
- PostgreSQL 连接数在阈值内 / 超阈值 / 上限低于要求；
- 运行事件表为空 / 有数据 / 表不存在（⇒ skipped）；
- 环境不可用（无 docker / 无只读 DSN）⇒ 显式 skipped，绝不静默通过；
- 退出码 0 / 1 / 2 与 ``--allow-local`` / ``--allow-insecure`` 的 fail-closed 参数校验；
- 报告脱敏：含 ``postgresql://user:pass@host/db`` 的失败信息必须被遮蔽。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from scripts.customer_acceptance_probe import (
    ProbeConfigError,
    main,
    resolve_base_url,
    run_probe,
)

BASE_URL = "https://workbench.customer.internal"
IMAGE = "workbench-app:v2026.09.16"
CONTAINERS = {"app": "wb-app-1", "worker": "wb-worker-1", "beat": "wb-beat-1"}
GOOD_LABELS = {
    "org.opencontainers.image.title": "company-workbench",
    "org.opencontainers.image.description": "公司数字员工工作台应用镜像（app / worker / beat 共用）",
    "org.opencontainers.image.version": "v2026.09.16",
    "org.opencontainers.image.revision": "37bba6f0d8c2a1b",
    "org.opencontainers.image.source": "https://example.internal/repo",
}
GOOD_LOGGING = {"Type": "json-file", "Config": {"max-size": "10m", "max-file": "5"}}
BEAT_LOG = "celery beat v5.4 (sunrise)\nSending due task outbox-publisher\n"
DSN = "postgresql://workbench_ro:EXAMPLESECRET@pg.customer.internal:5432/workbench"
LEAKED_DSN = "postgresql://workbench:SUPERSECRET@pg.customer.internal:5432/workbench"
NOW = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)


# --------------------------------------------------------------------------- 假执行器


def make_docker(
    *,
    labels: object = GOOD_LABELS,
    logging: object = GOOD_LOGGING,
    health: str = '{"Status":"healthy"}',
    logs: str = BEAT_LOG,
):
    """按 docker 子命令参数返回假输出；未预期的命令直接断言失败。"""

    def runner(args):
        argv = [str(item) for item in args]
        if argv[:1] == ["image"]:
            return json.dumps(labels)
        if argv[:1] == ["inspect"]:
            fmt = argv[argv.index("--format") + 1] if "--format" in argv else ""
            if "LogConfig" in fmt:
                return json.dumps(logging)
            if "State.Health" in fmt:
                return health
            raise AssertionError(f"未预期的 inspect 格式：{fmt}")
        if argv[:1] == ["logs"]:
            return logs
        raise AssertionError(f"未预期的 docker 命令：{argv}")

    return runner


def docker_unavailable(args):
    raise FileNotFoundError("docker: command not found")


class FakeResponse:
    def __init__(self, status_code: int = 200, payload: object = None) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> object:
        return self._payload


def make_http_get(*, status_code: int = 200, payload: object = ...):
    actual = {"status": "ok"} if payload is ... else payload

    def get(url, *, headers, timeout):
        return FakeResponse(status_code, actual)

    return get


def make_sql(
    *,
    used: int = 43,
    limit: int = 100,
    events: object = None,
    audit: object = None,
    events_error: BaseException | None = None,
    audit_error: BaseException | None = None,
):
    """按 SQL 关键字路由的假查询；返回行的形状与真实查询一致。"""
    events_row = events if events is not None else (0, None, None)
    audit_row = audit if audit is not None else (16, "2026-09-15T14:09:00+00:00")

    def query(sql: str):
        if "pg_stat_activity" in sql:
            return [(used, limit)]
        if "workbench_runtime_events" in sql:
            if events_error is not None:
                raise events_error
            return [events_row]
        if "workbench_audit_log" in sql:
            if audit_error is not None:
                raise audit_error
            return [audit_row]
        raise AssertionError(f"未预期的 SQL：{sql}")

    return query


def run(**overrides):
    kwargs = {
        "image": IMAGE,
        "base_url": BASE_URL,
        "containers": CONTAINERS,
        "psql_dsn": DSN,
        "docker": make_docker(),
        "http_get": make_http_get(),
        "sql_query": make_sql(),
        "timeout": 5.0,
    }
    kwargs.update(overrides)
    return run_probe(**kwargs)


def check(report, needle: str):
    matches = [item for item in report.checks if needle in item.name]
    assert matches, [item.name for item in report.checks]
    assert len(matches) == 1, [item.name for item in matches]
    return matches[0]


# --------------------------------------------------------------------------- 镜像


def test_image_reference_without_tag_is_rejected() -> None:
    report = run(image="workbench-app")

    item = check(report, "镜像引用")
    assert item.status == "fail"
    assert "latest" in item.observed


def test_image_reference_with_latest_tag_is_rejected() -> None:
    report = run(image="workbench-app:latest")

    assert check(report, "镜像引用").status == "fail"


def test_image_reference_with_version_tag_passes() -> None:
    report = run()

    item = check(report, "镜像引用")
    assert item.status == "pass"
    assert IMAGE in item.observed


def test_image_reference_missing_is_skipped_not_passed() -> None:
    report = run(image="")

    item = check(report, "镜像引用")
    assert item.status == "skipped"
    assert item.status != "pass"


def test_oci_labels_complete_pass() -> None:
    report = run()

    item = check(report, "OCI 标签")
    assert item.status == "pass"
    assert "revision" in item.criteria


def test_oci_labels_missing_fails() -> None:
    labels = {key: value for key, value in GOOD_LABELS.items() if "source" not in key}

    report = run(docker=make_docker(labels=labels))

    item = check(report, "OCI 标签")
    assert item.status == "fail"
    assert "source" in item.observed


@pytest.mark.parametrize("value", ["dev", "unknown", ""])
def test_oci_labels_default_values_fail(value: str) -> None:
    labels = dict(GOOD_LABELS)
    labels["org.opencontainers.image.version"] = value

    report = run(docker=make_docker(labels=labels))

    item = check(report, "OCI 标签")
    assert item.status == "fail"
    assert "默认值" in item.observed


def test_oci_labels_revision_default_unknown_fails() -> None:
    labels = dict(GOOD_LABELS)
    labels["org.opencontainers.image.revision"] = "unknown"

    assert check(run(docker=make_docker(labels=labels)), "OCI 标签").status == "fail"


# --------------------------------------------------------------------------- 日志上限


@pytest.mark.parametrize("service", ["app", "worker", "beat"])
def test_container_logging_caps_pass(service: str) -> None:
    report = run()

    item = check(report, f"容器日志上限（{service}）")
    assert item.status == "pass"
    assert "10m" in item.observed


def test_container_logging_missing_fails() -> None:
    report = run(docker=make_docker(logging={}))

    for service in ("app", "worker", "beat"):
        item = check(report, f"容器日志上限（{service}）")
        assert item.status == "fail"
        assert "json-file" in item.observed


def test_container_logging_wrong_driver_fails() -> None:
    logging = {"Type": "journald", "Config": {"max-size": "10m", "max-file": "5"}}

    report = run(docker=make_docker(logging=logging))

    assert check(report, "容器日志上限（app）").status == "fail"


# --------------------------------------------------------------------------- 健康


def test_health_ok_passes() -> None:
    item = check(run(), "应用健康检查")

    assert item.status == "pass"
    assert "/api/v1/health" in item.criteria


def test_health_non_200_fails() -> None:
    report = run(http_get=make_http_get(status_code=503, payload={"status": "degraded"}))

    item = check(report, "应用健康检查")
    assert item.status == "fail"
    assert "503" in item.observed


def test_health_transport_error_fails() -> None:
    def boom(url, *, headers, timeout):
        raise RuntimeError("connection refused")

    item = check(run(http_get=boom), "应用健康检查")

    assert item.status == "fail"


def test_worker_healthcheck_unhealthy_fails() -> None:
    report = run(docker=make_docker(health='{"Status":"unhealthy"}'))

    item = check(report, "worker healthcheck")
    assert item.status == "fail"
    assert "unhealthy" in item.observed


def test_worker_healthcheck_missing_fails() -> None:
    report = run(docker=make_docker(health="null"))

    item = check(report, "worker healthcheck")
    assert item.status == "fail"
    assert "healthcheck" in item.observed


def test_beat_not_dispatching_fails() -> None:
    report = run(docker=make_docker(logs="celery beat v5.4\n"))

    item = check(report, "派发")
    assert item.status == "fail"
    assert "Sending due task" in item.criteria


def test_beat_dispatching_passes() -> None:
    item = check(run(), "派发")

    assert item.status == "pass"


# --------------------------------------------------------------------------- 连接账目


def test_connections_within_threshold_passes() -> None:
    item = check(run(sql_query=make_sql(used=43, limit=100)), "连接数")

    assert item.status == "pass"
    assert "43" in item.observed
    assert "43" in item.criteria or "38" in item.criteria  # 账目公式写进判据


def test_connections_over_threshold_fails() -> None:
    item = check(run(sql_query=make_sql(used=85, limit=100)), "连接数")

    assert item.status == "fail"
    assert "85" in item.observed


def test_connections_limit_below_requirement_fails() -> None:
    item = check(run(sql_query=make_sql(used=30, limit=60)), "连接数")

    assert item.status == "fail"
    assert "100" in item.observed or "100" in item.criteria


def test_connections_reports_budget_for_concurrency() -> None:
    item = check(run(sql_query=make_sql(used=43, limit=100), concurrency=4), "连接数")

    # 稳态账目 = 38 + 2×并发 + 1 ⇒ 并发 4 时为 47
    assert "47" in item.observed


def test_connections_sql_unavailable_is_skipped() -> None:
    item = check(run(psql_dsn="", sql_query=None), "连接数")

    assert item.status == "skipped"
    assert "DSN" in item.observed or "连接串" in item.observed


# --------------------------------------------------------------------------- 运行事件表


def test_runtime_events_empty_passes() -> None:
    item = check(run(sql_query=make_sql(events=(0, None, None))), "运行事件")

    assert item.status == "pass"
    assert "0" in item.observed


def test_runtime_events_with_data_within_retention_passes() -> None:
    earliest = (NOW - timedelta(days=3)).isoformat()
    latest = (NOW - timedelta(hours=1)).isoformat()

    item = check(run(sql_query=make_sql(events=(120, earliest, latest))), "运行事件")

    assert item.status == "pass"
    assert "120" in item.observed


def test_runtime_events_older_than_retention_fails() -> None:
    earliest = (NOW - timedelta(days=120)).isoformat()

    item = check(run(sql_query=make_sql(events=(9, earliest, earliest))), "运行事件")

    assert item.status == "fail"
    assert "保留期" in item.observed


def test_runtime_events_missing_table_is_skipped() -> None:
    report = run(
        sql_query=make_sql(
            events_error=RuntimeError('relation "workbench_runtime_events" does not exist')
        )
    )

    item = check(report, "运行事件")
    assert item.status == "skipped"
    assert "does not exist" in item.observed


def test_audit_log_readable_passes() -> None:
    item = check(run(sql_query=make_sql(audit=(16, "2026-09-15T14:09:00+00:00"))), "审计")

    assert item.status == "pass"
    assert "16" in item.observed
    assert "不删除" in item.criteria or "不轮转" in item.criteria


def test_audit_log_unreadable_fails() -> None:
    report = run(sql_query=make_sql(audit_error=RuntimeError("permission denied for table")))

    item = check(report, "审计")
    assert item.status == "fail"


# --------------------------------------------------------------------------- 环境不可用


def test_docker_unavailable_skips_all_docker_checks() -> None:
    report = run(docker=docker_unavailable)

    docker_checks = [
        item
        for item in report.checks
        if item.name.startswith("镜像 OCI")
        or item.name.startswith("容器日志上限")
        or "healthcheck" in item.name
        or item.name.startswith("beat")
    ]
    assert docker_checks
    assert all(item.status == "skipped" for item in docker_checks)
    assert all("FileNotFoundError" in item.observed for item in docker_checks)
    # 其它检查照常执行：不得因为 docker 缺失而静默整份跳过
    assert check(report, "应用健康检查").status == "pass"


def test_all_checks_skipped_yields_skipped_status() -> None:
    """全项核对不到（无镜像、无 docker、无 DSN、无 base-url）⇒ 整体 skipped，不得读成 pass。"""
    report = run(image="", base_url="", psql_dsn="", docker=docker_unavailable, sql_query=None)

    assert report.status == "skipped"
    assert all(item.status == "skipped" for item in report.checks)


def test_skipped_checks_must_explain_why() -> None:
    report = run(image="", psql_dsn="", sql_query=None)

    skipped = [item for item in report.checks if item.status == "skipped"]
    assert skipped, [item.name for item in report.checks]
    for item in skipped:
        assert item.observed.strip(), item.name


# --------------------------------------------------------------------------- 脱敏


def test_report_masks_dsn_credentials() -> None:
    report = run(
        sql_query=make_sql(
            events_error=RuntimeError(f"could not connect to {LEAKED_DSN}: FATAL: auth failed")
        )
    )

    text = report.to_text()
    assert "SUPERSECRET" not in text
    assert "workbench:SUPERSECRET" not in text
    assert "postgresql://***@" in text


def test_report_never_prints_dsn_or_password() -> None:
    text = run().to_text()

    assert "EXAMPLESECRET" not in text
    assert DSN not in text
    assert BASE_URL in text  # 主机本身可用于回传核对


# --------------------------------------------------------------------------- 护栏


def test_resolve_base_url_requires_https() -> None:
    with pytest.raises(ProbeConfigError) as excinfo:
        resolve_base_url("http://workbench.customer.internal")

    assert "https" in str(excinfo.value)


@pytest.mark.parametrize(
    "base_url",
    ["https://localhost:8000", "https://127.0.0.1", "https://0.0.0.0"],
)
def test_resolve_base_url_rejects_local_hosts(base_url: str) -> None:
    with pytest.raises(ProbeConfigError) as excinfo:
        resolve_base_url(base_url)

    assert "本地" in str(excinfo.value)


def test_resolve_base_url_requires_value() -> None:
    with pytest.raises(ProbeConfigError):
        resolve_base_url("")


def test_resolve_base_url_allows_explicit_overrides() -> None:
    assert resolve_base_url(
        "http://staging.example.internal", allow_insecure=True
    ) == "http://staging.example.internal"
    assert resolve_base_url(
        "https://localhost:8000", allow_local=True
    ) == "https://localhost:8000"


# --------------------------------------------------------------------------- main


def _argv(**overrides) -> list[str]:
    values = {
        "--base-url": BASE_URL,
        "--image": IMAGE,
        "--app-container": CONTAINERS["app"],
        "--worker-container": CONTAINERS["worker"],
        "--beat-container": CONTAINERS["beat"],
        "--psql-dsn": DSN,
    }
    values.update(overrides)
    argv: list[str] = []
    for key, value in values.items():
        if value is None:
            continue
        argv.extend([key, value])
    return argv


def _main(argv, **overrides) -> int:
    kwargs = {
        "docker": make_docker(),
        "http_get": make_http_get(),
        "sql_query": make_sql(),
    }
    kwargs.update(overrides)
    return main(argv, **kwargs)


def test_main_returns_zero_when_everything_passes(capsys) -> None:
    rc = _main(_argv())

    out = capsys.readouterr().out
    assert rc == 0
    assert "pass" in out
    assert "实测值" in out
    assert "判据" in out


def test_main_returns_one_when_a_check_fails(capsys) -> None:
    rc = _main(_argv(), http_get=make_http_get(status_code=500, payload=None))

    out = capsys.readouterr().out
    assert rc == 1
    assert "fail" in out


def test_main_returns_one_when_beat_not_dispatching(capsys) -> None:
    rc = _main(_argv(), docker=make_docker(logs="no scheduler output"))

    assert rc == 1
    assert "fail" in capsys.readouterr().out


def test_main_returns_two_when_base_url_missing(capsys) -> None:
    rc = _main(_argv(**{"--base-url": None}))

    assert rc == 2
    assert "配置错误" in capsys.readouterr().out


def test_main_returns_two_without_allow_insecure(capsys) -> None:
    rc = _main(_argv(**{"--base-url": "http://workbench.customer.internal"}))

    assert rc == 2
    assert "配置错误" in capsys.readouterr().out


def test_main_returns_two_without_allow_local(capsys) -> None:
    rc = _main(_argv(**{"--base-url": "https://127.0.0.1:8000"}))

    assert rc == 2
    assert "配置错误" in capsys.readouterr().out


def test_main_returns_two_on_bad_timeout(capsys) -> None:
    rc = _main(_argv(**{"--timeout": "0"}))

    assert rc == 2
    assert "配置错误" in capsys.readouterr().out


def test_main_returns_two_on_bad_retention_days(capsys) -> None:
    rc = _main(_argv(**{"--retention-days": "-1"}))

    assert rc == 2
    assert "配置错误" in capsys.readouterr().out


def test_main_allows_explicit_local_and_insecure(capsys) -> None:
    rc = _main(
        [
            "--base-url",
            "http://127.0.0.1:8000",
            "--allow-insecure",
            "--allow-local",
            "--image",
            IMAGE,
            "--psql-dsn",
            DSN,
        ]
    )

    assert rc == 0
    assert "pass" in capsys.readouterr().out


def test_main_reads_configuration_from_environment(monkeypatch, capsys) -> None:
    monkeypatch.setenv("WORKBENCH_APP_IMAGE", IMAGE)
    monkeypatch.setenv("WORKBENCH_ACCEPTANCE_BASE_URL", BASE_URL)
    monkeypatch.setenv("WORKBENCH_PROBE_PSQL_DSN", DSN)
    monkeypatch.setenv("WORKBENCH_WORKER_CONCURRENCY", "4")
    monkeypatch.setenv("WORKBENCH_RUNTIME_EVENTS_RETENTION_DAYS", "30")
    monkeypatch.setenv("WORKBENCH_PROBE_APP_CONTAINER", CONTAINERS["app"])
    monkeypatch.setenv("WORKBENCH_PROBE_WORKER_CONTAINER", CONTAINERS["worker"])
    monkeypatch.setenv("WORKBENCH_PROBE_BEAT_CONTAINER", CONTAINERS["beat"])

    rc = _main([])

    out = capsys.readouterr().out
    assert rc == 0
    assert "47" in out  # 并发 4 ⇒ 账目预算 38 + 8 + 1


def test_main_returns_two_on_unparsable_env_concurrency(monkeypatch, capsys) -> None:
    monkeypatch.setenv("WORKBENCH_ACCEPTANCE_BASE_URL", BASE_URL)
    monkeypatch.setenv("WORKBENCH_WORKER_CONCURRENCY", "not-a-number")

    rc = _main(["--image", IMAGE])

    assert rc == 2
    assert "配置错误" in capsys.readouterr().out
