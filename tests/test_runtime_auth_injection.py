from __future__ import annotations

import httpx
import pytest

from app.runtime.adapters.common import HttpRuntimeTransport
from app.runtime.registry import (
    RuntimeConfigError,
    RuntimeEndpointConfig,
    build_runtime_registry,
)


def _client(requests: list[httpx.Request]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"run_id": "remote-1"})

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_http_transport_injects_configured_auth_header() -> None:
    requests: list[httpx.Request] = []
    transport = HttpRuntimeTransport(
        client=_client(requests),
        headers={"Authorization": "Bearer tok-123"},
    )

    transport.start("https://runtime.example", {})

    assert requests[0].headers["Authorization"] == "Bearer tok-123"


def test_http_transport_omits_auth_header_without_token() -> None:
    requests: list[httpx.Request] = []
    transport = HttpRuntimeTransport(client=_client(requests))

    transport.start("https://runtime.example", {})

    assert "authorization" not in requests[0].headers


def test_caller_headers_take_precedence_over_transport_headers() -> None:
    requests: list[httpx.Request] = []
    transport = HttpRuntimeTransport(
        client=_client(requests),
        headers={"Authorization": "Bearer default"},
    )

    transport._request(
        "GET",
        "https://runtime.example/health",
        headers={"Authorization": "Bearer caller"},
    )

    assert requests[0].headers["Authorization"] == "Bearer caller"


def test_endpoint_config_assembles_bearer_and_custom_header() -> None:
    bearer = RuntimeEndpointConfig(
        key="ragflow",
        endpoint="https://ragflow.example",
        timeout_seconds=30.0,
        capabilities=("read",),
        version="v1.0.0",
        auth_token="tok-123",
    )
    assert bearer.auth_headers() == {"Authorization": "Bearer tok-123"}

    bare = RuntimeEndpointConfig(
        key="agentscope",
        endpoint="https://agentscope.example",
        timeout_seconds=30.0,
        capabilities=("run",),
        version="v1.0.0",
        auth_token="tok-456",
        auth_header="X-Api-Key",
        auth_scheme="",
    )
    assert bare.auth_headers() == {"X-Api-Key": "tok-456"}


def test_registry_requires_token_when_auth_injection_is_declared() -> None:
    with pytest.raises(RuntimeConfigError):
        build_runtime_registry(
            {
                "agentscope": {
                    "enabled": True,
                    "endpoint": "https://agentscope.example",
                    "capabilities": ["run"],
                    "version": "v1.0.0",
                    "auth_injected": True,
                    "auth_token": "",
                }
            }
        )


def test_registry_requires_capabilities_and_fixed_version() -> None:
    with pytest.raises(RuntimeConfigError, match="能力"):
        build_runtime_registry(
            {
                "agentscope": {
                    "enabled": True,
                    "endpoint": "https://agentscope.example",
                    "capabilities": [],
                    "version": "v1.0.0",
                }
            }
        )
    with pytest.raises(RuntimeConfigError, match="版本"):
        build_runtime_registry(
            {
                "agentscope": {
                    "enabled": True,
                    "endpoint": "https://agentscope.example",
                    "capabilities": ["run"],
                    "version": "latest",
                }
            }
        )


def test_default_transport_factory_wires_auth_headers() -> None:
    registry = build_runtime_registry(
        {
            "agentscope": {
                "enabled": True,
                "endpoint": "https://agentscope.example",
                "capabilities": ["run"],
                "version": "v1.0.0",
                "auth_injected": True,
                "auth_token": "tok-789",
                "auth_header": "Authorization",
                "auth_scheme": "Bearer",
            }
        }
    )

    transport = registry.get("agentscope").transport
    assert transport.headers["Authorization"] == "Bearer tok-789"


def test_token_is_never_exposed_in_repr_exception_or_health() -> None:
    token = "super-secret-token"
    config = RuntimeEndpointConfig(
        key="ragflow",
        endpoint="https://ragflow.example",
        timeout_seconds=30.0,
        capabilities=("read",),
        version="v1.0.0",
        auth_injected=True,
        auth_token=token,
    )
    assert token not in repr(config)

    registry = build_runtime_registry(
        {
            "ragflow": {
                "enabled": True,
                "endpoint": "https://ragflow.example",
                "capabilities": ["read"],
                "version": "v1.0.0",
                "auth_injected": True,
                "auth_token": token,
            }
        }
    )
    assert token not in str(registry.health())

    with pytest.raises(RuntimeConfigError) as exc_info:
        build_runtime_registry(
            {
                "agentscope": {
                    "enabled": True,
                    "endpoint": "https://agentscope.example",
                    "capabilities": ["run"],
                    "version": "latest",
                    "auth_injected": True,
                    "auth_token": token,
                }
            }
        )
    assert token not in str(exc_info.value)
