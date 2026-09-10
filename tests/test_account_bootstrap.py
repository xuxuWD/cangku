import pytest

from app.accounts.repository import InMemoryAccountRepository
from app.bootstrap import build_account_service
from app.settings import Settings


def test_memory_backend_returns_in_memory_repository() -> None:
    settings = Settings(env="development", storage_backend="memory", bootstrap_token="boot-secret")

    service, repository = build_account_service(settings)

    assert isinstance(repository, InMemoryAccountRepository)
    assert service.bootstrap_token == "boot-secret"


def test_unsupported_backend_is_rejected() -> None:
    settings = Settings(env="development", storage_backend="sqlite")

    with pytest.raises(ValueError, match="账号存储类型"):
        build_account_service(settings)
