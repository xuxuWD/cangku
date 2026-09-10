import pytest

from app.accounts.rate_limit import InMemoryLoginAttemptStore, LoginRateLimiter
from app.accounts.repository import InMemoryAccountRepository
from app.audit.service import AuditService
from app.audit.store import InMemoryAuditStore
from app.bootstrap import build_account_service
from app.settings import Settings


def _audit() -> AuditService:
    return AuditService(InMemoryAuditStore())


def _login_limiter() -> LoginRateLimiter:
    return LoginRateLimiter(
        InMemoryLoginAttemptStore(),
        secret="s" * 40,
        max_failures=5,
        window_seconds=300,
        lock_seconds=900,
    )


def test_memory_backend_returns_in_memory_repository() -> None:
    settings = Settings(env="development", storage_backend="memory", bootstrap_token="boot-secret")

    service, repository = build_account_service(
        settings, audit=_audit(), login_limiter=_login_limiter()
    )

    assert isinstance(repository, InMemoryAccountRepository)
    assert service.bootstrap_token == "boot-secret"


def test_unsupported_backend_is_rejected() -> None:
    settings = Settings(env="development", storage_backend="sqlite")

    with pytest.raises(ValueError, match="账号存储类型"):
        build_account_service(settings, audit=_audit(), login_limiter=_login_limiter())
