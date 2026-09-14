"""执行回调边车 HTTP 服务（规格 §3.5 P1 第 3 条 ②④ / §8 U20 方案 b-1 / §8 U21 裁决路线）。

暴露面（**唯一**，可被门禁 §B14 判据 E 逐条核对）：
    - **只监听一个端口**（`ExecCallbackConfig.listen_port`）；
    - **只暴露一个端点**：`POST /internal/exec-callback`；其余路径一律 `404`，其余方法一律 `405`；
      **无**静态资源、**无**健康检查、**无**其它路由。

职责（**2026-09-14 返工，§8 U21 裁决「候选②：边车纯转发 + 判定回工作台」**）：
    边车是**无状态纯转发**——收到回调后，**原样转发**到工作台侧的回调接收端点
    （`WORKBENCH_EXEC_CALLBACK_FORWARD_URL`），随行附带**预共享密钥**（对称鉴权）。
    **边车不做任何判定**：不持有 `TokenBindingStore` / 「当前执行」登记表，不比对令牌 / 绑定，
    不解析请求体做取舍。②④ 判定一律在**工作台**（`app/tool_execution/callback_guard.py`）
    的权威状态处完成；拒绝 / 限流的 HTTP 语义由工作台返回，边车**原样透传**。

⚠️ 本模块为**标准库实现**（边车镜像只装标准库），**不导入** `app.tool_execution.*` 的判定组件。
⚠️ 边车不做判定 ⇒ 源码内**不得**出现 `compare_digest` / `TokenBinding` 等绑定比对原语
（`tests/test_exec_callback.py` 有静态断言守住）。
"""

from __future__ import annotations

import logging
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

LOGGER_NAME = "company_workbench.exec_callback"
CALLBACK_PATH = "/internal/exec-callback"
# 边车 → 工作台 的预共享密钥请求头（对称鉴权；值不落日志、不回显）。
SHARED_SECRET_HEADER = "X-Exec-Callback-Key"
MAX_BODY_BYTES = 65536


def get_logger() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)


@dataclass(frozen=True)
class CallbackOutcome:
    """一次回调处理的结果（纯数据，供 HTTP 层回写）。"""

    status: int
    body: bytes


class WorkbenchForwarder:
    """「边车 → 工作台」的**受控出向调用**（**纯转发**：不加判定、不加改写）。

    只把收到的请求（方法固定 `POST` + 原始查询串 + 原始请求体 + `Authorization` 令牌）
    **原样**投递到工作台接收端点，并附带预共享密钥。工作台返回的状态码 / 响应体**原样透传**。
    """

    def __init__(
        self,
        *,
        forward_url: str,
        shared_secret: str,
        timeout_seconds: float = 10.0,
    ) -> None:
        if not isinstance(forward_url, str) or not forward_url.strip():
            raise ValueError("未配置工作台转发地址，拒绝启用转发")
        if not isinstance(shared_secret, str) or not shared_secret.strip():
            raise ValueError("未配置「边车→工作台」预共享密钥，拒绝启用转发（fail-closed）")
        self.forward_url = forward_url.strip()
        self.shared_secret = shared_secret.strip()
        self.timeout_seconds = float(timeout_seconds)

    def forward(self, *, query: str, authorization: str | None, body: bytes) -> tuple[int, bytes]:
        """把回调**原样**交回工作台；返回 `(状态码, 响应体)`（网络失败返回 `502`）。"""
        target = self.forward_url + (f"?{query}" if query else "")
        headers = {
            "Content-Type": "application/json",
            SHARED_SECRET_HEADER: self.shared_secret,
        }
        if authorization:
            headers["Authorization"] = authorization
        request = urllib.request.Request(
            target, data=body or b"", method="POST", headers=headers
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                return int(response.status), response.read()
        except urllib.error.HTTPError as exc:  # 工作台侧拒绝（4xx/5xx）：原样透传
            get_logger().warning("边车→工作台转发被拒：HTTP %s", exc.code)
            try:
                passthrough = exc.read()
            except Exception:  # noqa: BLE001 - 读不到就回固定体
                passthrough = b""
            return int(exc.code), passthrough
        except urllib.error.URLError as exc:  # 不可达 / 超时
            get_logger().error("边车→工作台转发失败：%s", type(exc.reason).__name__)
            return 502, b'{"error":"upstream unreachable"}'


class ExecCallbackPlane:
    """边车本体：**纯转发**的纯逻辑（可脱离 socket 单测；**不含任何判定**）。"""

    def __init__(self, *, forwarder: WorkbenchForwarder, logger: logging.Logger | None = None) -> None:
        self.forwarder = forwarder
        self.logger = logger or get_logger()

    # ------------------------------------------------------------------ 入口

    def handle(
        self,
        *,
        method: str,
        path: str,
        query: str = "",
        headers: Any = None,
        body: bytes = b"",
    ) -> CallbackOutcome:
        # 暴露面收敛：非唯一端点 → 404；非 POST → 405。
        if path != CALLBACK_PATH:
            return CallbackOutcome(404, b'{"error":"not found"}')
        if method.upper() != "POST":
            return CallbackOutcome(405, b'{"error":"method not allowed"}')

        # **纯转发**：不读令牌、不解析请求体、不做任何取舍；工作台的状态码 / 响应体原样透传。
        status, response_body = self.forwarder.forward(
            query=query,
            authorization=self._authorization(headers),
            body=body,
        )
        return CallbackOutcome(status, response_body)

    # ------------------------------------------------------------------ 内部

    @staticmethod
    def _authorization(headers: Any) -> str | None:
        """仅**透传**原始 `Authorization` 值（不解析、不校验——判定在工作台）。"""
        if headers is None:
            return None
        raw = headers.get("Authorization")
        return raw.strip() if isinstance(raw, str) and raw.strip() else None


def build_plane(
    *,
    forward_url: str,
    shared_secret: str,
    forward_timeout_seconds: float = 10.0,
) -> ExecCallbackPlane:
    """装配边车本体（唯一构造路径：进程入口使用）。

    边车**只做转发** ⇒ 不再接受 `binding_store` / `registry` / `audit` 等判定构件；
    判定的权威状态与组件都在**工作台**（`app/tool_execution/callback_guard.py`）。
    """
    forwarder = WorkbenchForwarder(
        forward_url=forward_url,
        shared_secret=shared_secret,
        timeout_seconds=forward_timeout_seconds,
    )
    return ExecCallbackPlane(forwarder=forwarder)


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
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY_BYTES:
            self._send(CallbackOutcome(413, b'{"error":"payload too large"}'))
            return
        body = self.rfile.read(length) if length > 0 else b""
        try:
            outcome = self.plane.handle(
                method=method,
                path=parsed.path,
                # **原样**转发查询串（不改写、不重组），判定所需的选择器由工作台自行解释。
                query=parsed.query,
                headers=self.headers,
                body=body,
            )
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception as exc:  # noqa: BLE001 - 边车不得因单请求崩溃
            self.plane.logger.error("边车处理异常：%s", type(exc).__name__)
            outcome = CallbackOutcome(500, b'{"error":"internal"}')
        self._send(outcome)

    def _send(self, outcome: CallbackOutcome) -> None:
        payload = outcome.body or b""
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


__all__ = [
    "CALLBACK_PATH",
    "SHARED_SECRET_HEADER",
    "CallbackOutcome",
    "ExecCallbackPlane",
    "ExecCallbackServer",
    "WorkbenchForwarder",
    "build_plane",
    "get_logger",
    "start_in_thread",
]
