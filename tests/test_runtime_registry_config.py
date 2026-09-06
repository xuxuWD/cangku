import pytest

from app.runtime.adapters import FakeTransport
from app.runtime.registry import RuntimeConfigError, build_runtime_registry


def test_default_registry_only_exposes_mock() -> None:
    registry = build_runtime_registry({})

    assert registry.keys() == ("mock",)


def test_enabled_external_runtime_requires_valid_endpoint_and_capabilities() -> None:
    with pytest.raises(RuntimeConfigError, match="地址"):
        build_runtime_registry({"deerflow": {"enabled": True, "capabilities": ["research"]}})
    with pytest.raises(RuntimeConfigError, match="协议"):
        build_runtime_registry({"deerflow": {"enabled": True, "endpoint": "ftp://runtime", "capabilities": ["research"]}})
    with pytest.raises(RuntimeConfigError, match="能力"):
        build_runtime_registry({"deerflow": {"enabled": True, "endpoint": "http://runtime", "capabilities": []}})


def test_enabled_external_runtime_is_constructed_with_injected_transport() -> None:
    transport = FakeTransport()
    registry = build_runtime_registry(
        {"deerflow": {"enabled": True, "endpoint": "http://runtime", "capabilities": ["research"]}},
        transport_factory=lambda _key, _config: transport,
    )

    assert registry.keys() == ("deerflow", "mock")
    assert registry.get("deerflow").health()["runtime"] == "http://runtime"
