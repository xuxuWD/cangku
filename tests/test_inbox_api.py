"""站内通知接口的测试：本人可见性、跨租户 404、未读筛选与全部已读。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app import main
from app.inbox import InMemoryInboxStore, InboxService
from app.main import app

client = TestClient(app)

INBOX = "/api/v1/inbox"


def headers(*, user_id: str = "acct-1", tenant_id: str = "t-1", role: str = "employee") -> dict[str, str]:
    return {"X-Tenant-Id": tenant_id, "X-User-Id": user_id, "X-User-Role": role}


def install(monkeypatch, *, recipient: str = "acct-1") -> InboxService:
    """装配内存收件箱，并写入两条通知（任务通过 + 计划提案驳回）。"""
    service = InboxService(InMemoryInboxStore())
    monkeypatch.setattr(main, "inbox_service", service)
    service.task_approved(tenant_id="t-1", recipient_id=recipient, task_id="task-1")
    service.plan_decided(
        tenant_id="t-1", recipient_id=recipient, proposal_id="p-1", approved=False
    )
    return service


def test_list_returns_own_items_with_unread_count(monkeypatch) -> None:
    install(monkeypatch)

    response = client.get(INBOX, headers=headers())

    assert response.status_code == 200
    body = response.json()
    assert body["unread_count"] == 2
    kinds = {item["kind"] for item in body["items"]}
    assert kinds == {"task.approved", "plan.rejected"}
    task_item = next(item for item in body["items"] if item["kind"] == "task.approved")
    assert task_item["title"] == "你提交的任务已通过审批"
    assert (task_item["target_type"], task_item["target_id"]) == ("task", "task-1")
    assert task_item["read_at"] is None


def test_list_is_scoped_to_the_calling_user(monkeypatch) -> None:
    install(monkeypatch)

    other = client.get(INBOX, headers=headers(user_id="acct-2"))

    assert other.status_code == 200
    # 判定依据：收件箱只返回本人条目，看不到别人的通知。
    assert other.json() == {"items": [], "unread_count": 0}


def test_unread_only_filter_keeps_total_unread_count(monkeypatch) -> None:
    service = install(monkeypatch)
    listed = client.get(INBOX, headers=headers()).json()
    first_id = listed["items"][0]["inbox_id"]
    assert client.post(f"{INBOX}/{first_id}/read", headers=headers()).status_code == 200

    filtered = client.get(f"{INBOX}?unread_only=true", headers=headers()).json()

    assert len(filtered["items"]) == 1
    # 判定依据：unread_count 是本人未读总数，不随筛选条件变化。
    assert filtered["unread_count"] == 1
    assert all(item["read_at"] is None for item in filtered["items"])


def test_limit_out_of_range_is_rejected(monkeypatch) -> None:
    install(monkeypatch)

    assert client.get(f"{INBOX}?limit=0", headers=headers()).status_code == 422
    assert client.get(f"{INBOX}?limit=201", headers=headers()).status_code == 422


def test_mark_read_is_idempotent_and_hides_other_users_items(monkeypatch) -> None:
    install(monkeypatch)
    inbox_id = client.get(INBOX, headers=headers()).json()["items"][0]["inbox_id"]

    first = client.post(f"{INBOX}/{inbox_id}/read", headers=headers())
    second = client.post(f"{INBOX}/{inbox_id}/read", headers=headers())

    assert first.status_code == 200
    assert first.json()["read_at"] is not None
    # 判定依据：重复标记幂等——首次已读时间不被覆盖。
    assert second.status_code == 200
    assert second.json()["read_at"] == first.json()["read_at"]

    # 判定依据：他人或跨租户一律 404，不泄露存在性。
    assert client.post(f"{INBOX}/{inbox_id}/read", headers=headers(user_id="acct-2")).status_code == 404
    assert client.post(f"{INBOX}/{inbox_id}/read", headers=headers(tenant_id="t-2")).status_code == 404
    assert client.post(f"{INBOX}/inbox-missing/read", headers=headers()).status_code == 404


def test_read_all_marks_every_unread_item(monkeypatch) -> None:
    install(monkeypatch)

    response = client.post(f"{INBOX}/read-all", headers=headers())

    assert response.status_code == 200
    assert response.json() == {"updated": 2}
    assert client.get(INBOX, headers=headers()).json()["unread_count"] == 0
