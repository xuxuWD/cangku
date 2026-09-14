"""§5 用例 35：短期令牌绑定强制在**新拓扑**下的取证（规格 §3.5 P1 第 3 条 ②④ / §8 U21 裁决「候选②」）。

拓扑（2026-09-14 返工）：
    执行容器 →（`workbench-exec-internal`）→ **边车（无状态纯转发）** →（回调网）→ **工作台接收端点**。
    ②④ **判定在工作台**（权威状态处）：`expected` 从工作台权威状态重建、**绝不取自请求体**，
    与令牌自持绑定做 `constant-time` 比对；不匹配 / 跨租户 / 旧代次 / 未知令牌 → `403`（不泄露存在性）
    + 记审计（复用 `tool.blocked`，不新增动作码）。边车**不做任何判定**（连令牌都不解析）。

本文件三块取证：
    A. **工作台判定**（用例 35 六条 + 未知令牌 + 鉴权 + 限流）—— 打真 app 端点（`TestClient`）；
    B. **边车纯转发**（无判定、原样透传、暴露面收敛）；
    C. **单进程端到端**（真边车 HTTP 服务 → 真工作台 HTTP 服务，uvicorn 同进程另起监听）。
"""

from __future__ import annotations

import ast
import http.client
import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from app import main
from app.audit.models import AuditAction
from app.exec_callback import CALLBACK_PATH, SHARED_SECRET_HEADER, build_plane, start_in_thread
from app.main import WORKBENCH_EXEC_CALLBACK_PATH, app
from app.tool_execution.active_execution import ActiveExecutionRegistry
from app.tool_execution.callback_guard import CallbackRateLimiter, WorkbenchCallbackGuard
from app.tool_execution.token_binding import TokenBinding, TokenBindingStore

ROOT = Path(__file__).resolve().parents[1]
PSK = "psk-under-test"


class RecordingAudit:
    def __init__(self) -> None:
        self.calls: list[tuple[AuditAction, dict]] = []

    def record(self, action: AuditAction, **kwargs) -> None:
        self.calls.append((action, kwargs))


# ==================================================================== A. 工作台判定

client = TestClient(app)


@pytest.fixture()
def workbench_env(monkeypatch):
    """给真 app 端点注入**权威状态**与预共享密钥（判定在工作台）。"""
    store = TokenBindingStore()
    registry = ActiveExecutionRegistry()
    audit = RecordingAudit()
    guard = WorkbenchCallbackGuard(store=store, registry=registry, audit=audit)
    monkeypatch.setattr(main, "workbench_callback_guard", guard)
    monkeypatch.setattr(main, "exec_callback_limiter", CallbackRateLimiter(rate_per_second=100.0))
    monkeypatch.setattr(main.settings, "exec_callback_shared_secret", PSK)
    return SimpleNamespace(store=store, registry=registry, audit=audit, guard=guard)


def callback_post(
    *,
    token: str | None = None,
    session_id: str | None = None,
    body: dict | None = None,
    key: str | None = PSK,
) -> tuple[int, dict]:
    headers: dict[str, str] = {}
    if key is not None:
        headers[SHARED_SECRET_HEADER] = key
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    params = {"session_id": session_id} if session_id is not None else None
    response = client.post(
        WORKBENCH_EXEC_CALLBACK_PATH, params=params, headers=headers, json=body or {}
    )
    return response.status_code, response.json()


def test_case_35_1_token_does_not_match_current_execution_is_denied(workbench_env) -> None:
    # 令牌给 sess-A 铸的，回调却指向的当前执行是 sess-B。
    workbench_env.store.record(token="tok-A", binding=TokenBinding("t-1", "sess-A", 1))
    workbench_env.registry.register(TokenBinding("t-1", "sess-B", 1))

    status, body = callback_post(token="tok-A", session_id="sess-B")

    assert status == 403
    # 不泄露存在性：文案固定，不含会话 / 租户 / 代次 / 运行标识。
    assert "sess-B" not in json.dumps(body)
    assert "sess-A" not in json.dumps(body)
    assert [action for action, _ in workbench_env.audit.calls] == [AuditAction.TOOL_BLOCKED]


def test_case_35_2_cross_tenant_is_denied(workbench_env) -> None:
    workbench_env.store.record(token="tok-1", binding=TokenBinding("t-1", "sess-A", 1))
    # 当前执行隶属另一租户（服务端权威登记）。
    workbench_env.registry.register(TokenBinding("t-2", "sess-A", 1))

    status, _ = callback_post(token="tok-1", session_id="sess-A")

    assert status == 403
    assert workbench_env.audit.calls


def test_case_35_3_stale_generation_is_denied(workbench_env) -> None:
    workbench_env.store.record(token="tok-old", binding=TokenBinding("t-1", "sess-A", 1))
    workbench_env.registry.register(TokenBinding("t-1", "sess-A", 1))
    workbench_env.registry.register(TokenBinding("t-1", "sess-A", 2))  # 会话已进入第 2 代

    status, _ = callback_post(token="tok-old", session_id="sess-A")

    assert status == 403


def test_case_35_4_exact_match_is_allowed(workbench_env) -> None:
    workbench_env.store.record(token="tok-1", binding=TokenBinding("t-1", "sess-A", 3))
    for generation in (1, 2, 3):
        workbench_env.registry.register(TokenBinding("t-1", "sess-A", generation))

    status, body = callback_post(
        token="tok-1", session_id="sess-A", body={"run_id": "run-1", "tool_key": "artifact.export"}
    )

    assert status == 200 and body == {"status": "accepted"}
    assert not workbench_env.audit.calls  # 放行不记拒绝审计


def test_case_35_5_forged_container_declaration_has_no_effect(workbench_env) -> None:
    workbench_env.store.record(token="tok-1", binding=TokenBinding("t-1", "sess-A", 1))
    workbench_env.registry.register(TokenBinding("t-1", "sess-A", 1))

    # 情形一：请求体谎报成别的绑定 —— 仍按服务端权威放行（声明被忽略）。
    status, _ = callback_post(
        token="tok-1",
        session_id="sess-A",
        body={"claimed_binding": {"tenant_id": "t-9", "session_id": "sess-Z", "generation": 99}},
    )
    assert status == 200

    # 情形二：当前执行已是第 2 代，请求体谎报成"与服务端当前一致" —— 仍拒绝（伪造无效）。
    workbench_env.registry.register(TokenBinding("t-1", "sess-A", 2))
    status, _ = callback_post(
        token="tok-1",
        session_id="sess-A",
        body={"binding": {"tenant_id": "t-1", "session_id": "sess-A", "generation": 2}},
    )
    assert status == 403


def test_case_35_6_decision_is_not_in_the_sidecar_or_gateway() -> None:
    """⑥ 绑定判定不在网关数据面、也**不在边车**：只在工作台（`token_binding` / `callback_guard`）。"""
    gateway_src = (ROOT / "app" / "tool_execution" / "gateway_token.py").read_text(encoding="utf-8")
    for forbidden in ("compare_digest", "TokenBinding", "ControlPlaneBindingVerifier"):
        assert forbidden not in gateway_src
    # 边车包的**全部**模块都不得出现判定原语 / 判定构件（按 AST 判，避开"文档里提到"）。
    assert _sidecar_identifier_refs() == set(), (
        f"边车不得持有判定逻辑，命中：{_sidecar_identifier_refs()}"
    )
    assert "tool_execution" not in _sidecar_imported_modules()


def test_unknown_token_is_denied_without_leaking_existence(workbench_env) -> None:
    workbench_env.registry.register(TokenBinding("t-1", "sess-A", 1))

    status, body = callback_post(token="never-issued", session_id="sess-A")

    assert status == 403
    assert body == {"detail": "forbidden"}
    assert workbench_env.audit.calls


def test_missing_or_wrong_shared_secret_is_denied(workbench_env) -> None:
    workbench_env.store.record(token="tok-1", binding=TokenBinding("t-1", "sess-A", 1))
    workbench_env.registry.register(TokenBinding("t-1", "sess-A", 1))

    # 缺失即拒（fail-closed）：即便令牌与绑定完全匹配，无密钥也一律 403。
    assert callback_post(token="tok-1", session_id="sess-A", key=None)[0] == 403
    assert callback_post(token="tok-1", session_id="sess-A", key="wrong")[0] == 403
    # 未配置密钥时同样拒（不是"未配置就放行"）。
    main.settings.exec_callback_shared_secret = ""
    try:
        assert callback_post(token="tok-1", session_id="sess-A")[0] == 403
    finally:
        main.settings.exec_callback_shared_secret = PSK


def test_rate_limit_is_100rps_and_returns_429(monkeypatch, workbench_env) -> None:
    """限流 = 100 rps（超限 429）：与时钟联动，`0.01s` 恰好回补 1 个令牌。"""
    workbench_env.store.record(token="tok-1", binding=TokenBinding("t-1", "sess-A", 1))
    workbench_env.registry.register(TokenBinding("t-1", "sess-A", 1))
    now = [1000.0]
    monkeypatch.setattr(
        main,
        "exec_callback_limiter",
        CallbackRateLimiter(rate_per_second=100.0, capacity=1.0, clock=lambda: now[0]),
    )

    assert callback_post(token="tok-1", session_id="sess-A")[0] == 200  # 消耗唯一令牌
    assert callback_post(token="tok-1", session_id="sess-A")[0] == 429  # 超限
    now[0] += 0.02  # 100 rps ⇒ 0.02s 回补 2 个令牌（上限 1）
    assert callback_post(token="tok-1", session_id="sess-A")[0] == 200
    now[0] += 0.001  # 回补 0.1 个令牌，不足一个
    assert callback_post(token="tok-1", session_id="sess-A")[0] == 429


def test_sidecar_refuses_to_start_without_shared_secret() -> None:
    """边车侧「缺失即拒绝启动」：配置校验与装配器两处都 fail-closed。"""
    from app.exec_callback import ExecCallbackConfig, ExecCallbackConfigError

    with pytest.raises(ExecCallbackConfigError):
        ExecCallbackConfig.from_env(
            {"WORKBENCH_EXEC_CALLBACK_FORWARD_URL": "http://workbench:8000/api/v1/internal/exec-callback"}
        )
    with pytest.raises(ValueError):
        build_plane(forward_url="http://workbench:8000/api/v1/internal/exec-callback", shared_secret="")


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


# ==================================================================== 边车纯转发


class _WorkbenchStub:
    """假工作台回调接收端（进程内、非外网）：记录边车转发来的方法 / 查询 / 头 / 体。"""

    def __init__(self, status: int = 200, body: bytes = b'{"status":"accepted"}') -> None:
        self.received: list[dict] = []
        self.status = status
        self.response_body = body

        class _Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):  # noqa: D102 - 静音
                return

            def do_POST(self):  # noqa: N802
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                parsed = urlparse(self.path)
                self.server.received.append(
                    {
                        "path": parsed.path,
                        "query": parse_qs(parsed.query),
                        "authorization": self.headers.get("Authorization"),
                        "psk": self.headers.get(SHARED_SECRET_HEADER),
                        "body": raw,
                    }
                )
                payload = self.server.response_body
                self.send_response(self.server.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self._server.daemon_threads = True
        self._server.received = self.received  # type: ignore[attr-defined]
        self._server.status = status  # type: ignore[attr-defined]
        self._server.response_body = body  # type: ignore[attr-defined]
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}/api/v1/internal/exec-callback"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()


class Sidecar:
    """起一个真边车端点，指向给定的工作台 stub。"""

    def __init__(self, workbench_url: str, *, shared_secret: str = "sidecar-psk") -> None:
        self.plane = build_plane(forward_url=workbench_url, shared_secret=shared_secret)
        self.server, self.base = start_in_thread(self.plane, host="127.0.0.1", port=0)

    def stop(self) -> None:
        self.server.stop()

    def _request(self, method: str, path: str, *, token: str | None = None, body: bytes = b""):
        parsed = urlparse(self.base)
        conn = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=10)
        headers = {"Content-Type": "application/json"}
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        try:
            conn.request(method, path, body=body, headers=headers)
            response = conn.getresponse()
            return response.status, response.read()
        finally:
            conn.close()

    def post(self, *, query: str = "", token: str | None = None, body: bytes = b""):
        return self._request("POST", CALLBACK_PATH + (f"?{query}" if query else ""), token=token, body=body)

    def get(self, path: str) -> int:
        return self._request("GET", path)[0]


@pytest.fixture()
def workbench_stub():
    stub = _WorkbenchStub()
    try:
        yield stub
    finally:
        stub.stop()


@pytest.fixture()
def sidecar(workbench_stub):
    car = Sidecar(workbench_stub.url)
    try:
        yield car
    finally:
        car.stop()


def test_sidecar_is_a_pure_forwarder(sidecar, workbench_stub) -> None:
    """边车**不判定**：无论令牌真假，一律原样转发（连查询串与请求体都不改写）。"""
    status, _ = sidecar.post(
        query="session_id=sess-A",
        token="totally-unknown-token",
        body=json.dumps({"run_id": "run-1", "tool_key": "artifact.export"}).encode(),
    )

    assert status == 200  # 由工作台 stub 决定；边车只是透传
    assert len(workbench_stub.received) == 1
    forwarded = workbench_stub.received[0]
    assert forwarded["path"] == "/api/v1/internal/exec-callback"
    assert forwarded["query"] == {"session_id": ["sess-A"]}
    assert forwarded["authorization"] == "Bearer totally-unknown-token"
    assert forwarded["psk"] == "sidecar-psk"
    assert json.loads(forwarded["body"].decode()) == {"run_id": "run-1", "tool_key": "artifact.export"}


def test_sidecar_passes_through_workbench_rejection(workbench_stub) -> None:
    """工作台的拒绝语义（`403`）由边车**原样透传**——判定不在边车，边车不"二次解释"。"""
    workbench_stub._server.status = 403  # type: ignore[attr-defined]
    workbench_stub._server.response_body = b'{"error":"forbidden"}'  # type: ignore[attr-defined]
    car = Sidecar(workbench_stub.url)
    try:
        status, body = car.post(query="session_id=sess-A", token="any")
    finally:
        car.stop()
    assert status == 403
    assert json.loads(body.decode()) == {"error": "forbidden"}


def test_sidecar_reports_502_when_workbench_unreachable(workbench_stub) -> None:
    car = Sidecar("http://127.0.0.1:1/api/v1/internal/exec-callback")
    try:
        status, _ = car.post(query="session_id=sess-A", token="any")
    finally:
        car.stop()
    assert status == 502


def test_only_the_single_callback_route_is_exposed(sidecar) -> None:
    # 其余路径一律 404（无静态资源 / 无健康检查 / 无其它路由）。
    assert sidecar.get("/") == 404
    assert sidecar.get("/healthz") == 404
    assert sidecar._request("POST", "/internal/exec-callback/extra")[0] == 404
    assert sidecar._request("POST", "/internal/exec-callbac")[0] == 404
    # 唯一端点：非 POST → 405。
    assert sidecar.get(CALLBACK_PATH) == 405


def test_sidecar_binds_exactly_one_port(monkeypatch, workbench_stub) -> None:
    from app.exec_callback import server as server_mod

    created: list[object] = []
    real = server_mod.ThreadingHTTPServer

    class _Counting(real):  # type: ignore[misc, valid-type]
        def __init__(self, *args, **kwargs):
            created.append(args[0] if args else None)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(server_mod, "ThreadingHTTPServer", _Counting)
    car = Sidecar(workbench_stub.url)
    try:
        assert len(created) == 1  # 只绑一个端口、只起一个监听器
    finally:
        car.stop()


# ==================================================================== C. 单进程端到端


def _free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


@pytest.fixture()
def live_workbench(workbench_env):
    """用 uvicorn 在本进程另起监听，使「边车 → 真工作台」走**真 HTTP**（仍单进程，非两容器）。"""
    uvicorn = pytest.importorskip("uvicorn")
    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 15
    while time.time() < deadline and not server.started:
        time.sleep(0.02)
    if not server.started:
        server.should_exit = True
        pytest.skip("uvicorn 未能在本机起监听，跳过端到端")
    try:
        yield f"http://127.0.0.1:{port}{WORKBENCH_EXEC_CALLBACK_PATH}"
    finally:
        server.should_exit = True
        thread.join(timeout=15)


def test_end_to_end_sidecar_forwards_to_workbench_decision(live_workbench, workbench_env) -> None:
    """真边车 → 真工作台：**成功路径**与**拒绝路径**都走完整链路（单进程内两监听）。"""
    car = Sidecar(live_workbench, shared_secret=PSK)
    try:
        workbench_env.store.record(token="tok-1", binding=TokenBinding("t-1", "sess-A", 3))
        for generation in (1, 2, 3):
            workbench_env.registry.register(TokenBinding("t-1", "sess-A", generation))

        ok_status, ok_body = car.post(
            query="session_id=sess-A",
            token="tok-1",
            body=json.dumps({"run_id": "run-e2e", "tool_key": "artifact.export"}).encode(),
        )
        assert ok_status == 200, ok_body

        # 拒绝路径：旧代次令牌（会话已进入第 4 代）。
        workbench_env.registry.register(TokenBinding("t-1", "sess-A", 4))
        deny_status, deny_body = car.post(query="session_id=sess-A", token="tok-1")
        assert deny_status == 403, deny_body
        assert workbench_env.audit.calls  # 拒绝记审计（复用 `tool.blocked`）
    finally:
        car.stop()


# ==================================================================== 静态"纯转发"证据


_FORBIDDEN_SIDECAR_NAMES = {
    "compare_digest",
    "hmac",
    "TokenBinding",
    "TokenBindingStore",
    "ControlPlaneBindingVerifier",
    "ActiveExecutionRegistry",
    "WorkbenchCallbackGuard",
    "BindingDenied",
    "constant_time_equal",
}


def _sidecar_identifier_refs() -> set[str]:
    """按 AST 收集边车包内所有被**引用**的标识符（避开文档字符串里的词）。"""
    names: set[str] = set()
    for path in sorted((ROOT / "app" / "exec_callback").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                names.add(node.id)
            elif isinstance(node, ast.Attribute):
                names.add(node.attr)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    names.add(alias.name)
            elif isinstance(node, ast.ImportFrom):
                names.add(node.module or "")
                for alias in node.names:
                    names.add(alias.name)
    return names & _FORBIDDEN_SIDECAR_NAMES


def _sidecar_imported_modules() -> set[str]:
    modules: set[str] = set()
    for path in sorted((ROOT / "app" / "exec_callback").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                modules.add(node.module)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    modules.add(alias.name)
    return modules


def test_sidecar_source_has_no_decision_components() -> None:
    """边车"纯转发"的**代码级**证据：包内不引用任何判定构件、不导入 `app.tool_execution.*`。"""
    assert _sidecar_identifier_refs() == set()
    assert "tool_execution" not in _sidecar_imported_modules()
