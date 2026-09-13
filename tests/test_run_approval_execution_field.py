"""§5 用例 31：决议端点 `execution` 响应体（规格 §4.1.6-7）。

在既有 `{run_id, approval_id, status, run_status}` 之上**新增可选字段**
`execution: {outcome, code?, message_id?}`；**既有字段一个都不改**；
响应体**不得含**工具参数原文 / 宿主路径 / 凭据。
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app import main
from app.audit.service import AuditService
from app.audit.store import InMemoryAuditStore
from app.inbox import InMemoryInboxStore, InboxService
from app.main import app
from app.runtime.records import InMemoryRunRecordStore
from app.runtime.run_metrics import RunMetricsService
from app.runtime.service import RuntimeService
from app.tool_execution.service import ToolExecutionResult

client = TestClient(app)
TWO_STEPS = [
    {"step_id": "s1", "kind": "read", "tool": "knowledge.search"},
    {"step_id": "s2", "kind": "write", "tool": "file.write"},
]


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    from app.domain import TaskStore

    store = TaskStore()
    audit = AuditService(InMemoryAuditStore())
    metrics = RunMetricsService(InMemoryRunRecordStore())
    runtime = RuntimeService(store, run_metrics=metrics)
    inbox = InboxService(InMemoryInboxStore(), audit=audit)
    monkeypatch.setattr(main, "store", store)
    monkeypatch.setattr(main, "audit_service", audit)
    monkeypatch.setattr(main, "run_metrics_service", metrics)
    monkeypatch.setattr(main, "runtime_service", runtime)
    monkeypatch.setattr(main, "inbox_service", inbox)


def headers(user_id: str = "u-1", role: str = "employee") -> dict[str, str]:
    return {"X-Tenant-Id": "t-1", "X-User-Id": user_id, "X-User-Role": role}


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
            "idempotency_key": f"exec-{datetime.now(UTC).timestamp()}",
        },
    )
    assert created.status_code == 201
    run = client.post(
        f"/api/v1/tasks/{created.json()['id']}/runs",
        headers=headers(),
        json={"runtime_key": "mock", "steps": TWO_STEPS},
    )
    assert run.status_code == 201
    return run.json()["run_id"]


class RecordingToolExecution:
    def __init__(self, *, result=None, error=None) -> None:
        self.calls = 0
        self._result = result
        self._error = error

    def resume(self, *, tenant_id, run_id, approval_id, actor=None, plan=None):
        self.calls += 1
        if self._error is not None:
            raise self._error
        return self._result


def test_mock_backend_has_no_execution_field(monkeypatch) -> None:
    """`tool_execution_service is None`（backend=mock）→ 既有字段与形状与改动前完全一致。"""
    monkeypatch.setattr(main, "tool_execution_service", None)
    run_id = start_run()

    decided = client.post(
        f"/api/v1/runs/{run_id}/approvals/s2/approval", headers=ceo(), json={"approved": True}
    )

    assert decided.status_code == 200
    assert set(decided.json().keys()) == {"run_id", "approval_id", "status", "run_status"}


def test_execution_field_added_and_existing_fields_unchanged(monkeypatch) -> None:
    recorder = RecordingToolExecution(
        result=ToolExecutionResult(outcome="executed", code=201, message_id="msg-1")
    )
    monkeypatch.setattr(main, "tool_execution_service", recorder)
    run_id = start_run()

    decided = client.post(
        f"/api/v1/runs/{run_id}/approvals/s2/approval", headers=ceo(), json={"approved": True}
    )

    assert decided.status_code == 200
    body = decided.json()
    # 既有字段不变。
    assert body["run_id"] == run_id
    assert body["approval_id"] == "s2"
    assert body["status"] == "approved"
    assert "run_status" in body
    assert set(body) == {"run_id", "approval_id", "status", "run_status", "execution"}
    # 新增可选字段 `execution`。
    assert body["execution"] == {"outcome": "executed", "code": 201, "message_id": "msg-1"}


def test_execution_field_omits_absent_optional_parts(monkeypatch) -> None:
    recorder = RecordingToolExecution(
        result=ToolExecutionResult(outcome="pending_approval", code=202, approval_id="appr-1")
    )
    monkeypatch.setattr(main, "tool_execution_service", recorder)
    run_id = start_run()

    body = client.post(
        f"/api/v1/runs/{run_id}/approvals/s2/approval", headers=ceo(), json={"approved": True}
    ).json()

    # `code` 存在、`message_id` 缺省 → 不出现。
    assert body["execution"] == {"outcome": "pending_approval", "code": 202}


def test_rejected_decision_has_no_execution_field(monkeypatch) -> None:
    recorder = RecordingToolExecution(result=ToolExecutionResult(outcome="executed", code=201))
    monkeypatch.setattr(main, "tool_execution_service", recorder)
    run_id = start_run()

    body = client.post(
        f"/api/v1/runs/{run_id}/approvals/s2/approval", headers=ceo(), json={"approved": False}
    ).json()

    assert "execution" not in body
    assert recorder.calls == 0


def test_execution_response_does_not_leak_params_or_host_paths(monkeypatch) -> None:
    """反例：即便执行结果摘要里带着参数原文 / 宿主路径，响应体也**不得**透出（§4.1.6-7 / 用例 33②）。"""
    recorder = RecordingToolExecution(
        result=ToolExecutionResult(
            outcome="executed",
            code=201,
            message_id="msg-1",
            action_id="act-1",
            summary={"content": "机密正文", "host_path": "/etc/host/secret", "args_digest": "sha256:x"},
        )
    )
    monkeypatch.setattr(main, "tool_execution_service", recorder)
    run_id = start_run()

    decided = client.post(
        f"/api/v1/runs/{run_id}/approvals/s2/approval", headers=ceo(), json={"approved": True}
    )

    assert decided.status_code == 200
    text = decided.text
    for forbidden in ("机密正文", "/etc/host/secret", "args_digest", "act-1"):
        assert forbidden not in text, forbidden
