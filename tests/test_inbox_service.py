"""站内通知服务的测试：事件→接收人映射、写入失败的降级、读取与已读。"""

from __future__ import annotations

import pytest

from app.audit.models import AuditAction
from app.audit.service import AuditService
from app.audit.store import InMemoryAuditStore
from app.domain import UserContext
from app.inbox import (
    InMemoryInboxStore,
    InboxItem,
    InboxKind,
    InboxNotFound,
    InboxService,
)

TENANT = "t-1"
RECIPIENT = "acct-1"


def build_service() -> tuple[InboxService, InMemoryInboxStore, AuditService]:
    store = InMemoryInboxStore()
    audit = AuditService(InMemoryAuditStore())
    return InboxService(store, audit=audit), store, audit


def actor(*, user_id: str = RECIPIENT, tenant_id: str = TENANT) -> UserContext:
    return UserContext(tenant_id=tenant_id, user_id=user_id, role="employee")


def items(store: InMemoryInboxStore) -> list[InboxItem]:
    return store.list_for_recipient(TENANT, RECIPIENT, unread_only=False, limit=10)


# ------------------------------------------------------------------ 事件映射


def test_task_approved_notifies_the_creator() -> None:
    service, store, _audit = build_service()

    service.task_approved(tenant_id=TENANT, recipient_id=RECIPIENT, task_id="task-9")

    saved = items(store)[0]
    assert saved.kind is InboxKind.TASK_APPROVED
    assert saved.title == "你提交的任务已通过审批"
    assert (saved.target_type, saved.target_id) == ("task", "task-9")


def test_plan_decided_covers_approved_and_rejected() -> None:
    service, store, _audit = build_service()

    service.plan_decided(tenant_id=TENANT, recipient_id=RECIPIENT, proposal_id="p-1", approved=True)
    service.plan_decided(tenant_id=TENANT, recipient_id=RECIPIENT, proposal_id="p-2", approved=False)

    by_kind = {entry.kind: entry for entry in items(store)}
    assert set(by_kind) == {InboxKind.PLAN_APPROVED, InboxKind.PLAN_REJECTED}
    assert by_kind[InboxKind.PLAN_REJECTED].target_id == "p-2"
    assert by_kind[InboxKind.PLAN_APPROVED].target_type == "plan_proposal"


def test_orchestration_decided_covers_approved_and_rejected() -> None:
    service, store, _audit = build_service()

    service.orchestration_decided(
        tenant_id=TENANT, recipient_id=RECIPIENT, proposal_id="o-1", approved=True
    )
    service.orchestration_decided(
        tenant_id=TENANT, recipient_id=RECIPIENT, proposal_id="o-2", approved=False
    )

    kinds = {entry.kind for entry in items(store)}
    assert kinds == {InboxKind.ORCHESTRATION_APPROVED, InboxKind.ORCHESTRATION_REJECTED}


def test_publication_manual_takeover_notifies_the_owner() -> None:
    service, store, _audit = build_service()

    service.publication_manual_takeover(
        tenant_id=TENANT, recipient_id=RECIPIENT, task_id="task-3"
    )

    saved = items(store)[0]
    assert saved.kind is InboxKind.PUBLICATION_MANUAL_TAKEOVER
    assert saved.title == "内容发布失败，需人工接管"
    assert (saved.target_type, saved.target_id) == ("publication", "task-3")


def test_registration_approved_notifies_the_applicant() -> None:
    service, store, _audit = build_service()

    service.registration_approved(tenant_id=TENANT, recipient_id=RECIPIENT)

    saved = items(store)[0]
    assert saved.kind is InboxKind.ACCOUNT_REGISTRATION_APPROVED
    assert saved.title == "你的账号申请已通过审批"
    # 判定依据：账号级结果没有可跳转对象，target 留空而不是编造 id。
    assert (saved.target_type, saved.target_id) == (None, None)


def test_notify_skips_when_recipient_is_missing() -> None:
    service, store, _audit = build_service()

    service.notify(
        tenant_id=TENANT, recipient_id="", kind=InboxKind.TASK_APPROVED, target_type="task", target_id="task-1"
    )
    service.notify(
        tenant_id="", recipient_id=RECIPIENT, kind=InboxKind.TASK_APPROVED, target_type="task", target_id="task-1"
    )

    # 判定依据：没有租户或接收人 = 没有可通知对象，不写入也不报错，更不猜接收人。
    assert items(store) == []


# ------------------------------------------------------------------ 失败降级


class BrokenStore:
    """所有方法都抛错的仓储，用于验证「通知失败不阻断业务」。"""

    def add(self, entry: InboxItem) -> InboxItem:
        raise RuntimeError("db down")

    def list_for_recipient(self, *args, **kwargs):
        raise RuntimeError("db down")

    def count_unread(self, *args, **kwargs):
        raise RuntimeError("db down")

    def mark_read(self, *args, **kwargs):
        raise RuntimeError("db down")

    def mark_all_read(self, *args, **kwargs):
        raise RuntimeError("db down")


def test_write_failure_never_breaks_business_and_is_audited() -> None:
    audit = AuditService(InMemoryAuditStore())
    service = InboxService(BrokenStore(), audit=audit)

    # 判定依据：通知不是关键路径——写入失败不得把业务调用方拖挂。
    service.task_approved(tenant_id=TENANT, recipient_id=RECIPIENT, task_id="task-1")

    recorded = [record.action for record in audit.store.list_recent(limit=10)]
    # 判定依据：失败必须可观测（写审计），不静默吞掉。
    assert recorded == [AuditAction.INBOX_WRITE_FAILED]


# ------------------------------------------------------------------ 读取与已读


def test_list_returns_only_actor_items_with_unread_count() -> None:
    service, _store, _audit = build_service()
    service.task_approved(tenant_id=TENANT, recipient_id=RECIPIENT, task_id="task-1")
    service.task_approved(tenant_id=TENANT, recipient_id="acct-2", task_id="task-2")

    listed, unread = service.list(actor(), limit=50)

    assert [entry.target_id for entry in listed] == ["task-1"]
    assert unread == 1


def test_mark_read_hides_other_actors_items() -> None:
    service, _store, _audit = build_service()
    service.task_approved(tenant_id=TENANT, recipient_id=RECIPIENT, task_id="task-1")
    inbox_id = items(_store)[0].inbox_id

    with pytest.raises(InboxNotFound):
        service.mark_read(actor(user_id="acct-2"), inbox_id)

    marked = service.mark_read(actor(), inbox_id)
    assert marked.read_at is not None


def test_mark_all_read_returns_updated_count() -> None:
    service, _store, _audit = build_service()
    for index in range(3):
        service.task_approved(tenant_id=TENANT, recipient_id=RECIPIENT, task_id=f"task-{index}")

    assert service.mark_all_read(actor()) == 3
    assert service.list(actor(), limit=50)[1] == 0
