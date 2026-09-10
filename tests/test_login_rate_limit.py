from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest

from app.accounts.rate_limit import (
    InMemoryLoginAttemptStore,
    LoginRateLimited,
    LoginRateLimiter,
)

SECRET = "s" * 40
NOW = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)


def limiter(store=None, *, failures=5, window=300, lock=900) -> LoginRateLimiter:
    return LoginRateLimiter(
        store or InMemoryLoginAttemptStore(),
        secret=SECRET,
        max_failures=failures,
        window_seconds=window,
        lock_seconds=lock,
    )


def test_phone_is_never_stored_in_plain_text() -> None:
    store = InMemoryLoginAttemptStore()
    instance = limiter(store)

    instance.register_failure("13800000001", now=NOW)

    assert "13800000001" not in store.dump_keys()
    assert instance.phone_hash("13800000001") in store.dump_keys()


def test_failures_below_threshold_do_not_lock() -> None:
    instance = limiter(failures=5)

    for _index in range(4):
        state = instance.register_failure("13800000001", now=NOW)

    assert state.failure_count == 4
    assert state.locked_until is None
    assert instance.is_locked("13800000001", now=NOW) is False


def test_reaching_threshold_locks_for_configured_duration() -> None:
    instance = limiter(failures=5, lock=900)

    for _index in range(5):
        state = instance.register_failure("13800000001", now=NOW)

    assert state.failure_count == 5
    assert state.locked_until == NOW + timedelta(seconds=900)
    assert instance.is_locked("13800000001", now=NOW) is True
    assert instance.is_locked("13800000001", now=NOW + timedelta(seconds=899)) is True
    assert instance.is_locked("13800000001", now=NOW + timedelta(seconds=901)) is False


def test_window_expiry_resets_counter() -> None:
    instance = limiter(failures=5, window=300)

    for _index in range(3):
        instance.register_failure("13800000001", now=NOW)
    later = NOW + timedelta(seconds=301)
    state = instance.register_failure("13800000001", now=later)

    assert state.failure_count == 1
    assert state.window_started_at == later


def test_success_clears_counter_and_lock() -> None:
    instance = limiter(failures=2)

    instance.register_failure("13800000001", now=NOW)
    instance.register_failure("13800000001", now=NOW)
    assert instance.is_locked("13800000001", now=NOW) is True

    instance.register_success("13800000001")

    assert instance.is_locked("13800000001", now=NOW) is False
    assert instance.register_failure("13800000001", now=NOW).failure_count == 1


def test_require_unlocked_raises_when_locked() -> None:
    instance = limiter(failures=1, lock=900)
    instance.register_failure("13800000001", now=NOW)

    with pytest.raises(LoginRateLimited):
        instance.require_unlocked("13800000001", now=NOW)

    instance.require_unlocked("13800000001", now=NOW + timedelta(seconds=901))


def test_different_phones_are_counted_independently() -> None:
    instance = limiter(failures=2)

    instance.register_failure("13800000001", now=NOW)
    state = instance.register_failure("13800000002", now=NOW)

    assert state.failure_count == 1
    assert instance.is_locked("13800000001", now=NOW) is False


def test_concurrent_failures_do_not_lose_counts() -> None:
    store = InMemoryLoginAttemptStore()
    instance = limiter(store, failures=1_000, window=10_000)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _index: instance.register_failure("13800000001", now=NOW), range(20)))

    state = store.load(instance.phone_hash("13800000001"))
    assert state is not None
    assert state.failure_count == 20


def test_unknown_phone_reports_unlocked() -> None:
    instance = limiter()

    assert instance.is_locked("13900000009", now=NOW) is False
    assert instance.register_failure("13900000009", now=NOW).failure_count == 1
