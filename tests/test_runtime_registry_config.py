import pytest

from app.domain import RiskLevel, Task, TaskStatus, UserContext
from app.runtime.adapters import FakeTransport, RuntimeUnavailable
from app.runtime.registry import RuntimeConfigError, build_runtime_registry
from app.runtime.service import RunAccessDenied, RuntimeService


def test_default_registry_only_exposes_mock() -> None:
    registry = build_runtime_registry({})

    assert registry.keys() == ("mock",)


def test_enabled_external_runtime_requires_valid_endpoint_and_capabilities() -> None:
    with pytest.raises(RuntimeConfigError, match="地址"):
        build_runtime_registry({"deerflow": {"enabled": True, "capabilities": ["research"]}})
    with pytest.raises(RuntimeConfigError, match="协议"):
        build_runtime_registry(
            {
                "deerflow": {
                    "enabled": True,
                    "endpoint": "ftp://runtime",
                    "capabilities": ["research"],
                    "version": "v1.0.0",
                }
            }
        )
    with pytest.raises(RuntimeConfigError, match="能力"):
        build_runtime_registry(
            {
                "deerflow": {
                    "enabled": True,
                    "endpoint": "http://runtime",
                    "capabilities": [],
                    "version": "v1.0.0",
                }
            }
        )


def test_enabled_external_runtime_is_constructed_with_injected_transport() -> None:
    transport = FakeTransport()
    registry = build_runtime_registry(
        {
            "deerflow": {
                "enabled": True,
                "endpoint": "http://runtime",
                "capabilities": ["research"],
                "version": "v1.0.0",
            }
        },
        transport_factory=lambda _key, _config: transport,
    )

    assert registry.keys() == ("deerflow", "mock")
    assert registry.get("deerflow").health()["runtime"] == "http://runtime"


@pytest.mark.parametrize("key", ["ragflow", "agentscope"])
def test_enabled_new_runtime_is_explicitly_registered(key: str) -> None:
    registry = build_runtime_registry(
        {
            key: {
                "enabled": True,
                "endpoint": f"https://{key}.example",
                "capabilities": ["read"],
                "version": "v1.0.0",
            }
        },
        transport_factory=lambda _key, _config: FakeTransport(),
    )

    assert key in registry.keys()


@pytest.mark.parametrize("version", [None, "", "latest", "main", "head", " LATEST "])
def test_enabled_external_runtime_requires_fixed_version(version: str | None) -> None:
    with pytest.raises(RuntimeConfigError, match="版本"):
        build_runtime_registry(
            {
                "agentscope": {
                    "enabled": True,
                    "endpoint": "https://agentscope.example",
                    "capabilities": ["run"],
                    "version": version,
                }
            }
        )


def test_new_external_runtimes_remain_disabled_by_default() -> None:
    assert build_runtime_registry({}).keys() == ("mock",)


def test_external_runtime_version_is_stripped_before_storage() -> None:
    captured = []
    build_runtime_registry(
        {
            "agentscope": {
                "enabled": True,
                "endpoint": "https://agentscope.example",
                "capabilities": ["run"],
                "version": "  v1.0.0  ",
            }
        },
        transport_factory=lambda _key, item: captured.append(item) or FakeTransport(),
    )

    assert captured[0].version == "v1.0.0"


@pytest.mark.parametrize("capabilities", [None, "read", [""], [" "], [1], {"read"}])
def test_enabled_external_runtime_rejects_malformed_capabilities(capabilities: object) -> None:
    with pytest.raises(RuntimeConfigError, match="能力"):
        build_runtime_registry(
            {
                "agentscope": {
                    "enabled": True,
                    "endpoint": "https://agentscope.example",
                    "capabilities": capabilities,
                    "version": "v1.0.0",
                }
            }
        )


def _runtime_task() -> Task:
    return Task(
        tenant_id="tenant-1",
        project_id=None,
        created_by="user-1",
        employee_key="employee",
        title="runtime task",
        risk_level=RiskLevel.LOW,
        budget=10,
        idempotency_key="idempotency-1",
        request_fingerprint="fingerprint-1",
        status=TaskStatus.QUEUED,
    )


def test_ragflow_is_visible_as_unavailable_and_not_an_execution_runtime() -> None:
    registry = build_runtime_registry(
        {
            "ragflow": {
                "enabled": True,
                "endpoint": "https://ragflow.example",
                "capabilities": ["read"],
                "version": "v1.0.0",
            }
        },
        transport_factory=lambda _key, _config: FakeTransport(),
    )

    health = registry.health()

    assert health["ragflow"]["status"] == "unavailable"
    assert "知识检索" in health["ragflow"]["reason"]


def test_runtime_health_keeps_only_safe_summary_fields() -> None:
    class LeakyAdapter:
        def health(self):
            return {
                "status": "ok",
                "runtime": "agentscope",
                "version": "v1.0.0",
                "token": "secret",
                "session": {"cookie": "secret"},
            }

    from app.runtime.registry import RuntimeRegistry

    registry = RuntimeRegistry()
    registry.register("leaky", LeakyAdapter())

    assert registry.health()["leaky"] == {
        "status": "ok",
        "runtime": "agentscope",
        "version": "v1.0.0",
    }


def test_registry_reports_dsh_self_reported_unavailable() -> None:
    """缺陷 N3 的正面验证：注册表 `status` **按 adapter 自报输出**，不再"非 ragflow 一律 ok"。

    构造方式（与生产同一契约，**不用假 adapter**）：`DshAdapter` 目前**未注册进运行时**
    （§U25 A3「待接线」，`registry.py` 的 `constructors` 无 `dsh`），故用生产工厂
    `build_dsh_adapter` 造**真实** adapter —— 配置缺网关地址与镜像 digest ⇒
    `real_execution_enabled=False`（`dsh.py:232`）⇒ `health()` 自报 `status="unavailable"`（`dsh.py:343`）；
    再经 `RuntimeRegistry.register("dsh", …)` 放进注册表，即"注册表中存在一个自报 unavailable 的 adapter"。
    """
    from app.runtime.adapters.dsh import DshAdapterConfig, build_dsh_adapter
    from app.runtime.registry import RuntimeRegistry

    adapter = build_dsh_adapter(DshAdapterConfig(gateway_base_url="", exec_image_digest=""))
    assert adapter.health()["status"] == "unavailable"  # adapter 自报（非注册表默认）

    registry = RuntimeRegistry()
    registry.register("dsh", adapter)

    health = registry.health()["dsh"]
    assert health["status"] == "unavailable"
    assert health["runtime"] == "dsh"  # 其余字段仍照白名单透传
    assert health["sandbox"] == "read-only"


def test_registry_keeps_ok_default_when_adapter_reports_no_status() -> None:
    """`status` 是外部契约里的**可选**字段（`docs/runtime-onboarding-request.md` §1.4）。

    未上报 status 的 adapter（生产默认注册的 `mock` 即此类，`mock.py:152`）维持既有默认 `ok` ——
    **本次不新造默认口径**；依据：`tests/test_runtime_api.py::test_runtime_health_is_limited_to_management_roles`
    既已要求 mock 显示 `ok`。
    """
    registry = build_runtime_registry({})

    assert "status" not in registry.get("mock").health()
    assert registry.health()["mock"]["status"] == "ok"


def test_runtime_service_returns_controlled_unavailable_for_ragflow_execution() -> None:
    task = _runtime_task()
    actor = UserContext(tenant_id="tenant-1", user_id="user-1", role="employee")
    service = RuntimeService(
        type("TaskStoreStub", (), {"get": lambda _self, _context, _task_id: task})(),
        registry=build_runtime_registry(
            {
                "ragflow": {
                    "enabled": True,
                    "endpoint": "https://ragflow.example",
                    "capabilities": ["read"],
                    "version": "v1.0.0",
                }
            },
            transport_factory=lambda _key, _config: FakeTransport(),
        ),
    )

    with pytest.raises(RuntimeUnavailable, match="不可用"):
        service.start(actor, task.id, "ragflow", [], "product_manager")


def test_runtime_service_adapter_lookup_skips_knowledge_only_ragflow() -> None:
    actor = UserContext(tenant_id="tenant-1", user_id="user-1", role="employee")
    service = RuntimeService(
        type("TaskStoreStub", (), {})(),
        registry=build_runtime_registry(
            {
                "ragflow": {
                    "enabled": True,
                    "endpoint": "https://ragflow.example",
                    "capabilities": ["read"],
                    "version": "v1.0.0",
                }
            },
            transport_factory=lambda _key, _config: FakeTransport(),
        ),
    )

    with pytest.raises(RunAccessDenied, match="运行不存在"):
        service.adapter_for(actor, "missing-run")


def test_external_runtime_run_is_registered_for_control_plane_lookup() -> None:
    task = _runtime_task()
    actor = UserContext(tenant_id="tenant-1", user_id="user-1", role="employee")
    registry = build_runtime_registry(
        {
            "agentscope": {
                "enabled": True,
                "endpoint": "https://agentscope.example",
                "capabilities": ["run"],
                "version": "v1.0.0",
            }
        },
        transport_factory=lambda _key, _config: FakeTransport(),
    )
    service = RuntimeService(
        type("TaskStoreStub", (), {"get": lambda _self, _context, _task_id: task})(),
        registry=registry,
    )

    run_id, runtime_key, _policy = service.start(actor, task.id, "agentscope", [], "product_manager")

    key, _adapter, state = service.adapter_for_task(actor, run_id)
    assert (key, runtime_key, state.run_id) == ("agentscope", "agentscope", run_id)
