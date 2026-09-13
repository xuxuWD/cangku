"""Python 模型网关（`app/model_gateway`）单元验收 —— 规格 §3.5 P1 第 1/3/4 条。

用**进程内假上游**（非外网、非供应商）验证：
    - 控制面 mint / revoke 需 `mint secret`；
    - 数据面只认短期令牌（存在且未过期），并**透明转发 + 凭据注入**（上游收到供应商密钥，容器侧看不到）；
    - SSE 流式转发；上游超时与重试上限（传输级）显式可控；
    - 计量 / 限流 / 孤儿令牌上限；
    - **数据面不做绑定校验**（`bound` 仅审计元数据，用例 35 ⑥ / 反假 ③ 的判据面）；
    - 审计日志**不含供应商密钥**。
"""

from __future__ import annotations

import http.client
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.model_gateway import (
    FixedWindowRateLimiter,
    GatewayConfigError,
    ModelGateway,
    ModelGatewayConfig,
    TokenStore,
    start_in_thread,
)
from app.model_gateway import tokens as tokens_module
from app.model_gateway.server import LOGGER_NAME

VENDOR_KEY = "sk-vendor-canary-0123456789abcdef"  # 假供应商密钥（非真实凭据）
MINT_SECRET = "unit-gw-mint-secret"


# --------------------------------------------------------------- 假上游

def _make_upstream(state: dict):
    class _Upstream(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):  # noqa: D102 - 静音
            return

        def do_POST(self):  # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""
            state.setdefault("requests", []).append(
                {
                    "path": self.path,
                    "authorization": self.headers.get("Authorization"),
                    "body": body,
                }
            )
            if state.get("sleep_seconds"):
                time.sleep(state["sleep_seconds"])
            try:
                if state.get("sse"):
                    self._send_sse()
                else:
                    self._send_json()
            except (BrokenPipeError, ConnectionResetError):
                return

        def _send_json(self) -> None:
            payload = b'{"id":"chatcmpl-1","choices":[{"message":{"content":"PONG"}}]}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def _send_sse(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            for frame in (b'data: {"delta":"PO"}\n\n', b'data: {"delta":"NG"}\n\n', b"data: [DONE]\n\n"):
                self.wfile.write(f"{len(frame):X}\r\n".encode("ascii") + frame + b"\r\n")
                self.wfile.flush()
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()

    return _Upstream


@pytest.fixture()
def upstream():
    state: dict = {}
    server = ThreadingHTTPServer(("127.0.0.1", 0), _make_upstream(state))
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", state
    finally:
        server.shutdown()
        server.server_close()


def _make_gateway(upstream_base: str, **overrides):
    config = ModelGatewayConfig(
        upstream_base_url=upstream_base,
        upstream_api_key=VENDOR_KEY,
        mint_secret=MINT_SECRET,
        host="127.0.0.1",
        port=0,
        **overrides,
    )
    return start_in_thread(ModelGateway(config))


def _request(method: str, url: str, *, headers=None, body: bytes | None = None):
    from urllib.parse import urlparse

    parsed = urlparse(url)
    conn = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=10)
    target = parsed.path + (f"?{parsed.query}" if parsed.query else "")
    try:
        conn.request(method, target, body=body, headers=headers or {})
        resp = conn.getresponse()
        return resp.status, dict(resp.getheaders()), resp.read()
    finally:
        conn.close()


def _mint(base_url: str, bound: str, secret: str = MINT_SECRET) -> str:
    status, _headers, body = _request(
        "GET", f"{base_url}/__mint?bound={bound}", headers={"X-Mint-Secret": secret}
    )
    assert status == 200, status
    return body.decode()


def _chat(base_url: str, token: str, *, extra_headers=None):
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    headers.update(extra_headers or {})
    return _request("POST", f"{base_url}/chat/completions", headers=headers, body=b'{"stream":true}')


# --------------------------------------------------------------- 控制面 / 数据面

def test_mint_then_chat_forwards_and_injects_vendor_credential(upstream, caplog) -> None:
    upstream_base, state = upstream
    server, base_url = _make_gateway(upstream_base)
    try:
        with caplog.at_level("INFO", logger=LOGGER_NAME):
            token = _mint(base_url, "t-1:task-1:1")
            assert len(token) >= 40
            status, _headers, body = _chat(base_url, token)
        assert status == 200
        assert b"PONG" in body
        # 凭据注入：上游收到的是**供应商密钥**；容器侧只拿短期令牌。
        assert state["requests"][0]["authorization"] == f"Bearer {VENDOR_KEY}"
        assert state["requests"][0]["path"] == "/chat/completions"
        # 审计日志不得回显供应商密钥与完整令牌。
        joined = "\n".join(record.getMessage() for record in caplog.records)
        assert VENDOR_KEY not in joined
        assert token not in joined
    finally:
        server.stop()


def test_sse_stream_is_relayed(upstream) -> None:
    upstream_base, state = upstream
    state["sse"] = True
    server, base_url = _make_gateway(upstream_base)
    try:
        token = _mint(base_url, "turn-sse")
        status, headers, body = _chat(base_url, token)
        assert status == 200
        assert headers.get("Content-Type", "").startswith("text/event-stream")
        assert b'data: {"delta":"PO"}' in body
        assert b"data: [DONE]" in body
    finally:
        server.stop()


def test_unknown_token_is_rejected(upstream) -> None:
    upstream_base, _state = upstream
    server, base_url = _make_gateway(upstream_base)
    try:
        status, _headers, body = _chat(base_url, "not-a-real-token")
        assert status == 401
        assert b"invalid api key" in body
    finally:
        server.stop()


def test_expired_token_is_rejected(upstream) -> None:
    upstream_base, _state = upstream
    server, base_url = _make_gateway(upstream_base, token_ttl_seconds=1)
    try:
        token = _mint(base_url, "turn-expire")
        assert _chat(base_url, token)[0] == 200
        time.sleep(1.1)
        assert _chat(base_url, token)[0] == 401
    finally:
        server.stop()


def test_control_plane_requires_mint_secret(upstream) -> None:
    upstream_base, _state = upstream
    server, base_url = _make_gateway(upstream_base)
    try:
        assert _request("GET", f"{base_url}/__mint?bound=x")[0] == 403
        assert _request("GET", f"{base_url}/__mint?bound=x", headers={"X-Mint-Secret": "wrong"})[0] == 403
        assert _request("GET", f"{base_url}/__tokens")[0] == 403  # 控制面快照同样需密钥
    finally:
        server.stop()


def test_revoke_makes_token_unusable(upstream) -> None:
    upstream_base, _state = upstream
    server, base_url = _make_gateway(upstream_base)
    try:
        token = _mint(base_url, "turn-revoke")
        assert _chat(base_url, token)[0] == 200
        status, _headers, body = _request(
            "GET", f"{base_url}/__revoke?bound=turn-revoke", headers={"X-Mint-Secret": MINT_SECRET}
        )
        assert status == 200 and body == b"revoked 1"
        assert _chat(base_url, token)[0] == 401
    finally:
        server.stop()


# --------------------------------------------------------------- 绑定：数据面不做校验（反假 ③ 的判据面）

def test_data_plane_ignores_bound_claim(upstream) -> None:
    """用例 35 ⑥：网关数据面**不做绑定校验**；容器侧声明 `bound` 无任何效果。"""
    upstream_base, _state = upstream
    server, base_url = _make_gateway(upstream_base)
    try:
        token = _mint(base_url, "tenant-A:session-A:1")
        # 容器自称另一套绑定（含跨租户/跨代次）→ 仍放行（网关只判存在与过期）。
        for claim in ("tenant-B:session-B:9", "unbound", ""):
            status, _headers, _body = _chat(
                base_url,
                token,
                extra_headers={
                    "X-Workbench-Tenant": claim,
                    "X-Workbench-Session": claim,
                    "X-Workbench-Generation": claim,
                },
            )
            assert status == 200
    finally:
        server.stop()


# --------------------------------------------------------------- 超时 / 重试 / 限流 / 孤儿上限

def test_upstream_timeout_and_retry_bound(upstream) -> None:
    upstream_base, state = upstream
    state["sleep_seconds"] = 0.6
    server, base_url = _make_gateway(upstream_base, upstream_timeout_seconds=0.2, max_retries=1)
    try:
        token = _mint(base_url, "turn-timeout")
        started = time.time()
        status, _headers, _body = _chat(base_url, token)
        elapsed = time.time() - started
        assert status == 502
        assert elapsed < 1.2  # 有界：不是无限等待
        assert len(state["requests"]) == 2  # max_retries=1 ⇒ 共 2 次尝试
    finally:
        server.stop()


def test_max_retries_zero_single_attempt(upstream) -> None:
    upstream_base, state = upstream
    state["sleep_seconds"] = 0.6
    server, base_url = _make_gateway(upstream_base, upstream_timeout_seconds=0.2, max_retries=0)
    try:
        token = _mint(base_url, "turn-timeout-0")
        assert _chat(base_url, token)[0] == 502
        assert len(state["requests"]) == 1
    finally:
        server.stop()


def test_orphan_token_limit_refuses_new_mint(upstream) -> None:
    upstream_base, _state = upstream
    server, base_url = _make_gateway(upstream_base, orphan_token_limit=1)
    try:
        _mint(base_url, "turn-1")
        status, _headers, _body = _request(
            "GET", f"{base_url}/__mint?bound=turn-2", headers={"X-Mint-Secret": MINT_SECRET}
        )
        assert status == 429
    finally:
        server.stop()


def test_rate_limit_returns_429(upstream) -> None:
    upstream_base, _state = upstream
    server, base_url = _make_gateway(upstream_base, rate_limit_per_minute=1)
    try:
        token = _mint(base_url, "turn-rate")
        assert _chat(base_url, token)[0] == 200
        assert _chat(base_url, token)[0] == 429
    finally:
        server.stop()


def test_tokens_snapshot_hides_full_token_and_exposes_metering(upstream) -> None:
    upstream_base, _state = upstream
    server, base_url = _make_gateway(upstream_base)
    try:
        token = _mint(base_url, "turn-snap")
        _chat(base_url, token)
        status, _headers, body = _request(
            "GET", f"{base_url}/__tokens", headers={"X-Mint-Secret": MINT_SECRET}
        )
        assert status == 200
        text = body.decode()
        assert token not in text  # 快照不回显完整令牌
        assert "turn-snap" in text  # 但含审计元数据 bound
        assert '"totalRequests": 1' in text
    finally:
        server.stop()


# --------------------------------------------------------------- 令牌库（六条可离线项）

def test_token_six_offline_items() -> None:
    store = TokenStore(orphan_token_limit=2)
    # ① 每 turn 新铸：两次铸造必不同
    a = store.mint(bound="t:1:1", ttl_seconds=300)
    b = store.mint(bound="t:1:2", ttl_seconds=300)
    assert a != b
    # ② 绑定只是审计元数据（快照可见，但不参与判定）
    snapshot = {item["id"]: item["bound"] for item in store.snapshot()}
    assert snapshot[a[:6]] == "t:1:1"
    # ③ 服务端为准：库外令牌一律拒绝
    assert store.authorize("forged-token") is None
    assert store.authorize(a).bound == "t:1:1"
    # ⑥ 孤儿上限：已满（a、b 两枚）时拒绝新铸
    with pytest.raises(tokens_module.OrphanTokenLimitExceeded):
        store.mint(bound="t:1:3", ttl_seconds=300)
    # ⑤ 终态同步吊销
    assert store.revoke(bound="t:1:1") == 1
    assert store.authorize(a) is None


def test_expiry_is_enforced_in_store() -> None:
    store = TokenStore()
    token = store.mint(bound="t:1:1", ttl_seconds=1, now=1000.0)
    assert store.authorize(token, now=1000.5) is not None
    assert store.authorize(token, now=1001.5) is None  # 过期即拒


def test_authorize_uses_constant_time_primitive(monkeypatch) -> None:
    """用例 35 ④ 判据：以「调用 constant-time 原语」为准（不以计时为判据）。"""
    calls: list[tuple[str, str]] = []
    real = tokens_module.hmac.compare_digest

    def spy(left, right):
        calls.append((left, right))
        return real(left, right)

    monkeypatch.setattr(tokens_module.hmac, "compare_digest", spy)
    store = TokenStore()
    token = store.mint(bound="t:1:1", ttl_seconds=300)
    assert store.authorize(token) is not None
    assert calls, "authorize 必须调用 hmac.compare_digest（constant-time 原语）"


# --------------------------------------------------------------- 组件级

def test_rate_limiter_window_resets() -> None:
    limiter = FixedWindowRateLimiter(1)
    assert limiter.allow("k", now=0.0) is True
    assert limiter.allow("k", now=1.0) is False
    assert limiter.allow("k", now=61.0) is True  # 下一窗口


def test_upstream_forwarder_rejects_bad_base_url() -> None:
    with pytest.raises(GatewayConfigError):
        ModelGatewayConfig(
            upstream_base_url="not-a-url", upstream_api_key="", mint_secret=MINT_SECRET
        )


def test_config_requires_mint_secret() -> None:
    with pytest.raises(GatewayConfigError):
        ModelGatewayConfig(upstream_base_url="https://api.example.com", upstream_api_key="k", mint_secret="")


def test_config_from_env_shape() -> None:
    env = {
        "WORKBENCH_MODEL_GATEWAY_UPSTREAM_BASE_URL": "https://api.deepseek.com",
        "WORKBENCH_MODEL_GATEWAY_UPSTREAM_API_KEY": VENDOR_KEY,
        "WORKBENCH_MODEL_GATEWAY_MINT_SECRET": MINT_SECRET,
        "WORKBENCH_MODEL_GATEWAY_TOKEN_TTL_SECONDS": "300",
        "WORKBENCH_MODEL_GATEWAY_UPSTREAM_TIMEOUT_SECONDS": "60",
        "WORKBENCH_MODEL_GATEWAY_MAX_RETRIES": "0",
        "WORKBENCH_MODEL_GATEWAY_PORT": "8080",
    }
    config = ModelGatewayConfig.from_env(env)
    assert config.has_upstream_key is True
    assert config.token_ttl_seconds == 300
    empty = ModelGatewayConfig.from_env({**env, "WORKBENCH_MODEL_GATEWAY_UPSTREAM_API_KEY": ""})
    assert empty.has_upstream_key is False  # 只暴露布尔，不回显密钥


def test_default_rate_limit_allows_requests(upstream) -> None:
    upstream_base, _state = upstream
    server, base_url = _make_gateway(upstream_base)
    try:
        token = _mint(base_url, "turn-default")
        for _ in range(3):
            assert _chat(base_url, token)[0] == 200
    finally:
        server.stop()


def test_mint_secret_setting_is_registered_and_templated() -> None:
    """网关控制面密钥必须作为外置配置登记（Settings + staging 模板）。"""
    from pathlib import Path

    from app.settings import Settings

    root = Path(__file__).resolve().parents[1]
    assert "model_gateway_mint_secret" in Settings.model_fields
    assert Settings.model_fields["model_gateway_mint_secret"].default == ""
    template = (root / ".env.staging.example").read_text(encoding="utf-8")
    assert "WORKBENCH_MODEL_GATEWAY_MINT_SECRET=" in template
