import pytest
from pydantic import ValidationError

from app.agent_services import DataClassification, ModelNotAllowed
from app.audit.service import AuditService
from app.audit.store import InMemoryAuditStore
from app.bootstrap import build_planner_service
from app.planner.classification import PLAN_GENERATION_CAPABILITY
from app.planner.generator import MockPlanGenerator, OpenAICompatiblePlanGenerator
from app.planner.models import ToolCatalog
from app.planner.store import InMemoryPlanProposalStore
from app.settings import Settings


def audit() -> AuditService:
    return AuditService(InMemoryAuditStore())


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
    service, store = build_planner_service(memory_settings(), audit=audit())

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
            ),
            audit=audit(),
        )


def test_openai_backend_builds_model_generator() -> None:
    service, _store = build_planner_service(
        memory_settings(
            planner_backend="openai_compatible",
            planner_model_base_url="https://model.example/v1",
            planner_model_name="planner-small",
            planner_model_api_key="secret-key",
        ),
        audit=audit(),
    )

    assert isinstance(service.generator, OpenAICompatiblePlanGenerator)
    assert service.generator.model_name == "planner-small"


def test_unsupported_backend_and_bad_tools_are_rejected() -> None:
    with pytest.raises(ValueError, match="规划生成后端"):
        build_planner_service(memory_settings(planner_backend="other"), audit=audit())

    with pytest.raises(ValueError, match="工具白名单"):
        build_planner_service(memory_settings(planner_tools="not-json"), audit=audit())


def test_postgres_backend_requires_postgres_storage() -> None:
    with pytest.raises(ValueError, match="计划提案存储类型"):
        build_planner_service(memory_settings(storage_backend="sqlite"), audit=audit())


def test_planner_max_steps_bounds() -> None:
    assert Settings().planner_max_steps == 10

    with pytest.raises(ValidationError):
        Settings(planner_max_steps=0)
    with pytest.raises(ValidationError):
        Settings(planner_max_steps=99)


def test_default_catalog_is_empty_and_config_parses() -> None:
    assert Settings().planner_tools == "[]"
    assert ToolCatalog.from_config(Settings().planner_tools).is_empty() is True


def test_mock_backend_does_not_wire_a_model_gateway() -> None:
    service, _store = build_planner_service(memory_settings(), audit=audit())

    assert service.model_gateway is None


def test_openai_backend_wires_gateway_and_rejects_restricted_by_default() -> None:
    service, _store = build_planner_service(
        memory_settings(
            planner_backend="openai_compatible",
            planner_model_base_url="https://model.example/v1",
            planner_model_name="planner-small",
            planner_model_api_key="secret-key",
        ),
        audit=audit(),
    )

    assert service.model_gateway is not None
    with pytest.raises(ModelNotAllowed):
        service.model_gateway.choose(
            capability=PLAN_GENERATION_CAPABILITY,
            data_classification=DataClassification.RESTRICTED.value,
            preferred="planner-small",
        )


def test_openai_backend_sensitive_flag_allows_restricted_data() -> None:
    service, _store = build_planner_service(
        memory_settings(
            planner_backend="openai_compatible",
            planner_model_base_url="https://model.example/v1",
            planner_model_name="planner-small",
            planner_model_api_key="secret-key",
            planner_model_sensitive_data=True,
        ),
        audit=audit(),
    )

    route = service.model_gateway.choose(
        capability=PLAN_GENERATION_CAPABILITY,
        data_classification=DataClassification.RESTRICTED.value,
        preferred="planner-small",
    )

    assert route.model_key == "planner-small"
