"""运行终态：接口可见性、取消/失败回写，以及运行结果站内通知（含 S1 第三款的上文标识）。"""

import base64
import json
import os
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app import main
from app.audit.models import AuditAction
from app.audit.service import AuditService
from app.audit.store import InMemoryAuditStore
from app.conversation.execution import ConversationExecutionService
from app.conversation.idempotency import InMemoryExecutionIdempotencyStore
from app.conversation.service import ConversationService
from app.conversation.store import InMemoryConversationStore
from app.domain import TaskNotFound, UserContext
from app.inbox import (
    InboxItem,
    InboxKind,
    InboxService,
    InMemoryInboxStore,
    PostgresInboxStore,
)
from app.main import app
from app.runtime.records import InMemoryRunRecordStore
from app.runtime.run_metrics import RunMetricsService
from app.runtime.service import RuntimeService
from app.tool_execution.body_cipher import BodyCipher
from app.tool_execution.catalog import build_tool_spec_catalog
from app.tool_execution.executor import DeterministicFakeExecutor
from app.tool_execution.service import ToolExecutionService
from app.tool_execution.store import InMemoryToolActionStore
from app.tool_execution.workspace import WorkspaceManager
from app.workforce.store import InMemoryWorkforceDirectoryStore

client = TestClient(app)
READ_STEPS = [{"step_id": "s1", "kind": "read", "tool": "knowledge.search"}]
FAIL_STEPS = [{"step_id": "s1", "kind": "read", "tool": "fail.step"}]
# 待审批步骤：运行**停在运行中**（终态不可再干预，故干预类用例必须用非终态运行）。
PENDING_STEPS = [{"step_id": "s1", "kind": "write", "tool": "fs.write", "requires_approval": True}]


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
    # S1 第三款：会话反查走幂等行；这里换成空实现，「非会话触发的运行」必然是 `None`（不依赖环境）。
    monkeypatch.setattr(main, "execution_idempotency_store", InMemoryExecutionIdempotencyStore())
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
    # 终态不可再干预 ⇒ 用「停在运行中」的运行来验证取消路径。
    run_id = start_run(create_task(), PENDING_STEPS)

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
    # 终态不可再干预 ⇒ 用「停在运行中」的运行来验证暂停路径。
    run_id = start_run(create_task(), PENDING_STEPS)

    assert client.post(
        f"/api/v1/runs/{run_id}/pause", headers=headers(), json={"reason": "等待确认"}
    ).status_code == 200

    metrics = client.get(f"/api/v1/runs/{run_id}/metrics", headers=headers()).json()
    assert metrics["status"] == "paused"
    assert metrics["finish_reason"] is None


def test_terminal_run_cannot_be_intervened_again() -> None:
    """终态即终态：已完成 / 已取消的运行上，暂停 / 恢复 / 取消一律 409（不给终态二次结局）。"""
    run_id = start_run(create_task(), READ_STEPS)  # 读完即 completed

    for path, payload in (
        ("pause", {"reason": "再暂停"}),
        ("cancel", {"reason": "再取消"}),
        ("resume", None),
    ):
        response = client.post(
            f"/api/v1/runs/{run_id}/{path}",
            headers=headers(),
            json=payload if payload is not None else None,
        )
        assert response.status_code == 409, f"{path} 应被终态拒绝：{response.text}"

    metrics = client.get(f"/api/v1/runs/{run_id}/metrics", headers=headers()).json()
    assert metrics["status"] == "completed", "终态不得被干预动作改写"


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


# ------------------- S1 第三款：通知携带上文（该会话 / 该条审批），直达「该会话的该条卡」 -------------------


def test_rejected_approval_notification_carries_approval_and_no_guessed_conversation() -> None:
    """非会话触发的运行（无幂等行）：带上 `approval_id`，`conversation_id` 为 `null`——服务端不猜会话。"""
    run_id = start_run(create_task(), PENDING_STEPS)

    decided = client.post(
        f"/api/v1/runs/{run_id}/approvals/s1/approval",
        headers=headers(user_id="ceo-1", role="ceo"),
        json={"approved": False},
    )
    assert decided.status_code == 200, decided.text

    item = client.get("/api/v1/inbox", headers=headers()).json()["items"][0]
    assert item["kind"] == "run.approval_rejected"
    assert item["target_type"] == "run"
    assert item["target_id"] == run_id
    assert item["target_approval_id"] == "s1"
    assert item["target_conversation_id"] is None


def test_run_failure_notification_stays_null_context_when_no_conversation() -> None:
    """失败/取消类通知在同一反查链路上：无幂等行 ⇒ 两个上文标识都为 `null`（旧落点不变）。"""
    run_id = start_run(create_task(), FAIL_STEPS)

    item = client.get("/api/v1/inbox", headers=headers()).json()["items"][0]
    assert item["kind"] == "run.failed"
    assert item["target_id"] == run_id
    assert item["target_conversation_id"] is None
    assert item["target_approval_id"] is None


AGENT = "content-writer"


def _owner_uid() -> int:
    getuid = getattr(os, "getuid", None)
    return int(getuid()) if getuid is not None else 0


@pytest.fixture()
def conversation_wired(monkeypatch, tmp_path):
    """对话触发的运行真链路（会话 → 幂等行 → 运行 → 待批）：用来证明 `conversation_id` 反查。"""
    task_store = main.store
    run_store = InMemoryRunRecordStore()
    metrics = RunMetricsService(run_store)
    action_store = InMemoryToolActionStore()
    runtime = RuntimeService(task_store, run_metrics=metrics, tool_actions=action_store)
    audit = main.audit_service
    conv_store = InMemoryConversationStore()
    conversations = ConversationService(conv_store, audit=audit)
    idempotency = InMemoryExecutionIdempotencyStore()
    directory = InMemoryWorkforceDirectoryStore()
    admin = UserContext("t-1", "admin-1", "super_admin")
    directory.create_role(admin, role_key="writer", name="内容岗")
    # O3 派生授权：AGENT 归属人 = 会话发起人本人（`u-1`，见 `headers()` 默认），使会话合法可用。
    directory.create_employee(UserContext("t-1", "u-1", "employee"), agent_key=AGENT, name="内容员工", role_key="writer")

    trusted = tmp_path / "trusted"
    trusted.mkdir(exist_ok=True)
    workspace_root = tmp_path / "ws"
    workspace_root.mkdir(exist_ok=True)
    tool_execution = ToolExecutionService(
        catalog=build_tool_spec_catalog(),
        body_cipher=BodyCipher.from_base64(base64.b64encode(os.urandom(32)).decode("ascii")),
        executor=DeterministicFakeExecutor(),
        workspace=WorkspaceManager(str(workspace_root)),
        tool_actions=action_store,
        run_records=run_store,
        audit=audit,
        authorize_execution=runtime.ensure_execution_authorized,
        trusted_roots=(str(trusted),),
        trusted_uid=_owner_uid(),
    )
    route = ConversationExecutionService(
        conversations=conversations,
        conversation_store=conv_store,
        task_store=task_store,
        runtime_service=runtime,
        tool_execution=tool_execution,
        idempotency=idempotency,
        catalog=build_tool_spec_catalog(),
        audit=audit,
        directory_store=directory,
    )
    monkeypatch.setattr(main, "run_metrics_service", metrics)
    monkeypatch.setattr(main, "runtime_service", runtime)
    monkeypatch.setattr(main, "conversation_store", conv_store)
    monkeypatch.setattr(main, "conversation_service", conversations)
    monkeypatch.setattr(main, "execution_idempotency_store", idempotency)
    monkeypatch.setattr(main, "tool_execution_service", tool_execution)
    monkeypatch.setattr(main, "conversation_execution_service", route)
    return {"runtime": runtime, "idempotency": idempotency}


def test_conversation_run_notification_points_back_to_the_conversation_card(conversation_wired) -> None:
    """对话里触发的运行被驳回 ⇒ 通知带上该会话与**该条审批**（界面据此直达那张卡）。"""
    conversation = client.post(
        "/api/v1/conversations", headers=headers(), json={"agent_key": AGENT}
    ).json()["conversation_id"]
    invocation = json.dumps(
        {"tool_key": "fs.write", "params": {"path": "/workspace/a.txt", "content": "正文"}}
    )
    pending = client.post(
        f"/api/v1/conversations/{conversation}/messages",
        headers={**headers(), "Idempotency-Key": "s1-third-1"},
        json={"content": invocation},
    )
    assert pending.status_code == 202, pending.text
    run_id, approval_id = pending.json()["run_id"], pending.json()["approval_id"]
    assert run_id and approval_id
    # 幂等行确实带会话（反查的来源就是它）。
    assert conversation_wired["idempotency"].find_by_run("t-1", run_id).conversation_id == conversation

    decided = client.post(
        f"/api/v1/runs/{run_id}/approvals/{approval_id}/approval",
        headers=headers(user_id="ceo-1", role="ceo"),
        json={"approved": False},
    )
    assert decided.status_code == 200, decided.text

    item = client.get("/api/v1/inbox", headers=headers()).json()["items"][0]
    assert item["kind"] == "run.approval_rejected"
    assert item["target_type"] == "run"
    assert item["target_id"] == run_id
    assert item["target_conversation_id"] == conversation
    assert item["target_approval_id"] == approval_id
    # 通知仍不承载正文（收件箱只放「发生了什么 + 去哪看」）。
    assert "正文" not in json.dumps(item, ensure_ascii=False)


# ------------------------------- 真库（pg16）：迁移 041 加列 + 上下文往返 + 存量行零破坏

PG_DSN = os.environ.get("WORKBENCH_TEST_DATABASE_URL", "")
PG_TENANT = "test-inbox-context-pg"


def test_inbox_context_columns_round_trip_postgres() -> None:
    """真库往返：`041` 两列能写能读；写入方仍是 `InboxService`（不另写一套 SQL）；存量行（NULL）不破坏。"""
    if not PG_DSN:
        pytest.skip("未设置 WORKBENCH_TEST_DATABASE_URL，跳过真库集成测试")
    psycopg = pytest.importorskip("psycopg")
    from pathlib import Path

    from app.migrations import apply_migrations

    connection = psycopg.connect(PG_DSN, autocommit=True)
    apply_migrations(connection, Path(__file__).resolve().parents[1] / "migrations")
    store = PostgresInboxStore(connection)
    service = InboxService(store)
    try:
        service.run_approval_rejected(
            tenant_id=PG_TENANT,
            recipient_id="u-1",
            run_id="run-pg-with-context",
            conversation_id="conv-pg",
            approval_id="approval-pg-1",
        )
        service.run_decided(
            tenant_id=PG_TENANT,
            recipient_id="u-1",
            run_id="run-pg-without-context",
            status="cancelled",
        )
        # 存量行：迁移前写入的通知（新列为 NULL），用最朴素的 INSERT 复现，读回不得报错。
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO workbench_inbox_items (inbox_id, tenant_id, recipient_id, kind, title)
                VALUES (%s, %s, %s, %s, %s)
                """,
                ("inbox-legacy-pg", PG_TENANT, "u-1", "run.cancelled", "存量通知"),
            )

        rows = {
            item.target_id: item
            for item in store.list_for_recipient(PG_TENANT, "u-1", unread_only=False, limit=10)
        }
        with_context = rows["run-pg-with-context"]
        assert with_context.target_conversation_id == "conv-pg"
        assert with_context.target_approval_id == "approval-pg-1"
        without_context = rows["run-pg-without-context"]
        assert without_context.target_conversation_id is None
        assert without_context.target_approval_id is None
        legacy = store.mark_read(PG_TENANT, "u-1", "inbox-legacy-pg")
        assert legacy.read_at is not None
        assert legacy.target_conversation_id is None and legacy.target_approval_id is None
    finally:
        with connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM workbench_inbox_items WHERE tenant_id = %s", (PG_TENANT,)
            )
        connection.close()


def test_inbox_item_rejects_nothing_and_hydrates_legacy_shape() -> None:
    """内存实现同口径：不带上下文的条目（= 存量行形态）取回来是 `None`，不是空串。"""
    store = InMemoryInboxStore()
    store.add(
        InboxItem(
            tenant_id="t-1",
            recipient_id="u-1",
            kind=InboxKind.RUN_CANCELLED,
            title="存量通知",
            target_type="run",
            target_id="run-legacy",
        )
    )
    item = store.list_for_recipient("t-1", "u-1", unread_only=False, limit=10)[0]
    assert item.target_conversation_id is None and item.target_approval_id is None
