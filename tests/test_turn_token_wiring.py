"""§3.5 P1 第 3 条 ②④⑤ 的**生产接线**取证（规格 §8 U24 / §8 U25 A2 / §8 U26）。

覆盖**写入侧**接线（§8 U24 缺的那一半）：
    - 一次 turn（= 一次 ⑧ 容器执行）开始 ⇒ mint + `TokenBindingStore.record` + `ActiveExecutionRegistry.register`；
    - 容器 spec 里**确有 env**（短期网关令牌 + 网关内网地址，**无供应商密钥**）；
    - 终态 ⇒ `registry.retire` + 网关 `revoke`（⑧ 的 `token_revoker` 出口）；
    - 共享单例：mint 侧（写）与回调判定侧（读）**同一实例** ⇒ 进行中的回调可放行、终态后恒拒。

用**进程内桩网关**（非真实外网 / 非真实供应商）+ **假 Docker 客户端**（不起真容器）。
**未验证**：真实 dsh turn / 真实容器内 env 实跑（见报告"未验证项"）。
"""

from __future__ import annotations

import base64
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pytest

from app.runtime.adapters.dsh import ENV_API_KEY, ENV_BASE_URL, FORBIDDEN_IN_CONTAINER_ENV_NAMES
from app.tool_execution.active_execution import ActiveExecutionRegistry
from app.tool_execution.body_cipher import BodyCipher
from app.tool_execution.callback_guard import WorkbenchCallbackGuard
from app.tool_execution.catalog import ToolSpecCatalog, default_tool_specs
from app.tool_execution.errors import ToolExecutionConfigError
from app.tool_execution.executor import ContainerExecutor, DeterministicFakeExecutor
from app.tool_execution.gateway_token import GatewayControlError
from app.tool_execution.service import ToolExecutionRequest, ToolExecutionService
from app.tool_execution.startup import assert_real_execution_ready
from app.tool_execution.store import InMemoryToolActionStore
from app.tool_execution.token_binding import BindingDenied, TokenBinding, TokenBindingStore
from app.tool_execution.turn_token import TurnTokenController, bound_label
from app.tool_execution.workspace import WorkspaceManager

SECRET = "unit-test-mint-secret"
VENDOR_KEY = "sk-vendor-key-must-never-enter-container"
GATEWAY_URL = "http://gw.internal:8080"
IMAGE = "registry.local/dsh@sha256:" + "a" * 64


# ---------------------------------------------------------------- 桩网关

class _GatewayStub(BaseHTTPRequestHandler):
    tokens: dict[str, str] = {}
    revokes: list[str] = []

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
        if parsed.path not in ("/__mint", "/__revoke"):
            self._write(404, "not found")
            return
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
        hit = [tok for tok, owner in list(self.tokens.items()) if owner == bound]
        for tok in hit:
            del self.tokens[tok]
        self.revokes.append(bound)
        self._write(200, f"revoked {len(hit)}")


@pytest.fixture()
def gateway():
    _GatewayStub.tokens = {}
    _GatewayStub.revokes = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _GatewayStub)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


# ---------------------------------------------------------------- 假 Docker 客户端

class _FakeContainer:
    def __init__(self, kwargs: dict) -> None:
        self.id = "c-fake-1"
        self.kwargs = kwargs
        self.removed = False
        self.killed = False

    def wait(self, timeout=None):  # noqa: ANN001
        return {"StatusCode": 0}

    def remove(self, force=False):  # noqa: ANN001
        self.removed = True

    def kill(self) -> None:
        self.killed = True

    def logs(self) -> bytes:
        return b""


class _FakeContainers:
    def __init__(self) -> None:
        self.runs: list[dict] = []
        self._live: list[_FakeContainer] = []

    def run(self, **kwargs):  # noqa: ANN003
        self.runs.append(kwargs)
        container = _FakeContainer(kwargs)
        self._live.append(container)
        return container

    def list(self, all=False, filters=None):  # noqa: ANN001, A002
        return []


class _FakeNetworks:
    def __init__(self) -> None:
        self.created: list[str] = []

    def list(self, names=None):  # noqa: ANN001
        return []

    def create(self, name, driver=None, internal=False):  # noqa: ANN001
        self.created.append(name)
        return None


class _FakeDockerClient:
    def __init__(self) -> None:
        self.containers = _FakeContainers()
        self.networks = _FakeNetworks()


def _executor(client: _FakeDockerClient, *, token_revoker=None) -> ContainerExecutor:
    return ContainerExecutor(
        image_digest=IMAGE,
        pids_limit=64,
        memory_mb=512,
        cpu_quota=1.5,
        timeout_seconds=60,
        client_factory=lambda: client,
        token_revoker=token_revoker,
    )


def _controller(gateway_url: str, store, registry, **overrides) -> TurnTokenController:
    base = dict(
        gateway_base_url=gateway_url,
        mint_secret=SECRET,
        vendor_api_key=VENDOR_KEY,
    )
    base.update(overrides)
    return TurnTokenController(store=store, registry=registry, **base)


# ==================================================================== ① 成功路径

def test_container_spec_carries_environment_in_both_forms() -> None:
    """§3.5 注 2-乙：`create_kwargs` 与 `docker_args()` **同口径**都带 env（防两份口径漂移）。"""
    executor = _executor(_FakeDockerClient())
    spec = executor.build_spec(environment={ENV_API_KEY: "tok-x", ENV_BASE_URL: GATEWAY_URL})
    kwargs = spec.create_kwargs(labels={"a": "1"}, command=["python", "-c", "x"])
    assert kwargs["environment"] == {ENV_API_KEY: "tok-x", ENV_BASE_URL: GATEWAY_URL}

    args = spec.docker_args("/srv/exec-ws/t-1/run-1")
    assert f"{ENV_API_KEY}=tok-x" in args
    assert f"{ENV_BASE_URL}={GATEWAY_URL}" in args
    # 无 env 时两式都不带（既有口径不变）。
    bare = executor.build_spec()
    assert "environment" not in bare.create_kwargs(labels={}, command=["x"])
    assert "-e" not in bare.docker_args("/w")


def test_real_execute_injects_env_records_binding_and_revokes_on_terminal(gateway) -> None:
    """真实 `execute`（假 Docker）：容器 spec 有 env、store/registry 有写入、终态 retire + revoke。"""
    store, registry = TokenBindingStore(), ActiveExecutionRegistry()
    controller = _controller(gateway, store, registry)
    client = _FakeDockerClient()
    executor = _executor(client, token_revoker=controller.on_terminal)

    env = controller.open_turn(tenant_id="t-1", session_id="task-1", run_id="run-1")
    token = env[ENV_API_KEY]
    binding = TokenBinding("t-1", "task-1", 1)

    # 写入侧证据：自持绑定 + 权威登记。
    assert store.lookup(token) == binding
    assert registry.current_for("task-1") == binding
    assert bound_label(binding) == "t-1:task-1:1"

    outcome = executor.execute(
        tool_key="cmd.run",
        params={"executable": "python", "args": ["-c", "print(1)"]},
        workspace_path="/srv/exec-ws/t-1/run-1",
        environment=env,
    )
    assert outcome.ok is True

    # 容器 spec 里确有 env（令牌 + 网关内网地址），且**无供应商密钥 / 无禁止字段名**。
    served = client.containers.runs[0]["environment"]
    assert served[ENV_API_KEY] == token
    assert served[ENV_BASE_URL] == gateway
    assert VENDOR_KEY not in served.values()
    assert not (set(served) & set(FORBIDDEN_IN_CONTAINER_ENV_NAMES))

    # 终态：registry.retire（登记摘除）+ 网关 revoke（令牌撤出在册）。
    assert registry.current_for("task-1") is None
    assert token not in _GatewayStub.tokens
    assert len(_GatewayStub.revokes) == 1


class _TerminalFakeExecutor(DeterministicFakeExecutor):
    """既有测试替身 + **终态钩子**（等价 `ContainerExecutor` 的 `token_revoker` 出口）。"""

    def __init__(self, controller: TurnTokenController) -> None:
        super().__init__()
        self._controller = controller

    def execute(self, **kwargs):  # noqa: ANN003
        outcome = super().execute(**kwargs)
        run_id = str(kwargs["workspace_path"]).replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
        self._controller.on_terminal(run_id)
        return outcome


def test_service_gate8_mints_and_injects_env_then_retires_on_terminal(gateway, tmp_path) -> None:
    """服务层：⑧ 前 mint 并注入 env；终态经 executor 出口 retire（写入侧全链路）。"""
    store, registry = TokenBindingStore(), ActiveExecutionRegistry()
    controller = _controller(gateway, store, registry)
    executor = _TerminalFakeExecutor(controller)
    service = ToolExecutionService(
        catalog=ToolSpecCatalog(default_tool_specs()),
        body_cipher=BodyCipher.from_base64(base64.b64encode(os.urandom(32)).decode("ascii")),
        executor=executor,
        workspace=WorkspaceManager(str(tmp_path)),
        tool_actions=InMemoryToolActionStore(),
        run_records=None,
        turn_tokens=controller,
    )
    request = ToolExecutionRequest(
        tenant_id="t-1",
        run_id="run-1",
        task_id="task-1",
        step_id="step-1",
        tool_key="fs.list",
        params={"path": "/workspace"},
        requested_by="u-1",
        plan_digest="sha256:plan",
        autonomy_level="full_auto",
        risk_threshold="high",
    )

    result = service.execute(request)

    assert result.outcome == "executed"
    assert executor.calls[0]["environment_keys"] == sorted([ENV_API_KEY, ENV_BASE_URL])
    # 终态：登记摘除（retire 已被调用）+ 网关令牌撤出在册（revoke 已被调用）。
    assert registry.current_for("task-1") is None
    assert _GatewayStub.revokes == ["t-1:task-1:1"]


def test_open_then_callback_authorized_then_denied_after_terminal(gateway) -> None:
    """共享单例的端到端语义：turn 进行中回调**放行**、终态后**恒拒**（②④）。"""
    store, registry = TokenBindingStore(), ActiveExecutionRegistry()
    controller = _controller(gateway, store, registry)
    guard = WorkbenchCallbackGuard(store=store, registry=registry)

    env = controller.open_turn(tenant_id="t-1", session_id="task-1", run_id="run-1")
    token = env[ENV_API_KEY]

    # 进行中：按会话反查权威登记 ⇒ 绑定一致 ⇒ 放行。
    assert guard.authorize(token=token, session_id="task-1") == TokenBinding("t-1", "task-1", 1)

    controller.on_terminal("run-1")

    # 终态后：登记已摘 ⇒ 一律 403（不泄露存在性）。
    with pytest.raises(BindingDenied):
        guard.authorize(token=token, session_id="task-1")


def test_env_never_carries_vendor_key(gateway) -> None:
    """§3.5：容器 env 只含「网关内网地址 + 短期令牌」，**供应商密钥绝不进容器**。"""
    controller = _controller(gateway, TokenBindingStore(), ActiveExecutionRegistry())
    env = controller.open_turn(tenant_id="t-1", session_id="task-1", run_id="run-1")
    assert set(env) <= {ENV_API_KEY, ENV_BASE_URL}
    assert VENDOR_KEY not in env.values()
    assert not (set(env) & set(FORBIDDEN_IN_CONTAINER_ENV_NAMES))


# ==================================================================== 启动期断言

def test_missing_mint_secret_refuses_real_execution(gateway) -> None:
    """§3.5：缺 `WORKBENCH_MODEL_GATEWAY_MINT_SECRET` ⇒ 拒绝启用真实执行（记 error，不打挂进程）。"""
    controller = _controller(gateway, TokenBindingStore(), ActiveExecutionRegistry(), mint_secret="")
    assert controller.problems()
    with pytest.raises(ToolExecutionConfigError):
        controller.open_turn(tenant_id="t-1", session_id="task-1", run_id="run-1")

    ok = assert_real_execution_ready(
        tool_execution=object(),
        run_records=object(),
        tool_actions=object(),
        catalog=_GoodCatalog(),
        turn_tokens=controller,
    )
    assert ok is False


def test_missing_gateway_base_url_refuses_real_execution() -> None:
    controller = _controller("", TokenBindingStore(), ActiveExecutionRegistry())
    assert any("BASE_URL" in p or "网关地址" in p for p in controller.problems())


class _GoodCatalog:
    def param_role_problems(self) -> list[str]:
        return []


# ==================================================================== 生成 / 撤销的边界

def test_token_equal_to_vendor_key_is_refused(gateway) -> None:
    """反假目标③：若"令牌"实为供应商密钥 ⇒ **必须拒绝**（供应商密钥只在网关）。"""
    class _VendorTokenClient:
        def mint(self, bound: str) -> str:  # noqa: ARG002
            return VENDOR_KEY

        def revoke(self, bound: str) -> int:  # noqa: ARG002
            return 0

    store, registry = TokenBindingStore(), ActiveExecutionRegistry()
    controller = _controller(gateway, store, registry)
    controller._client_obj = _VendorTokenClient()  # type: ignore[assignment]
    with pytest.raises(Exception):
        controller.open_turn(tenant_id="t-1", session_id="task-1", run_id="run-1")
    # 拒绝路径不得留下自持绑定 / 登记（fail-closed，无孤儿）。
    assert registry.current_for("task-1") is None


def test_gateway_failure_leaves_no_partial_state(gateway) -> None:
    """mint 失败（错密钥）⇒ 不落绑定、不登记（无"存在但无调用方"的半接线）。"""
    store, registry = TokenBindingStore(), ActiveExecutionRegistry()
    controller = _controller(gateway, store, registry, mint_secret="wrong")
    with pytest.raises(GatewayControlError):
        controller.open_turn(tenant_id="t-1", session_id="task-1", run_id="run-1")
    assert registry.current_for("task-1") is None
    assert controller._by_run == {}


def _dsh_settings(tmp_path, gateway_url, **overrides):
    from app.settings import Settings

    base = dict(
        env="development",
        storage_backend="memory",
        agent_runtime_backend="dsh",
        body_encryption_key=base64.b64encode(os.urandom(32)).decode("ascii"),
        exec_workspace_root=str(tmp_path),
        exec_image_digest=IMAGE,
        model_gateway_base_url=gateway_url,
        model_gateway_mint_secret=SECRET,
    )
    base.update(overrides)
    return Settings(**base)


def test_bootstrap_shares_authority_state_and_wires_revoker(gateway, tmp_path) -> None:
    """装配路径（= `app/main.py` 口径）：mint 侧与判定侧**同一 store/registry**，⑤ 出口已接。"""
    from app.bootstrap import build_exec_callback_guard, build_tool_execution
    from app.runtime.records import InMemoryRunRecordStore
    from app.runtime.run_metrics import RunMetricsService

    settings = _dsh_settings(tmp_path, gateway)
    store, registry = TokenBindingStore(), ActiveExecutionRegistry()
    service = build_tool_execution(
        settings,
        run_metrics=RunMetricsService(InMemoryRunRecordStore()),
        audit=None,
        token_store=store,
        token_registry=registry,
    )
    assert service is not None
    # 写入侧与判定侧拿到的是**同一实例**（否则 ②④ 恒 403）。
    assert service.turn_tokens.store is store
    assert service.turn_tokens.registry is registry
    # ⑤ 出口已注入（此前 `from_settings` 恒为 None ⇒ 首行即 return）。
    assert service.executor.token_revoker == service.turn_tokens.on_terminal

    guard = build_exec_callback_guard(settings, store=store, registry=registry)
    assert guard.store is store and guard.registry is registry

    env = service.turn_tokens.open_turn(tenant_id="t-1", session_id="task-1", run_id="run-1")
    assert guard.authorize(token=env[ENV_API_KEY], session_id="task-1") == TokenBinding(
        "t-1", "task-1", 1
    )


def test_bootstrap_refuses_real_execution_without_mint_secret(gateway, tmp_path, caplog) -> None:
    """启动期断言：缺 `MINT_SECRET` ⇒ `build_tool_execution` 返回 `None` 且记 `error`（不退进程）。"""
    import logging

    from app.bootstrap import build_tool_execution
    from app.runtime.records import InMemoryRunRecordStore
    from app.runtime.run_metrics import RunMetricsService

    settings = _dsh_settings(tmp_path, gateway, model_gateway_mint_secret="")
    with caplog.at_level(logging.ERROR, logger="company_workbench.tool_execution"):
        service = build_tool_execution(
            settings, run_metrics=RunMetricsService(InMemoryRunRecordStore())
        )
    assert service is None
    assert any(record.levelno == logging.ERROR for record in caplog.records)


def test_generation_increments_then_resets_after_retire(gateway) -> None:
    """代次取自权威登记：同会话连续 turn 递增；终态摘除后回到首代（`retire` 已接）。"""
    store, registry = TokenBindingStore(), ActiveExecutionRegistry()
    controller = _controller(gateway, store, registry)

    env1 = controller.open_turn(tenant_id="t-1", session_id="task-1", run_id="run-1")
    assert store.lookup(env1[ENV_API_KEY]) == TokenBinding("t-1", "task-1", 1)

    env2 = controller.open_turn(tenant_id="t-1", session_id="task-1", run_id="run-2")
    assert store.lookup(env2[ENV_API_KEY]) == TokenBinding("t-1", "task-1", 2)
    assert registry.current_for("task-1") == TokenBinding("t-1", "task-1", 2)

    controller.on_terminal("run-1")
    controller.on_terminal("run-2")
    assert registry.current_for("task-1") is None
