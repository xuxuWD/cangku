"""运行内审批决议的接口层：状态码矩阵、终态、通知与审计。"""

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app import main
from app.audit.models import AuditAction
from app.audit.service import AuditService
from app.audit.store import InMemoryAuditStore
from app.inbox import InMemoryInboxStore, InboxService
from app.main import app
from app.runtime.records import InMemoryRunRecordStore
from app.runtime.run_metrics import RunMetricsService
from app.runtime.service import RuntimeService

client = TestClient(app)
TWO_STEPS = [
    {"step_id": "s1", "kind": "read", "tool": "knowledge.search"},
    {"step_id": "s2", "kind": "write", "tool": "file.write"},
]


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    from app.domain import TaskStore

    store = TaskStore()
    audit_store = InMemoryAuditStore()
    audit = AuditService(audit_store)
    metrics = RunMetricsService(InMemoryRunRecordStore())
    runtime = RuntimeService(store, run_metrics=metrics)
    inbox = InboxService(InMemoryInboxStore(), audit=audit)
    monkeypatch.setattr(main, "store", store)
    monkeypatch.setattr(main, "audit_service", audit)
    monkeypatch.setattr(main, "run_metrics_service", metrics)
    monkeypatch.setattr(main, "runtime_service", runtime)
    monkeypatch.setattr(main, "inbox_service", inbox)
    return {"audit_store": audit_store}


def headers(user_id: str = "u-1", role: str = "employee", tenant_id: str = "t-1") -> dict[str, str]:
    return {"X-Tenant-Id": tenant_id, "X-User-Id": user_id, "X-User-Role": role}


def ceo() -> dict[str, str]:
    return headers(user_id="ceo-1", role="ceo")


def start_run() -> str:
    created = client.post(
        "/api/v1/tasks",
        headers=headers(),
        json={
            "title": "审批任务",
            "employee_key": "content-operator",
            "risk_level": "low",
            "budget": 10,
            "idempotency_key": f"appr-{datetime.now(UTC).timestamp()}",
        },
    )
    assert created.status_code == 201
    run = client.post(
        f"/api/v1/tasks/{created.json()['id']}/runs",
        headers=headers(),
        json={"runtime_key": "mock", "steps": TWO_STEPS},
    )
    assert run.status_code == 201
    assert run.json()["status"] == "running"
    return run.json()["run_id"]


def test_list_shows_pending_approval() -> None:
    run_id = start_run()

    body = client.get(f"/api/v1/runs/{run_id}/approvals", headers=headers()).json()

    assert body["items"] == [
        {"approval_id": "s2", "step_id": "s2", "tool": "file.write", "status": "pending"}
    ]


def test_ceo_approval_completes_run_and_sends_no_notification() -> None:
    run_id = start_run()

    decided = client.post(
        f"/api/v1/runs/{run_id}/approvals/s2/approval", headers=ceo(), json={"approved": True}
    )

    assert decided.status_code == 200
    assert decided.json()["run_status"] == "completed"
    metrics = client.get(f"/api/v1/runs/{run_id}/metrics", headers=headers()).json()
    assert metrics["status"] == "completed"
    assert metrics["finish_reason"] == "run_completed"
    assert client.get("/api/v1/inbox", headers=headers()).json()["items"] == []


def test_ceo_rejection_fails_run_and_notifies_author() -> None:
    run_id = start_run()

    decided = client.post(
        f"/api/v1/runs/{run_id}/approvals/s2/approval", headers=ceo(), json={"approved": False}
    )

    assert decided.status_code == 200
    assert decided.json()["run_status"] == "failed"
    metrics = client.get(f"/api/v1/runs/{run_id}/metrics", headers=headers()).json()
    assert metrics["status"] == "failed"
    assert metrics["finish_reason"] == "approval_rejected"
    inbox = client.get("/api/v1/inbox", headers=headers()).json()
    assert [item["kind"] for item in inbox["items"]] == ["run.approval_rejected"]
    assert inbox["items"][0]["target_id"] == run_id


def test_decision_is_audited() -> None:
    run_id = start_run()

    client.post(
        f"/api/v1/runs/{run_id}/approvals/s2/approval", headers=ceo(), json={"approved": False}
    )

    actions = [item.action for item in main.audit_service.store.list_recent(None, limit=50)]
    assert AuditAction.RUN_APPROVAL_DECIDED in actions


def test_employee_and_author_cannot_decide() -> None:
    run_id = start_run()

    assert client.post(
        f"/api/v1/runs/{run_id}/approvals/s2/approval", headers=headers(), json={"approved": True}
    ).status_code == 403
    assert client.post(
        f"/api/v1/runs/{run_id}/approvals/s2/approval",
        headers=headers(user_id="u-1", role="ceo"),
        json={"approved": True},
    ).status_code == 403


def test_cross_tenant_unknown_and_repeated_decisions() -> None:
    run_id = start_run()
    other_tenant = headers(user_id="ceo-2", role="ceo", tenant_id="t-2")

    assert client.get(f"/api/v1/runs/{run_id}/approvals", headers=other_tenant).status_code == 404
    assert client.post(
        f"/api/v1/runs/{run_id}/approvals/s2/approval", headers=other_tenant, json={"approved": True}
    ).status_code == 404
    assert client.post(
        f"/api/v1/runs/{run_id}/approvals/nope/approval", headers=ceo(), json={"approved": True}
    ).status_code == 404

    assert client.post(
        f"/api/v1/runs/{run_id}/approvals/s2/approval", headers=ceo(), json={"approved": True}
    ).status_code == 200
    assert client.post(
        f"/api/v1/runs/{run_id}/approvals/s2/approval", headers=ceo(), json={"approved": False}
    ).status_code == 409


def test_decision_requires_login() -> None:
    run_id = start_run()

    assert client.get(f"/api/v1/runs/{run_id}/approvals").status_code == 401
    assert client.post(
        f"/api/v1/runs/{run_id}/approvals/s2/approval", json={"approved": True}
    ).status_code == 401
