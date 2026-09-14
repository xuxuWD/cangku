"""`ToolActionStore` 的 `workbench_tool_actions` 读写约束（迁移 027 / 规格 §4.1.1）。

判据：
    - `reason_code` 只能取 9 值受控枚举；
    - `body_ciphertext` 与 `body_expires_at` **同有同无**（迁移 027 的 `body_check`）；
    - **到期即清**（§4.1.5 ②/§4.1.6-8）：到期 `pending` 行 → `expired` + 两列清空；未到期绝不动、幂等。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import pytest

from app.domain import RiskLevel
from app.audit.models import AuditAction
from app.tool_execution.cleanup import BodyCleanupTask
from app.tool_execution.log import LOGGER_NAME
from app.tool_execution.store import (
    EXPIRY_DECIDED_BY,
    EXPIRY_DECISION_SOURCE,
    InMemoryToolActionStore,
    ReasonCode,
    ToolAction,
    ToolActionStatus,
)

NOW = datetime(2026, 9, 13, 12, 0, tzinfo=UTC)


def _pending(**overrides) -> ToolAction:
    base = dict(
        tenant_id="t-1",
        action_id="act-1",
        approval_id="appr-1",
        run_id="run-1",
        task_id="task-1",
        step_id="step-1",
        tool_key="fs.write",
        args_digest="sha256:digest",
        args_json={"path": "/workspace/a.txt", "content": "«body»"},
        body_ciphertext=b"cipher",
        body_expires_at=datetime(2026, 9, 13, tzinfo=UTC),
        plan_digest="sha256:plan",
        risk_level=RiskLevel.MEDIUM,
        requires_approval=True,
        status=ToolActionStatus.PENDING,
        requested_by="user-1",
        requested_at=datetime(2026, 9, 13, tzinfo=UTC),
    )
    base.update(overrides)
    return ToolAction(**base)


def test_reason_code_enum_has_exactly_nine_values() -> None:
    assert {code.value for code in ReasonCode} == {
        "path_denied",
        "blacklisted",
        "param_invalid",
        "not_authorized",
        "not_in_catalog",
        "timeout",
        "runtime_error",
        "approval_denied",
        "approval_expired",
    }


def test_store_rejects_unknown_reason_code() -> None:
    store = InMemoryToolActionStore()
    with pytest.raises(ValueError):
        store.upsert(_pending(reason_code="free_text_reason"))  # type: ignore[arg-type]


@pytest.mark.parametrize("code", [code.value for code in ReasonCode])
def test_store_accepts_each_controlled_reason_code(code: str) -> None:
    store = InMemoryToolActionStore()
    action = _pending(
        status=ToolActionStatus.REJECTED,
        decided_by="ceo-1",
        decided_at=datetime(2026, 9, 13, tzinfo=UTC),
        decision_source="user",
        reason_code=ReasonCode(code),
    )
    assert store.upsert(action).reason_code is ReasonCode(code)


def test_store_rejects_ciphertext_without_expiry() -> None:
    store = InMemoryToolActionStore()
    with pytest.raises(ValueError):
        store.upsert(_pending(body_expires_at=None))


def test_store_rejects_expiry_without_ciphertext() -> None:
    store = InMemoryToolActionStore()
    with pytest.raises(ValueError):
        store.upsert(_pending(body_ciphertext=None))


def test_store_roundtrip_preserves_body_and_decision() -> None:
    store = InMemoryToolActionStore()
    store.upsert(_pending())
    loaded = store.get("t-1", "act-1")
    assert loaded.body_ciphertext == b"cipher"
    assert loaded.body_expires_at == datetime(2026, 9, 13, tzinfo=UTC)

    decided = store.upsert(
        _pending(
            status=ToolActionStatus.APPROVED,
            decided_by="ceo-1",
            decided_at=datetime(2026, 9, 13, tzinfo=UTC),
            decision_source="user",
        )
    )
    assert decided.status is ToolActionStatus.APPROVED
    assert store.find_approved(tenant_id="t-1", run_id="run-1", approval_id="appr-1") is not None


def test_store_isolates_tenants() -> None:
    store = InMemoryToolActionStore()
    store.upsert(_pending())
    assert store.list_for_run("t-2", "run-1") == []
    assert store.find_approved(tenant_id="t-2", run_id="run-1", approval_id="appr-1") is None


# ------------------------------------------------------------ 到期清理（§4.1.5 ② / §4.1.6-8）


def test_expire_only_touches_due_pending_rows() -> None:
    """**未到期的绝不动**；到期（含恰好等于 `now`）的 `pending` 行置 `expired` 并清空两列。"""
    store = InMemoryToolActionStore()
    store.upsert(_pending(action_id="due", step_id="step-due", body_expires_at=NOW - timedelta(seconds=1)))
    store.upsert(_pending(action_id="edge", step_id="step-edge", body_expires_at=NOW))
    store.upsert(_pending(action_id="later", step_id="step-later", body_expires_at=NOW + timedelta(seconds=1)))

    assert len(store.expire_pending_bodies(now=NOW)) == 2

    due = store.get("t-1", "due")
    assert due.status is ToolActionStatus.EXPIRED
    assert due.decided_by == EXPIRY_DECIDED_BY
    assert due.decision_source == EXPIRY_DECISION_SOURCE
    assert due.decided_at == NOW - timedelta(seconds=1)  # decided_at = **到期时刻**，不是 now
    assert due.body_ciphertext is None and due.body_expires_at is None
    assert store.get("t-1", "edge").status is ToolActionStatus.EXPIRED

    later = store.get("t-1", "later")
    assert later.status is ToolActionStatus.PENDING
    assert later.body_ciphertext == b"cipher"
    assert later.body_expires_at == NOW + timedelta(seconds=1)


def test_expire_ignores_decided_rows_and_is_idempotent() -> None:
    """已判决（`approved`）的行**不动**（保留密文供重跑还原）；重复执行幂等、不误删。"""
    store = InMemoryToolActionStore()
    store.upsert(
        _pending(
            action_id="approved",
            step_id="step-approved",
            status=ToolActionStatus.APPROVED,
            decided_by="ceo-1",
            decided_at=NOW - timedelta(minutes=1),
            decision_source="user",
            body_expires_at=NOW - timedelta(seconds=1),
        )
    )
    store.upsert(_pending(action_id="due", step_id="step-due", body_expires_at=NOW - timedelta(seconds=5)))

    assert len(store.expire_pending_bodies(now=NOW)) == 1
    assert store.expire_pending_bodies(now=NOW) == []  # 幂等：第二次无命中且不报错

    approved = store.get("t-1", "approved")
    assert approved.status is ToolActionStatus.APPROVED
    assert approved.body_ciphertext == b"cipher"
    assert approved.decided_by == "ceo-1"

    expired = store.get("t-1", "due")
    assert expired.status is ToolActionStatus.EXPIRED
    assert expired.body_ciphertext is None
    assert expired.body_expires_at is None


def test_body_cleanup_task_reports_expired_count() -> None:
    store = InMemoryToolActionStore()
    store.upsert(_pending(body_expires_at=NOW - timedelta(seconds=1)))

    report = BodyCleanupTask(store, interval_seconds=60, now=lambda: NOW).run_once()

    assert (report.expired, report.failures) == (1, 0)
    assert store.get("t-1", "act-1").status is ToolActionStatus.EXPIRED


def test_body_cleanup_task_alerts_and_records_on_failure(caplog) -> None:
    """清理失败必须**告警并登记**（§4.1.5 ④）：记 `error` + 计数，**不静默吞掉**。"""

    class _Boom:
        def expire_pending_bodies(self, *, now):
            raise RuntimeError("database is gone")

    with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
        report = BodyCleanupTask(_Boom(), interval_seconds=60).run_once()

    assert (report.expired, report.failures) == (0, 1)
    assert any(record.levelno == logging.ERROR for record in caplog.records)


# ------------------------------------------------------- 到期决议的审计证据（§4.1.7-6）


class RecordingAudit:
    def __init__(self) -> None:
        self.calls: list[tuple[object, dict]] = []

    def record(self, action, **kwargs) -> None:
        self.calls.append((action, kwargs))


def test_expiry_writes_existing_decided_audit_and_skips_undue_rows() -> None:
    """到期行按**既有**动作码 `run.approval_decided` 留决议事实；未到期行不留、不动。"""
    store = InMemoryToolActionStore()
    store.upsert(_pending(action_id="due", step_id="step-due", body_expires_at=NOW - timedelta(seconds=1)))
    store.upsert(_pending(action_id="later", step_id="step-later", body_expires_at=NOW + timedelta(seconds=1)))
    audit = RecordingAudit()

    report = BodyCleanupTask(store, interval_seconds=60, now=lambda: NOW, audit=audit).run_once()

    assert report.expired == 1
    assert len(audit.calls) == 1
    action, kwargs = audit.calls[0]
    assert action is AuditAction.RUN_APPROVAL_DECIDED  # 既有动作码，未新增
    assert kwargs["actor_id"] == EXPIRY_DECIDED_BY
    assert kwargs["target_type"] == "run" and kwargs["target_id"] == "run-1"
    assert kwargs["detail"] == {"status": "expired"}


def test_expiry_audit_failure_is_alerted_and_counted(caplog) -> None:
    """审计写入失败同样**告警并登记**（不静默吞掉），且不掩盖已生效的清理动作。"""
    store = InMemoryToolActionStore()
    store.upsert(_pending(body_expires_at=NOW - timedelta(seconds=1)))

    class _AuditBoom:
        def record(self, *args, **kwargs):
            raise RuntimeError("audit store down")

    with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
        report = BodyCleanupTask(
            store, interval_seconds=60, now=lambda: NOW, audit=_AuditBoom()
        ).run_once()

    assert (report.expired, report.failures) == (1, 1)
    assert store.get("t-1", "act-1").status is ToolActionStatus.EXPIRED
    assert any(record.levelno == logging.ERROR for record in caplog.records)
