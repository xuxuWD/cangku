import pytest
from pydantic import ValidationError

from app.audit.service import AuditService
from app.audit.store import InMemoryAuditStore
from app.bootstrap import build_orchestration_proposal_service
from app.orchestration.service import OrchestrationProposalService
from app.orchestration.store import (
    InMemoryOrchestrationProposalStore,
    PostgresOrchestrationProposalStore,
)
from app.runtime.records import InMemoryRunRecordStore
from app.runtime.run_metrics import RunMetricsService
from app.settings import Settings


def metrics() -> RunMetricsService:
    return RunMetricsService(InMemoryRunRecordStore())


def audit() -> AuditService:
    return AuditService(InMemoryAuditStore())


def postgres_settings() -> Settings:
    return Settings(
        env="production",
        storage_backend="postgres",
        database_url="postgresql://workbench:pw@pg.internal:5432/workbench",
        auth_secret="a" * 32,
        backup_encryption_key="b" * 32,
        content_store_backend="sqlite",
    )


def test_memory_backend_builds_in_memory_store_and_defaults() -> None:
    service = build_orchestration_proposal_service(
        Settings(env="development", storage_backend="memory"), metrics=metrics(), audit=audit()
    )

    assert isinstance(service, OrchestrationProposalService)
    assert isinstance(service.store, InMemoryOrchestrationProposalStore)
    assert service.default_runtime_key == "mock"
    assert service.min_samples == 5
    assert service.improvement_threshold == 0.1


def test_postgres_backend_uses_injected_connection() -> None:
    service = build_orchestration_proposal_service(
        postgres_settings(), metrics=metrics(), audit=audit(), connection=object(), migrate=False
    )

    assert isinstance(service.store, PostgresOrchestrationProposalStore)


def test_unsupported_storage_backend_is_rejected() -> None:
    with pytest.raises(ValueError, match="优化提案存储类型"):
        build_orchestration_proposal_service(
            Settings(env="development", storage_backend="sqlite"), metrics=metrics(), audit=audit()
        )


def test_settings_defaults_and_bounds() -> None:
    defaults = Settings()

    assert defaults.orchestration_default_runtime_key == "mock"
    assert defaults.orchestration_min_samples == 5
    assert defaults.orchestration_improvement_threshold == 0.1

    with pytest.raises(ValidationError):
        Settings(orchestration_min_samples=0)
    with pytest.raises(ValidationError):
        Settings(orchestration_min_samples=1001)
    with pytest.raises(ValidationError):
        Settings(orchestration_improvement_threshold=1.5)
