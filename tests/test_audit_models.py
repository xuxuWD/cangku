import pytest

from app.audit.models import AuditAction, AuditDetailNotAllowed, AuditRecord, build_record


def test_build_record_defaults_and_identity() -> None:
    record = build_record(
        AuditAction.ACCOUNT_LOGIN_SUCCEEDED,
        tenant_id="t-1",
        actor_id="acct-1",
        target_type="account",
        target_id="acct-1",
        phone_masked="138****0001",
    )

    assert record.record_id.startswith("audit-")
    assert record.occurred_at.tzinfo is not None
    assert record.detail == {}
    assert record.action is AuditAction.ACCOUNT_LOGIN_SUCCEEDED


def test_action_values_are_stable_strings() -> None:
    assert AuditAction.ACCOUNT_LOGIN_LOCKED.value == "account.login.locked"
    assert AuditAction.PLAN_RUN_STARTED.value == "plan.run_started"
    assert AuditAction.DEAD_LETTER_NOTIFIED.value == "dead_letter.notified"
    assert AuditAction.DEAD_LETTER_NOTIFICATION_FAILED.value == "dead_letter.notification_failed"
    assert len(set(AuditAction)) == 21


def test_build_record_rejects_undeclared_detail_keys() -> None:
    for bad in (
        {"password": "x"},
        {"apiKey": "x"},
        {"unknown": "x"},
        {"nested": {"accessToken": "x"}},
    ):
        with pytest.raises(AuditDetailNotAllowed):
            build_record(AuditAction.PLAN_PROPOSED, tenant_id="t-1", detail=bad)


def test_build_record_allows_every_declared_detail_key() -> None:
    from app.audit.models import ALLOWED_DETAIL_KEYS

    record = build_record(
        AuditAction.PLAN_RUN_STARTED,
        tenant_id="t-1",
        detail={key: "v" for key in ALLOWED_DETAIL_KEYS},
    )

    assert set(record.detail) == set(ALLOWED_DETAIL_KEYS)


def test_build_record_accepts_bounded_structured_detail() -> None:
    record = build_record(
        AuditAction.PLAN_RUN_STARTED,
        tenant_id="t-1",
        detail={"runtime_key": "mock", "step_count": 3},
    )

    assert record.detail == {"runtime_key": "mock", "step_count": 3}
