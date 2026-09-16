"""监控告警探针：把部署手册「监控与告警」的 9 条规则变成可执行、可测的**只读**检查。

用途
    逐条核对 ``docs/private-deployment-runbook.md``「监控与告警」表（第 65–75 行）的 9 条规则，
    **阈值口径与该表逐条一致**：

    1. beat 是否在派发（日志 ``Sending due task`` 断档 ≥5 分钟 ⇒ 告警）；
    2. worker 容器 healthcheck 是否 ``unhealthy``；
    3. ``GET /api/v1/health`` 非 200 或超时；
    4. Outbox 积压（``published_at IS NULL`` 的行数；表口径为连续 2 个派发周期约 30s 不下降）；
    5. 死信新增（``workbench_dead_letters`` 中 ``replayed_at IS NULL`` 的行）；
    6. 审计是否在落（``max(occurred_at)`` 与当前时间的差值 ≥ 阈值）；
    7. 宿主磁盘使用率（≥80% 预警、≥90% 严重）；
    8. PostgreSQL 连接数（``pg_stat_activity`` 计数占 ``max_connections`` 的比例 >80%）；
    9. worker 容器 RSS（>512MiB）。

    每条规则给出 ``ok`` / ``alert`` / ``skipped``：**信号不可用**（docker CLI 缺失、容器不存在、
    未配置数据库地址、容器没有 healthcheck 等）时一律显式 ``skipped`` 并写明原因，
    **绝不静默当作通过**；同时把「单次采样看不出的部分」（Outbox 是否在下降、RSS 是否持续超限）
    写进结论，交人判读。

只读承诺
    本脚本**只读**：只执行 ``docker logs`` / ``docker inspect`` / ``docker stats``、一次
    ``GET /api/v1/health`` 与若干 ``SELECT``（连接显式置为只读事务）。**不写数据库、不改配置、
    不重启或停止任何容器/进程、不触发死信重放**。唯一可能的出站写入是**可选**告警通知
    （``--notify`` 且配置了 ``WORKBENCH_ALERT_WEBHOOK_URL``），载荷脱敏、不含任何事件 payload。

边界（AI 不连生产）
    本脚本由**人**在客户环境执行，输出文本报告回传给 AI 判读；AI 不得直连生产边查边改
    （宪法「发布与运维红线」第 7 条）。脚本自身不落盘、不上传任何数据，也不构成验收证据——
    规则写在手册里不等于告警已生效（runbook 第 77 行）。

接入方式
    对应 runbook 第 77 行「接入方式（三选一）」的第 ② 种（宿主侧轻量采集脚本 + webhook），
    并**复用既有死信通知渠道** ``app.notifications.WebhookNotificationChannel`` 与其
    ``_redact_error`` 脱敏口径，**不另写一套发送逻辑**；错误文本一律先脱敏再进报告与载荷。

可测试性
    docker 命令执行（``runner``）、HTTP GET（``fetch``）、SQL 查询（``query``）、磁盘用量
    （``disk_usage``）与时钟（``now``）均可注入假实现，单测不会真连 PG / Redis / docker / 网络。

配置（全部外置，默认值来源见注释与报告「阈值」列）
    - ``WORKBENCH_MONITOR_APP_URL``：健康检查基址（缺省 → 规则 3 ``skipped``）；
    - ``WORKBENCH_DATABASE_URL``：只读查询目标（``postgresql://`` 或 ``postgresql+psycopg://``；
      缺省 → 规则 4/5/6/8 ``skipped``）；
    - ``WORKBENCH_MONITOR_BEAT_CONTAINER``（默认 ``beat``）、
      ``WORKBENCH_MONITOR_WORKER_CONTAINER``（默认 ``worker``）；
    - ``WORKBENCH_MONITOR_DISK_PATH``（默认 ``/``）；
    - ``WORKBENCH_MONITOR_BEAT_STALE_SECONDS``（默认 300 = runbook 第 67 行「≥5 分钟」）、
      ``WORKBENCH_MONITOR_DISK_WARN_PERCENT``（80）、``WORKBENCH_MONITOR_DISK_CRITICAL_PERCENT``（90）、
      ``WORKBENCH_MONITOR_PG_CONNECTION_PERCENT``（80）、``WORKBENCH_MONITOR_AUDIT_STALE_SECONDS``
      （3600，runbook 第 72 行未给定默认值，按客户业务节奏定）、``WORKBENCH_MONITOR_WORKER_RSS_MIB``
      （512）、``WORKBENCH_MONITOR_OUTBOX_CYCLES``（2）、``WORKBENCH_MONITOR_OUTBOX_INTERVAL_SECONDS``（15）；
      并支持 ``--threshold name=value`` 覆盖（name 即上述变量的 ``WORKBENCH_MONITOR_`` 后缀小写形式）；
    - ``WORKBENCH_ALERT_WEBHOOK_URL`` / ``WORKBENCH_ALERT_WEBHOOK_TIMEOUT_SECONDS``（默认 5，
      对齐 runbook「异步链路」第 4 条的超时口径）。

安全护栏
    健康检查目标默认强制 https + 非本地主机，越界即 ``MonitorConfigError``（fail-closed，先于任何
    检查）；仅联调自测可显式 ``--allow-insecure`` / ``--allow-local``。报告只输出**脱敏后的**
    数据库目标（口令替换为 ``***``），任何错误文本先经 ``_redact_error`` 再进入报告与载荷。

退出码
    ``0`` 全部 ``ok`` 或 ``skipped``；``1`` 存在 ``alert``；``2`` 参数/配置错误。
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, Mapping, Sequence
from urllib.parse import urlsplit

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

from app.notifications import WebhookNotificationChannel, _redact_error

SIGNAL_BEAT = "beat 是否在派发"
SIGNAL_WORKER_HEALTH = "worker 容器健康"
SIGNAL_APP_HEALTH = "app 健康"
SIGNAL_OUTBOX = "Outbox 积压"
SIGNAL_DEAD_LETTER = "死信新增"
SIGNAL_AUDIT = "审计是否在落"
SIGNAL_DISK = "宿主磁盘"
SIGNAL_PG_CONNECTIONS = "PostgreSQL 连接数"
SIGNAL_WORKER_RSS = "worker 资源"

SIGNALS: tuple[str, ...] = (
    SIGNAL_BEAT,
    SIGNAL_WORKER_HEALTH,
    SIGNAL_APP_HEALTH,
    SIGNAL_OUTBOX,
    SIGNAL_DEAD_LETTER,
    SIGNAL_AUDIT,
    SIGNAL_DISK,
    SIGNAL_PG_CONNECTIONS,
    SIGNAL_WORKER_RSS,
)

#: 阈值名 → 默认值（括号内注明来源；runbook 未给默认值的按本脚本默认并在报告里写明）。
THRESHOLD_DEFAULTS: dict[str, float] = {
    "beat_stale_seconds": 300.0,  # runbook 第 67 行：断档 ≥5 分钟
    "disk_warn_percent": 80.0,  # 第 73 行
    "disk_critical_percent": 90.0,  # 第 73 行
    "pg_connection_percent": 80.0,  # 第 74 行（使用率 >80%）
    "audit_stale_seconds": 3600.0,  # 第 72 行未给定默认值；本脚本默认 1 小时
    "worker_rss_mib": 512.0,  # 第 75 行（>512MiB）
    "outbox_cycles": 2.0,  # 第 70 行：连续 2 个派发周期
    "outbox_interval_seconds": 15.0,  # 第 67/70 行：outbox-publisher 每 15s
}

#: 阈值名 → 环境变量名（前缀统一 WORKBENCH_MONITOR_）。
THRESHOLD_ENV: dict[str, str] = {
    name: f"WORKBENCH_MONITOR_{name.upper()}" for name in THRESHOLD_DEFAULTS
}

_MONITOR_ENV = {
    "app_url": "WORKBENCH_MONITOR_APP_URL",
    "database_url": "WORKBENCH_DATABASE_URL",
    "beat_container": "WORKBENCH_MONITOR_BEAT_CONTAINER",
    "worker_container": "WORKBENCH_MONITOR_WORKER_CONTAINER",
    "disk_path": "WORKBENCH_MONITOR_DISK_PATH",
    "alert_webhook_url": "WORKBENCH_ALERT_WEBHOOK_URL",
    "alert_webhook_timeout_seconds": "WORKBENCH_ALERT_WEBHOOK_TIMEOUT_SECONDS",
}

_DEFAULTS = {
    "app_url": "",
    "database_url": "",
    "beat_container": "beat",
    "worker_container": "worker",
    "disk_path": "/",
    "alert_webhook_url": "",
    "alert_webhook_timeout_seconds": "5",
}

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}
_DSN_SCHEMES = ("postgresql://", "postgresql+psycopg://", "postgres://")
_SQL_UNAVAILABLE = "未配置 WORKBENCH_DATABASE_URL，无法读取数据库信号"

# 规则 3/4/5/6/8 的只读查询（全部为 SELECT；连接另置只读事务）。
_SQL_OUTBOX = "SELECT count(*) FROM workbench_event_outbox WHERE published_at IS NULL"
_SQL_DEAD_LETTERS = (
    "SELECT count(*), count(*) FILTER (WHERE notified_at IS NULL) "
    "FROM workbench_dead_letters WHERE replayed_at IS NULL"
)
_SQL_AUDIT = "SELECT max(occurred_at) FROM workbench_audit_log"
_SQL_CONNECTIONS = (
    "SELECT (SELECT count(*) FROM pg_stat_activity), current_setting('max_connections')::int"
)

_BEAT_DISPATCH_MARKER = "Sending due task"

_TIMESTAMP = re.compile(
    r"^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})(?:\.(\d+))?(Z|[+-]\d{2}:?\d{2})?"
)
_MEMORY = re.compile(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*([KMGTP]?i?B)\s*$", re.IGNORECASE)

CommandRunner = Callable[[Sequence[str]], "tuple[int, str]"]
"""执行外部命令（docker）并返回 ``(退出码, 合并输出)``。"""
FetchFn = Callable[..., "tuple[int, object]"]
"""HTTP GET，返回 ``(状态码, 载荷)``；签名 ``(url, *, timeout)``。"""
QueryFn = Callable[[str], "list[tuple[object, ...]]"]
"""执行一条只读 SQL，返回行列表。"""
DiskUsageFn = Callable[[str], "tuple[int, int, int]"]
"""返回 ``(total, used, free)`` 字节数，签名与 ``shutil.disk_usage`` 一致。"""
ClockFn = Callable[[], datetime]


class MonitorConfigError(ValueError):
    """参数/配置错误；必须在执行任何检查前抛出（退出码 2）。"""


@dataclass(frozen=True)
class ProbeCheck:
    signal: str
    status: str  # ok / alert / skipped
    value: str  # 实测值（已脱敏）
    threshold: str  # 阈值口径（runbook 为准）
    basis: str  # 依据出处


@dataclass(frozen=True)
class MonitoringReport:
    status: str  # ok / alert / skipped
    checks: tuple[ProbeCheck, ...]
    generated_at: str
    database_target: str = ""  # 脱敏后的数据库目标（无凭据）
    channel_note: str = ""  # 通知渠道结果（未接入/已发送/无告警）

    def to_text(self) -> str:
        lines = [f"监控告警探针结果：{self.status}", f"生成时间：{self.generated_at}"]
        if self.database_target:
            lines.append(f"数据库目标（脱敏）：{self.database_target}")
        lines.append(f"通知渠道：{self.channel_note or '未启用（未指定 --notify）'}")
        for check in self.checks:
            lines.append(
                f"[{check.status}] {check.signal}：实测 {check.value}｜阈值 {check.threshold}｜"
                f"依据 {check.basis}"
            )
        lines.append("只读探针：未写库、未改配置、未重启任何进程；请把本报告回传给 AI 判读。")
        return "\n".join(lines)


# --------------------------------------------------------------------------- 脱敏与小工具


def _redact(text: object) -> str:
    """复用既有 ``_redact_error`` 口径：``scheme://user:pass@host`` → ``scheme://***@host``。"""
    return _redact_error("" if text is None else str(text))


def _error_text(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {_redact(exc)}"


def _num(value: float) -> str:
    return f"{value:g}"


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _as_aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _host(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        return ""
    try:
        parsed = urlsplit(value.strip())
    except ValueError:
        return ""
    return (parsed.hostname or "").lower()


def parse_timestamp(value: str) -> datetime | None:
    """解析 docker ``--timestamps`` 前缀（RFC3339，纳秒截断到微秒）；失败返回 ``None``。"""
    match = _TIMESTAMP.match(str(value).strip())
    if match is None:
        return None
    date, clock, fraction, zone = match.groups()
    fraction = (fraction or "")[:6].ljust(6, "0")
    if zone in (None, "Z"):
        zone = "+00:00"
    elif ":" not in zone:
        zone = f"{zone[:3]}:{zone[3:]}"
    try:
        return datetime.fromisoformat(f"{date}T{clock}.{fraction}{zone}")
    except ValueError:
        return None


def parse_memory_mib(value: str) -> float | None:
    """解析 docker stats 的内存用量（如 ``206.3MiB`` / ``1.5GiB``）为 MiB；失败返回 ``None``。"""
    match = _MEMORY.match(str(value))
    if match is None:
        return None
    amount = float(match.group(1))
    unit = match.group(2).upper().replace("I", "")
    factor = {"B": 1 / 1024 / 1024, "KB": 1 / 1024, "MB": 1.0, "GB": 1024.0, "TB": 1024.0 * 1024}
    return amount * factor.get(unit, 1.0)


def resolve_app_url(app_url: str, *, allow_insecure: bool = False, allow_local: bool = False) -> str:
    """校验健康检查目标；越界立即 fail-closed（缺省即拒绝 http 与本地主机）。"""
    if not isinstance(app_url, str) or not app_url.strip():
        raise MonitorConfigError(
            "必须提供健康检查地址（--app-url 或 WORKBENCH_MONITOR_APP_URL）"
        )
    candidate = app_url.strip()
    parsed = urlsplit(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise MonitorConfigError("健康检查地址必须是 http(s):// 形式")
    if parsed.scheme != "https" and not allow_insecure:
        raise MonitorConfigError(
            "健康检查目标必须使用 https（仅联调自测可加 --allow-insecure）"
        )
    if (parsed.hostname or "").lower() in _LOCAL_HOSTS and not allow_local:
        raise MonitorConfigError(
            "健康检查目标必须指向独立主机，不能回落本地（仅联调自测可加 --allow-local）"
        )
    return candidate.rstrip("/")


def parse_threshold_overrides(items: Sequence[str] | None) -> dict[str, float]:
    """解析 ``--threshold name=value``；未知名称或非数值 fail-closed。"""
    overrides: dict[str, float] = {}
    for item in items or []:
        name, separator, raw = str(item).partition("=")
        name = name.strip().lower()
        if not separator or not name:
            raise MonitorConfigError(f"阈值必须为 name=value 形式，收到：{item}")
        if name not in THRESHOLD_DEFAULTS:
            raise MonitorConfigError(
                f"未知阈值名：{name}（可用：{', '.join(sorted(THRESHOLD_DEFAULTS))}）"
            )
        try:
            overrides[name] = float(raw.strip())
        except ValueError as exc:
            raise MonitorConfigError(f"阈值 {name} 必须是数值，收到：{raw.strip()}") from exc
    return overrides


# --------------------------------------------------------------------------- 配置


def _as_mapping(config: Mapping[str, object] | None = None) -> dict[str, object]:
    values: dict[str, object] = {
        key: os.getenv(_MONITOR_ENV[key], _DEFAULTS[key]) for key in _MONITOR_ENV
    }
    values["thresholds"] = {
        name: os.getenv(THRESHOLD_ENV[name], _num(default))
        for name, default in THRESHOLD_DEFAULTS.items()
    }
    if config is not None:
        for key, value in config.items():
            if key == "thresholds" and isinstance(value, Mapping):
                current = dict(values["thresholds"])  # type: ignore[arg-type]
                current.update(value)
                values["thresholds"] = current
            else:
                values[key] = value
    return values


def _to_float(name: str, value: object, default: float) -> float:
    if value is None:
        return default
    if isinstance(value, bool):
        raise MonitorConfigError(f"阈值 {name} 必须是数值")
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except ValueError as exc:
        raise MonitorConfigError(f"阈值 {name} 必须是数值，收到：{value}") from exc


def _resolve_thresholds(values: Mapping[str, object]) -> dict[str, float]:
    raw = values.get("thresholds")
    mapping: Mapping[str, object] = raw if isinstance(raw, Mapping) else {}
    return {
        name: _to_float(name, mapping.get(name, default), default)
        for name, default in THRESHOLD_DEFAULTS.items()
    }


def _resolve_dsn(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        return ""
    candidate = value.strip()
    if not candidate.startswith(_DSN_SCHEMES):
        raise MonitorConfigError(
            f"数据库地址必须是 postgresql:// 或 postgresql+psycopg:// 形式（当前：{_redact(candidate)}）"
        )
    return candidate


def _masked_dsn(dsn: str) -> str:
    return _redact(dsn)


# --------------------------------------------------------------------------- 默认实现（可注入）


def _default_runner(cmd: Sequence[str]) -> tuple[int, str]:
    completed = subprocess.run(
        list(cmd), capture_output=True, text=True, encoding="utf-8", errors="replace", check=False
    )
    return int(completed.returncode), f"{completed.stdout or ''}{completed.stderr or ''}"


def _default_fetch(url: str, *, timeout: float = 10.0) -> tuple[int, object]:
    response = httpx.get(url, headers={"Accept": "application/json"}, timeout=timeout)
    try:
        payload: object = response.json()
    except Exception:  # noqa: BLE001 响应体不可解析时视作无内容
        payload = None
    return int(response.status_code), payload


def _default_query(statement: str, dsn: str) -> list[tuple[object, ...]]:
    import psycopg

    target = dsn.replace("postgresql+psycopg://", "postgresql://", 1)
    with psycopg.connect(target, connect_timeout=5) as connection:
        connection.read_only = True  # 只读事务：从连接层禁止任何写入
        with connection.cursor() as cursor:
            cursor.execute(statement)
            rows = cursor.fetchall()
    return [tuple(row) for row in rows]


def _default_disk_usage(path: str) -> tuple[int, int, int]:
    usage = shutil.disk_usage(path)
    return int(usage.total), int(usage.used), int(usage.free)


def _dsn_query(dsn: str) -> QueryFn:
    """把只读查询绑定到指定 DSN（真正的连接在调用时才建立）。"""

    def run(statement: str) -> list[tuple[object, ...]]:
        return _default_query(statement, dsn)

    return run


def _docker_failure_reason(container: str, code: int, output: str) -> str:
    """区分「容器不存在」与「容器没有 healthcheck」——两者都必须 skipped，但原因不同。

    实测：容器未配置 healthcheck 时 ``docker inspect --format '{{.State.Health.Status}}'``
    直接以退出码 1 报 ``map has no entry for key "Health"``（不是输出 ``<no value>``）。
    """
    detail = _redact(output.strip())
    lowered = detail.lower()
    if "no such" in lowered or "not found" in lowered:
        return f"容器 {container} 不存在（docker 返回：{detail}）"
    if "health" in lowered:
        return f"容器 {container} 未配置 healthcheck（docker 返回：{detail}）"
    return f"docker 命令退出码 {code}（{detail or '无输出'}）"


# --------------------------------------------------------------------------- 规则 1：beat 派发


def _check_beat(
    *, container: str, threshold_seconds: float, runner: CommandRunner, clock: ClockFn
) -> ProbeCheck:
    threshold = (
        f"日志「{_BEAT_DISPATCH_MARKER}」断档 ≥{_num(threshold_seconds)}s"
        "（runbook 第 67 行：≥5 分钟）"
    )
    basis = "docs/private-deployment-runbook.md 第 67 行（监控与告警 1）"
    window = max(int(threshold_seconds * 3), 60)
    command = ["docker", "logs", "--since", f"{window}s", "--timestamps", container]
    try:
        code, output = runner(command)
    except FileNotFoundError:
        return ProbeCheck(SIGNAL_BEAT, "skipped", "docker 命令不可用（未安装或不在 PATH）", threshold, basis)
    except Exception as exc:  # noqa: BLE001 fail-closed：信号取不到就明说
        return ProbeCheck(SIGNAL_BEAT, "skipped", f"docker logs 执行失败：{_error_text(exc)}", threshold, basis)
    if code != 0:
        return ProbeCheck(
            SIGNAL_BEAT, "skipped", _docker_failure_reason(container, code, output), threshold, basis
        )
    if not output.strip():
        return ProbeCheck(SIGNAL_BEAT, "skipped", f"容器 {container} 无日志输出", threshold, basis)

    stamps = [
        parsed
        for parsed in (
            parse_timestamp(line) for line in output.splitlines() if _BEAT_DISPATCH_MARKER in line
        )
        if parsed is not None
    ]
    if not stamps:
        return ProbeCheck(
            SIGNAL_BEAT,
            "alert",
            f"最近 {window}s 窗口内无「{_BEAT_DISPATCH_MARKER}」记录（调度可能已停）",
            threshold,
            basis,
        )
    gap = (clock() - max(stamps)).total_seconds()
    value = f"最近派发距今 {gap:.0f}s（窗口 {window}s，容器 {container}）"
    return ProbeCheck(SIGNAL_BEAT, "alert" if gap >= threshold_seconds else "ok", value, threshold, basis)


# --------------------------------------------------------------------------- 规则 2：worker 健康


def _check_worker_health(*, container: str, runner: CommandRunner) -> ProbeCheck:
    threshold = "healthcheck 状态转 unhealthy（interval 30s / retries 3；runbook 第 68 行）"
    basis = "docs/private-deployment-runbook.md 第 68 行（监控与告警 2）"
    command = ["docker", "inspect", "--format", "{{.State.Health.Status}}", container]
    try:
        code, output = runner(command)
    except FileNotFoundError:
        return ProbeCheck(
            SIGNAL_WORKER_HEALTH, "skipped", "docker 命令不可用（未安装或不在 PATH）", threshold, basis
        )
    except Exception as exc:  # noqa: BLE001
        return ProbeCheck(
            SIGNAL_WORKER_HEALTH, "skipped", f"docker inspect 执行失败：{_error_text(exc)}", threshold, basis
        )
    if code != 0:
        return ProbeCheck(
            SIGNAL_WORKER_HEALTH,
            "skipped",
            _docker_failure_reason(container, code, output),
            threshold,
            basis,
        )
    status = output.strip()
    if not status or "<no value>" in status:
        return ProbeCheck(
            SIGNAL_WORKER_HEALTH,
            "skipped",
            f"容器 {container} 未配置 healthcheck，无法判定（beat 服务在编排里显式关闭了 healthcheck）",
            threshold,
            basis,
        )
    if status == "healthy":
        return ProbeCheck(SIGNAL_WORKER_HEALTH, "ok", f"容器 {container} healthcheck = healthy", threshold, basis)
    if status == "unhealthy":
        return ProbeCheck(
            SIGNAL_WORKER_HEALTH, "alert", f"容器 {container} healthcheck = unhealthy", threshold, basis
        )
    if status == "starting":
        return ProbeCheck(
            SIGNAL_WORKER_HEALTH,
            "ok",
            f"容器 {container} healthcheck = starting（启动中，未进入健康判定）",
            threshold,
            basis,
        )
    return ProbeCheck(
        SIGNAL_WORKER_HEALTH, "skipped", f"未知 healthcheck 状态：{_redact(status)}", threshold, basis
    )


# --------------------------------------------------------------------------- 规则 3：app 健康


def _check_app_health(*, app_url: str, fetch: FetchFn, timeout: float) -> ProbeCheck:
    threshold = "GET /api/v1/health 非 200 或超时（runbook 第 69 行）"
    basis = "docs/private-deployment-runbook.md 第 69 行（监控与告警 3）"
    if not app_url:
        return ProbeCheck(
            SIGNAL_APP_HEALTH,
            "skipped",
            "未配置健康检查地址（--app-url 或 WORKBENCH_MONITOR_APP_URL）",
            threshold,
            basis,
        )
    url = f"{app_url}/api/v1/health"
    try:
        status_code, payload = fetch(url, timeout=timeout)
    except Exception as exc:  # noqa: BLE001 超时/连接失败即告警
        return ProbeCheck(SIGNAL_APP_HEALTH, "alert", f"请求失败：{_error_text(exc)}", threshold, basis)
    detail = ""
    if isinstance(payload, dict) and payload.get("status") is not None:
        detail = f"（status={_redact(payload.get('status'))}）"
    value = f"HTTP {status_code}{detail}（{_host(url)}）"
    return ProbeCheck(SIGNAL_APP_HEALTH, "ok" if status_code == 200 else "alert", value, threshold, basis)


# --------------------------------------------------------------------------- 规则 4：Outbox 积压


def _check_outbox(*, query: QueryFn | None, thresholds: Mapping[str, float]) -> ProbeCheck:
    cycles = thresholds["outbox_cycles"]
    interval = thresholds["outbox_interval_seconds"]
    threshold = (
        f"连续 {_num(cycles)} 个派发周期（约 {_num(cycles * interval)}s）不下降 ⇒ 告警 "
        "（runbook 第 70 行；单次运行以是否为零给结论）"
    )
    basis = "docs/private-deployment-runbook.md 第 70 行（监控与告警 4）"
    if query is None:
        return ProbeCheck(SIGNAL_OUTBOX, "skipped", _SQL_UNAVAILABLE, threshold, basis)
    try:
        rows = query(_SQL_OUTBOX)
    except Exception as exc:  # noqa: BLE001 数据库不可用 ⇒ 信号不可用，如实 skipped
        return ProbeCheck(SIGNAL_OUTBOX, "skipped", f"数据库不可用：{_error_text(exc)}", threshold, basis)
    try:
        backlog = int(rows[0][0])
    except (IndexError, TypeError, ValueError) as exc:
        return ProbeCheck(
            SIGNAL_OUTBOX, "skipped", f"查询结果不可解析：{type(exc).__name__}", threshold, basis
        )
    if backlog == 0:
        return ProbeCheck(
            SIGNAL_OUTBOX, "ok", "未发布事件 0 条（单次采样；稳态应为每周期清零，需连续观测）", threshold, basis
        )
    return ProbeCheck(
        SIGNAL_OUTBOX,
        "alert",
        f"未发布事件 {backlog} 条（单次采样：不为零即「消费跟不上生产」，需连续观测确认是否下降）",
        threshold,
        basis,
    )


# --------------------------------------------------------------------------- 规则 5：死信新增


def _check_dead_letters(*, query: QueryFn | None) -> ProbeCheck:
    threshold = "出现 replayed_at IS NULL 的新行 ⇒ 告警（runbook 第 71 行）"
    basis = "docs/private-deployment-runbook.md 第 71 行（监控与告警 5）"
    if query is None:
        return ProbeCheck(SIGNAL_DEAD_LETTER, "skipped", _SQL_UNAVAILABLE, threshold, basis)
    try:
        rows = query(_SQL_DEAD_LETTERS)
    except Exception as exc:  # noqa: BLE001
        return ProbeCheck(
            SIGNAL_DEAD_LETTER, "skipped", f"数据库不可用：{_error_text(exc)}", threshold, basis
        )
    try:
        pending = int(rows[0][0])
        unnotified = int(rows[0][1])
    except (IndexError, TypeError, ValueError) as exc:
        return ProbeCheck(
            SIGNAL_DEAD_LETTER, "skipped", f"查询结果不可解析：{type(exc).__name__}", threshold, basis
        )
    value = f"未重放死信 {pending} 条（其中未通知 {unnotified} 条）"
    return ProbeCheck(
        SIGNAL_DEAD_LETTER, "alert" if pending > 0 else "ok", value, threshold, basis
    )


# --------------------------------------------------------------------------- 规则 6：审计推进


def _check_audit(
    *, query: QueryFn | None, threshold_seconds: float, clock: ClockFn
) -> ProbeCheck:
    threshold = (
        f"最近审计距今 ≥{_num(threshold_seconds)}s ⇒ 告警"
        "（runbook 第 72 行未给定默认值，按客户业务节奏定；本脚本默认 3600s）"
    )
    basis = "docs/private-deployment-runbook.md 第 72 行（监控与告警 6）"
    if query is None:
        return ProbeCheck(SIGNAL_AUDIT, "skipped", _SQL_UNAVAILABLE, threshold, basis)
    try:
        rows = query(_SQL_AUDIT)
    except Exception as exc:  # noqa: BLE001
        return ProbeCheck(SIGNAL_AUDIT, "skipped", f"数据库不可用：{_error_text(exc)}", threshold, basis)
    try:
        latest = rows[0][0]
    except (IndexError, TypeError) as exc:
        return ProbeCheck(
            SIGNAL_AUDIT, "skipped", f"查询结果不可解析：{type(exc).__name__}", threshold, basis
        )
    if latest is None:
        return ProbeCheck(
            SIGNAL_AUDIT, "alert", "无审计记录（workbench_audit_log 为空）", threshold, basis
        )
    if not isinstance(latest, datetime):
        return ProbeCheck(
            SIGNAL_AUDIT,
            "skipped",
            f"max(occurred_at) 不是时间类型：{type(latest).__name__}",
            threshold,
            basis,
        )
    gap = (clock() - _as_aware(latest)).total_seconds()
    value = f"最近审计距今 {gap:.0f}s（max(occurred_at)）"
    if gap < 0:
        return ProbeCheck(
            SIGNAL_AUDIT,
            "ok",
            f"{value}（时间差为负，疑宿主与数据库时钟偏差，请人工核对）",
            threshold,
            basis,
        )
    return ProbeCheck(SIGNAL_AUDIT, "alert" if gap >= threshold_seconds else "ok", value, threshold, basis)


# --------------------------------------------------------------------------- 规则 7：宿主磁盘


def _check_disk(
    *, path: str, warn_percent: float, critical_percent: float, disk_usage: DiskUsageFn
) -> ProbeCheck:
    threshold = (
        f"使用率 ≥{_num(warn_percent)}% 预警、≥{_num(critical_percent)}% 严重（runbook 第 73 行）"
    )
    basis = "docs/private-deployment-runbook.md 第 73 行（监控与告警 7）"
    try:
        total, used, _free = disk_usage(path)
    except Exception as exc:  # noqa: BLE001
        return ProbeCheck(SIGNAL_DISK, "skipped", f"磁盘用量读取失败：{_error_text(exc)}", threshold, basis)
    if not total or total <= 0:
        return ProbeCheck(SIGNAL_DISK, "skipped", f"路径 {path} 容量未知（total=0）", threshold, basis)
    percent = used / total * 100
    if percent >= critical_percent:
        return ProbeCheck(SIGNAL_DISK, "alert", f"{percent:.1f}%（{path}，严重）", threshold, basis)
    if percent >= warn_percent:
        return ProbeCheck(SIGNAL_DISK, "alert", f"{percent:.1f}%（{path}，预警）", threshold, basis)
    return ProbeCheck(SIGNAL_DISK, "ok", f"{percent:.1f}%（{path}）", threshold, basis)


# --------------------------------------------------------------------------- 规则 8：连接数


def _check_pg_connections(*, query: QueryFn | None, percent_threshold: float) -> ProbeCheck:
    threshold = (
        f"连接使用率 >{_num(percent_threshold)}%（max_connections 的 {_num(percent_threshold)}%；"
        "runbook 第 74 行）"
    )
    basis = "docs/private-deployment-runbook.md 第 74 行（监控与告警 8）"
    if query is None:
        return ProbeCheck(SIGNAL_PG_CONNECTIONS, "skipped", _SQL_UNAVAILABLE, threshold, basis)
    try:
        rows = query(_SQL_CONNECTIONS)
    except Exception as exc:  # noqa: BLE001
        return ProbeCheck(
            SIGNAL_PG_CONNECTIONS, "skipped", f"数据库不可用：{_error_text(exc)}", threshold, basis
        )
    try:
        used = int(rows[0][0])
        maximum = int(rows[0][1])
    except (IndexError, TypeError, ValueError) as exc:
        return ProbeCheck(
            SIGNAL_PG_CONNECTIONS,
            "skipped",
            f"查询结果不可解析：{type(exc).__name__}",
            threshold,
            basis,
        )
    if maximum <= 0:
        return ProbeCheck(
            SIGNAL_PG_CONNECTIONS, "skipped", f"max_connections 取值异常（{maximum}）", threshold, basis
        )
    ratio = used / maximum * 100
    value = f"{used}/{maximum}（{ratio:.1f}%，pg_stat_activity 计数）"
    return ProbeCheck(
        SIGNAL_PG_CONNECTIONS,
        "alert" if ratio > percent_threshold else "ok",
        value,
        threshold,
        basis,
    )


# --------------------------------------------------------------------------- 规则 9：worker 资源


def _check_worker_rss(*, container: str, threshold_mib: float, runner: CommandRunner) -> ProbeCheck:
    threshold = f"单容器 RSS 持续 >{_num(threshold_mib)}MiB ⇒ 告警（runbook 第 75 行；不自动重启）"
    basis = "docs/private-deployment-runbook.md 第 75 行（监控与告警 9）"
    command = ["docker", "stats", "--no-stream", "--format", "{{.MemUsage}}", container]
    try:
        code, output = runner(command)
    except FileNotFoundError:
        return ProbeCheck(
            SIGNAL_WORKER_RSS, "skipped", "docker 命令不可用（未安装或不在 PATH）", threshold, basis
        )
    except Exception as exc:  # noqa: BLE001
        return ProbeCheck(
            SIGNAL_WORKER_RSS, "skipped", f"docker stats 执行失败：{_error_text(exc)}", threshold, basis
        )
    if code != 0:
        return ProbeCheck(
            SIGNAL_WORKER_RSS,
            "skipped",
            _docker_failure_reason(container, code, output),
            threshold,
            basis,
        )
    usage = output.strip().split("/")[0].strip()
    mib = parse_memory_mib(usage)
    if mib is None:
        return ProbeCheck(
            SIGNAL_WORKER_RSS,
            "skipped",
            f"无法解析内存用量（原始值：{_redact(usage) or '（空）'}）",
            threshold,
            basis,
        )
    value = f"{mib:.1f}MiB（容器 {container}，单次采样需持续观测）"
    return ProbeCheck(SIGNAL_WORKER_RSS, "alert" if mib > threshold_mib else "ok", value, threshold, basis)


# --------------------------------------------------------------------------- 汇总


def _report_status(checks: Sequence[ProbeCheck]) -> str:
    if any(check.status == "alert" for check in checks):
        return "alert"
    if checks and all(check.status == "skipped" for check in checks):
        return "skipped"
    return "ok"


def run_probe(
    config: Mapping[str, object] | None = None,
    *,
    allow_insecure: bool = False,
    allow_local: bool = False,
    runner: CommandRunner | None = None,
    fetch: FetchFn | None = None,
    query: QueryFn | None = None,
    disk_usage: DiskUsageFn | None = None,
    now: ClockFn | None = None,
    timeout: float = 10.0,
) -> MonitoringReport:
    """执行 9 条只读检查并返回报告；``runner`` / ``fetch`` / ``query`` / ``disk_usage`` 可注入。"""
    values = _as_mapping(config)
    thresholds = _resolve_thresholds(values)
    dsn = _resolve_dsn(values.get("database_url"))
    raw_app_url = values.get("app_url")
    app_url = (
        resolve_app_url(
            str(raw_app_url), allow_insecure=allow_insecure, allow_local=allow_local
        )
        if isinstance(raw_app_url, str) and raw_app_url.strip()
        else ""
    )

    docker = runner or _default_runner
    http = fetch or _default_fetch
    disk = disk_usage or _default_disk_usage
    clock = now or _utc_now
    if query is not None:
        sql: QueryFn | None = query
    elif dsn:
        sql = _dsn_query(dsn)
    else:
        sql = None

    beat_container = str(values.get("beat_container") or _DEFAULTS["beat_container"])
    worker_container = str(values.get("worker_container") or _DEFAULTS["worker_container"])

    checks = (
        _check_beat(
            container=beat_container,
            threshold_seconds=thresholds["beat_stale_seconds"],
            runner=docker,
            clock=clock,
        ),
        _check_worker_health(container=worker_container, runner=docker),
        _check_app_health(app_url=app_url, fetch=http, timeout=timeout),
        _check_outbox(query=sql, thresholds=thresholds),
        _check_dead_letters(query=sql),
        _check_audit(
            query=sql, threshold_seconds=thresholds["audit_stale_seconds"], clock=clock
        ),
        _check_disk(
            path=str(values.get("disk_path") or _DEFAULTS["disk_path"]),
            warn_percent=thresholds["disk_warn_percent"],
            critical_percent=thresholds["disk_critical_percent"],
            disk_usage=disk,
        ),
        _check_pg_connections(
            query=sql, percent_threshold=thresholds["pg_connection_percent"]
        ),
        _check_worker_rss(
            container=worker_container,
            threshold_mib=thresholds["worker_rss_mib"],
            runner=docker,
        ),
    )
    return MonitoringReport(
        status=_report_status(checks),
        checks=checks,
        generated_at=clock().isoformat(),
        database_target=_masked_dsn(dsn) if dsn else "",
    )


def _alert_summary(report: MonitoringReport) -> dict[str, object]:
    """组装脱敏告警摘要：只含结论字段，**不含任何事件 payload，也不含 DSN/令牌**。"""
    alerts = [check for check in report.checks if check.status == "alert"]
    return {
        "kind": "monitoring_alert",
        "source": "scripts/monitoring_probe.py",
        "generated_at": report.generated_at,
        "status": report.status,
        "alerts": [
            {
                "signal": check.signal,
                "value": _redact(check.value),
                "threshold": _redact(check.threshold),
                "basis": check.basis,
            }
            for check in alerts
        ],
    }


def _notify(
    report: MonitoringReport,
    *,
    url: str,
    timeout_seconds: float,
    transport: Callable[..., object] | None,
) -> str:
    """可选告警通知：未配置渠道时明确「不生效」，发送失败也不改变检查结论。"""
    alerts = [check for check in report.checks if check.status == "alert"]
    if not alerts:
        return "无告警，未发送"
    channel = WebhookNotificationChannel(
        url, timeout_seconds=timeout_seconds, transport=transport
    )
    try:
        channel.send(_alert_summary(report))
    except Exception as exc:  # noqa: BLE001 通知失败不掩盖检查结论
        return f"告警摘要发送失败（不影响本次判定）：{_error_text(exc)}"
    return f"已发送脱敏告警摘要（{len(alerts)} 条）"


def _run_example() -> int:
    """离线演示 fail-closed 参数校验：不执行任何检查。"""
    print("示例：演示监控探针的 fail-closed 参数校验（不执行任何检查）")
    print("配置错误：健康检查目标必须使用 https（仅联调自测可加 --allow-insecure）")
    return 2


def main(
    argv: list[str] | None = None,
    *,
    runner: CommandRunner | None = None,
    fetch: FetchFn | None = None,
    query: QueryFn | None = None,
    disk_usage: DiskUsageFn | None = None,
    now: ClockFn | None = None,
    transport: Callable[..., object] | None = None,
) -> int:
    parser = argparse.ArgumentParser(description="公司工作台监控告警只读探针（runbook 9 条规则）")
    parser.add_argument(
        "--app-url", default="", help="健康检查基址（须 https、非本地；也可用 WORKBENCH_MONITOR_APP_URL）"
    )
    parser.add_argument("--beat-container", default="", help="beat 容器名（覆盖 WORKBENCH_MONITOR_BEAT_CONTAINER）")
    parser.add_argument(
        "--worker-container", default="", help="worker 容器名（覆盖 WORKBENCH_MONITOR_WORKER_CONTAINER）"
    )
    parser.add_argument("--disk-path", default="", help="宿主磁盘挂载点（覆盖 WORKBENCH_MONITOR_DISK_PATH）")
    parser.add_argument(
        "--threshold",
        action="append",
        default=None,
        metavar="NAME=VALUE",
        help=f"覆盖阈值，可重复；可用名称：{', '.join(sorted(THRESHOLD_DEFAULTS))}",
    )
    parser.add_argument(
        "--notify",
        action="store_true",
        help="存在告警时向 WORKBENCH_ALERT_WEBHOOK_URL 发送脱敏摘要（未配置则明确不生效）",
    )
    parser.add_argument("--timeout", type=float, default=10.0, help="单请求超时秒数（默认 10）")
    parser.add_argument("--allow-insecure", action="store_true", help="允许 http:// 健康检查目标（仅联调自测）")
    parser.add_argument("--allow-local", action="store_true", help="允许本地健康检查目标（仅联调自测）")
    parser.add_argument("--example", action="store_true", help="演示 fail-closed 参数校验")
    args = parser.parse_args(argv)

    if args.example:
        return _run_example()
    if args.timeout <= 0:
        print("配置错误：--timeout 必须为正数")
        return 2

    try:
        overrides = parse_threshold_overrides(args.threshold)
        if args.app_url:
            overrides_app_url = resolve_app_url(
                args.app_url, allow_insecure=args.allow_insecure, allow_local=args.allow_local
            )
        else:
            overrides_app_url = ""
        config: dict[str, object] = {"thresholds": overrides}
        if overrides_app_url:
            config["app_url"] = overrides_app_url
        if args.beat_container:
            config["beat_container"] = args.beat_container
        if args.worker_container:
            config["worker_container"] = args.worker_container
        if args.disk_path:
            config["disk_path"] = args.disk_path
        report = run_probe(
            config,
            allow_insecure=args.allow_insecure,
            allow_local=args.allow_local,
            runner=runner,
            fetch=fetch,
            query=query,
            disk_usage=disk_usage,
            now=now,
            timeout=args.timeout,
        )
    except MonitorConfigError as exc:
        print(f"配置错误：{exc}")
        return 2

    channel_note = ""
    if args.notify:
        values = _as_mapping(config)
        webhook_url = str(values.get("alert_webhook_url") or "").strip()
        if not webhook_url:
            channel_note = "未接入渠道：未配置 WORKBENCH_ALERT_WEBHOOK_URL，--notify 不生效（未发送任何通知）"
        else:
            try:
                webhook_timeout = _to_float(
                    "alert_webhook_timeout_seconds",
                    values.get("alert_webhook_timeout_seconds"),
                    5.0,
                )
                if webhook_timeout <= 0:
                    raise MonitorConfigError("WORKBENCH_ALERT_WEBHOOK_TIMEOUT_SECONDS 必须为正数")
            except MonitorConfigError as exc:
                print(f"配置错误：{exc}")
                return 2
            channel_note = _notify(
                report, url=webhook_url, timeout_seconds=webhook_timeout, transport=transport
            )

    print(replace(report, channel_note=channel_note).to_text())
    return 0 if report.status in {"ok", "skipped"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
