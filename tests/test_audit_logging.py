import json
import logging

import pytest

from app.audit.logging import AUDIT_LOGGER_NAME, configure_audit_logging, emit_audit_line
from app.audit.models import AuditAction, build_record


@pytest.fixture(autouse=True)
def _restore_audit_logger():
    import app.audit.logging as module

    logger = logging.getLogger(AUDIT_LOGGER_NAME)
    snapshot = (list(logger.handlers), logger.level, logger.propagate, module._configured)
    try:
        yield
    finally:
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
        for handler in snapshot[0]:
            logger.addHandler(handler)
        logger.setLevel(snapshot[1])
        logger.propagate = snapshot[2]
        module._configured = snapshot[3]


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
    configure_audit_logging("INFO")
    after_first = len(logger.handlers)
    configure_audit_logging("INFO")
    after_second = len(logger.handlers)

    assert after_first == before + 1
    assert after_second == after_first


def test_configure_audit_logging_sets_level() -> None:
    import app.audit.logging as module

    module._configured = False

    configure_audit_logging("WARNING")

    assert logging.getLogger(AUDIT_LOGGER_NAME).level == logging.WARNING


def test_configure_audit_logging_rejects_invalid_level() -> None:
    import app.audit.logging as module

    module._configured = False

    configure_audit_logging("NOT-A-LEVEL")

    assert logging.getLogger(AUDIT_LOGGER_NAME).level == logging.INFO
