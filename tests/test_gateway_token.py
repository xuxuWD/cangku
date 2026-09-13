"""短期网关令牌控制面客户端（§3.5 P1 第 3 条：⑤ 终态同步吊销）的单元验收。

用进程内桩网关（**非真实外网 / 非真实供应商**）验证：
    - 控制面需要密钥（错密钥 → 拒）；
    - `mint` → 数据面可用（对照组成功）；
    - `revoke` → **同一令牌复用被拒**（⑤ 的核心判据）；
    - 终态吊销器可注入 `ContainerExecutor.token_revoker`。
"""

from __future__ import annotations

import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pytest

from app.tool_execution.errors import ToolExecutionConfigError
from app.tool_execution.gateway_token import (
    GatewayControlError,
    GatewayTokenClient,
    build_terminal_state_revoker,
)

SECRET = "unit-test-mint-secret"


class _GatewayStub(BaseHTTPRequestHandler):
    """最小网关桩：控制面（铸/吊销）+ 数据面（只认在册令牌）。"""

    tokens: dict[str, str] = {}

    def log_message(self, *args):  # noqa: D102 - 静音
        return

    def _write(self, status: int, body: str) -> None:
        payload = body.encode()
        self.send_response(status)
        self.send_header("content-type", "text/plain")
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):  # noqa: N802 - http.server API
        parsed = urlparse(self.path)
        if parsed.path in ("/__mint", "/__revoke"):
            if self.headers.get("X-Mint-Secret") != SECRET:
                self._write(403, "forbidden")
                return
            if parsed.path == "/__mint":
                bound = parse_qs(parsed.query).get("bound", ["unbound"])[0]
                token = f"tok-{len(self.tokens) + 1}"
                self.tokens[token] = bound
                self._write(200, token)
                return
            bound = parse_qs(parsed.query).get("bound", [""])[0]
            revoked = 0
            for token, owner in list(self.tokens.items()):
                if owner == bound:
                    del self.tokens[token]
                    revoked += 1
            self._write(200, f"revoked {revoked}")
            return
        auth = self.headers.get("Authorization", "")
        token = auth.split(" ", 1)[1] if auth.startswith("Bearer ") else ""
        if token not in self.tokens:
            self._write(401, '{"error":{"message":"invalid api key"}}')
            return
        self._write(200, '{"ok":true}')


@pytest.fixture()
def gateway():
    _GatewayStub.tokens = {}
    server = ThreadingHTTPServer(("127.0.0.1", 0), _GatewayStub)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", _GatewayStub
    finally:
        server.shutdown()
        server.server_close()


def _data_plane_status(base_url: str, token: str) -> int:
    request = urllib.request.Request(
        f"{base_url}/chat/completions",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code


def test_mint_then_data_plane_ok(gateway) -> None:
    base_url, _ = gateway
    client = GatewayTokenClient(base_url=base_url, admin_secret=SECRET)
    token = client.mint("run-1")
    assert _data_plane_status(base_url, token) == 200  # 对照组：成功


def test_revoke_makes_token_reuse_rejected(gateway) -> None:
    base_url, _ = gateway
    client = GatewayTokenClient(base_url=base_url, admin_secret=SECRET)
    token = client.mint("run-2")
    assert _data_plane_status(base_url, token) == 200

    assert client.revoke("run-2") == 1  # 终态同步吊销
    assert _data_plane_status(base_url, token) == 401  # 同一令牌复用被拒

    # 对照组：新铸令牌仍可用（排除「网关全拒」的假象）
    fresh = client.mint("run-2")
    assert _data_plane_status(base_url, fresh) == 200


def test_control_plane_requires_secret(gateway) -> None:
    base_url, _ = gateway
    client = GatewayTokenClient(base_url=base_url, admin_secret="wrong")
    with pytest.raises(GatewayControlError):
        client.mint("run-3")


def test_revoker_is_callable_as_terminal_state_hook(gateway) -> None:
    base_url, _ = gateway
    revoke = build_terminal_state_revoker(base_url=base_url, admin_secret=SECRET)
    revoke("run-4")  # 不抛即通过；绑定不匹配时吊销 0 个也属正常


def test_blank_secret_is_refused() -> None:
    with pytest.raises(ToolExecutionConfigError):
        GatewayTokenClient(base_url="http://127.0.0.1:1", admin_secret="")
