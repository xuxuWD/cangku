"""模型网关 HTTP 服务（规格 §3.5 P1）。

面划分：
    - **控制面**（`/__mint` / `/__revoke` / `/__tokens`）：需 `X-Mint-Secret` 鉴权，
      供**工作台控制面**（容器外）铸造 / 吊销令牌、查看在册快照；
    - **数据面**（其余全部路径，即 OpenAI 兼容的 `chat/completions`，含 SSE）：只认
      `Authorization: Bearer <短期令牌>`，**只判「存在且未过期」**，随后透明转发到上游。

职责：凭据注入 + 转发 + 计量/限流 + 审计；**不改写模型语义**。
审计日志**只允许出现令牌前缀**与状态码，**绝不含令牌全文 / 供应商密钥**。
"""

from __future__ import annotations

import hmac
import json
import logging
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from .config import ModelGatewayConfig
from .tokens import OrphanTokenLimitExceeded, TokenStore
from .upstream import UpstreamForwarder, UpstreamTransportError

LOGGER_NAME = "company_workbench.model_gateway"
CONTROL_PATHS = ("/__mint", "/__revoke", "/__tokens")
CHUNK_SIZE = 65536
# 逐跳头（RFC 7230 §6.1）：不得原样透传；`content-length` 因改分块编码而剔除。
HOP_BY_HOP = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
        "content-length",
    }
)


def get_logger() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)


class FixedWindowRateLimiter:
    """按令牌的固定窗口限流（每分钟 `limit` 次）；`limit <= 0` = 关闭。"""

    def __init__(self, limit_per_minute: int) -> None:
        self.limit_per_minute = limit_per_minute
        self._windows: dict[str, tuple[int, int]] = {}

    def allow(self, key: str, *, now: float | None = None) -> bool:
        if self.limit_per_minute <= 0:
            return True
        moment = time.time() if now is None else now
        window = int(moment // 60)
        current_window, count = self._windows.get(key, (window, 0))
        if current_window != window:
            current_window, count = window, 0
        if count >= self.limit_per_minute:
            self._windows[key] = (current_window, count)
            return False
        self._windows[key] = (current_window, count + 1)
        return True


class Metering:
    """最小计量：总请求数 / 按状态码计数（供 `/__tokens` 与审计读取）。"""

    def __init__(self) -> None:
        self.total_requests = 0
        self.denied = 0
        self.by_status: dict[int, int] = {}

    def record_request(self) -> None:
        self.total_requests += 1

    def record_denied(self) -> None:
        self.denied += 1

    def record_status(self, status: int, *, bytes_out: int = 0) -> None:
        self.by_status[status] = self.by_status.get(status, 0) + 1


class ModelGateway:
    """网关本体：控制面 + 数据面的纯逻辑（可脱离 socket 单测）。"""

    def __init__(
        self,
        config: ModelGatewayConfig,
        *,
        token_store: TokenStore | None = None,
        forwarder: UpstreamForwarder | None = None,
        rate_limiter: FixedWindowRateLimiter | None = None,
        meter: Metering | None = None,
    ) -> None:
        self.config = config
        self.tokens = token_store or TokenStore(orphan_token_limit=config.orphan_token_limit)
        self.forwarder = forwarder or UpstreamForwarder(
            base_url=config.upstream_base_url,
            api_key=config.upstream_api_key,
            timeout_seconds=config.upstream_timeout_seconds,
            max_retries=config.max_retries,
        )
        self.rate_limiter = rate_limiter or FixedWindowRateLimiter(config.rate_limit_per_minute)
        self.meter = meter or Metering()
        self.logger = get_logger()

    # ------------------------------------------------------------------ 控制面

    def secret_ok(self, presented: str | None) -> bool:
        """constant-time 校验控制面密钥（④ 同口径）。"""
        return bool(presented) and hmac.compare_digest(str(presented), self.config.mint_secret)

    def mint(self, bound: str) -> str:
        token = self.tokens.mint(bound=bound, ttl_seconds=self.config.token_ttl_seconds)
        self.logger.info(
            "MINT id=%s.. bound=%s ttl=%ss total=%d",
            token[:6],
            bound or "unbound",
            self.config.token_ttl_seconds,
            self.tokens.live_count,
        )
        return token

    def revoke(self, bound: str) -> int:
        count = self.tokens.revoke(bound=bound)
        self.logger.info("REVOKE bound=%s n=%d total=%d", bound, count, self.tokens.live_count)
        return count


class _GatewayHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "WorkbenchModelGateway/1"

    @property
    def gateway(self) -> ModelGateway:
        return self.server.gateway  # type: ignore[attr-defined]

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: D102 - 静音默认 stderr
        return

    # ------------------------------------------------------------------ 路由

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        self._dispatch()

    def do_POST(self) -> None:  # noqa: N802 - http.server API
        self._dispatch()

    def _dispatch(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path in CONTROL_PATHS:
                self._control(parsed.path, parse_qs(parsed.query))
            else:
                self._data_plane(parsed)
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception as exc:  # noqa: BLE001 - 网关不得因单请求崩溃
            self.gateway.logger.error("网关处理异常：%s", type(exc).__name__)
            self._send_error_json(502, "gateway error")

    # ------------------------------------------------------------------ 控制面

    def _control(self, path: str, query: dict[str, list[str]]) -> None:
        peer = self.client_address[0]
        if not self.gateway.secret_ok(self.headers.get("X-Mint-Secret")):
            self.gateway.logger.warning("ADMIN-DENY path=%s peer=%s", path, peer)
            self._send_text(403, "forbidden")
            return
        if path == "/__mint":
            bound = (query.get("bound") or ["unbound"])[0]
            try:
                token = self.gateway.mint(bound)
            except OrphanTokenLimitExceeded as exc:
                self.gateway.logger.error("MINT-DENY reason=orphan-limit peer=%s", peer)
                self._send_text(429, str(exc))
                return
            self._send_text(200, token)
            return
        if path == "/__revoke":
            bound = (query.get("bound") or [""])[0]
            count = self.gateway.revoke(bound)
            self._send_text(200, f"revoked {count}")
            return
        payload = {
            "tokens": self.gateway.tokens.snapshot(),
            "metering": {
                "totalRequests": self.gateway.meter.total_requests,
                "denied": self.gateway.meter.denied,
                "byStatus": self.gateway.meter.by_status,
            },
        }
        self._send_json(200, payload)

    # ------------------------------------------------------------------ 数据面

    def _data_plane(self, parsed) -> None:
        peer = self.client_address[0]
        token = self._bearer_token()
        record = self.gateway.tokens.authorize(token) if token else None
        if record is None:
            self.gateway.meter.record_denied()
            self.gateway.logger.warning("DENY path=%s reason=unknown-or-expired peer=%s", parsed.path, peer)
            self._send_json(
                401, {"error": {"message": "invalid api key", "type": "authentication_error"}}
            )
            return
        # 限流：按令牌（不按 bound —— bound 是审计元数据，不参与判定）。
        if not self.gateway.rate_limiter.allow(token):
            self.gateway.meter.record_denied()
            self.gateway.logger.warning("DENY path=%s reason=rate-limited peer=%s", parsed.path, peer)
            self._send_json(
                429, {"error": {"message": "rate limited", "type": "rate_limit_error"}}
            )
            return

        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length > 0 else b""
        forwarded = {
            key: value
            for key, value in self.headers.items()
            if key.lower() not in HOP_BY_HOP and key.lower() not in ("host", "authorization")
        }
        self.gateway.meter.record_request()
        self.gateway.logger.info(
            "UPSTREAM-REQ %s %s token=%s.. peer=%s",
            self.command,
            parsed.path,
            token[:6],
            peer,
        )
        try:
            upstream = self.gateway.forwarder.request(self.command, parsed.path, forwarded, body)
        except UpstreamTransportError as exc:
            self.gateway.logger.error(
                "UPSTREAM-ERR token=%s.. kind=%s", token[:6], type(exc).__name__
            )
            self._send_error_json(502, "bad gateway")
            return
        try:
            self._relay(upstream)
        finally:
            upstream.close()

    def _bearer_token(self) -> str:
        header = self.headers.get("Authorization") or ""
        prefix, _, value = header.partition(" ")
        if prefix.lower() != "bearer" or not value:
            return ""
        return value.strip()

    def _relay(self, upstream) -> None:
        token = self._bearer_token()
        self.gateway.logger.info(
            "UPSTREAM-RES status=%s token=%s.. attempts=%s",
            upstream.status,
            token[:6],
            upstream.attempts,
        )
        self.send_response(upstream.status)
        for key, value in upstream.headers:
            if key.lower() in HOP_BY_HOP:
                continue
            self.send_header(key, value)
        no_body = upstream.status in (204, 304) or self.command == "HEAD"
        if no_body:
            self.send_header("Content-Length", "0")
            self.end_headers()
            self.gateway.meter.record_status(upstream.status)
            return
        # SSE / 常规响应统一改分块编码转发，避免依赖上游是否带 Content-Length。
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        bytes_out = 0
        while True:
            chunk = upstream.read(CHUNK_SIZE)
            if not chunk:
                break
            bytes_out += len(chunk)
            self.wfile.write(f"{len(chunk):X}\r\n".encode("ascii"))
            self.wfile.write(chunk)
            self.wfile.write(b"\r\n")
        self.wfile.write(b"0\r\n\r\n")
        self.wfile.flush()
        self.gateway.meter.record_status(upstream.status, bytes_out=bytes_out)

    # ------------------------------------------------------------------ 回写

    def _send_text(self, status: int, body: str) -> None:
        payload = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_error_json(self, status: int, message: str) -> None:
        self._send_json(status, {"error": {"message": message, "type": "gateway_error"}})


class ModelGatewayServer:
    """把 `ModelGateway` 挂到 `ThreadingHTTPServer` 上（可线程内起停，供单测与进程入口共用）。"""

    def __init__(self, gateway: ModelGateway) -> None:
        self.gateway = gateway
        self._httpd: ThreadingHTTPServer | None = None

    def _build(self) -> ThreadingHTTPServer:
        httpd = ThreadingHTTPServer(
            (self.gateway.config.host, self.gateway.config.port), _GatewayHandler
        )
        httpd.daemon_threads = True
        httpd.gateway = self.gateway  # type: ignore[attr-defined]
        return httpd

    def start(self) -> None:
        self._httpd = self._build()
        self.gateway.logger.info(
            "LISTEN %s:%d upstream=%s hasUpstreamKey=%s hasMintSecret=%s",
            self.gateway.config.host,
            self.gateway.config.port,
            self.gateway.config.upstream_base_url,
            self.gateway.config.has_upstream_key,
            bool(self.gateway.config.mint_secret),
        )
        self._httpd.serve_forever()

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None

    @property
    def port(self) -> int:
        if self._httpd is None:
            return self.gateway.config.port
        return self._httpd.server_address[1]


def start_in_thread(gateway: ModelGateway) -> tuple[ModelGatewayServer, str]:
    """在后台线程起服务（单测用）；返回 (server, base_url)。"""
    import threading

    server = ModelGatewayServer(gateway)
    thread = threading.Thread(target=server.start, daemon=True)
    thread.start()
    # 等端口就绪（`start` 内先 bind 后 serve）。
    deadline = time.time() + 5
    while time.time() < deadline:
        if server._httpd is not None:  # noqa: SLF001 - 测试辅助
            break
        time.sleep(0.01)
    base_url = f"http://127.0.0.1:{server.port}"
    return server, base_url
