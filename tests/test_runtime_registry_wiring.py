from __future__ import annotations

import app.main as main
from app.bootstrap import build_runtime_service
from app.settings import Settings


def _settings(**overrides) -> Settings:
    base = {"env": "development", "storage_backend": "memory"}
    base.update(overrides)
    return Settings(**base)


def test_configured_ragflow_is_registered_in_assembled_service() -> None:
    settings = _settings(
        ragflow_endpoint="https://ragflow.example",
        ragflow_version="v1.0.0",
        ragflow_capabilities="read, search",
    )

    service = build_runtime_service(settings, store=object())

    assert service.registry.keys() == ("mock", "ragflow")


def test_no_runtime_configured_keeps_mock_only() -> None:
    service = build_runtime_service(_settings(), store=object())

    assert service.registry.keys() == ("mock",)


def test_auth_injected_without_token_is_rejected_during_assembly() -> None:
    import pytest

    from app.runtime.registry import RuntimeConfigError

    settings = _settings(
        agentscope_endpoint="https://agentscope.example",
        agentscope_version="v1.2.3",
        agentscope_capabilities="run",
        agentscope_auth_injected=True,
        agentscope_auth_token="",
    )

    with pytest.raises(RuntimeConfigError):
        build_runtime_service(settings, store=object())


def test_main_service_defaults_to_mock_registry() -> None:
    assert main.runtime_service.registry.keys() == ("mock",)
