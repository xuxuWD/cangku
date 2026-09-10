import pytest
from pydantic import ValidationError

from app.accounts.rate_limit import InMemoryLoginAttemptStore, LoginRateLimiter
from app.audit.service import AuditService
from app.audit.store import InMemoryAuditStore
from app.bootstrap import build_audit_service, build_login_rate_limiter
from app.settings import Settings


def memory_settings(**overrides) -> Settings:
    base = {
        "env": "development",
        "storage_backend": "memory",
        "login_max_failures": 5,
        "login_window_seconds": 300,
        "login_lock_seconds": 900,
    }
    base.update(overrides)
    return Settings(**base)


def test_memory_backend_builds_audit_and_limiter() -> None:
    settings = memory_settings(auth_secret="s" * 40)

    audit = build_audit_service(settings)
    limiter = build_login_rate_limiter(settings)

    assert isinstance(audit, AuditService)
    assert isinstance(audit.store, InMemoryAuditStore)
    assert isinstance(limiter, LoginRateLimiter)
    assert isinstance(limiter.store, InMemoryLoginAttemptStore)
    assert limiter.max_failures == 5
    assert limiter.window_seconds == 300
    assert limiter.lock_seconds == 900
    assert limiter.secret == "s" * 40


def test_login_throttle_defaults() -> None:
    settings = Settings()

    assert settings.login_max_failures == 5
    assert settings.login_window_seconds == 300
    assert settings.login_lock_seconds == 900


def test_login_throttle_bounds_are_enforced() -> None:
    for overrides in (
        {"login_max_failures": 0},
        {"login_max_failures": 21},
        {"login_window_seconds": 10},
        {"login_window_seconds": 3601},
        {"login_lock_seconds": 10},
        {"login_lock_seconds": 86_401},
    ):
        with pytest.raises(ValidationError):
            Settings(**overrides)


def test_unsupported_storage_backend_is_rejected() -> None:
    with pytest.raises(ValueError):
        build_audit_service(memory_settings(storage_backend="sqlite"))

    with pytest.raises(ValueError):
        build_login_rate_limiter(memory_settings(storage_backend="sqlite"))
