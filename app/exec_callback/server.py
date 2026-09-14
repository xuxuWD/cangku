"""执行回调边车 HTTP 服务（规格 §3.5 P1 第 3 条 ②④ / §8 U20 方案 b-1）。

暴露面（**唯一**，可被门禁 §B14 判据 E 逐条核对）：
    - **只监听一个端口**（`ExecCallbackConfig.listen_port`）；
    - **只暴露一个端点**：`POST /internal/exec-callback`；其余路径一律 `404`，其余方法一律 `405`；
      **无**静态资源、**无**健康检查、**无**其它路由。

②④ 强制校验（**判定在工作台控制面 = 本边车**，恒定时间比对）：
    1. 请求头 `Authorization: Bearer <短期令牌>` 取令牌；
    2. `expected` **从服务端权威上下文重建**：查询参数 `session_id` 只是**查找键**，
       用它去 `ActiveExecutionRegistry`（由工作台控制面登记）取**该会话当前执行**的绑定；
       **绝不**以请求体中的任何绑定声明为准；
    3. 交给 `ControlPlaneBindingVerifier` 做 `constant-time` 比对：令牌**与当前执行不匹配 /
       跨租户 / 旧代次 / 未知令牌** 一律 `403`（**不泄露存在性**、文案固定）、并记审计
       （复用既有动作码 `tool.blocked`，**不新增动作码**）；
    4. 放行后经「**边车 → 工作台**」的**受控出向调用**交回工作台——容器**不直连**工作台。

⚠️ 边车**只做判定 + 受控转发**：不改写回调用途 / 语义、不动迁移、不新增审计动作码。
⚠️ 本模块为**标准库实现**（边车镜像只装标准库）。
"""

from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Mapping

from ..tool_execution.token_binding import (
    BindingDenied,
    ControlPlaneBindingVerifier,
    TokenBinding,
)
from .registry import ActiveExecutionRegistry

LOGGER_NAME = "company_workbench.exec_callback"
CALLBACK_PATH = "/internal/exec-callback"
MAX_BODY_BYTES = 65536
# 必不匹配的占位绑定：会话无活动执行 / 未给出时会话选择器时，用它把请求引到
# `verify` 的统一拒绝路径（恒定时间比对 + 审计），避免绕开审计。
_NO_MATCH_SEP = "__no_active_execution__"


def get_logger() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)


@dataclass(frozen=True)
class CallbackOutcome:
    """一次回调处理的结果（纯数据，供 HTTP 层回写）。"""

    status: int
    body: dict[str, Any]


class WorkbenchForwarder:
    """「边车 → 工作台」的**受控出向调用**（唯一允许的转发路径）。

    只转发**已通过 ②④ 校验**的绑定与回调载荷；容器**不能**直连工作台（它在
    `workbench-exec-internal` 上，无通往工作台默认网络的路由）。
    """

    def __init__(self, *, forward_url: str, timeout_seconds: float = 10.0) -> None:
        if not isinstance(forward_url, str) or not forward_url.strip():
            raise ValueError("未配置工作台转发地址，拒绝启用转发")
        self.forward_url = forward_url.strip()
        self.timeout_seconds = float(timeout_seconds)

    def forward(self, *, binding: TokenBinding, payload: Mapping[str, Any]) -> int:
        """把已校验的回调交回工作台；返回工作台侧 HTTP 状态码（网络失败返回 `502`）。"""
        body = json.dumps(
            {
                "tenant_id": binding.tenant_id,
                "session_id": binding.session_id,
                "generation": int(binding.generation),
                "callback": dict(payload),
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            self.forward_url,
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                return int(response.status)
        except urllib.error.HTTPError as exc:  # 工作台侧拒绝（4xx/5xx）
            get_logger().warning("边车→工作台转发被拒：HTTP %s", exc.code)
            return int(exc.code)
        except urllib.error.URLError as exc:  # 不可达 / 超时
            get_logger().error("边车→工作台转发失败：%s", type(exc.reason).__name__)
            return 502


class ExecCallbackPlane:
    """边车本体：②④ 判定 + 受控转发的**纯逻辑**（可脱离 socket 单测）。"""

    def __init__(
        self,
        *,
        verifier: ControlPlaneBindingVerifier,
        registry: Any,
        forwarder: WorkbenchForwarder,
        logger: logging.Logger | None = None,
    ) -> None:
        self.verifier = verifier
        self.registry = registry
        self.forwarder = forwarder
        self.logger = logger or get_logger()

    # ------------------------------------------------------------------ 入口

    def handle(
        self,
        *,
        method: str,
        path: str,
        query: Mapping[str, list[str]],
        headers: Any,
        body: bytes,
    ) -> CallbackOutcome:
        # 暴露面收敛：非唯一端点 → 404；非 POST → 405。
        if path != CALLBACK_PATH:
            return CallbackOutcome(404, {"error": "not found"})
        if method.upper() != "POST":
            return CallbackOutcome(405, {"error": "method not allowed"})

        token = self._bearer(headers)
        session_id = self._first(query, "session_id")
        payload = self._parse_body(body)

        # `expected` ＝ 服务端权威「当前执行」；请求体中的绑定声明**一律不参与判定**。
        expected = self.registry.current_for(session_id)
        if expected is None:
            expected = TokenBinding(_NO_MATCH_SEP, session_id or _NO_MATCH_SEP, 0)

        try:
            binding = self.verifier.verify(
                token=token,
                expected=expected,
                run_id=self._payload_text(payload, "run_id"),
                tool_key=self._payload_text(payload, "tool_key"),
                # 执行侧（容器）声明的绑定：**刻意透传以证明被忽略**（`verify` 内 `del`）。
                claimed_binding=self._claimed_binding(payload),
            )
        except BindingDenied:
            return CallbackOutcome(403, {"error": "forbidden"})

        status = self.forwarder.forward(binding=binding, payload=self._forward_payload(payload))
        if status >= 400:
            return CallbackOutcome(502, {"error": "forward failed"})
        return CallbackOutcome(200, {"status": "accepted"})

    # ------------------------------------------------------------------ 内部

    @staticmethod
    def _first(query: Mapping[str, list[str]], key: str) -> str:
        values = (query or {}).get(key) or []
        return (values[0] if values else "").strip()

    @staticmethod
    def _bearer(headers: Any) -> str:
        raw = ""
        if headers is not None:
            raw = headers.get("Authorization") or ""
        prefix, _, value = raw.partition(" ")
        if prefix.lower() != "bearer":
            return ""
        return value.strip()

    @staticmethod
    def _parse_body(body: bytes) -> dict[str, Any]:
        if not body:
            return {}
        try:
            parsed = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}

    @staticmethod
    def _payload_text(payload: Mapping[str, Any], key: str) -> str | None:
        value = payload.get(key)
        return value if isinstance(value, str) and value else None

    @staticmethod
    def _claimed_binding(payload: Mapping[str, Any]) -> TokenBinding | None:
        """解析请求体里的「绑定声明」——**只为显式表达不读它**，不作为判定输入。"""
        raw = payload.get("claimed_binding") or payload.get("binding")
        if not isinstance(raw, dict):
            return None
        tenant = raw.get("tenant_id")
        session = raw.get("session_id")
        generation = raw.get("generation")
        if not isinstance(tenant, str) or not isinstance(session, str):
            return None
        try:
            return TokenBinding(tenant, session, int(generation))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _forward_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
        """转发载荷：剔除任何「绑定声明」字段，避免把一个不可信声明原样带给工作台。"""
        return {
            key: value
            for key, value in (payload or {}).items()
            if key not in ("binding", "claimed_binding")
        }


def build_plane(
    *,
    forward_url: str,
    binding_store: Any | None = None,
    registry: Any | None = None,
    audit: Any | None = None,
    forward_timeout_seconds: float = 10.0,
) -> ExecCallbackPlane:
    """装配边车本体（唯一构造路径：控制面侧与进程入口共用，避免第二事实源）。

    - `binding_store` ＝ 工作台侧**自持绑定**（`token -> TokenBinding`，mint 时落）；
      生产部署中须与**签发令牌**的那一份是**同一实例**（否则不成其为「服务端为准」）；
    - `registry` ＝ 服务端权威「当前执行」登记表；
    - `audit` ＝ 审计落点；未注入时不写审计（判定本身不受影响）。
    """
    from ..tool_execution.token_binding import TokenBindingStore

    store = binding_store if binding_store is not None else TokenBindingStore()
    active = registry if registry is not None else ActiveExecutionRegistry()
    verifier = ControlPlaneBindingVerifier(store=store, audit=audit)
    forwarder = WorkbenchForwarder(forward_url=forward_url, timeout_seconds=forward_timeout_seconds)
    return ExecCallbackPlane(verifier=verifier, registry=active, forwarder=forwarder)


class _CallbackHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "WorkbenchExecCallback/1"

    @property
    def plane(self) -> ExecCallbackPlane:
        return self.server.plane  # type: ignore[attr-defined]

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: D102 - 静音默认 stderr
        return

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        self._dispatch("GET")

    def do_POST(self) -> None:  # noqa: N802 - http.server API
        self._dispatch("POST")

    def _dispatch(self, method: str) -> None:
        from urllib.parse import parse_qs, urlparse

        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY_BYTES:
            self._send(CallbackOutcome(413, {"error": "payload too large"}))
            return
        body = self.rfile.read(length) if length > 0 else b""
        try:
            outcome = self.plane.handle(
                method=method,
                path=parsed.path,
                query=parse_qs(parsed.query),
                headers=self.headers,
                body=body,
            )
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception as exc:  # noqa: BLE001 - 边车不得因单请求崩溃
            self.plane.logger.error("边车处理异常：%s", type(exc).__name__)
            outcome = CallbackOutcome(500, {"error": "internal"})
        self._send(outcome)

    def _send(self, outcome: CallbackOutcome) -> None:
        payload = json.dumps(outcome.body).encode("utf-8")
        self.send_response(outcome.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


class ExecCallbackServer:
    """把 `ExecCallbackPlane` 挂到 `ThreadingHTTPServer` 上（**单端口**；可线程内起停）。"""

    def __init__(self, plane: ExecCallbackPlane, *, host: str, port: int) -> None:
        self.plane = plane
        self.host = host
        self.port = int(port)
        self._httpd: ThreadingHTTPServer | None = None

    def start(self) -> None:
        self._httpd = ThreadingHTTPServer((self.host, self.port), _CallbackHandler)
        self._httpd.daemon_threads = True
        self._httpd.plane = self.plane  # type: ignore[attr-defined]
        # 启动行只打印监听面与「转发地址是否已配置」，**不回显任何密钥 / 令牌**。
        self.plane.logger.info(
            "LISTEN %s:%d forward=%s", self.host, self.port, bool(self.plane.forwarder.forward_url)
        )
        self._httpd.serve_forever()

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None

    @property
    def bound_port(self) -> int:
        if self._httpd is None:
            return self.port
        return int(self._httpd.server_address[1])


def start_in_thread(plane: ExecCallbackPlane, *, host: str = "127.0.0.1", port: int = 0):
    """在后台线程起边车服务（单测用）；返回 `(server, base_url)`。"""
    server = ExecCallbackServer(plane, host=host, port=port)
    thread = threading.Thread(target=server.start, daemon=True)
    thread.start()
    deadline = time.time() + 5
    while time.time() < deadline:
        if server._httpd is not None:  # noqa: SLF001 - 测试辅助
            break
        time.sleep(0.01)
    return server, f"http://{host}:{server.bound_port}"
