import logging

import pytest

from app.audit.logging import AUDIT_LOGGER_NAME
from app.audit.models import AuditAction, build_record
from app.audit.service import AuditService
from app.audit.store import InMemoryAuditStore


@pytest.fixture(autouse=True)
def _audit_logger_propagates():
    """隔离其他测试对审计 logger 的全局配置，保证 caplog 能经 root handler 捕获记录。"""
    logger = logging.getLogger(AUDIT_LOGGER_NAME)
    original_propagate = logger.propagate
    logger.propagate = True
    try:
        yield
    finally:
        logger.propagate = original_propagate


def record(tenant_id: str | None = "t-1", action: AuditAction = AuditAction.ACCOUNT_LOGIN_SUCCEEDED):
    return build_record(action, tenant_id=tenant_id, actor_id="u-1", target_type="account", target_id="u-1")


def test_store_append_and_list_recent_is_tenant_scoped() -> None:
    store = InMemoryAuditStore()

    first = store.append(record())
    store.append(record("t-other"))

    assert store.list_recent("t-1", limit=10) == [first]
    assert store.list_recent("t-other", limit=10)[0].tenant_id == "t-other"
    assert store.list_recent("t-missing", limit=10) == []


def test_store_list_recent_without_tenant_returns_all_in_order() -> None:
    store = InMemoryAuditStore()
    saved = [store.append(record()) for _index in range(3)]

    recent = store.list_recent(None, limit=10)

    assert [item.record_id for item in recent] == [item.record_id for item in saved]


def test_store_list_recent_respects_limit_and_keeps_newest_last() -> None:
    store = InMemoryAuditStore()
    for _index in range(5):
        store.append(record())

    recent = store.list_recent("t-1", limit=3)

    assert len(recent) == 3
    assert [item.record_id for item in recent] == [
        item.record_id for item in store.list_recent("t-1", limit=5)[-3:]
    ]


def test_service_writes_to_store_and_emits_log(caplog) -> None:
    import logging

    from app.audit.logging import AUDIT_LOGGER_NAME

    caplog.set_level(logging.INFO, logger=AUDIT_LOGGER_NAME)
    store = InMemoryAuditStore()
    service = AuditService(store)

    saved = service.record(
        AuditAction.PLAN_PROPOSED,
        tenant_id="t-1",
        actor_id="u-1",
        target_type="task",
        target_id="task-1",
        detail={"step_count": 2},
    )

    assert store.list_recent("t-1", limit=10) == [saved]
    assert saved.action is AuditAction.PLAN_PROPOSED
    assert caplog.records[-1].getMessage().find('"action": "plan.proposed"') >= 0


def test_service_rejects_undeclared_detail() -> None:
    from app.audit.models import AuditDetailNotAllowed

    service = AuditService(InMemoryAuditStore())

    with pytest.raises(AuditDetailNotAllowed):
        service.record(AuditAction.PLAN_PROPOSED, tenant_id="t-1", detail={"apiKey": "x"})


def test_service_propagates_store_failure_and_does_not_swallow(caplog) -> None:
    import logging

    from app.audit.logging import AUDIT_LOGGER_NAME

    caplog.set_level(logging.INFO, logger=AUDIT_LOGGER_NAME)

    class ExplodingStore:
        def append(self, item):
            raise RuntimeError("db down")

        def list_recent(self, tenant_id=None, *, limit=100):
            return []

    service = AuditService(ExplodingStore())

    with pytest.raises(RuntimeError, match="db down"):
        service.record(AuditAction.PLAN_PROPOSED, tenant_id="t-1")
