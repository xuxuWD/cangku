"""客户侧交付验收只读探针（人机协作：人在客户侧执行，AI 判读回传）。

用途
    交付验收时，把 `docs/private-deployment-runbook.md` 与
    `docs/customer-side-acceptance-runbook.md` 里**能机械核对**的交付面做成一次只读检查，
    输出可直接回传的文本报告（每项：检查项 / 结论 / 实测值 / 判据）：

    1. 镜像引用（禁止 `latest` / 无标签回落）与 5 个 OCI 标签（title / description /
       version / revision / source）；`version` / `revision` 不得为未注入参数的默认值
       `dev` / `unknown`（宪法 §6.3 产物可追溯）；
    2. `app` / `worker` / `beat` 三服务容器日志上限（`json-file` / `max-size=10m` /
       `max-file=5`，组 10.3「日志有界」）；
    3. 应用健康检查 `GET /api/v1/health` 与 `worker` healthcheck 状态；
    4. 调度是否在跑：`beat` 日志中是否可见 `Sending due task`（调度停 ⇒ 周期任务全停）；
    5. PostgreSQL 连接数与 `max_connections`：上限 ≥100，且使用率 ≤80%；同时给出
       runbook「容量与并发」的稳态账目（38 + 2×并发 + 1）与实测连接数对照；
    6. 运行事件表体量与最早/最晚事件时间（保留期口径），以及审计表
       `workbench_audit_log` 的可读性与最新时间（口径：不轮转、不删除）。

只读承诺（本脚本不写任何东西）
    - docker 只用 `inspect` / `logs`：**不启动、不重启、不停止容器，不拉/推镜像，不跑迁移，不改配置**；
    - SQL **只发 SELECT**，并在只读会话（`SET default_transaction_read_only = on`）内执行；
    - HTTP **只发 GET**。本脚本没有任何写路径。

人在客户侧执行（AI 不连客户 / 生产环境）
    本脚本由**人在客户侧服务器上执行**，把输出回传（DSN / 口令 / 令牌一律用 `***` 替换），
    再由 AI 判读。报告对 `scheme://user:pass@host` 形式的凭据做遮蔽，**不打印 DSN / 口令 / 令牌**，
    只暴露主机与库名。

环境变量（也可用同名命令行参数，参数优先）
    `WORKBENCH_APP_IMAGE`（受检镜像引用）、`WORKBENCH_ACCEPTANCE_BASE_URL`（应用入口）、
    `WORKBENCH_PROBE_PSQL_DSN`（**只读**连接串，用 `psql` 那套不带 `+psycopg` 的写法）、
    `WORKBENCH_PROBE_APP_CONTAINER` / `WORKBENCH_PROBE_WORKER_CONTAINER` /
    `WORKBENCH_PROBE_BEAT_CONTAINER`（容器名，`docker compose ps --format '{{.Name}}'` 可查）、
    `WORKBENCH_WORKER_CONCURRENCY`（默认 2）、
    `WORKBENCH_RUNTIME_EVENTS_RETENTION_DAYS`（默认 30）、
    `WORKBENCH_PROBE_RUNTIME_EVENTS_TABLE`（默认 `workbench_runtime_events`）。

核对不到的环境（无 docker 守护进程、无只读 DSN、表不存在）一律输出 **`skipped` 并说明原因**，
**不得静默通过**；`skipped` 项必须由人工在回传里登记为「未验证」。

护栏（fail-closed）
    `--base-url` 必须 `https`（否则 `--allow-insecure`）、必须是独立主机
    （否则 `--allow-local`）；两者缺省都拒绝。

退出码
    `0` = 全部通过或跳过；`1` = 存在不通过；`2` = 参数或配置错误。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Callable, Mapping, Sequence
from urllib.parse import urlsplit

# runbook「容量与并发」的连接账目与阈值
BASE_CONNECTIONS = 38
CONNECTIONS_PER_CONCURRENCY = 2
OPERATIONS_CONNECTIONS = 1
REQUIRED_MAX_CONNECTIONS = 100
CONNECTION_USAGE_ALERT_RATIO = 0.8

# container 日志上限（docker-compose.app.yml 三服务口径）
EXPECTED_LOG_DRIVER = "json-file"
EXPECTED_LOG_MAX_SIZE = "10m"
EXPECTED_LOG_MAX_FILE = "5"

# 运行事件保留期默认 30 天（runbook）
DEFAULT_RETENTION_DAYS = 30
DEFAULT_RUNTIME_EVENTS_TABLE = "workbench_runtime_events"
DEFAULT_CONCURRENCY = 2
DEFAULT_TIMEOUT_SECONDS = 10.0
DEFAULT_CONTAINERS = {
    "app": "workbench-app-1",
    "worker": "workbench-worker-1",
    "beat": "workbench-beat-1",
}

IMAGE_LABELS = (
    "org.opencontainers.image.title",
    "org.opencontainers.image.description",
    "org.opencontainers.image.version",
    "org.opencontainers.image.revision",
    "org.opencontainers.image.source",
)
DEFAULT_LABEL_VALUES = frozenset({"", "dev", "unknown", "latest"})
BEAT_DISPATCH_MARKER = "Sending due task"

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}
_SAFE_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]*$")
_CREDENTIALS_IN_URL = re.compile(r"([a-zA-Z][a-zA-Z0-9+.\-]*://)[^/@\s]*@")

DockerRunner = Callable[[Sequence[str]], str]
HttpGet = Callable[..., object]
SqlRunner = Callable[[str], Sequence[Sequence[object]]]


class ProbeConfigError(ValueError):
    """探针参数或配置错误；必须在执行任何检查前抛出（退出码 2）。"""


@dataclass(frozen=True)
class ProbeCheck:
    name: str
    status: str
    observed: str
    criteria: str

    def to_text(self) -> str:
        return (
            f"[{self.status}] 检查项：{self.name}\n"
            f"    实测值：{self.observed}\n"
            f"    判据：{self.criteria}"
        )


@dataclass(frozen=True)
class ProbeReport:
    status: str
    target: str
    generated_at: str
    checks: tuple[ProbeCheck, ...]

    def to_text(self) -> str:
        lines = [
            f"客户侧交付验收只读探针结果：{self.status}",
            f"受检目标：{self.target}",
            f"生成时间：{self.generated_at}",
            "（本报告由人工在客户侧执行后回传；凭据已遮蔽，`skipped` 项必须登记为「未验证」）",
            "",
        ]
        lines.extend(check.to_text() for check in self.checks)
        return redact("\n".join(lines))


# --------------------------------------------------------------------------- 脱敏


def redact(text: object) -> str:
    """把 URL 里的 userinfo（`scheme://user:pass@host`）替换为 `scheme://***@host`。"""
    value = "" if text is None else str(text)
    return _CREDENTIALS_IN_URL.sub(r"\1***@", value)


def _truncate(text: str, limit: int = 300) -> str:
    return text if len(text) <= limit else text[:limit] + "…"


def _error_text(exc: BaseException) -> str:
    """保留报错原文（便于排障），由报告层统一脱敏。"""
    detail = _truncate(str(exc).strip())
    return f"{type(exc).__name__}: {detail}" if detail else type(exc).__name__


def _dsn_hint(dsn: str) -> str:
    """只暴露主机:端口/库名，绝不回显凭据。"""
    candidate = dsn.replace("postgresql+psycopg://", "postgresql://", 1).strip()
    try:
        parsed = urlsplit(candidate)
    except ValueError:
        return "(连接串无法解析)"
    if not parsed.hostname:
        return "(连接串无法解析)"
    return f"{parsed.hostname}:{parsed.port or 5432}/{parsed.path.lstrip('/') or '(未配置库名)'}"


# --------------------------------------------------------------------------- 护栏


def resolve_base_url(base_url: str, *, allow_insecure: bool = False, allow_local: bool = False) -> str:
    """解析并校验应用入口地址；越界立即 fail-closed。"""
    if not isinstance(base_url, str) or not base_url.strip():
        raise ProbeConfigError("必须提供 --base-url（或设置 WORKBENCH_ACCEPTANCE_BASE_URL）")
    candidate = base_url.strip()
    parsed = urlsplit(candidate)
    if not parsed.hostname or parsed.scheme not in {"http", "https"}:
        raise ProbeConfigError("--base-url 必须是含主机的完整 URL")
    if parsed.scheme != "https" and not allow_insecure:
        raise ProbeConfigError("拒绝：目标必须使用 https（仅联调可加 --allow-insecure）")
    if (parsed.hostname or "").lower() in _LOCAL_HOSTS and not allow_local:
        raise ProbeConfigError("拒绝：必须指向客户侧独立主机，不能回落本地（仅联调可加 --allow-local）")
    return candidate.rstrip("/")


# --------------------------------------------------------------------------- 默认执行器


def default_docker(args: Sequence[str]) -> str:
    """只读 docker 调用；docker 不可用或命令失败时抛错（由检查项转为 skipped）。"""
    completed = subprocess.run(
        ["docker", *[str(item) for item in args]],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(detail or f"docker 退出码 {completed.returncode}")
    return completed.stdout


def default_http_get(url: str, *, headers: Mapping[str, str], timeout: float) -> object:
    import httpx

    return httpx.get(url, headers=dict(headers), timeout=timeout)


def default_http_get_without_client(url: str, *, headers: Mapping[str, str], timeout: float) -> object:
    """无 httpx 时的兜底实现（标准库），只发 GET。"""
    import urllib.request

    request = urllib.request.Request(url, headers=dict(headers), method="GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 目标由护栏限定
        return _UrlLibResponse(int(response.status), response.read())


class _UrlLibResponse:
    def __init__(self, status_code: int, body: bytes) -> None:
        self.status_code = status_code
        self._body = body

    def json(self) -> object:
        return json.loads(self._body.decode("utf-8"))


def default_sql_query(dsn: str) -> SqlRunner:
    """构造只读 SQL 执行器：只发 SELECT，且套会话级只读（双保险口径，同只读核验清单）。"""
    target = dsn.replace("postgresql+psycopg://", "postgresql://", 1).strip()

    def query(sql: str) -> list[tuple[object, ...]]:
        import psycopg

        with psycopg.connect(target, connect_timeout=DEFAULT_TIMEOUT_SECONDS) as connection:
            connection.execute("SET default_transaction_read_only = on")
            with connection.cursor() as cursor:
                cursor.execute(sql)
                return list(cursor.fetchall())

    return query


# --------------------------------------------------------------------------- 单项检查


def _check_image_reference(image: str) -> ProbeCheck:
    name = "镜像引用（禁止 latest）"
    criteria = "起栈镜像必须带版本标签：不得为 `:latest`，也不得无标签（无标签即回落 `:latest`）"
    reference = (image or "").strip()
    if not reference:
        return ProbeCheck(
            name,
            "skipped",
            "未提供镜像引用（--image / WORKBENCH_APP_IMAGE）⇒ 无法核对，须登记为未验证",
            criteria,
        )
    if "@sha256:" in reference:
        return ProbeCheck(name, "pass", f"{reference.split('@', 1)[0]}@sha256:***（按 digest 固定）", criteria)
    last_segment = reference.rsplit("/", 1)[-1]
    tag = last_segment.split(":", 1)[1] if ":" in last_segment else ""
    if not tag:
        return ProbeCheck(name, "fail", f"{reference}（无标签 ⇒ 回落到 :latest，正式交付禁止）", criteria)
    if tag == "latest":
        return ProbeCheck(name, "fail", f"{reference}（标签为 latest，正式交付禁止）", criteria)
    return ProbeCheck(name, "pass", reference, criteria)


def _check_image_labels(image: str, docker: DockerRunner | None) -> ProbeCheck:
    name = "镜像 OCI 标签（可追溯）"
    criteria = (
        "`docker image inspect` 须同时含 title / description / version / revision / source 五个 OCI 标签，"
        "且 version / revision 不得为未注入参数的默认值 `dev` / `unknown`（宪法 §6.3）"
    )
    if not (image or "").strip():
        return ProbeCheck(name, "skipped", "未提供镜像引用 ⇒ 无法核对镜像标签", criteria)
    assert docker is not None  # run_probe 保证非 None
    try:
        raw = docker(["image", "inspect", image.strip(), "--format", "{{json .Config.Labels}}"])
    except Exception as exc:  # noqa: BLE001 核对不到 ⇒ 显式 skipped，不得静默通过
        return ProbeCheck(name, "skipped", f"无法核对（{_error_text(exc)}）", criteria)
    try:
        labels = json.loads(raw) if str(raw).strip() else {}
    except ValueError:
        return ProbeCheck(name, "skipped", "`docker image inspect` 输出不是合法 JSON ⇒ 未核对", criteria)
    if not isinstance(labels, dict):
        labels = {}
    missing = [key for key in IMAGE_LABELS if not str(labels.get(key) or "").strip()]
    version = str(labels.get("org.opencontainers.image.version") or "")
    revision = str(labels.get("org.opencontainers.image.revision") or "")
    defaults = [
        f"{key.rsplit('.', 1)[-1]}={labels.get(key)!r}"
        for key in ("org.opencontainers.image.version", "org.opencontainers.image.revision")
        if str(labels.get(key) or "").strip().lower() in DEFAULT_LABEL_VALUES
    ]
    problems: list[str] = []
    if missing:
        problems.append(f"缺少标签：{'、'.join(missing)}")
    if defaults:
        problems.append(f"为未注入参数的默认值（不算正式版本）：{'、'.join(defaults)}")
    if problems:
        return ProbeCheck(name, "fail", "；".join(problems), criteria)
    return ProbeCheck(
        name,
        "pass",
        f"五个 OCI 标签齐备（version={version}，revision={revision[:12]}）",
        criteria,
    )


def _check_container_logging(service: str, container: str, docker: DockerRunner | None) -> ProbeCheck:
    name = f"容器日志上限（{service}）"
    criteria = (
        f"`docker inspect` 的 LogConfig 须为 {EXPECTED_LOG_DRIVER} + max-size={EXPECTED_LOG_MAX_SIZE} "
        f"+ max-file={EXPECTED_LOG_MAX_FILE}（组 10.3「日志有界」：未设上限时容器日志无界增长，会先写爆宿主盘）"
    )
    if not (container or "").strip():
        return ProbeCheck(name, "skipped", f"未提供 {service} 容器名 ⇒ 无法核对日志上限", criteria)
    assert docker is not None
    try:
        raw = docker(["inspect", container.strip(), "--format", "{{json .HostConfig.LogConfig}}"])
    except Exception as exc:  # noqa: BLE001
        return ProbeCheck(name, "skipped", f"无法核对（{_error_text(exc)}）", criteria)
    try:
        config = json.loads(raw) if str(raw).strip() else {}
    except ValueError:
        return ProbeCheck(name, "skipped", "`docker inspect` 输出不是合法 JSON ⇒ 未核对", criteria)
    if not isinstance(config, dict):
        config = {}
    driver = str(config.get("Type") or config.get("driver") or "")
    options = config.get("Config") or config.get("options") or {}
    if not isinstance(options, dict):
        options = {}
    size = str(options.get("max-size") or "")
    files = str(options.get("max-file") or "")
    observed = (
        f"driver={driver or '(未设置)'}（期望 {EXPECTED_LOG_DRIVER}）"
        f" max-size={size or '(未设置)'}（期望 {EXPECTED_LOG_MAX_SIZE}）"
        f" max-file={files or '(未设置)'}（期望 {EXPECTED_LOG_MAX_FILE}）"
    )
    if driver != EXPECTED_LOG_DRIVER:
        return ProbeCheck(name, "fail", observed, criteria)
    if size != EXPECTED_LOG_MAX_SIZE or files != EXPECTED_LOG_MAX_FILE:
        return ProbeCheck(name, "fail", observed, criteria)
    return ProbeCheck(name, "pass", observed, criteria)


def _check_health(base_url: str, http_get: HttpGet | None, timeout: float) -> ProbeCheck:
    name = "应用健康检查（GET /api/v1/health）"
    criteria = "`GET /api/v1/health` 返回 HTTP 2xx 且响应体 `status=ok`"
    if not (base_url or "").strip():
        return ProbeCheck(name, "skipped", "未提供 base-url ⇒ 无法核对健康检查", criteria)
    if http_get is None:
        return ProbeCheck(name, "skipped", "未提供 HTTP 执行器 ⇒ 无法核对健康检查", criteria)
    url = base_url.rstrip("/") + "/api/v1/health"
    try:
        response = http_get(url, headers={"Accept": "application/json"}, timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        return ProbeCheck(name, "fail", f"请求失败：{_error_text(exc)}", criteria)
    status_code = int(getattr(response, "status_code", 0) or 0)
    try:
        payload = response.json()
    except Exception:  # noqa: BLE001 响应体不可解析视作无内容
        payload = None
    if 200 <= status_code < 300 and isinstance(payload, dict) and payload.get("status") == "ok":
        return ProbeCheck(name, "pass", f"HTTP {status_code}，status=ok", criteria)
    if 200 <= status_code < 300:
        return ProbeCheck(name, "fail", f"HTTP {status_code}，响应体非 status=ok", criteria)
    return ProbeCheck(name, "fail", f"HTTP {status_code}（非 2xx）", criteria)


def _check_worker_health(container: str, docker: DockerRunner | None) -> ProbeCheck:
    name = "worker healthcheck（docker inspect）"
    criteria = "`docker inspect` 的 State.Health.Status 为 healthy（覆盖「worker 挂死但容器还在」）"
    if not (container or "").strip():
        return ProbeCheck(name, "skipped", "未提供 worker 容器名 ⇒ 无法核对 healthcheck", criteria)
    assert docker is not None
    try:
        raw = docker(["inspect", container.strip(), "--format", "{{json .State.Health}}"])
    except Exception as exc:  # noqa: BLE001
        return ProbeCheck(name, "skipped", f"无法核对（{_error_text(exc)}）", criteria)
    try:
        health = json.loads(raw) if str(raw).strip() else None
    except ValueError:
        return ProbeCheck(name, "skipped", "`docker inspect` 输出不是合法 JSON ⇒ 未核对", criteria)
    if not isinstance(health, dict):
        return ProbeCheck(name, "fail", "容器未定义 healthcheck（看不到 State.Health）", criteria)
    status = str(health.get("Status") or "")
    if status == "healthy":
        return ProbeCheck(name, "pass", "State.Health.Status=healthy", criteria)
    return ProbeCheck(name, "fail", f"State.Health.Status={status or '(空)'}", criteria)


def _check_beat_dispatch(container: str, docker: DockerRunner | None) -> ProbeCheck:
    name = "beat 是否在派发（Sending due task）"
    criteria = (
        f"`docker logs` 最近 500 行中须出现 ≥1 条 `{BEAT_DISPATCH_MARKER}`"
        "（调度停 ⇒ Outbox 不发布、生命周期作业与到期扫描全停）"
    )
    if not (container or "").strip():
        return ProbeCheck(name, "skipped", "未提供 beat 容器名 ⇒ 无法核对派发", criteria)
    assert docker is not None
    try:
        raw = docker(["logs", "--tail", "500", container.strip()])
    except Exception as exc:  # noqa: BLE001
        return ProbeCheck(name, "skipped", f"无法核对（{_error_text(exc)}）", criteria)
    hits = [line for line in str(raw).splitlines() if BEAT_DISPATCH_MARKER in line]
    if not hits:
        return ProbeCheck(name, "fail", f"最近日志未见 `{BEAT_DISPATCH_MARKER}`（调度可能已停）", criteria)
    return ProbeCheck(name, "pass", f"最近日志命中 {len(hits)} 条派发记录；末条：{_truncate(hits[-1])}", criteria)


def _check_connections(sql_query: SqlRunner | None, concurrency: int) -> ProbeCheck:
    name = "PostgreSQL 连接数与上限"
    budget = BASE_CONNECTIONS + CONNECTIONS_PER_CONCURRENCY * concurrency + OPERATIONS_CONNECTIONS
    criteria = (
        f"max_connections ≥ {REQUIRED_MAX_CONNECTIONS}，且使用率 ≤ {int(CONNECTION_USAGE_ALERT_RATIO * 100)}%"
        f"（稳态账目 = {BASE_CONNECTIONS} + {CONNECTIONS_PER_CONCURRENCY}×并发 + {OPERATIONS_CONNECTIONS}，"
        "见 runbook「容量与并发」；本机数据不替代客户侧压测）"
    )
    if sql_query is None:
        return ProbeCheck(
            name,
            "skipped",
            "未提供只读连接串（--psql-dsn / WORKBENCH_PROBE_PSQL_DSN）⇒ 无法核对连接账目",
            criteria,
        )
    sql = (
        "SELECT count(*)::int AS used, "
        "(SELECT setting::int FROM pg_settings WHERE name = 'max_connections') AS max_connections "
        "FROM pg_stat_activity"
    )
    try:
        rows = sql_query(sql)
    except Exception as exc:  # noqa: BLE001
        return ProbeCheck(name, "skipped", f"查询失败（{_error_text(exc)}）", criteria)
    if not rows or len(rows[0]) < 2:
        return ProbeCheck(name, "skipped", "查询未返回预期两列 ⇒ 未核对", criteria)
    used = _as_int(rows[0][0])
    limit = _as_int(rows[0][1])
    if used is None or limit is None:
        return ProbeCheck(name, "skipped", f"返回值无法解析：{rows[0]}", criteria)
    observed = (
        f"当前连接 {used}；max_connections {limit}；"
        f"账目预算 {budget}（{BASE_CONNECTIONS} + {CONNECTIONS_PER_CONCURRENCY}×{concurrency} + {OPERATIONS_CONNECTIONS}）"
    )
    if limit < REQUIRED_MAX_CONNECTIONS:
        return ProbeCheck(name, "fail", f"{observed}；上限低于要求（< {REQUIRED_MAX_CONNECTIONS}）", criteria)
    if used > limit * CONNECTION_USAGE_ALERT_RATIO:
        return ProbeCheck(
            name,
            "fail",
            f"{observed}；使用率 {used}/{limit} 超过 {int(CONNECTION_USAGE_ALERT_RATIO * 100)}% 告警线",
            criteria,
        )
    if used > budget:
        observed += "；高于账目预算，须按扩容信号复核（runbook「容量与并发」第 3 条）"
    return ProbeCheck(name, "pass", observed, criteria)


def _check_runtime_events(sql_query: SqlRunner | None, table: str, retention_days: int) -> ProbeCheck:
    name = "运行事件表（体量与保留期）"
    criteria = (
        f"`{table}` 可读；最早事件不得早于保留期窗口（{retention_days} 天，"
        "`WORKBENCH_RUNTIME_EVENTS_RETENTION_DAYS`）；表不存在 ⇒ 记 skipped 并登记为未验证"
    )
    if sql_query is None:
        return ProbeCheck(
            name,
            "skipped",
            "未提供只读连接串（--psql-dsn / WORKBENCH_PROBE_PSQL_DSN）⇒ 无法核对运行事件表",
            criteria,
        )
    if not _SAFE_IDENTIFIER.match(table or ""):
        return ProbeCheck(name, "skipped", f"表名非法：{table!r} ⇒ 未核对", criteria)
    try:
        rows = sql_query(f"SELECT count(*)::int, min(occurred_at), max(occurred_at) FROM {table}")
    except Exception as exc:  # noqa: BLE001
        return ProbeCheck(
            name,
            "skipped",
            f"核对不到（{_error_text(exc)}）⇒ 保留期未核对，必须登记为未验证",
            criteria,
        )
    if not rows or len(rows[0]) < 3:
        return ProbeCheck(name, "skipped", "查询未返回预期三列 ⇒ 未核对", criteria)
    count = _as_int(rows[0][0])
    earliest = _parse_time(rows[0][1])
    latest = _parse_time(rows[0][2])
    if count is None:
        return ProbeCheck(name, "skipped", f"条数无法解析：{rows[0][0]!r}", criteria)
    if count == 0:
        return ProbeCheck(name, "pass", f"{table} 共 0 条（当前无运行事件）；保留期 {retention_days} 天", criteria)
    if earliest is None:
        return ProbeCheck(
            name,
            "skipped",
            f"{table} 共 {count} 条，但最早事件时间无法解析（{rows[0][1]!r}）⇒ 保留期未核对",
            criteria,
        )
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    observed = (
        f"{table} 共 {count} 条；最早 {earliest.isoformat()}，最晚 "
        f"{latest.isoformat() if latest else '(无法解析)'}；保留期 {retention_days} 天"
    )
    if earliest < cutoff:
        return ProbeCheck(
            name,
            "fail",
            f"{observed}；存在早于保留期窗口（{cutoff.isoformat()}）的事件 ⇒ 保留期清理未生效",
            criteria,
        )
    return ProbeCheck(name, "pass", observed, criteria)


def _check_audit_log(sql_query: SqlRunner | None) -> ProbeCheck:
    name = "审计表 workbench_audit_log（可读性与最新时间）"
    criteria = (
        "审计表存在且可读（口径：审计**不轮转、不删除**，10.1 / 10.2）；"
        "本项只能证明「可读 + 最新时间」，删除路径由代码与权限守护，不在此项覆盖"
    )
    if sql_query is None:
        return ProbeCheck(
            name,
            "skipped",
            "未提供只读连接串（--psql-dsn / WORKBENCH_PROBE_PSQL_DSN）⇒ 无法核对审计表",
            criteria,
        )
    try:
        rows = sql_query("SELECT count(*)::int, max(occurred_at) FROM workbench_audit_log")
    except Exception as exc:  # noqa: BLE001
        return ProbeCheck(name, "fail", f"审计表不可读（{_error_text(exc)}）⇒ 合规证据链不成立", criteria)
    if not rows or len(rows[0]) < 2:
        return ProbeCheck(name, "skipped", "查询未返回预期两列 ⇒ 未核对", criteria)
    count = _as_int(rows[0][0])
    latest = _parse_time(rows[0][1])
    if count is None:
        return ProbeCheck(name, "skipped", f"条数无法解析：{rows[0][0]!r}", criteria)
    if count == 0:
        return ProbeCheck(
            name,
            "pass",
            f"{rows[0][0]} 条；最新审计时间（无记录，说明尚无业务流量或审计未落）",
            criteria,
        )
    return ProbeCheck(
        name,
        "pass",
        f"共 {count} 条；最新审计时间 {latest.isoformat() if latest else '(无法解析)'}",
        criteria,
    )


# --------------------------------------------------------------------------- 工具


def _as_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    return None


def _parse_time(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return None


# --------------------------------------------------------------------------- 编排


def run_probe(
    *,
    image: str,
    base_url: str,
    containers: Mapping[str, str],
    psql_dsn: str = "",
    retention_days: int = DEFAULT_RETENTION_DAYS,
    concurrency: int = DEFAULT_CONCURRENCY,
    runtime_events_table: str = DEFAULT_RUNTIME_EVENTS_TABLE,
    docker: DockerRunner | None = None,
    http_get: HttpGet | None = None,
    sql_query: SqlRunner | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> ProbeReport:
    """执行全部只读检查并返回可回传报告（三个执行器可注入，供离线测试）。"""
    docker = docker or default_docker
    if http_get is None:
        try:
            import httpx  # noqa: F401

            http_get = default_http_get
        except ImportError:  # pragma: no cover 环境缺 httpx 时落到标准库
            http_get = default_http_get_without_client
    if sql_query is None and (psql_dsn or "").strip():
        sql_query = default_sql_query(psql_dsn.strip())

    checks: list[ProbeCheck] = [
        _check_image_reference(image),
        _check_image_labels(image, docker),
    ]
    for service in ("app", "worker", "beat"):
        checks.append(_check_container_logging(service, containers.get(service, ""), docker))
    checks.append(_check_health(base_url, http_get, timeout))
    checks.append(_check_worker_health(containers.get("worker", ""), docker))
    checks.append(_check_beat_dispatch(containers.get("beat", ""), docker))
    checks.append(_check_connections(sql_query, concurrency))
    checks.append(_check_runtime_events(sql_query, runtime_events_table, retention_days))
    checks.append(_check_audit_log(sql_query))

    if any(check.status == "fail" for check in checks):
        status = "fail"
    elif all(check.status == "skipped" for check in checks):
        status = "skipped"
    else:
        status = "pass"
    target = base_url
    if sql_query is not None and (psql_dsn or "").strip():
        target += f"；PG {_dsn_hint(psql_dsn)}"
    return ProbeReport(
        status=status,
        target=target,
        generated_at=datetime.now(UTC).isoformat(),
        checks=tuple(checks),
    )


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    if not raw.lstrip("-").isdigit():
        raise ProbeConfigError(f"{name} 必须是整数，收到：{raw!r}")
    return int(raw)


def main(
    argv: list[str] | None = None,
    *,
    docker: DockerRunner | None = None,
    http_get: HttpGet | None = None,
    sql_query: SqlRunner | None = None,
) -> int:
    parser = argparse.ArgumentParser(description="客户侧交付验收只读探针（docker / SQL / HTTP 全部只读）")
    parser.add_argument("--image", default="", help="受检镜像引用（也可用 WORKBENCH_APP_IMAGE）")
    parser.add_argument(
        "--base-url", default="", help="应用入口（须 https、非本地；也可用 WORKBENCH_ACCEPTANCE_BASE_URL）"
    )
    parser.add_argument("--app-container", default="", help="app 容器名（默认 workbench-app-1）")
    parser.add_argument("--worker-container", default="", help="worker 容器名（默认 workbench-worker-1）")
    parser.add_argument("--beat-container", default="", help="beat 容器名（默认 workbench-beat-1）")
    parser.add_argument(
        "--psql-dsn",
        default="",
        help="**只读** PostgreSQL 连接串（不会写入报告；也可用 WORKBENCH_PROBE_PSQL_DSN）",
    )
    parser.add_argument(
        "--runtime-events-table",
        default="",
        help=f"运行事件表名（默认 {DEFAULT_RUNTIME_EVENTS_TABLE}）",
    )
    parser.add_argument(
        "--retention-days", type=int, default=0, help="运行事件保留期天数（默认 30；也可用环境变量）"
    )
    parser.add_argument("--concurrency", type=int, default=0, help="worker 并发（默认 2；也可用环境变量）")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS, help="单请求超时秒数（默认 10）")
    parser.add_argument("--allow-insecure", action="store_true", help="允许 http://（仅限联调自测）")
    parser.add_argument("--allow-local", action="store_true", help="允许本地主机（仅限联调自测）")
    args = parser.parse_args(argv)

    try:
        base_url = resolve_base_url(
            args.base_url or os.getenv("WORKBENCH_ACCEPTANCE_BASE_URL", ""),
            allow_insecure=args.allow_insecure,
            allow_local=args.allow_local,
        )
        if args.timeout <= 0:
            raise ProbeConfigError("--timeout 必须为正数")
        retention_days = args.retention_days or _env_int(
            "WORKBENCH_RUNTIME_EVENTS_RETENTION_DAYS", DEFAULT_RETENTION_DAYS
        )
        if retention_days <= 0:
            raise ProbeConfigError("--retention-days 必须为正整数")
        concurrency = args.concurrency or _env_int("WORKBENCH_WORKER_CONCURRENCY", DEFAULT_CONCURRENCY)
        if concurrency < 0:
            raise ProbeConfigError("--concurrency 不能为负数")
    except ProbeConfigError as exc:
        print(f"配置错误：{exc}")
        return 2

    containers = {
        service: (
            getattr(args, f"{service}_container")
            or os.getenv(f"WORKBENCH_PROBE_{service.upper()}_CONTAINER", "")
            or DEFAULT_CONTAINERS[service]
        )
        for service in ("app", "worker", "beat")
    }

    report = run_probe(
        image=args.image or os.getenv("WORKBENCH_APP_IMAGE", ""),
        base_url=base_url,
        containers=containers,
        psql_dsn=args.psql_dsn or os.getenv("WORKBENCH_PROBE_PSQL_DSN", ""),
        retention_days=retention_days,
        concurrency=concurrency,
        runtime_events_table=(
            args.runtime_events_table
            or os.getenv("WORKBENCH_PROBE_RUNTIME_EVENTS_TABLE", "")
            or DEFAULT_RUNTIME_EVENTS_TABLE
        ),
        docker=docker,
        http_get=http_get,
        sql_query=sql_query,
        timeout=args.timeout,
    )
    print(report.to_text())
    return 0 if report.status in {"pass", "skipped"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
