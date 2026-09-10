import pytest
from pydantic import ValidationError

from app.bootstrap import build_planner_service
from app.planner.generator import MockPlanGenerator, OpenAICompatiblePlanGenerator
from app.planner.models import ToolCatalog
from app.planner.store import InMemoryPlanProposalStore
from app.settings import Settings


def memory_settings(**overrides) -> Settings:
    base = {
        "env": "development",
        "storage_backend": "memory",
        "planner_backend": "mock",
        "planner_tools": '[{"name": "knowledge.search", "kind": "read"}]',
        "planner_max_steps": 5,
    }
    base.update(overrides)
    return Settings(**base)


def test_memory_backend_builds_mock_planner() -> None:
    service, store = build_planner_service(memory_settings())

    assert isinstance(store, InMemoryPlanProposalStore)
    assert isinstance(service.generator, MockPlanGenerator)
    assert service.catalog.names() == ("knowledge.search",)
    assert service.max_steps == 5


def test_openai_backend_requires_connection_settings() -> None:
    with pytest.raises(ValueError, match="地址、模型名和 API Key"):
        build_planner_service(
            memory_settings(
                planner_backend="openai_compatible",
                planner_model_base_url="",
                planner_model_name="",
                planner_model_api_key="",
            )
        )


def test_openai_backend_builds_model_generator() -> None:
    service, _store = build_planner_service(
        memory_settings(
            planner_backend="openai_compatible",
            planner_model_base_url="https://model.example/v1",
            planner_model_name="planner-small",
            planner_model_api_key="secret-key",
        )
    )

    assert isinstance(service.generator, OpenAICompatiblePlanGenerator)
    assert service.generator.model_name == "planner-small"


def test_unsupported_backend_and_bad_tools_are_rejected() -> None:
    with pytest.raises(ValueError, match="规划生成后端"):
        build_planner_service(memory_settings(planner_backend="other"))

    with pytest.raises(ValueError, match="工具白名单"):
        build_planner_service(memory_settings(planner_tools="not-json"))


def test_planner_max_steps_bounds() -> None:
    assert Settings().planner_max_steps == 10

    with pytest.raises(ValidationError):
        Settings(planner_max_steps=0)
    with pytest.raises(ValidationError):
        Settings(planner_max_steps=99)


def test_default_catalog_is_empty_and_config_parses() -> None:
    assert Settings().planner_tools == "[]"
    assert ToolCatalog.from_config(Settings().planner_tools).is_empty() is True
