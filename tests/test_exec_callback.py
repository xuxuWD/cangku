"""§5 用例 35：短期令牌绑定强制在**真边车端点**上的端到端取证（规格 §3.5 P1 第 3 条 ②④ / §8 U20 方案 b-1）。

与 `tests/test_token_binding.py`（纯内存）互补：本文件对 `app/exec_callback` 起的**真 HTTP
端点**取证——判定落点 = 工作台控制面（边车侧），恒定时间比对，`expected` 只来自**服务端权威**。

六条（沿用 §5 用例 35 口径）：
    ① 令牌与当前执行不匹配 → `403`（不泄露存在性）；
    ② 跨租户 → `403`；③ 旧代次 → `403`；④ 完全匹配 → `200`（并经**受控转发**交回工作台）；
    ⑤ 容器侧伪造绑定声明（请求体 `binding` / `claimed_binding`）**无效果**；
    ⑥ 网关数据面不做绑定（本文件补一条「边车只判定 + 转发，不把凭证面交给转发层」的静态断言）。

另含**暴露面**断言（门禁 §B14 判据 E）：**只有 `POST /internal/exec-callback` 一条路由**、
**只绑一个端口**。
"""

from __future__ import annotations

import http.client
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import pytest

from app.audit.models import AuditAction
from app.exec_callback import (
    CALLBACK_PATH,
    ActiveExecutionRegistry,
    build_plane,
    start_in_thread,
)
from app.tool_execution.token_binding import TokenBinding, TokenBindingStore


class RecordingAudit:
    def __init__(self) -> None:
        self.calls: list[tuple[AuditAction, dict]] = []

    def record(self, action: AuditAction, **kwargs) -> None:
        self.calls.append((action, kwargs))


class _WorkbenchStub:
    """假工作台回调接收端（进程内、非外网）：记录边车转发来的载荷。"""

    def __init__(self) -> None:
        self.received: list[dict] = []
        self._state = self

        class _Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):  # noqa: D102 - 静音
                return

            def do_POST(self):  # noqa: N802
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b"{}"
                try:
                    self.server.received.append(json.loads(body.decode("utf-8")))
                except ValueError:
                    self.server.received.append({"_raw": body.decode("utf-8", "replace")})
                payload = b'{"status":"ok"}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self._server.daemon_threads = True
        self._server.received = self.received  # type: ignore[attr-defined]
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}/workbench/exec-callback"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()


@pytest.fixture()
def workbench():
    stub = _WorkbenchStub()
    try:
        yield stub
    finally:
        stub.stop()


class Sidecar:
    """起一个真边车端点，并暴露其权威存储 / 登记表 / 审计，供用例布置与断言。"""

    def __init__(self, workbench_url: str) -> None:
        self.store = TokenBindingStore()
        self.registry = ActiveExecutionRegistry()
        self.audit = RecordingAudit()
        self.plane = build_plane(
            forward_url=workbench_url,
            binding_store=self.store,
            registry=self.registry,
            audit=self.audit,
        )
        self.server, self.base = start_in_thread(self.plane, host="127.0.0.1", port=0)

    def stop(self) -> None:
        self.server.stop()

    def post(self, *, path: str = CALLBACK_PATH, query: str = "", token: str | None = None,
             body: dict | None = None) -> tuple[int, dict]:
        parsed = urlparse(self.base)
        conn = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=10)
        headers = {"Content-Type": "application/json"}
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        payload = json.dumps(body).encode("utf-8") if body is not None else b""
        target = path + (f"?{query}" if query else "")
        try:
            conn.request("POST", target, body=payload, headers=headers)
            response = conn.getresponse()
            raw = response.read().decode("utf-8", "replace")
            return response.status, (json.loads(raw) if raw else {})
        finally:
            conn.close()

    def get(self, path: str) -> int:
        parsed = urlparse(self.base)
        conn = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=10)
        try:
            conn.request("GET", path)
            return conn.getresponse().status
        finally:
            conn.close()


@pytest.fixture()
def sidecar(workbench):
    car = Sidecar(workbench.url)
    try:
        yield car
    finally:
        car.stop()


# ------------------------------------------------------------------ 用例 35（真端点）

def test_case_35_1_token_does_not_match_current_execution_is_denied(sidecar, workbench) -> None:
    # 令牌给 sess-A 铸的，回调却声明的当前执行是 sess-B。
    sidecar.store.record(token="tok-A", binding=TokenBinding("t-1", "sess-A", 1))
    sidecar.registry.register(TokenBinding("t-1", "sess-B", 1))

    status, body = sidecar.post(query="session_id=sess-B", token="tok-A")

    assert status == 403
    # 不泄露存在性：文案固定，不含会话 / 租户 / 代次 / 运行标识。
    assert "sess-B" not in json.dumps(body)
    assert "sess-A" not in json.dumps(body)
    assert workbench.received == []  # 拒绝不得转发
    assert [action for action, _ in sidecar.audit.calls] == [AuditAction.TOOL_BLOCKED]


def test_case_35_2_cross_tenant_is_denied(sidecar, workbench) -> None:
    sidecar.store.record(token="tok-1", binding=TokenBinding("t-1", "sess-A", 1))
    # 当前执行隶属另一租户（服务端权威登记）。
    sidecar.registry.register(TokenBinding("t-2", "sess-A", 1))

    status, _ = sidecar.post(query="session_id=sess-A", token="tok-1")

    assert status == 403
    assert workbench.received == []
    assert sidecar.audit.calls


def test_case_35_3_stale_generation_is_denied(sidecar, workbench) -> None:
    sidecar.store.record(token="tok-old", binding=TokenBinding("t-1", "sess-A", 1))
    sidecar.registry.register(TokenBinding("t-1", "sess-A", 1))
    sidecar.registry.register(TokenBinding("t-1", "sess-A", 2))  # 会话已进入第 2 代

    status, _ = sidecar.post(query="session_id=sess-A", token="tok-old")

    assert status == 403
    assert workbench.received == []


def test_case_35_4_exact_match_is_allowed_and_forwarded(sidecar, workbench) -> None:
    sidecar.store.record(token="tok-1", binding=TokenBinding("t-1", "sess-A", 3))
    for generation in (1, 2, 3):
        sidecar.registry.register(TokenBinding("t-1", "sess-A", generation))

    status, body = sidecar.post(
        query="session_id=sess-A", token="tok-1", body={"run_id": "run-1", "tool_key": "artifact.export"}
    )

    assert status == 200 and body == {"status": "accepted"}
    # 判定通过后由「边车 → 工作台」的受控出向调用交回工作台。
    assert len(workbench.received) == 1
    forwarded = workbench.received[0]
    assert forwarded["tenant_id"] == "t-1"
    assert forwarded["session_id"] == "sess-A"
    assert forwarded["generation"] == 3
    assert not sidecar.audit.calls  # 放行不记拒绝审计


def test_case_35_5_forged_container_declaration_has_no_effect(sidecar, workbench) -> None:
    sidecar.store.record(token="tok-1", binding=TokenBinding("t-1", "sess-A", 1))
    sidecar.registry.register(TokenBinding("t-1", "sess-A", 1))

    # 情形一：容器谎报成别的绑定 —— 仍按服务端权威放行（声明被忽略）。
    status, _ = sidecar.post(
        query="session_id=sess-A",
        token="tok-1",
        body={"claimed_binding": {"tenant_id": "t-9", "session_id": "sess-Z", "generation": 99}},
    )
    assert status == 200

    # 情形二：当前执行已是第 2 代，容器谎报成"与服务端当前一致" —— 仍拒绝（伪造无效）。
    sidecar.registry.register(TokenBinding("t-1", "sess-A", 2))
    status, _ = sidecar.post(
        query="session_id=sess-A",
        token="tok-1",
        body={"binding": {"tenant_id": "t-1", "session_id": "sess-A", "generation": 2}},
    )
    assert status == 403


def test_case_35_6_gateway_and_forwarder_do_not_decide() -> None:
    """⑥ 网关数据面不得做绑定：绑定逻辑只在控制面（`token_binding` / 边车判定）。"""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    gateway_src = (root / "app" / "tool_execution" / "gateway_token.py").read_text(encoding="utf-8")
    for forbidden in ("compare_digest", "TokenBinding", "ControlPlaneBindingVerifier"):
        assert forbidden not in gateway_src
    # 边车的**转发器**只转发，不判定：源码内不得出现绑定比对原语。
    server_src = (root / "app" / "exec_callback" / "server.py").read_text(encoding="utf-8")
    forwarder_src = server_src.split("class ExecCallbackPlane", 1)[0]
    assert "compare_digest" not in forwarder_src


# ------------------------------------------------------------------ 暴露面（门禁 §B14 判据 E）

def test_only_the_single_callback_route_is_exposed(sidecar) -> None:
    # 其余路径一律 404（无静态资源 / 无健康检查 / 无其它路由）。
    assert sidecar.get("/") == 404
    assert sidecar.get("/healthz") == 404
    assert sidecar.post(path="/internal/exec-callback/extra")[0] == 404
    assert sidecar.post(path="/internal/exec-callbac")[0] == 404
    # 唯一端点：非 POST → 405。
    assert sidecar.get(CALLBACK_PATH) == 405
    # 无令牌 → 403（且不泄露存在性）。
    status, _ = sidecar.post(query="session_id=sess-A")
    assert status == 403


def test_sidecar_binds_exactly_one_port(monkeypatch, workbench) -> None:
    from app.exec_callback import server as server_mod

    created: list[object] = []
    real = server_mod.ThreadingHTTPServer

    class _Counting(real):  # type: ignore[misc, valid-type]
        def __init__(self, *args, **kwargs):
            created.append(args[0] if args else None)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(server_mod, "ThreadingHTTPServer", _Counting)
    car = Sidecar(workbench.url)
    try:
        assert len(created) == 1  # 只绑一个端口、只起一个监听器
    finally:
        car.stop()


# ------------------------------------------------------------------ 登记表口径（generation）

def test_registry_generation_is_monotonic_from_one() -> None:
    registry = ActiveExecutionRegistry()
    with pytest.raises(ValueError):
        registry.register(TokenBinding("t-1", "sess-A", 2))  # 首次必须为 1
    registry.register(TokenBinding("t-1", "sess-A", 1))
    with pytest.raises(ValueError):
        registry.register(TokenBinding("t-1", "sess-A", 1))  # 不得重复
    with pytest.raises(ValueError):
        registry.register(TokenBinding("t-2", "sess-A", 2))  # 不得中途跨租户
    registry.register(TokenBinding("t-1", "sess-A", 2))
    assert registry.current_for("sess-A") == TokenBinding("t-1", "sess-A", 2)
    assert registry.current_for("sess-unknown") is None
