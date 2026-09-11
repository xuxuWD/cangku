"""运行终态：接口可见性、取消/失败回写，以及运行结果站内通知。"""

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app import main
from app.audit.models import AuditAction
from app.audit.service import AuditService
from app.audit.store import InMemoryAuditStore
from app.domain import TaskNotFound, UserContext
from app.inbox import InMemoryInboxStore, InboxService
from app.main import app
from app.runtime.records import InMemoryRunRecordStore
from app.runtime.run_metrics import RunMetricsService
from app.runtime.service import RuntimeService

client = TestClient(app)
READ_STEPS = [{"step_id": "s1", "kind": "read", "tool": "knowledge.search"}]
FAIL_STEPS = [{"step_id": "s1", "kind": "read", "tool": "fail.step"}]


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    from app.domain import TaskStore

    store = TaskStore()
    audit_store = InMemoryAuditStore()
    audit = AuditService(audit_store)
    record_store = InMemoryRunRecordStore()
    metrics = RunMetricsService(record_store)
    runtime = RuntimeService(store, run_metrics=metrics)
    inbox = InboxService(InMemoryInboxStore(), audit=audit)
    monkeypatch.setattr(main, "store", store)
    monkeypatch.setattr(main, "audit_service", audit)
    monkeypatch.setattr(main, "run_metrics_service", metrics)
    monkeypatch.setattr(main, "runtime_service", runtime)
    monkeypatch.setattr(main, "inbox_service", inbox)
    return {"store": store, "audit_store": audit_store, "runtime": runtime}


def headers(role: str = "employee", user_id: str = "u-1", tenant_id: str = "t-1") -> dict[str, str]:
    return {"X-Tenant-Id": tenant_id, "X-User-Id": user_id, "X-User-Role": role}


def create_task() -> str:
    response = client.post(
        "/api/v1/tasks",
        headers=headers(),
        json={
            "title": "运行任务",
            "employee_key": "content-operator",
            "risk_level": "low",
            "budget": 10,
            "idempotency_key": f"run-{datetime.now(UTC).timestamp()}",
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


def start_run(task_id: str, steps: list[dict]) -> str:
    response = client.post(
        f"/api/v1/tasks/{task_id}/runs",
        headers=headers(),
        json={"runtime_key": "mock", "steps": steps},
    )
    assert response.status_code == 201
    return response.json()["run_id"]


def test_direct_run_is_recorded_and_metrics_exposes_finish_reason() -> None:
    run_id = start_run(create_task(), READ_STEPS)

    body = client.get(f"/api/v1/runs/{run_id}/metrics", headers=headers()).json()

    assert body["status"] == "completed"
    assert body["finish_reason"] == "run_completed"
    assert body["finished_at"] is not None
    assert body["proposal_id"] is None


def test_failed_run_records_step_failed_and_notifies_creator() -> None:
    run_id = start_run(create_task(), FAIL_STEPS)

    metrics = client.get(f"/api/v1/runs/{run_id}/metrics", headers=headers()).json()
    inbox = client.get("/api/v1/inbox", headers=headers()).json()

    assert metrics["status"] == "failed"
    assert metrics["finish_reason"] == "step_failed"
    assert [item["kind"] for item in inbox["items"]] == ["run.failed"]
    assert inbox["items"][0]["target_id"] == run_id
    assert "你的任务运行失败" in inbox["items"][0]["title"]


def test_cancel_records_terminal_state_and_notifies_creator() -> None:
    run_id = start_run(create_task(), READ_STEPS)

    cancelled = client.post(
        f"/api/v1/runs/{run_id}/cancel", headers=headers(), json={"reason": "测试取消"}
    )
    assert cancelled.status_code == 200

    metrics = client.get(f"/api/v1/runs/{run_id}/metrics", headers=headers()).json()
    inbox = client.get("/api/v1/inbox", headers=headers()).json()

    assert metrics["status"] == "cancelled"
    assert metrics["finish_reason"] == "cancelled_by_user"
    assert metrics["finished_at"] is not None
    assert [item["kind"] for item in inbox["items"]] == ["run.cancelled"]


def test_other_user_sees_no_run_notification() -> None:
    run_id = start_run(create_task(), FAIL_STEPS)

    inbox = client.get("/api/v1/inbox", headers=headers(user_id="u-2")).json()

    assert inbox == {"items": [], "unread_count": 0}
    assert client.get(f"/api/v1/runs/{run_id}/metrics", headers=headers(user_id="u-2")).status_code == 404


def test_paused_run_has_no_finish_reason() -> None:
    run_id = start_run(create_task(), READ_STEPS)

    assert client.post(
        f"/api/v1/runs/{run_id}/pause", headers=headers(), json={"reason": "等待确认"}
    ).status_code == 200

    metrics = client.get(f"/api/v1/runs/{run_id}/metrics", headers=headers()).json()
    assert metrics["status"] == "paused"
    assert metrics["finish_reason"] is None
    assert metrics["finished_at"] is None


def test_notify_skips_and_audits_when_task_is_unavailable(monkeypatch) -> None:
    run_id = start_run(create_task(), FAIL_STEPS)
    before = client.get("/api/v1/inbox", headers=headers()).json()["items"]

    class MissingTaskStore:
        def get(self, *_args, **_kwargs):
            raise TaskNotFound("任务不可见")

    monkeypatch.setattr(main, "store", MissingTaskStore())

    main._notify_run_terminal(UserContext("t-1", "u-1", "employee"), run_id)

    actions = [item.action for item in main.audit_service.store.list_recent(None, limit=50)]
    assert AuditAction.RUN_NOTIFY_SKIPPED in actions
    after = client.get("/api/v1/inbox", headers=headers()).json()["items"]
    assert after == before
