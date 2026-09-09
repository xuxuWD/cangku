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


@pytest.mark.parametrize("version", [None, "", "latest", "main", "head"])
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
