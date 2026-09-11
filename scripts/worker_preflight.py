"""Celery Worker / Outbox / 死信通知「实跑」验收前置预检。

用途
    在验收门禁项「Celery Worker 实跑、Outbox 生产连接池、死信通知渠道」前，核对异步链路的
    **配置**与**运行态**是否具备实跑条件：

    配置层（``--offline`` 也执行）：
        - 运行环境非 ``development``（避免拿开发配置冒充 staging）；
        - 持久化后端为 ``postgres``；
        - ``WORKBENCH_REDIS_URL`` 非空且为 ``redis://`` 或 ``rediss://``；
        - ``WORKBENCH_OUTBOX_MAX_ATTEMPTS`` 在 ``1–20`` 合法区间（与 ``app.settings`` 一致）；
        - 若配置了 ``WORKBENCH_DEAD_LETTER_WEBHOOK_URL`` 则必须为 ``https://``；
        - ``WORKBENCH_APPLIED_MIGRATIONS`` 与 ``migrations/*.sql`` 逐一一致。

    联网层（默认执行，``--offline`` 跳过）：
        - 目标地址护栏：必须 https、独立主机（未加 ``--allow-insecure-local`` 时越界即拒绝）；
        - ``GET /api/v1/health`` 应用健康检查；
        - Redis 可达性：标准库 ``socket`` 做 TCP 连接 + RESP ``PING``（可用注入探针离线测试）；
        - 死信运行态：若提供管理员令牌，读取 ``GET /api/v1/dead-letters`` 报告未重放/已通知数量；
        - Outbox 积压：**当前后端没有可读接口**，如实输出 ``skipped``（见下）。

已知缺口（脚本据实输出 ``skipped``，绝不臆造接口）
    - **无 Outbox 积压可读接口**：``workbench_event_outbox`` 仅由 ``OutboxPublisher.publish_pending``
      在内部以 SQL 读取（``WHERE published_at IS NULL``），既无 HTTP 接口也无仓储只读方法，
      因此本脚本无法核对积压数量。
    - **死信运行态需要管理员令牌**：``GET /api/v1/dead-letters`` 仅 CEO / 超级管理员可读；
      未提供 ``--token`` 时输出 ``skipped``。

安全
    - 只读取配置与非敏感元数据，绝不打印任何密钥或令牌；输出只保留主机名。
    - 退出码：``pass`` / ``skipped`` → 0；``fail`` → 1；参数错误 → 2（argparse 默认）。
"""

from __future__ import annotations

import argparse
import os
import socket
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping
from urllib.parse import urlsplit

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

_MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"
_LOCAL_HOSTS = {"", "localhost", "127.0.0.1", "::1", "0.0.0.0"}
_REDIS_SCHEMES = {"redis", "rediss"}

Transport = Callable[..., object]
RedisProbe = Callable[[str], str]


@dataclass(frozen=True)
class PreflightCheck:
    name: str
    status: str
    message: str


@dataclass(frozen=True)
class PreflightReport:
    status: str
    checks: tuple[PreflightCheck, ...]

    def to_text(self) -> str:
        lines = [f"Worker 运行态前置预检结果：{self.status}"]
        lines.extend(f"[{check.status}] {check.name}：{check.message}" for check in self.checks)
        return "\n".join(lines)


def _host(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        return ""
    try:
        parsed = urlsplit(value.strip())
    except ValueError:
        return ""
    return (parsed.hostname or "").lower()


def _redis_scheme_ok(value: object) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        parsed = urlsplit(value.strip())
    except ValueError:
        return False
    return parsed.scheme in _REDIS_SCHEMES and bool(parsed.hostname)


def _expected_migrations() -> list[str]:
    return sorted(path.stem for path in _MIGRATIONS_DIR.glob("*.sql"))


def _as_mapping(config: Mapping[str, object] | None = None) -> dict[str, object]:
    expected = _expected_migrations()
    if config is not None:
        values = dict(config)
        values.setdefault("expected_migrations", expected)
        values.setdefault("base_url", "")
        values.setdefault("token", "")
        return values
    applied = [item.strip() for item in os.getenv("WORKBENCH_APPLIED_MIGRATIONS", "").split(",") if item.strip()]
    return {
        "environment": os.getenv("WORKBENCH_ENV", ""),
        "storage_backend": os.getenv("WORKBENCH_STORAGE_BACKEND", ""),
        "redis_url": os.getenv("WORKBENCH_REDIS_URL", ""),
        "outbox_max_attempts": os.getenv("WORKBENCH_OUTBOX_MAX_ATTEMPTS", ""),
        "dead_letter_webhook_url": os.getenv("WORKBENCH_DEAD_LETTER_WEBHOOK_URL", ""),
        "applied_migrations": applied,
        "expected_migrations": expected,
        "base_url": os.getenv("WORKBENCH_ACCEPTANCE_BASE_URL", ""),
        "token": os.getenv("WORKBENCH_ACCEPTANCE_TOKEN", ""),
    }


def _parse_attempts(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _config_checks(values: Mapping[str, object]) -> list[PreflightCheck]:
    checks: list[PreflightCheck] = []

    environment = values.get("environment")
    if isinstance(environment, str) and environment.strip() and environment.strip().lower() != "development":
        checks.append(PreflightCheck("运行环境", "pass", "已设置为非 development 环境"))
    else:
        checks.append(
            PreflightCheck("运行环境", "fail", "必须设置为非 development 环境（避免用开发配置冒充 staging）")
        )

    if values.get("storage_backend") == "postgres":
        checks.append(PreflightCheck("持久化后端", "pass", "已配置 PostgreSQL 持久化"))
    else:
        checks.append(PreflightCheck("持久化后端", "fail", "必须使用 PostgreSQL 持久化后端"))

    redis_url = values.get("redis_url")
    if _redis_scheme_ok(redis_url):
        checks.append(PreflightCheck("Redis 地址协议", "pass", f"{urlsplit(str(redis_url).strip()).scheme}://{_host(redis_url)}"))
    else:
        checks.append(PreflightCheck("Redis 地址协议", "fail", "缺少 redis:// 或 rediss:// 地址"))

    attempts = _parse_attempts(values.get("outbox_max_attempts"))
    if attempts is not None and 1 <= attempts <= 20:
        checks.append(PreflightCheck("Outbox 最大尝试次数", "pass", f"当前为 {attempts}（合法区间 1–20）"))
    else:
        checks.append(PreflightCheck("Outbox 最大尝试次数", "fail", "必须为 1–20 之间的整数"))

    webhook = values.get("dead_letter_webhook_url")
    if not isinstance(webhook, str) or not webhook.strip():
        checks.append(PreflightCheck("死信通知渠道", "pass", "未配置 Webhook，通知关闭（死信仍可查可重放）"))
    elif webhook.strip().startswith("https://"):
        checks.append(PreflightCheck("死信通知渠道", "pass", f"已配置 https Webhook（{_host(webhook)}，值不显示）"))
    else:
        checks.append(PreflightCheck("死信通知渠道", "fail", "死信通知 Webhook 必须使用 https"))

    expected = {str(item).strip() for item in values.get("expected_migrations") or [] if str(item).strip()}
    applied = {str(item).strip() for item in values.get("applied_migrations") or [] if str(item).strip()}
    if not expected:
        checks.append(PreflightCheck("迁移清单一致", "fail", "未提供待核对的迁移清单"))
    elif applied != expected:
        missing = len(expected - applied)
        extra = len(applied - expected)
        checks.append(
            PreflightCheck("迁移清单一致", "fail", f"迁移清单不一致（缺少 {missing} 项，多出 {extra} 项）")
        )
    else:
        checks.append(PreflightCheck("迁移清单一致", "pass", f"迁移清单一致（{len(expected)} 项）"))

    return checks


def _guard_check(base_url: str, allow_insecure_local: bool) -> PreflightCheck:
    if not isinstance(base_url, str) or not base_url.strip():
        return PreflightCheck(
            "目标地址护栏", "fail", "必须提供 --base-url（或设置 WORKBENCH_ACCEPTANCE_BASE_URL）"
        )
    parsed = urlsplit(base_url.strip())
    scheme = parsed.scheme
    host = (parsed.hostname or "").lower()
    if scheme != "https" and not allow_insecure_local:
        return PreflightCheck("目标地址护栏", "fail", "拒绝：目标必须使用 https（仅联调可加 --allow-insecure-local）")
    if host in _LOCAL_HOSTS and not allow_insecure_local:
        return PreflightCheck(
            "目标地址护栏", "fail", "拒绝：必须指向独立主机，不能回落本地（仅联调可加 --allow-insecure-local）"
        )
    message = f"{scheme}://{host}"
    if allow_insecure_local:
        message += "（已显式允许非 https/本地目标，仅限联调自测）"
    return PreflightCheck("目标地址护栏", "pass", message)


def _get_json(
    url: str, *, headers: Mapping[str, str], transport: Transport | None, timeout: float
) -> tuple[int, object]:
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


def _health_check(base_url: str, transport: Transport | None, timeout: float) -> PreflightCheck:
    url = base_url.rstrip("/") + "/api/v1/health"
    try:
        status_code, payload = _get_json(
            url, headers={"Accept": "application/json"}, transport=transport, timeout=timeout
        )
    except Exception as exc:  # noqa: BLE001 fail-closed
        return PreflightCheck("应用健康检查", "fail", f"获取失败：{type(exc).__name__}")
    if 200 <= status_code < 300 and isinstance(payload, dict) and payload.get("status") == "ok":
        return PreflightCheck("应用健康检查", "pass", f"{_host(url)} 返回 ok")
    return PreflightCheck("应用健康检查", "fail", f"未返回健康状态（HTTP {status_code}）")


def _dead_letter_check(
    base_url: str, token: str, transport: Transport | None, timeout: float
) -> PreflightCheck:
    if not isinstance(token, str) or not token.strip():
        return PreflightCheck(
            "死信运行态",
            "skipped",
            "需要管理员令牌（--token 或 WORKBENCH_ACCEPTANCE_TOKEN），跳过死信运行态核对",
        )
    url = base_url.rstrip("/") + "/api/v1/dead-letters"
    try:
        status_code, payload = _get_json(
            url,
            headers={"Accept": "application/json", "Authorization": f"Bearer {token.strip()}"},
            transport=transport,
            timeout=timeout,
        )
    except Exception as exc:  # noqa: BLE001 fail-closed
        return PreflightCheck("死信运行态", "fail", f"获取失败：{type(exc).__name__}")
    if status_code == 401:
        return PreflightCheck("死信运行态", "fail", "令牌无效或已过期")
    if status_code == 403:
        return PreflightCheck("死信运行态", "fail", "令牌缺少管理员权限（需要 CEO 或超级管理员）")
    if not 200 <= status_code < 300:
        return PreflightCheck("死信运行态", "fail", f"HTTP {status_code}")
    if not isinstance(payload, list):
        return PreflightCheck("死信运行态", "fail", "响应不是死信列表")
    total = len(payload)
    unreplayed = sum(1 for item in payload if isinstance(item, dict) and item.get("replayed_at") is None)
    notified = sum(1 for item in payload if isinstance(item, dict) and item.get("notified_at") is not None)
    return PreflightCheck("死信运行态", "pass", f"死信 {total} 条，未重放 {unreplayed} 条，已通知 {notified} 条")


def _default_redis_probe(redis_url: str) -> str:
    """标准库 socket 做 TCP 连接 + RESP PING；成功后返回 ``host:port``。"""
    parsed = urlsplit(redis_url.strip())
    host = parsed.hostname or ""
    port = parsed.port or 6379
    use_tls = parsed.scheme == "rediss"
    with socket.create_connection((host, port), timeout=5.0) as sock:
        target = sock
        if use_tls:
            import ssl

            target = ssl.create_default_context().wrap_socket(sock, server_hostname=host)
        target.sendall(b"*1\r\n$4\r\nPING\r\n")
        data = target.recv(64)
    if not data.startswith(b"+PONG"):
        raise RuntimeError("Redis 未返回 PONG")
    return f"{host}:{port}"


def _redis_check(redis_url: object, probe: RedisProbe) -> PreflightCheck:
    if not _redis_scheme_ok(redis_url):
        return PreflightCheck("Redis 可达性", "fail", "缺少合法 Redis 地址，无法探测")
    try:
        target = probe(str(redis_url).strip())
    except Exception as exc:  # noqa: BLE001 fail-closed
        return PreflightCheck("Redis 可达性", "fail", f"不可达：{type(exc).__name__}")
    return PreflightCheck("Redis 可达性", "pass", f"TCP+RESP PING 成功（{target}）")


_OUTBOX_BACKLOG_NO_INTERFACE = PreflightCheck(
    "Outbox 积压",
    "skipped",
    "当前后端无可读的 Outbox 积压接口（workbench_event_outbox 仅由 OutboxPublisher 内部 SQL 读取），无法读取积压",
)


def run_preflight(
    config: Mapping[str, object] | None = None,
    *,
    offline: bool = False,
    base_url: str | None = None,
    token: str | None = None,
    allow_insecure_local: bool = False,
    transport: Transport | None = None,
    redis_probe: RedisProbe | None = None,
    timeout: float = 10.0,
) -> PreflightReport:
    values = _as_mapping(config)
    resolved_base = base_url if base_url is not None else str(values.get("base_url") or "")
    resolved_token = token if token is not None else str(values.get("token") or "")

    checks = _config_checks(values)
    if offline:
        checks.append(PreflightCheck("联网运行态校验", "skipped", "已按 --offline 跳过联网与 Redis 探测"))
    else:
        guard = _guard_check(resolved_base, allow_insecure_local)
        checks.append(guard)
        if guard.status == "pass":
            checks.append(_health_check(resolved_base, transport, timeout))
            checks.append(_dead_letter_check(resolved_base, resolved_token, transport, timeout))
        else:
            checks.append(PreflightCheck("应用健康检查", "skipped", "目标地址护栏未通过，未发起请求"))
            checks.append(PreflightCheck("死信运行态", "skipped", "目标地址护栏未通过，未发起请求"))
        checks.append(_redis_check(values.get("redis_url"), redis_probe or _default_redis_probe))
        checks.append(_OUTBOX_BACKLOG_NO_INTERFACE)

    if any(check.status == "fail" for check in checks):
        status = "fail"
    elif all(check.status == "skipped" for check in checks):
        status = "skipped"
    else:
        status = "pass"
    return PreflightReport(status=status, checks=tuple(checks))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="公司工作台 Celery Worker 运行态前置预检")
    parser.add_argument("--offline", action="store_true", help="只做本地配置校验，不发起任何网络/Redis 探测")
    parser.add_argument("--example", action="store_true", help="使用空配置演示 fail-closed 输出")
    parser.add_argument(
        "--base-url", default="", help="受检应用地址（须 https、非本地；也可用 WORKBENCH_ACCEPTANCE_BASE_URL）"
    )
    parser.add_argument(
        "--token", default="", help="管理员会话令牌（不会写入报告；也可用 WORKBENCH_ACCEPTANCE_TOKEN）"
    )
    parser.add_argument(
        "--allow-insecure-local", action="store_true", help="允许 http/本地目标（仅限联调自测）"
    )
    parser.add_argument("--timeout", type=float, default=10.0, help="单请求超时秒数（默认 10）")
    args = parser.parse_args(argv)

    if args.example:
        report = run_preflight({}, offline=True)
    else:
        report = run_preflight(
            None,
            offline=args.offline,
            base_url=(args.base_url or None),
            token=(args.token or None),
            allow_insecure_local=args.allow_insecure_local,
            timeout=args.timeout,
        )
    print(report.to_text())
    return 0 if report.status in {"pass", "skipped"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
