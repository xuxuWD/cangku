import json
import logging

from app.audit.logging import AUDIT_LOGGER_NAME, configure_audit_logging, emit_audit_line
from app.audit.models import AuditAction, build_record


def test_emit_writes_single_json_line_with_expected_fields(caplog) -> None:
    caplog.set_level(logging.INFO, logger=AUDIT_LOGGER_NAME)
    record = build_record(
        AuditAction.ACCOUNT_LOGIN_FAILED,
        tenant_id="t-1",
        actor_id=None,
        target_type="account",
        target_id=None,
        phone_masked="138****0001",
        detail={"reason": "invalid_credentials"},
    )

    emit_audit_line(record)

    message = caplog.records[-1].getMessage()
    assert "\n" not in message
    payload = json.loads(message)
    assert payload["event"] == "audit"
    assert payload["action"] == "account.login.failed"
    assert payload["tenant_id"] == "t-1"
    assert payload["phone_masked"] == "138****0001"
    assert payload["detail"] == {"reason": "invalid_credentials"}
    assert payload["occurred_at"]
    assert "actor_id" in payload


def test_configure_audit_logging_is_idempotent() -> None:
    import app.audit.logging as module

    module._configured = False
    logger = logging.getLogger(AUDIT_LOGGER_NAME)
    before = len(logger.handlers)
    try:
        configure_audit_logging("INFO")
        after_first = len(logger.handlers)
        configure_audit_logging("INFO")
        after_second = len(logger.handlers)
    finally:
        for handler in list(logger.handlers)[before:]:
            logger.removeHandler(handler)
        module._configured = False

    assert after_first == before + 1
    assert after_second == after_first


def test_configure_audit_logging_sets_level() -> None:
    import app.audit.logging as module

    module._configured = False
    logger = logging.getLogger(AUDIT_LOGGER_NAME)
    before = len(logger.handlers)
    try:
        configure_audit_logging("WARNING")
        assert logging.getLogger(AUDIT_LOGGER_NAME).level == logging.WARNING
    finally:
        for handler in list(logger.handlers)[before:]:
            logger.removeHandler(handler)
        module._configured = False


def test_configure_audit_logging_rejects_invalid_level() -> None:
    import app.audit.logging as module

    module._configured = False
    try:
        configure_audit_logging("NOT-A-LEVEL")
    finally:
        module._configured = False
    # 非法级别不抛异常，回退到 INFO
    assert logging.getLogger(AUDIT_LOGGER_NAME).level == logging.INFO
