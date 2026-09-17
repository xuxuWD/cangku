"""CRM 周期任务（§2.11）测试：未接线零值 / 重算逐租户 / 活动提醒幂等 / 续约窗口与过期翻转。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app import worker
from app.crm import InMemoryCrmStore
from app.crm.service import CrmService
from app.domain import UserContext
from tests.test_crm_service import FakeAudit

TENANT = "t-crm"
ALICE = "acct-alice"


class FakeNotifier:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def notify(self, *, tenant_id, recipient_id, kind, target_type=None, target_id=None) -> None:
        self.calls.append(
            {
                "tenant_id": tenant_id,
                "recipient_id": recipient_id,
                "kind": str(kind),
                "target_type": target_type,
                "target_id": target_id,
            }
        )


@pytest.fixture(autouse=True)
def _no_runtime(monkeypatch):
    """任务测试不触发进程级自动装配（同既有 worker 测试口径）。"""
    monkeypatch.setattr(worker, "_ensure_runtime", lambda: None)
    yield
    worker.configure_crm(service=None, notifier=None)


def _alice() -> UserContext:
    return UserContext(TENANT, ALICE, "employee")


def test_tasks_return_zero_when_not_wired() -> None:
    worker.configure_crm(service=None, notifier=None)
    assert worker.recompute_crm_health() == {"tenants": 0, "accounts": 0}
    assert worker.remind_crm_activities() == {"scanned": 0, "delivered": 0}
    assert worker.remind_crm_renewals() == {"reminded": 0, "expired": 0}


def test_recompute_health_across_tenants() -> None:
    service = CrmService(InMemoryCrmStore(), audit=FakeAudit())
    account = service.create_account(_alice(), name="某某公司")
    worker.configure_crm(service=service, notifier=FakeNotifier())
    assert worker.recompute_crm_health() == {"tenants": 1, "accounts": 1}
    refreshed = service.get_account(_alice(), account.account_id)
    assert refreshed.health_score is not None


def test_activity_reminder_is_idempotent_within_day() -> None:
    service = CrmService(InMemoryCrmStore(), audit=FakeAudit())
    account = service.create_account(_alice(), name="某某公司")
    service.log_activity(
        _alice(), kind="task", subject="回访",
        due_at=datetime.now(UTC) + timedelta(hours=1), account_id=account.account_id,
    )
    # 非 task（call）与未来更远的 task 不入选
    service.log_activity(_alice(), kind="call", subject="已电话")
    service.log_activity(
        _alice(), kind="task", subject="下周", due_at=datetime.now(UTC) + timedelta(days=5),
    )
    notifier = FakeNotifier()
    worker.configure_crm(service=service, notifier=notifier)
    assert worker.remind_crm_activities() == {"scanned": 1, "delivered": 1}
    # 同日重复扫描：不重复投递（reminded_on 幂等）
    assert worker.remind_crm_activities() == {"scanned": 1, "delivered": 0}
    assert len(notifier.calls) == 1
    assert notifier.calls[0]["kind"] == "crm.activity.due"
    assert notifier.calls[0]["recipient_id"] == ALICE
    assert notifier.calls[0]["target_type"] == "crm_activity"


def test_renewal_window_notifies_and_expires_past_due() -> None:
    service = CrmService(InMemoryCrmStore(), audit=FakeAudit())
    account = service.create_account(_alice(), name="某某公司")
    today = datetime.now(UTC).date()

    soon = service.create_contract(
        _alice(), account_id=account.account_id, title="续约中", amount_cents=1000,
        ends_on=today + timedelta(days=30),
    )
    service.submit_contract_for_sign(_alice(), soon.contract_id)
    service.register_signature(_alice(), soon.contract_id, signed_at=datetime.now(UTC))

    overdue = service.create_contract(
        _alice(), account_id=account.account_id, title="已到期", amount_cents=1000,
        ends_on=today - timedelta(days=1),
    )
    service.submit_contract_for_sign(_alice(), overdue.contract_id)
    service.register_signature(_alice(), overdue.contract_id, signed_at=datetime.now(UTC))

    notifier = FakeNotifier()
    worker.configure_crm(service=service, notifier=notifier)
    result = worker.remind_crm_renewals()
    # 窗口内 1 个；已到期 1 个 ⇒ expired 翻转（状态翻转仅此，不删数据）
    assert result == {"reminded": 1, "expired": 1}
    assert notifier.calls[0]["kind"] == "crm.renewal.window"
    assert notifier.calls[0]["target_id"] == soon.contract_id
    refreshed = service.get_contract(_alice(), overdue.contract_id)
    assert refreshed.status == "expired"