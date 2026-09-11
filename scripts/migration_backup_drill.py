"""真实 PostgreSQL 商业化迁移 / 备份恢复演练的可机械执行步骤（门禁项验收前置）。

用途
    把「真实 PostgreSQL 商业化迁移、备份/恢复演练」拆成可独立运行、可复审的机械步骤：

    - ``--phase list``    ：核对 ``migrations/*.sql`` 与 ``WORKBENCH_APPLIED_MIGRATIONS`` 的差异（一致/缺/多）。
    - ``--phase backup``  ：构造 ``pg_dump``（自定义格式）命令，**默认只打印不执行**；``--execute`` 才真正调用。
    - ``--phase restore`` ：在**隔离库**上构造 ``pg_restore`` 命令 + 迁移后一致性核对步骤；同样默认 dry-run。
    - ``--phase verify``  ：迁移后冒烟（健康检查 + 迁移清单一致性；如可用则加一次读取）。

安全护栏（fail-closed，先于任何动作）
    - ``WORKBENCH_DATABASE_URL`` / ``WORKBENCH_RESTORE_DATABASE_URL`` 必须是 ``postgresql+psycopg://``；
    - 不得指向 ``localhost`` / ``127.0.0.1`` / ``sqlite``，除非显式 ``--allow-local``（该开关会在输出里显著标注）；
    - ``WORKBENCH_ENV`` 为 ``production`` 时必须显式 ``--confirm-production``。

DSN 脱敏（硬要求）
    任何输出——包括报错信息、命令回显——都把口令替换为 ``***``；命令真正执行时才把完整 DSN 交给
    ``pg_dump``/``pg_restore``（生产建议改用 ``PGPASSWORD``，避免口令出现在进程参数中）。

已知前置/缺口（据实输出 ``skipped``，绝不臆造）
    - ``backup`` / ``restore`` 依赖部署机安装 ``pg_dump`` / ``pg_restore``；缺失时输出 ``fail`` 并说明。
    - ``restore`` 需要独立隔离恢复库地址；未提供时输出 ``skipped``。
    - ``verify`` 的联网冒烟需要 ``--base-url``（及读取所需的 ``--token``）；缺省时对应步骤 ``skipped``。

退出码：``pass`` / ``skipped`` → 0；``fail`` → 1；护栏拒绝或参数错误 → 2。
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping
from urllib.parse import urlsplit

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

_MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"
_SCHEME = "postgresql+psycopg://"
_LOCAL_HOSTS = {"", "localhost", "127.0.0.1", "::1", "0.0.0.0"}
_PRODUCTION_ENVS = {"production", "prod"}

_DSN_CREDENTIALS = re.compile(r"://([^:/@\s]+):([^@\s]*)@")

CommandRunner = Callable[[list[str]], int]
WhichFn = Callable[[str], str | None]
Transport = Callable[..., object]


class DrillConfigError(ValueError):
    """护栏拒绝或配置非法；必须在任何动作前抛出。"""


@dataclass(frozen=True)
class DrillStep:
    name: str
    status: str
    message: str


@dataclass(frozen=True)
class DrillReport:
    phase: str
    status: str
    steps: tuple[DrillStep, ...]

    def to_text(self) -> str:
        lines = [f"迁移/备份演练（{self.phase}）：{self.status}"]
        lines.extend(f"[{step.status}] {step.name}：{step.message}" for step in self.steps)
        return "\n".join(lines)


def mask_dsn(dsn: object) -> str:
    """把 DSN userinfo 里的口令替换为 ``***``；无口令的地址原样返回。"""
    if not isinstance(dsn, str) or not dsn:
        return "" if dsn is None else str(dsn)
    return _DSN_CREDENTIALS.sub(r"://\1:***@", dsn)


def _host(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        return ""
    try:
        parsed = urlsplit(value.strip())
    except ValueError:
        return ""
    return (parsed.hostname or "").lower()


def check_dsn(
    dsn: object, *, allow_local: bool, confirm_production: bool, environment: str
) -> None:
    """校验演练目标地址；越界立即 fail-closed。错误信息中只出现脱敏 DSN。"""
    if not isinstance(dsn, str) or not dsn.strip():
        raise DrillConfigError("必须配置 WORKBENCH_DATABASE_URL")
    candidate = dsn.strip()
    if not candidate.startswith(_SCHEME):
        raise DrillConfigError("数据库地址必须是 postgresql+psycopg:// 形式（不得使用 sqlite 或其它驱动）")
    host = _host(candidate)
    if host in _LOCAL_HOSTS and not allow_local:
        raise DrillConfigError(
            f"目标数据库 {mask_dsn(candidate)} 指向本地地址（localhost/127.0.0.1），禁止作为演练目标；"
            "如确为本地演练请显式 --allow-local"
        )
    if isinstance(environment, str) and environment.strip().lower() in _PRODUCTION_ENVS and not confirm_production:
        raise DrillConfigError(
            f"目标数据库 {mask_dsn(candidate)} 指向生产库，必须显式 --confirm-production"
        )


def _expected_migrations() -> list[str]:
    return sorted(path.stem for path in _MIGRATIONS_DIR.glob("*.sql"))


def _as_mapping(config: Mapping[str, object] | None = None) -> dict[str, object]:
    expected = _expected_migrations()
    if config is not None:
        values = dict(config)
        values.setdefault("expected_migrations", expected)
        return values
    applied = [item.strip() for item in os.getenv("WORKBENCH_APPLIED_MIGRATIONS", "").split(",") if item.strip()]
    return {
        "dsn": os.getenv("WORKBENCH_DATABASE_URL", ""),
        "restore_dsn": os.getenv("WORKBENCH_RESTORE_DATABASE_URL", ""),
        "environment": os.getenv("WORKBENCH_ENV", ""),
        "applied_migrations": applied,
        "expected_migrations": expected,
        "backup_key": os.getenv("WORKBENCH_BACKUP_ENCRYPTION_KEY", ""),
        "base_url": os.getenv("WORKBENCH_ACCEPTANCE_BASE_URL", ""),
        "token": os.getenv("WORKBENCH_ACCEPTANCE_TOKEN", ""),
    }


def _default_runner(cmd: list[str]) -> int:
    return subprocess.run(list(cmd), check=False).returncode


def _status(steps: tuple[DrillStep, ...]) -> str:
    if any(step.status == "fail" for step in steps):
        return "fail"
    if steps and all(step.status == "skipped" for step in steps):
        return "skipped"
    return "pass"


def _migration_step(values: Mapping[str, object]) -> DrillStep:
    expected = {str(item).strip() for item in values.get("expected_migrations") or [] if str(item).strip()}
    applied = {str(item).strip() for item in values.get("applied_migrations") or [] if str(item).strip()}
    if not expected:
        return DrillStep("迁移清单一致", "fail", "未找到 migrations/*.sql，无法核对")
    if applied != expected:
        return DrillStep(
            "迁移清单一致",
            "fail",
            f"迁移清单不一致（缺少 {len(expected - applied)} 项，多出 {len(applied - expected)} 项）",
        )
    return DrillStep("迁移清单一致", "pass", f"迁移清单一致（{len(expected)} 项）")


# --- phase list ---------------------------------------------------------------


def _phase_list(values: Mapping[str, object]) -> DrillReport:
    steps = (
        DrillStep("目标数据库（脱敏）", "pass", mask_dsn(values.get("dsn"))),
        _migration_step(values),
    )
    return DrillReport("list", _status(steps), steps)


# --- phase backup -------------------------------------------------------------


def _dump_command(pg_dump: str, dsn: str, dump_path: str) -> list[str]:
    return [pg_dump, "--format=custom", "--no-owner", "--no-privileges", "--file", dump_path, dsn]


def _phase_backup(
    values: Mapping[str, object],
    *,
    execute: bool,
    backup_dir: str,
    runner: CommandRunner,
    which: WhichFn,
) -> DrillReport:
    steps: list[DrillStep] = []
    pg_dump = which("pg_dump")
    if not pg_dump:
        steps.append(
            DrillStep(
                "pg_dump 可用性",
                "fail",
                "未找到 pg_dump，请先在部署机安装 PostgreSQL 客户端（如 postgresql-client）",
            )
        )
        return DrillReport("backup", _status(tuple(steps)), tuple(steps))
    steps.append(DrillStep("pg_dump 可用性", "pass", str(pg_dump)))

    dump_path = str(Path(backup_dir) / "workbench-backup.dump")
    real = _dump_command(pg_dump, str(values.get("dsn") or ""), dump_path)
    shown = [mask_dsn(part) for part in real]

    key = values.get("backup_key")
    if isinstance(key, str) and len(key) >= 32:
        steps.append(
            DrillStep(
                "加密密钥",
                "pass",
                "已配置备份加密密钥（值不显示）；pg_dump 不内置加密，导出后必须用该密钥加密落盘",
            )
        )
    else:
        steps.append(
            DrillStep("加密密钥", "fail", "必须配置至少 32 位 WORKBENCH_BACKUP_ENCRYPTION_KEY 用于落盘加密")
        )

    if not execute:
        steps.append(
            DrillStep(
                "备份命令（脱敏）",
                "pass",
                f"dry-run：未执行（加 --execute 才真正调用 pg_dump）；命令：{' '.join(shown)}",
            )
        )
    else:
        returncode = runner(real)
        steps.append(
            DrillStep(
                "备份命令（脱敏）",
                "pass" if returncode == 0 else "fail",
                f"pg_dump 退出码 {returncode}；命令：{' '.join(shown)}",
            )
        )
    return DrillReport("backup", _status(tuple(steps)), tuple(steps))


# --- phase restore ------------------------------------------------------------


def _phase_restore(
    values: Mapping[str, object],
    *,
    execute: bool,
    allow_local: bool,
    confirm_production: bool,
    backup_dir: str,
    runner: CommandRunner,
    which: WhichFn,
) -> DrillReport:
    restore_dsn = values.get("restore_dsn")
    if not isinstance(restore_dsn, str) or not restore_dsn.strip():
        steps = (
            DrillStep(
                "隔离恢复库",
                "skipped",
                "需要隔离恢复库地址（--restore-dsn 或 WORKBENCH_RESTORE_DATABASE_URL），未提供则跳过恢复演练",
            ),
        )
        return DrillReport("restore", "skipped", steps)

    check_dsn(
        restore_dsn,
        allow_local=allow_local,
        confirm_production=confirm_production,
        environment=str(values.get("environment") or ""),
    )

    steps: list[DrillStep] = []
    pg_restore = which("pg_restore")
    if not pg_restore:
        steps.append(
            DrillStep(
                "pg_restore 可用性",
                "fail",
                "未找到 pg_restore，请先在部署机安装 PostgreSQL 客户端",
            )
        )
        return DrillReport("restore", _status(tuple(steps)), tuple(steps))
    steps.append(DrillStep("pg_restore 可用性", "pass", str(pg_restore)))

    dump_path = str(Path(backup_dir) / "workbench-backup.dump")
    real = [pg_restore, "--clean", "--if-exists", "--no-owner", "--dbname", restore_dsn.strip(), dump_path]
    shown = [mask_dsn(part) for part in real]

    if not execute:
        steps.append(
            DrillStep(
                "恢复命令（脱敏）",
                "pass",
                f"dry-run：未执行（加 --execute 才真正调用 pg_restore）；命令：{' '.join(shown)}",
            )
        )
    else:
        returncode = runner(real)
        steps.append(
            DrillStep(
                "恢复命令（脱敏）",
                "pass" if returncode == 0 else "fail",
                f"pg_restore 退出码 {returncode}；命令：{' '.join(shown)}",
            )
        )
    steps.append(
        DrillStep(
            "恢复后一致性核对",
            "pass",
            "核对步骤：恢复后在隔离库执行 app.migrations.apply_migrations 至最新，"
            "再用 WORKBENCH_APPLIED_MIGRATIONS 与 migrations/*.sql 逐一比对（可复跑 `--phase verify`）",
        )
    )
    return DrillReport("restore", _status(tuple(steps)), tuple(steps))


# --- phase verify -------------------------------------------------------------


def _get_json(url: str, *, headers: Mapping[str, str], transport: Transport | None, timeout: float) -> tuple[int, object]:
    if transport is None:
        response = httpx.get(url, headers=dict(headers), timeout=timeout)
    else:
        response = transport("GET", url, headers=dict(headers), timeout=timeout)
    status_code = int(getattr(response, "status_code", 0))
    try:
        payload: object = response.json()
    except Exception:  # noqa: BLE001 响应体不可解析时视作无内容
        payload = None
    return status_code, payload


def _phase_verify(
    values: Mapping[str, object],
    *,
    offline: bool,
    transport: Transport | None,
    timeout: float,
) -> DrillReport:
    steps: list[DrillStep] = [_migration_step(values)]
    base_url = str(values.get("base_url") or "").strip()
    token = str(values.get("token") or "").strip()

    if offline or not base_url:
        steps.append(DrillStep("应用健康检查", "skipped", "需要 --base-url 且未加 --offline"))
        steps.append(DrillStep("读取冒烟", "skipped", "需要 --base-url 与 --token，且未加 --offline"))
        return DrillReport("verify", _status(tuple(steps)), tuple(steps))

    health_url = base_url.rstrip("/") + "/api/v1/health"
    try:
        status_code, payload = _get_json(
            health_url, headers={"Accept": "application/json"}, transport=transport, timeout=timeout
        )
    except Exception as exc:  # noqa: BLE001 fail-closed
        steps.append(DrillStep("应用健康检查", "fail", f"获取失败：{type(exc).__name__}"))
    else:
        if 200 <= status_code < 300 and isinstance(payload, dict) and payload.get("status") == "ok":
            steps.append(DrillStep("应用健康检查", "pass", f"{_host(health_url)} 返回 ok"))
        else:
            steps.append(DrillStep("应用健康检查", "fail", f"未返回健康状态（HTTP {status_code}）"))

    if not token:
        steps.append(DrillStep("读取冒烟", "skipped", "需要管理员令牌（--token）执行一次读取"))
        return DrillReport("verify", _status(tuple(steps)), tuple(steps))

    read_url = base_url.rstrip("/") + "/api/v1/dead-letters"
    try:
        status_code, payload = _get_json(
            read_url,
            headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
            transport=transport,
            timeout=timeout,
        )
    except Exception as exc:  # noqa: BLE001 fail-closed
        steps.append(DrillStep("读取冒烟", "fail", f"获取失败：{type(exc).__name__}"))
    else:
        if 200 <= status_code < 300:
            count = len(payload) if isinstance(payload, list) else "未知"
            steps.append(DrillStep("读取冒烟", "pass", f"{_host(read_url)} 可读取（{count} 条）"))
        else:
            steps.append(DrillStep("读取冒烟", "fail", f"HTTP {status_code}"))
    return DrillReport("verify", _status(tuple(steps)), tuple(steps))


_PHASES = ("list", "backup", "restore", "verify")


def run_phase(
    phase: str,
    config: Mapping[str, object] | None = None,
    *,
    execute: bool = False,
    allow_local: bool = False,
    confirm_production: bool = False,
    backup_dir: str = "backups",
    runner: CommandRunner | None = None,
    which: WhichFn | None = None,
    transport: Transport | None = None,
    timeout: float = 10.0,
    offline: bool = False,
) -> DrillReport:
    values = _as_mapping(config)
    check_dsn(
        values.get("dsn"),
        allow_local=allow_local,
        confirm_production=confirm_production,
        environment=str(values.get("environment") or ""),
    )
    resolved_runner = runner or _default_runner
    resolved_which = which or shutil.which

    if phase == "list":
        report = _phase_list(values)
    elif phase == "backup":
        report = _phase_backup(
            values, execute=execute, backup_dir=backup_dir, runner=resolved_runner, which=resolved_which
        )
    elif phase == "restore":
        report = _phase_restore(
            values,
            execute=execute,
            allow_local=allow_local,
            confirm_production=confirm_production,
            backup_dir=backup_dir,
            runner=resolved_runner,
            which=resolved_which,
        )
    elif phase == "verify":
        report = _phase_verify(values, offline=offline, transport=transport, timeout=timeout)
    else:
        raise DrillConfigError(f"未知阶段：{phase}")

    if allow_local:
        steps = (
            DrillStep(
                "本地目标许可",
                "warn",
                "已显式 --allow-local：目标为本地地址，仅限本地演练，禁止用于生产验收",
            ),
            *report.steps,
        )
        return DrillReport(report.phase, _status(steps), steps)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="公司工作台迁移与备份/恢复演练")
    parser.add_argument("--phase", choices=_PHASES, default="list", help="演练阶段（默认 list）")
    parser.add_argument("--example", action="store_true", help="使用越界配置演示 fail-closed 输出")
    parser.add_argument("--restore-dsn", default="", help="隔离恢复库地址（restore 阶段必需）")
    parser.add_argument("--execute", action="store_true", help="真正调用 pg_dump/pg_restore（默认 dry-run）")
    parser.add_argument("--allow-local", action="store_true", help="允许本地地址（仅限本地演练）")
    parser.add_argument("--confirm-production", action="store_true", help="确认目标为生产库")
    parser.add_argument("--backup-dir", default="backups", help="备份文件目录（默认 backups）")
    parser.add_argument("--base-url", default="", help="verify 阶段受检应用地址")
    parser.add_argument("--token", default="", help="verify 阶段读取用管理员令牌（不会写入报告）")
    parser.add_argument("--offline", action="store_true", help="verify 阶段跳过联网冒烟")
    parser.add_argument("--timeout", type=float, default=10.0, help="单请求超时秒数（默认 10）")
    args = parser.parse_args(argv)

    if args.example:
        values: dict[str, object] = {
            "dsn": "postgresql+psycopg://workbench:EXAMPLE_SECRET@localhost:5432/workbench",
            "environment": "staging",
        }
        phase = "list"
    else:
        values = _as_mapping(None)
        if args.restore_dsn:
            values["restore_dsn"] = args.restore_dsn
        if args.base_url:
            values["base_url"] = args.base_url
        if args.token:
            values["token"] = args.token
        phase = args.phase

    try:
        report = run_phase(
            phase,
            values,
            execute=args.execute,
            allow_local=args.allow_local,
            confirm_production=args.confirm_production,
            backup_dir=args.backup_dir,
            timeout=args.timeout,
            offline=args.offline,
        )
    except DrillConfigError as exc:
        print(f"配置错误：{exc}")
        return 2
    print(report.to_text())
    return 0 if report.status in {"pass", "skipped"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
