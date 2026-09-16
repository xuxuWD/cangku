"""monitoring_probe 的离线单元测试。

全部注入假 docker runner / HTTP fetch / SQL query / 磁盘用量 / 时钟：**不连 PG、Redis、
docker，也不发起任何网络请求**（通知渠道一律用假 transport）。

覆盖：runbook「监控与告警」9 条规则各自的 ok 与 alert、边界值（磁盘 79.9% / 80% / 90%；
连接数恰为 80% 与超过；审计时间差恰等于与超过阈值）、不可用信号 ⇒ ``skipped``（不得静默
当作通过）、退出码 0/1/2、``--notify`` 未接入渠道时不发送且不崩、HTTP 目标护栏 fail-closed、
以及凭据脱敏（输出与通知载荷都不得出现 DSN 口令）。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from scripts.monitoring_probe import (
    SIGNALS,
    SIGNAL_APP_HEALTH,
    SIGNAL_AUDIT,
    SIGNAL_BEAT,
    SIGNAL_DEAD_LETTER,
    SIGNAL_DISK,
    SIGNAL_OUTBOX,
    SIGNAL_PG_CONNECTIONS,
    SIGNAL_WORKER_HEALTH,
    SIGNAL_WORKER_RSS,
    THRESHOLD_ENV,
    MonitorConfigError,
    main,
    parse_threshold_overrides,
    run_probe,
)

CLOCK = datetime(2026, 9, 16, 12, 0, 0, tzinfo=UTC)
DSN = "postgresql://monitor:monitor-secret@pg.example.com:5432/workbench"
DSN_PASSWORD = "monitor-secret"
HEALTH_URL = "https://workbench.example.com"
ALERT_URL = "https://alert.example.com/hook"


def fixed_now() -> datetime:
    return CLOCK


# --------------------------------------------------------------------------- 假实现


class FakeResponse:
    """同时满足探针读取（status_code/json）与通知渠道（raise_for_status）的假响应。"""

    def __init__(self, status_code: int = 200, payload: object = None) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> object:
        return self._payload

    def raise_for_status(self) -> None:
        if not 200 <= self.status_code < 300:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeRunner:
    """按 docker 子命令分派的假 runner：返回 ``(退出码, 输出)``。"""

    def __init__(
        self,
        *,
        health: str = "healthy",
        beat_log: str = "",
        rss: str = "206.3MiB / 1GiB",
        code: int = 0,
        raise_error: bool = False,
    ) -> None:
        self.health = health
        self.beat_log = beat_log
        self.rss = rss
        self.code = code
        self.raise_error = raise_error
        self.calls: list[list[str]] = []

    def __call__(self, cmd):
        self.calls.append(list(cmd))
        if self.raise_error:
            raise FileNotFoundError("docker 不在 PATH")
        joined = " ".join(cmd)
        if "inspect" in joined and "State.Health.Status" in joined:
            return self.code, self.health
        if "logs" in joined:
            return self.code, self.beat_log
        if "stats" in joined:
            return self.code, self.rss
        raise AssertionError(f"未预期的 docker 命令：{joined}")


class FakeFetch:
    """假 HTTP GET：返回 ``(状态码, 载荷)``，或抛出注入的异常（模拟超时）。"""

    def __init__(self, *, status: int = 200, payload: object = None, error=None) -> None:
        self.status = status
        self._payload = {"status": "ok"} if payload is None else payload
        self.error = error
        self.urls: list[str] = []

    def __call__(self, url: str, *, timeout: float = 10.0):
        self.urls.append(url)
        if self.error is not None:
            raise self.error
        return self.status, self._payload


class FakeQuery:
    """假 SQL 查询：按语句关键字返回固定行；可注入异常模拟数据库不可用。"""

    def __init__(
        self,
        *,
        outbox: int = 0,
        dead_letters: int = 0,
        unnotified: int = 0,
        audit_at: datetime | None = None,
        audit_no_rows: bool = False,
        connections: int = 10,
        max_connections: int = 100,
        error: BaseException | None = None,
    ) -> None:
        self.outbox = outbox
        self.dead_letters = dead_letters
        self.unnotified = unnotified
        self.audit_at = CLOCK - timedelta(seconds=60) if audit_at is None else audit_at
        self.audit_no_rows = audit_no_rows
        self.connections = connections
        self.max_connections = max_connections
        self.error = error
        self.statements: list[str] = []

    def __call__(self, statement: str):
        self.statements.append(statement)
        if self.error is not None:
            raise self.error
        if "workbench_event_outbox" in statement:
            return [(self.outbox,)]
        if "workbench_dead_letters" in statement:
            return [(self.dead_letters, self.unnotified)]
        if "workbench_audit_log" in statement:
            return [(None,)] if self.audit_no_rows else [(self.audit_at,)]
        if "pg_stat_activity" in statement:
            return [(self.connections, self.max_connections)]
        raise AssertionError(f"未预期的 SQL：{statement}")


class FakeTransport:
    """假通知传输层（签名与 ``httpx.post`` 一致），记录载荷供脱敏断言。"""

    def __init__(self, status_code: int = 200) -> None:
        self.status_code = status_code
        self.calls: list[dict[str, object]] = []

    def __call__(self, url: str, *, json: object = None, timeout: float = 5.0):
        self.calls.append({"url": url, "json": json, "timeout": timeout})
        return FakeResponse(self.status_code)


def fake_disk(used_percent: float, *, total: int = 1000):
    used = int(round(total * used_percent / 100))

    def usage(path: str):
        return (total, used, total - used)

    return usage


def dispatch_log(seconds_ago: float) -> str:
    stamp = (CLOCK - timedelta(seconds=seconds_ago)).isoformat().replace("+00:00", "Z")
    return f"{stamp} [INFO/MainProcess] beat: Sending due task outbox-publisher"


def ok_runner(**overrides) -> FakeRunner:
    values = {"health": "healthy", "beat_log": dispatch_log(5.0), "rss": "206.3MiB / 1GiB"}
    values.update(overrides)
    return FakeRunner(**values)


def base_config(**overrides) -> dict[str, object]:
    config: dict[str, object] = {
        "app_url": HEALTH_URL,
        "database_url": DSN,
        "worker_container": "workbench-worker",
        "beat_container": "workbench-beat",
        "disk_path": "/",
        "alert_webhook_url": "",
        "alert_webhook_timeout_seconds": "5",
        "thresholds": {},
    }
    config.update(overrides)
    return config


def make_report(*, config=None, runner=None, fetch=None, query=None, disk=None, **kwargs):
    return run_probe(
        base_config() if config is None else config,
        runner=ok_runner() if runner is None else runner,
        fetch=FakeFetch() if fetch is None else fetch,
        query=FakeQuery() if query is None else query,
        disk_usage=fake_disk(50.0) if disk is None else disk,
        now=fixed_now,
        **kwargs,
    )


def check_of(report, signal: str):
    for check in report.checks:
        if check.signal == signal:
            return check
    raise AssertionError(f"未找到规则：{signal}")


def status_of(report, signal: str) -> str:
    return check_of(report, signal).status


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """隔离宿主环境变量，避免本机配置影响断言。"""
    names = [
        "WORKBENCH_DATABASE_URL",
        "WORKBENCH_MONITOR_APP_URL",
        "WORKBENCH_MONITOR_BEAT_CONTAINER",
        "WORKBENCH_MONITOR_WORKER_CONTAINER",
        "WORKBENCH_MONITOR_DISK_PATH",
        "WORKBENCH_ALERT_WEBHOOK_URL",
        "WORKBENCH_ALERT_WEBHOOK_TIMEOUT_SECONDS",
        *THRESHOLD_ENV.values(),
    ]
    for name in names:
        monkeypatch.delenv(name, raising=False)


# --------------------------------------------------------------------------- 基线：9 条规则


def test_baseline_reports_all_nine_rules_in_runbook_order() -> None:
    report = make_report()

    assert [check.signal for check in report.checks] == list(SIGNALS)
    assert len(report.checks) == 9
    assert report.status == "ok"
    assert {check.status for check in report.checks} == {"ok"}


def test_report_line_carries_signal_value_threshold_and_basis() -> None:
    text = make_report().to_text()

    for line in text.splitlines():
        if line.startswith("[ok] ") or line.startswith("[alert] "):
            assert "实测 " in line
            assert "阈值 " in line
            assert "依据 " in line
    assert "未写库" in text


# --------------------------------------------------------------------------- 规则 1：beat 派发


def test_beat_ok_when_dispatch_recent() -> None:
    report = make_report(runner=ok_runner(beat_log=dispatch_log(5.0)))

    assert status_of(report, SIGNAL_BEAT) == "ok"


def test_beat_ok_just_below_threshold() -> None:
    report = make_report(runner=ok_runner(beat_log=dispatch_log(299.0)))

    assert status_of(report, SIGNAL_BEAT) == "ok"


def test_beat_alerts_when_exactly_at_threshold() -> None:
    """边界：断档恰为 300s（runbook 第 67 行「≥5 分钟」）⇒ 告警。"""
    report = make_report(runner=ok_runner(beat_log=dispatch_log(300.0)))

    assert status_of(report, SIGNAL_BEAT) == "alert"


def test_beat_alerts_when_beyond_threshold() -> None:
    report = make_report(runner=ok_runner(beat_log=dispatch_log(900.0)))

    assert status_of(report, SIGNAL_BEAT) == "alert"


def test_beat_alerts_when_window_has_no_dispatch_line() -> None:
    report = make_report(runner=ok_runner(beat_log="2026-09-16T11:59:00Z [INFO] 无派发关键字\n"))

    assert status_of(report, SIGNAL_BEAT) == "alert"


def test_beat_skipped_when_docker_missing() -> None:
    report = make_report(runner=FakeRunner(raise_error=True))

    check = check_of(report, SIGNAL_BEAT)
    assert check.status == "skipped"
    assert "docker" in check.value


def test_beat_skipped_when_container_absent() -> None:
    report = make_report(runner=FakeRunner(code=1, beat_log=""))

    check = check_of(report, SIGNAL_BEAT)
    assert check.status == "skipped"
    assert "退出码 1" in check.value


def test_beat_skipped_reports_missing_container_reason() -> None:
    runner = FakeRunner(code=1, beat_log="Error: No such container: workbench-beat\n")

    check = check_of(make_report(runner=runner), SIGNAL_BEAT)

    assert check.status == "skipped"
    assert "不存在" in check.value


# --------------------------------------------------------------------------- 规则 2：worker 健康


def test_worker_health_ok_when_healthy() -> None:
    assert status_of(make_report(runner=ok_runner(health="healthy")), SIGNAL_WORKER_HEALTH) == "ok"


def test_worker_health_alerts_when_unhealthy() -> None:
    report = make_report(runner=ok_runner(health="unhealthy"))

    assert status_of(report, SIGNAL_WORKER_HEALTH) == "alert"


def test_worker_health_skipped_when_healthcheck_absent() -> None:
    report = make_report(runner=ok_runner(health=""))

    check = check_of(report, SIGNAL_WORKER_HEALTH)
    assert check.status == "skipped"
    assert "healthcheck" in check.value


def test_worker_health_skipped_when_inspect_unavailable() -> None:
    report = make_report(runner=FakeRunner(code=1))

    assert status_of(report, SIGNAL_WORKER_HEALTH) == "skipped"


def test_worker_health_skipped_when_container_lacks_healthcheck() -> None:
    """本机实测：无 healthcheck 时 docker inspect 直接退出 1（不是输出 <no value>）。"""
    runner = FakeRunner(
        code=1,
        health=(
            'template parsing error: template: :1:8: executing "" at <.State.Health.Status>: '
            'map has no entry for key "Health"'
        ),
    )

    check = check_of(make_report(runner=runner), SIGNAL_WORKER_HEALTH)

    assert check.status == "skipped"
    assert "未配置 healthcheck" in check.value


def test_worker_health_skipped_when_container_absent() -> None:
    runner = FakeRunner(code=1, health="error: no such object: workbench-worker")

    check = check_of(make_report(runner=runner), SIGNAL_WORKER_HEALTH)

    assert check.status == "skipped"
    assert "不存在" in check.value


# --------------------------------------------------------------------------- 规则 3：app 健康


def test_app_health_ok_on_200() -> None:
    assert status_of(make_report(fetch=FakeFetch(status=200)), SIGNAL_APP_HEALTH) == "ok"


def test_app_health_alerts_on_non_200() -> None:
    report = make_report(fetch=FakeFetch(status=503))

    assert status_of(report, SIGNAL_APP_HEALTH) == "alert"


def test_app_health_alerts_on_timeout() -> None:
    report = make_report(fetch=FakeFetch(error=TimeoutError("timed out")))

    check = check_of(report, SIGNAL_APP_HEALTH)
    assert check.status == "alert"
    assert "TimeoutError" in check.value


def test_app_health_skipped_without_url() -> None:
    report = make_report(config=base_config(app_url=""))

    check = check_of(report, SIGNAL_APP_HEALTH)
    assert check.status == "skipped"
    assert "WORKBENCH_MONITOR_APP_URL" in check.value


def test_app_health_uses_runbook_path() -> None:
    fetch = FakeFetch()
    make_report(fetch=fetch)

    assert fetch.urls == [f"{HEALTH_URL}/api/v1/health"]


# --------------------------------------------------------------------------- 规则 4：Outbox 积压


def test_outbox_ok_when_zero() -> None:
    assert status_of(make_report(query=FakeQuery(outbox=0)), SIGNAL_OUTBOX) == "ok"


def test_outbox_alerts_when_non_zero() -> None:
    report = make_report(query=FakeQuery(outbox=7))

    check = check_of(report, SIGNAL_OUTBOX)
    assert check.status == "alert"
    assert "7" in check.value
    assert "连续观测" in check.value  # 单次运行必须注明需连续观测


def test_outbox_skipped_when_database_unavailable() -> None:
    report = make_report(query=FakeQuery(error=RuntimeError("connection refused")))

    assert status_of(report, SIGNAL_OUTBOX) == "skipped"


def test_sql_checks_skipped_without_database_url() -> None:
    report = run_probe(
        base_config(database_url=""),
        runner=ok_runner(),
        fetch=FakeFetch(),
        disk_usage=fake_disk(50.0),
        now=fixed_now,
    )

    for signal in (SIGNAL_OUTBOX, SIGNAL_DEAD_LETTER, SIGNAL_AUDIT, SIGNAL_PG_CONNECTIONS):
        check = check_of(report, signal)
        assert check.status == "skipped"
        assert "WORKBENCH_DATABASE_URL" in check.value


# --------------------------------------------------------------------------- 规则 5：死信新增


def test_dead_letters_ok_when_none_pending() -> None:
    assert status_of(make_report(query=FakeQuery(dead_letters=0)), SIGNAL_DEAD_LETTER) == "ok"


def test_dead_letters_alerts_when_unreplayed_rows_exist() -> None:
    report = make_report(query=FakeQuery(dead_letters=2, unnotified=1))

    check = check_of(report, SIGNAL_DEAD_LETTER)
    assert check.status == "alert"
    assert "2" in check.value
    assert "未通知" in check.value


# --------------------------------------------------------------------------- 规则 6：审计推进


def test_audit_ok_when_recent() -> None:
    query = FakeQuery(audit_at=CLOCK - timedelta(seconds=60))

    assert status_of(make_report(query=query), SIGNAL_AUDIT) == "ok"


def test_audit_alerts_when_exactly_at_threshold() -> None:
    """边界：时间差恰等于阈值 ⇒ 告警。"""
    query = FakeQuery(audit_at=CLOCK - timedelta(seconds=3600))

    assert status_of(make_report(query=query), SIGNAL_AUDIT) == "alert"


def test_audit_alerts_when_beyond_threshold() -> None:
    query = FakeQuery(audit_at=CLOCK - timedelta(seconds=7200))

    assert status_of(make_report(query=query), SIGNAL_AUDIT) == "alert"


def test_audit_alerts_when_no_rows() -> None:
    report = make_report(query=FakeQuery(audit_no_rows=True))

    check = check_of(report, SIGNAL_AUDIT)
    assert check.status == "alert"
    assert "无审计记录" in check.value


def test_audit_skipped_when_database_unavailable() -> None:
    report = make_report(query=FakeQuery(error=RuntimeError("db down")))

    assert status_of(report, SIGNAL_AUDIT) == "skipped"


# --------------------------------------------------------------------------- 规则 7：宿主磁盘


def test_disk_ok_below_warning_threshold() -> None:
    report = make_report(disk=fake_disk(79.9))

    assert status_of(report, SIGNAL_DISK) == "ok"


def test_disk_alerts_at_warning_threshold() -> None:
    """边界：恰好 80% ⇒ 预警（runbook 第 73 行「≥80% 预警」）。"""
    report = make_report(disk=fake_disk(80.0))

    check = check_of(report, SIGNAL_DISK)
    assert check.status == "alert"
    assert "预警" in check.value


def test_disk_alerts_severely_at_critical_threshold() -> None:
    """边界：恰好 90% ⇒ 严重（runbook 第 73 行「≥90% 严重」）。"""
    report = make_report(disk=fake_disk(90.0))

    check = check_of(report, SIGNAL_DISK)
    assert check.status == "alert"
    assert "严重" in check.value


# --------------------------------------------------------------------------- 规则 8：连接数


def test_pg_connections_ok_at_exactly_eighty_percent() -> None:
    """边界：恰为 80%（80/100）⇒ 不告警（runbook 第 74 行是「>80%」）。"""
    report = make_report(query=FakeQuery(connections=80, max_connections=100))

    assert status_of(report, SIGNAL_PG_CONNECTIONS) == "ok"


def test_pg_connections_ok_below_eighty_percent() -> None:
    report = make_report(query=FakeQuery(connections=79, max_connections=100))

    assert status_of(report, SIGNAL_PG_CONNECTIONS) == "ok"


def test_pg_connections_alerts_beyond_eighty_percent() -> None:
    report = make_report(query=FakeQuery(connections=81, max_connections=100))

    check = check_of(report, SIGNAL_PG_CONNECTIONS)
    assert check.status == "alert"
    assert "81/100" in check.value


def test_pg_connections_skipped_when_database_unavailable() -> None:
    report = make_report(query=FakeQuery(error=RuntimeError("db down")))

    assert status_of(report, SIGNAL_PG_CONNECTIONS) == "skipped"


# --------------------------------------------------------------------------- 规则 9：worker 资源


def test_worker_rss_ok_below_threshold() -> None:
    assert status_of(make_report(runner=ok_runner(rss="206.3MiB / 1GiB")), SIGNAL_WORKER_RSS) == "ok"


def test_worker_rss_ok_at_exactly_threshold() -> None:
    """边界：恰好 512MiB ⇒ 不告警（runbook 第 75 行是「>512MiB」）。"""
    report = make_report(runner=ok_runner(rss="512MiB / 1GiB"))

    assert status_of(report, SIGNAL_WORKER_RSS) == "ok"


def test_worker_rss_alerts_just_above_threshold() -> None:
    report = make_report(runner=ok_runner(rss="512.1MiB / 1GiB"))

    assert status_of(report, SIGNAL_WORKER_RSS) == "alert"


def test_worker_rss_alerts_above_threshold_in_gib() -> None:
    report = make_report(runner=ok_runner(rss="1.5GiB / 4GiB"))

    check = check_of(report, SIGNAL_WORKER_RSS)
    assert check.status == "alert"
    assert "1536" in check.value


def test_worker_rss_skipped_when_stats_output_unparseable() -> None:
    report = make_report(runner=ok_runner(rss=""))

    assert status_of(report, SIGNAL_WORKER_RSS) == "skipped"


def test_worker_rss_skipped_when_docker_missing() -> None:
    report = make_report(runner=FakeRunner(raise_error=True))

    assert status_of(report, SIGNAL_WORKER_RSS) == "skipped"


# --------------------------------------------------------------------------- 脱敏


def test_report_redacts_credentials_in_failure_text() -> None:
    query = FakeQuery(error=RuntimeError("connect failed: postgresql://user:pass@pg.internal/db"))

    report = make_report(query=query)
    text = report.to_text()

    assert "user:pass" not in text
    assert "postgresql://***@pg.internal/db" in text
    assert DSN_PASSWORD not in text


def test_report_never_prints_database_password() -> None:
    text = make_report().to_text()

    assert DSN_PASSWORD not in text
    assert "postgresql://***@pg.example.com:5432/workbench" in text


# --------------------------------------------------------------------------- 阈值覆盖


def test_parse_threshold_overrides_accepts_known_names() -> None:
    assert parse_threshold_overrides(["disk_warn_percent=70", "worker_rss_mib=256"]) == {
        "disk_warn_percent": 70.0,
        "worker_rss_mib": 256.0,
    }


@pytest.mark.parametrize("item", ["unknown_name=1", "disk_warn_percent", "disk_warn_percent=abc", "=5"])
def test_parse_threshold_overrides_rejects_bad_input(item: str) -> None:
    with pytest.raises(MonitorConfigError):
        parse_threshold_overrides([item])


def test_threshold_override_changes_verdict() -> None:
    report = make_report(
        config=base_config(thresholds={"worker_rss_mib": 100}),
        runner=ok_runner(rss="206.3MiB / 1GiB"),
    )

    assert status_of(report, SIGNAL_WORKER_RSS) == "alert"


def test_disk_threshold_override_changes_verdict() -> None:
    report = make_report(
        config=base_config(thresholds={"disk_warn_percent": 40}),
        disk=fake_disk(50.0),
    )

    assert status_of(report, SIGNAL_DISK) == "alert"


# --------------------------------------------------------------------------- main：退出码与护栏


_UNSET: object = object()


def run_main(
    argv, *, runner=_UNSET, fetch=_UNSET, query=_UNSET, disk=_UNSET, transport=None
):
    """默认注入「一切正常」的假实现；显式传 ``None`` 表示**不注入**（走真实实现的分支）。"""
    return main(
        argv,
        runner=ok_runner() if runner is _UNSET else runner,
        fetch=FakeFetch() if fetch is _UNSET else fetch,
        query=FakeQuery() if query is _UNSET else query,
        disk_usage=fake_disk(50.0) if disk is _UNSET else disk,
        now=fixed_now,
        transport=transport,
    )


def test_main_returns_zero_when_all_ok(capsys) -> None:
    rc = run_main(["--app-url", HEALTH_URL])

    assert rc == 0
    assert "ok" in capsys.readouterr().out


def test_main_returns_one_when_alert(capsys) -> None:
    rc = run_main(["--app-url", HEALTH_URL], query=FakeQuery(outbox=3))

    assert rc == 1
    assert "alert" in capsys.readouterr().out


def test_main_returns_zero_when_checks_are_skipped(capsys) -> None:
    """全部信号不可用（docker 缺失 + 未配数据库与应用地址）⇒ 不告警，退出码 0。"""
    rc = run_main(
        [],
        runner=FakeRunner(raise_error=True),
        fetch=FakeFetch(),
        query=None,
    )

    assert rc == 0


def test_main_returns_two_on_unknown_threshold(capsys) -> None:
    rc = run_main(["--app-url", HEALTH_URL, "--threshold", "nope=1"])

    assert rc == 2
    assert "配置错误" in capsys.readouterr().out


def test_main_returns_two_on_non_numeric_threshold(capsys) -> None:
    rc = run_main(["--app-url", HEALTH_URL, "--threshold", "disk_warn_percent=abc"])

    assert rc == 2
    assert "配置错误" in capsys.readouterr().out


def test_main_returns_two_on_insecure_app_url(capsys) -> None:
    rc = run_main(["--app-url", "http://workbench.example.com"])

    assert rc == 2
    assert "配置错误" in capsys.readouterr().out


def test_main_returns_two_on_local_app_url(capsys) -> None:
    rc = run_main(["--app-url", "https://127.0.0.1:8000"])

    assert rc == 2
    assert "配置错误" in capsys.readouterr().out


def test_main_returns_two_on_local_http_app_url(capsys) -> None:
    rc = run_main(["--app-url", "http://localhost:8000"])

    assert rc == 2
    assert "配置错误" in capsys.readouterr().out


def test_main_allows_local_insecure_when_explicitly_permitted(capsys) -> None:
    rc = run_main(
        ["--app-url", "http://127.0.0.1:8000", "--allow-local", "--allow-insecure"]
    )

    assert rc == 0


def test_main_returns_two_on_non_positive_timeout(capsys) -> None:
    rc = run_main(["--app-url", HEALTH_URL, "--timeout", "0"])

    assert rc == 2
    assert "配置错误" in capsys.readouterr().out


def test_main_example_returns_two(capsys) -> None:
    rc = main(["--example"])

    assert rc == 2
    assert "配置错误" in capsys.readouterr().out


# --------------------------------------------------------------------------- main：通知（可选）


def test_notify_without_channel_does_not_send_and_does_not_fail(capsys) -> None:
    transport = FakeTransport()

    rc = run_main(["--app-url", HEALTH_URL, "--notify"], transport=transport)

    assert rc == 0
    assert "未接入渠道" in capsys.readouterr().out
    assert transport.calls == []


def test_notify_sends_redacted_summary_when_alerts_exist(capsys, monkeypatch) -> None:
    monkeypatch.setenv("WORKBENCH_ALERT_WEBHOOK_URL", ALERT_URL)
    transport = FakeTransport()

    rc = run_main(
        ["--app-url", HEALTH_URL, "--notify"],
        query=FakeQuery(outbox=4),
        disk=fake_disk(91.0),
        transport=transport,
    )

    out = capsys.readouterr().out
    assert rc == 1
    assert len(transport.calls) == 1
    payload = transport.calls[0]["json"]
    dumped = json.dumps(payload, ensure_ascii=False)
    assert payload["kind"] == "monitoring_alert"
    assert payload["status"] == "alert"
    assert len(payload["alerts"]) == 2
    assert DSN_PASSWORD not in dumped
    assert "postgresql://" not in dumped  # 载荷只带脱敏后的结论，不带 DSN
    assert DSN_PASSWORD not in out
    assert "已发送" in out


def test_notify_does_not_send_when_no_alert(capsys, monkeypatch) -> None:
    monkeypatch.setenv("WORKBENCH_ALERT_WEBHOOK_URL", ALERT_URL)
    transport = FakeTransport()

    rc = run_main(["--app-url", HEALTH_URL, "--notify"], transport=transport)

    assert rc == 0
    assert transport.calls == []
    assert "无告警" in capsys.readouterr().out


def test_notify_send_failure_does_not_mask_verdict(capsys, monkeypatch) -> None:
    monkeypatch.setenv("WORKBENCH_ALERT_WEBHOOK_URL", ALERT_URL)

    class BrokenChannel:
        def __call__(self, *args, **kwargs):
            raise RuntimeError("webhook 502 for https://user:pass@alert.example.com/hook")

    rc = run_main(
        ["--app-url", HEALTH_URL, "--notify"],
        query=FakeQuery(outbox=4),
        transport=BrokenChannel(),
    )

    out = capsys.readouterr().out
    assert rc == 1  # 告警结论不被通知失败掩盖
    assert "user:pass" not in out
