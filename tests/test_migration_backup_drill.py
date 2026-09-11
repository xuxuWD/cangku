"""migration_backup_drill 测试：DSN 脱敏、护栏 fail-closed、dry-run 不调 subprocess。

所有阶段均使用注入的 which/runner/transport，测试本身不安装 PostgreSQL、不发起任何真实请求。
"""

from __future__ import annotations

import types

import pytest

import scripts.migration_backup_drill as drill
from scripts.migration_backup_drill import (
    DrillConfigError,
    DrillReport,
    check_dsn,
    main,
    mask_dsn,
    run_phase,
)

DSN = "postgresql+psycopg://workbench:pg-super-secret@pg.staging.internal:5432/workbench"
RESTORE_DSN = (
    "postgresql+psycopg://workbench:restore-secret@restore.staging.internal:5432/workbench_restore"
)
PASSWORD = "pg-super-secret"
MIGRATIONS = ["001_initial", "002_event_outbox"]


def valid_config() -> dict[str, object]:
    return {
        "dsn": DSN,
        "restore_dsn": RESTORE_DSN,
        "environment": "staging",
        "applied_migrations": list(MIGRATIONS),
        "expected_migrations": list(MIGRATIONS),
        "backup_key": "k" * 32,
        "base_url": "https://workbench.staging.example",
        "token": "admin-token-super-secret-value",
    }


class RecordingRunner:
    def __init__(self, returncode: int = 0) -> None:
        self.calls: list[list[str]] = []
        self.returncode = returncode

    def __call__(self, cmd):
        self.calls.append(list(cmd))
        return self.returncode


class FakeResponse:
    def __init__(self, *, status_code: int = 200, payload=None) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def which_ok(name: str) -> str:
    return f"/usr/bin/{name}"


def find_step(report: DrillReport, name: str) -> str:
    for step in report.steps:
        if step.name == name:
            return step.status
    raise AssertionError(f"未找到步骤：{name}")


# --- DSN 脱敏（硬要求）--------------------------------------------------------


def test_mask_dsn_replaces_password_with_asterisks() -> None:
    masked = mask_dsn(DSN)

    assert PASSWORD not in masked
    assert "workbench:***@pg.staging.internal:5432/workbench" in masked


def test_mask_dsn_keeps_passwordless_dsn_unchanged() -> None:
    plain = "postgresql+psycopg://workbench@pg.staging.internal:5432/workbench"

    assert mask_dsn(plain) == plain


# --- 护栏 fail-closed ---------------------------------------------------------


def test_check_dsn_rejects_non_psycopg_scheme() -> None:
    for bad in ("", "postgresql://workbench:pw@pg.internal:5432/db", "sqlite:///./dev.db"):
        with pytest.raises(DrillConfigError):
            check_dsn(bad, allow_local=False, confirm_production=False, environment="staging")


def test_check_dsn_rejects_local_host_without_allow_local() -> None:
    for host in ("localhost", "127.0.0.1"):
        dsn = f"postgresql+psycopg://workbench:pw@{host}:5432/workbench"
        with pytest.raises(DrillConfigError):
            check_dsn(dsn, allow_local=False, confirm_production=False, environment="staging")


def test_check_dsn_allows_local_when_explicit() -> None:
    dsn = "postgresql+psycopg://workbench:pw@localhost:5432/workbench"

    check_dsn(dsn, allow_local=True, confirm_production=False, environment="staging")


def test_check_dsn_requires_confirmation_for_production() -> None:
    with pytest.raises(DrillConfigError):
        check_dsn(DSN, allow_local=False, confirm_production=False, environment="production")

    check_dsn(DSN, allow_local=False, confirm_production=True, environment="production")


def test_guard_error_message_is_masked() -> None:
    dsn = "postgresql+psycopg://workbench:guard-secret@pghost:5432/workbench"
    with pytest.raises(DrillConfigError) as excinfo:
        check_dsn(dsn, allow_local=True, confirm_production=False, environment="production")

    assert "guard-secret" not in str(excinfo.value)
    assert "***" in str(excinfo.value)


# --- phase list ---------------------------------------------------------------


def test_list_phase_reports_consistent_migrations() -> None:
    report = run_phase("list", valid_config())

    assert report.status == "pass"
    assert find_step(report, "迁移清单一致") == "pass"
    assert PASSWORD not in report.to_text()
    assert "***" in report.to_text()


def test_list_phase_reports_missing_and_extra() -> None:
    config = valid_config()
    config["applied_migrations"] = ["001_initial", "999_extra"]
    config["expected_migrations"] = ["001_initial", "002_event_outbox"]

    report = run_phase("list", config)
    message = next(s.message for s in report.steps if s.name == "迁移清单一致")

    assert report.status == "fail"
    assert "缺少 1" in message and "多出 1" in message


# --- phase backup -------------------------------------------------------------


def test_backup_dry_run_does_not_call_runner() -> None:
    runner = RecordingRunner()
    report = run_phase("backup", valid_config(), runner=runner, which=which_ok)
    text = report.to_text()

    assert runner.calls == []
    assert "dry-run" in text
    assert "--format=custom" in text
    assert PASSWORD not in text
    assert "***" in text


def test_backup_dry_run_never_calls_subprocess(monkeypatch) -> None:
    calls: list[object] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(drill.subprocess, "run", fake_run)
    run_phase("backup", valid_config(), which=which_ok)

    assert calls == []


def test_backup_execute_calls_runner_once_with_real_dsn() -> None:
    runner = RecordingRunner(returncode=0)
    report = run_phase("backup", valid_config(), execute=True, runner=runner, which=which_ok)

    assert len(runner.calls) == 1
    assert report.status == "pass"
    # 真正执行时把完整 DSN 交给 pg_dump（内部参数），但输出绝不回显口令。
    assert any(PASSWORD in part for part in runner.calls[0])
    text = report.to_text()
    assert PASSWORD not in text
    assert "***" in text


def test_backup_execute_failure_is_reported() -> None:
    runner = RecordingRunner(returncode=1)
    report = run_phase("backup", valid_config(), execute=True, runner=runner, which=which_ok)

    assert report.status == "fail"
    assert find_step(report, "备份命令（脱敏）") == "fail" or find_step(report, "执行结果") == "fail"


def test_backup_without_pg_dump_fails_and_explains() -> None:
    report = run_phase("backup", valid_config(), which=lambda _name: None)

    assert report.status == "fail"
    assert find_step(report, "pg_dump 可用性") == "fail"
    assert "pg_dump" in report.to_text()


# --- phase restore ------------------------------------------------------------


def test_restore_without_isolated_target_is_skipped() -> None:
    config = valid_config()
    config["restore_dsn"] = ""

    report = run_phase("restore", config, which=which_ok)

    assert report.status == "skipped"
    assert find_step(report, "隔离恢复库") == "skipped"


def test_restore_dry_run_builds_masked_command() -> None:
    runner = RecordingRunner()
    report = run_phase("restore", valid_config(), runner=runner, which=which_ok)
    text = report.to_text()

    assert runner.calls == []
    assert "pg_restore" in text
    assert "dry-run" in text
    assert "restore-secret" not in text
    assert "***" in text
    assert find_step(report, "恢复后一致性核对") in {"pass", "skipped"}


# --- phase verify -------------------------------------------------------------


def test_verify_offline_reports_migration_consistency() -> None:
    report = run_phase("verify", valid_config(), offline=True)

    assert find_step(report, "迁移清单一致") == "pass"
    assert find_step(report, "应用健康检查") == "skipped"


def test_verify_online_health_and_read_smoke() -> None:
    def transport(*args, **kwargs):
        url = args[1] if len(args) > 1 else kwargs.get("url", "")
        if url.endswith("/api/v1/health"):
            return FakeResponse(payload={"status": "ok"})
        return FakeResponse(payload=[{"event_id": "a", "notified_at": None}])

    report = run_phase("verify", valid_config(), transport=transport, offline=False)

    assert report.status == "pass"
    assert find_step(report, "应用健康检查") == "pass"
    assert find_step(report, "读取冒烟") == "pass"


# --- allow-local 显著标注 -----------------------------------------------------


def test_allow_local_is_prominently_labeled() -> None:
    config = valid_config()
    config["dsn"] = "postgresql+psycopg://workbench:local-secret@localhost:5432/workbench"

    report = run_phase("list", config, allow_local=True)
    text = report.to_text()

    assert report.status == "pass"
    assert "已显式 --allow-local" in text
    assert "local-secret" not in text


# --- main() 退出码 ------------------------------------------------------------


def test_main_example_refuses_and_exits_two(capsys) -> None:
    assert main(["--example"]) == 2
    output = capsys.readouterr().out
    assert "***" in output
    assert "EXAMPLE_SECRET" not in output


def test_main_list_complete_config_exits_zero(monkeypatch, capsys) -> None:
    from pathlib import Path

    expected = sorted(
        path.stem for path in (Path(__file__).resolve().parents[1] / "migrations").glob("*.sql")
    )
    monkeypatch.setenv("WORKBENCH_DATABASE_URL", DSN)
    monkeypatch.setenv("WORKBENCH_ENV", "staging")
    monkeypatch.setenv("WORKBENCH_APPLIED_MIGRATIONS", ",".join(expected))

    assert main(["--phase", "list"]) == 0
    output = capsys.readouterr().out
    assert PASSWORD not in output
    assert "***" in output
