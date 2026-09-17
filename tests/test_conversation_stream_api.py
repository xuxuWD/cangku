"""P2b 实时流**端点层**用例（`messages:stream` §2.4 + SSE 读端点 §2.3）。

覆盖（规格 §4「依赖端点」的部分）：
  - `messages:stream` 与旧 `POST /messages` **请求/响应逐字一致**，仅多一个响应头 `X-Stream-Run-Id`；
  - **零破坏哨兵**：走旧 `POST /messages`（带键真实执行）⇒ **帧表计数为 0**；
  - 帧写入触发面：仅 `messages:stream`（不带键的桩路径同样零帧）；幂等重放**不重复写帧**；
  - SSE 读端点：帧序列 `id` 单调、`event` = `kind`、`data` 为可解析 JSON、心跳注释、
    终态关流、续播（`after_seq` / `Last-Event-ID` 取 max）**不重复投递**、无 run 挂起仅心跳；
  - 权限矩阵：`401` / `403`（`customer_admin`）/ `404`（跨租户、他人会话、未知 run）/ `422`（非法参数）。

真实 DB（PG）承载的流仓储用例见 `tests/test_conversation_stream_postgres.py`（DSN 门控）；
本文件用**内存流仓储**（与 `test_conversation_execution_api.py` 同手法），不依赖外部资源。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app import main
from app.audit.service import AuditService
from app.audit.store import InMemoryAuditStore
from app.conversation.execution import ConversationExecutionService
from app.conversation.idempotency import InMemoryExecutionIdempotencyStore
from app.conversation.service import ConversationService
from app.conversation.store import InMemoryConversationStore
from app.conversation.stream import (
    MESSAGE_ASSISTANT_KIND,
    MESSAGE_USER_KIND,
    STATUS_COMPLETED,
    STATUS_UNAVAILABLE,
    UNAVAILABLE_KIND,
    InMemoryStreamStore,
)
from app.conversation.stream_writer import StreamWriter
from app.domain import TaskStore, UserContext
from app.main import app
from app.runtime.records import InMemoryRunRecordStore
from app.runtime.run_metrics import RunMetricsService
from app.runtime.service import RuntimeService
from app.tool_execution.catalog import build_tool_spec_catalog
from app.tool_execution.service import ToolExecutionResult
from app.workforce.store import InMemoryWorkforceDirectoryStore

client = TestClient(app)

AGENT = "content-writer"
TENANT = "t-1"
EMPLOYEE = "u-1"
OTHER_USER = "u-2"


class FakeToolExecution:
    """打桩的工具执行入口：记录调用次数并返回受控结果（与实际执行语义无关）。"""

    def __init__(self, *, result=None) -> None:
        self.calls = 0
        self.requests = []
        self._result = result if result is not None else ToolExecutionResult(outcome="executed", code=201)

    def execute(self, request, *, actor=None, plan=None):
        self.calls += 1
        self.requests.append(request)
        return self._result


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    task_store = TaskStore()
    run_store = InMemoryRunRecordStore()
    metrics = RunMetricsService(run_store)
    runtime = RuntimeService(task_store, run_metrics=metrics)
    conv_store = InMemoryConversationStore()
    audit = AuditService(InMemoryAuditStore())
    conversations = ConversationService(conv_store, audit=audit)
    idempotency = InMemoryExecutionIdempotencyStore()
    directory = InMemoryWorkforceDirectoryStore()
    admin = UserContext(TENANT, "admin-1", "super_admin")
    directory.create_role(admin, role_key="writer", name="内容岗")
    directory.create_employee(admin, agent_key=AGENT, name="内容员工", role_key="writer")
    stream_store = InMemoryStreamStore()
    stream_writer = StreamWriter(stream_store, audit=audit, retention_days=7)

    monkeypatch.setattr(main, "store", task_store)
    monkeypatch.setattr(main, "run_metrics_service", metrics)
    monkeypatch.setattr(main, "runtime_service", runtime)
    monkeypatch.setattr(main, "conversation_store", conv_store)
    monkeypatch.setattr(main, "conversation_service", conversations)
    monkeypatch.setattr(main, "audit_service", audit)
    monkeypatch.setattr(main, "execution_idempotency_store", idempotency)
    monkeypatch.setattr(main, "conversation_stream_store", stream_store)
    monkeypatch.setattr(main, "conversation_stream_writer", stream_writer)
    return {
        "tasks": task_store,
        "conversations": conversations,
        "conv_store": conv_store,
        "idempotency": idempotency,
        "directory": directory,
        "stream_store": stream_store,
        "stream_writer": stream_writer,
    }


def wire_execution(monkeypatch, tool_execution, env) -> ConversationExecutionService:
    """接线执行服务：与生产装配同口径（`stream_writer` 注入，只有 `stream=True` 才写帧）。"""
    service = ConversationExecutionService(
        conversations=main.conversation_service,
        conversation_store=main.conversation_store,
        task_store=main.store,
        runtime_service=main.runtime_service,
        tool_execution=tool_execution,
        idempotency=main.execution_idempotency_store,
        catalog=build_tool_spec_catalog(),
        audit=main.audit_service,
        directory_store=env["directory"],
        stream_writer=main.conversation_stream_writer,
    )
    monkeypatch.setattr(main, "conversation_execution_service", service)
    return service


def headers(role: str = "employee", user_id: str = EMPLOYEE, tenant: str = TENANT) -> dict[str, str]:
    return {"X-Tenant-Id": tenant, "X-User-Id": user_id, "X-User-Role": role}


def create_conversation(agent_key: str | None = AGENT, *, who: str = EMPLOYEE) -> str:
    response = client.post(
        "/api/v1/conversations", headers=headers(user_id=who), json={"agent_key": agent_key}
    )
    assert response.status_code == 201, response.text
    return response.json()["conversation_id"]


def invocation(tool_key: str = "fs.list", params: dict | None = None) -> str:
    return json.dumps({"tool_key": tool_key, "params": params or {"path": "/workspace"}})


def send(conversation_id: str, content: str, *, key: str | None = None, path_suffix: str = ""):
    extra = {"Idempotency-Key": key} if key is not None else {}
    return client.post(
        f"/api/v1/conversations/{conversation_id}/messages{path_suffix}",
        headers={**headers(), **extra},
        json={"content": content},
    )


def frames_of(env, conversation_id: str, run_id: str):
    return env["stream_store"].list_frames(TENANT, conversation_id, run_id)


def frame_total(env) -> int:
    """内存仓储的帧总数（零破坏哨兵要求「帧表计数为 0」，需精确计数）。

    本文件全部使用**内存仓储** ⇒ 直接数其内部帧表；**不为测试在生产代码加只读出口**。
    """
    return sum(len(frames) for frames in env["stream_store"]._frames.values())


def _read_sse(path: str, *, request_headers: dict[str, str] | None = None):
    """读一次 SSE 响应：返回 (状态码, 响应头, 原始行)。流必须自行结束（终态 / 连接上限）。"""
    with client.stream("GET", path, headers=request_headers or headers()) as response:
        return response.status_code, response.headers, [line for line in response.iter_lines()]


def _events(lines: list[str]) -> list[dict[str, object]]:
    """把 SSE 行解析为事件（`: hb` 注释行不计入事件）。"""
    events: list[dict[str, object]] = []
    current: dict[str, object] = {}
    for line in lines:
        if line.startswith(":"):
            continue
        if line == "":
            if current:
                events.append(current)
                current = {}
            continue
        field, _, value = line.partition(": ")
        current[field] = value
    if current:
        events.append(current)
    return events


class _StreamSettings:
    """SSE 读端的极短时序桩（连接上限 1s / 轮询 50ms）：让「无 run 挂起」的流自然结束。"""

    stream_poll_interval_ms = 50
    stream_max_connection_seconds = 1

    # 其余字段按 `app.settings.Settings` 缺省（读端只读上面两项）。
    stream_retention_days = 7
    stream_max_frames = 2000
    stream_max_bytes = 4 * 1024 * 1024
    stream_stalled_hours = 6


# ------------------------------------------------------------ ① 与旧端点逐字一致 + 新响应头


def test_stream_endpoint_matches_legacy_contract_and_adds_only_run_header(monkeypatch, _isolate) -> None:
    fake = FakeToolExecution()
    wire_execution(monkeypatch, fake, _isolate)
    content = invocation()

    legacy = send(create_conversation(), content, key="k-1")
    streamed = send(create_conversation(), content, key="k-1", path_suffix=":stream")

    assert streamed.status_code == legacy.status_code == 201
    legacy_body, streamed_body = legacy.json(), streamed.json()
    assert set(streamed_body) == set(legacy_body)  # 响应体字段集合逐字一致
    assert streamed_body["stub"] is False and legacy_body["stub"] is False
    assert streamed_body["reply"]["content"] == legacy_body["reply"]["content"]
    # 唯一差异：`messages:stream` 多一个 `X-Stream-Run-Id`（有运行时）；旧端点**没有**这个头。
    assert streamed.headers["X-Stream-Run-Id"] == streamed_body["run_id"]
    assert "X-Stream-Run-Id" not in legacy.headers
    assert fake.calls == 2  # 两个端点复用同一执行服务


def test_stream_endpoint_stub_path_keeps_legacy_shape_and_writes_no_frame(monkeypatch, _isolate) -> None:
    fake = FakeToolExecution()
    wire_execution(monkeypatch, fake, _isolate)
    conversation_id = create_conversation()

    response = send(conversation_id, "你好", path_suffix=":stream")  # 不带 Idempotency-Key

    assert response.status_code == 201
    body = response.json()
    assert body["stub"] is True and body["run_id"] is None
    assert "X-Stream-Run-Id" not in response.headers  # 无运行时 ⇒ 不写该头
    assert fake.calls == 0
    assert _isolate["stream_store"].latest_run_id(TENANT, conversation_id) is None  # 桩路径零帧


# ------------------------------------------------------------ ② 零破坏哨兵（旧端点零帧）


def test_legacy_messages_endpoint_writes_zero_frames(monkeypatch, _isolate) -> None:
    """**零破坏哨兵**：旧 `POST /messages`（带键真实执行）⇒ 帧表计数为 0。"""
    fake = FakeToolExecution()
    wire_execution(monkeypatch, fake, _isolate)
    conversation_id = create_conversation()

    response = send(conversation_id, invocation(), key="k-legacy")

    assert response.status_code == 201 and response.json()["stub"] is False
    assert fake.calls == 1  # 真实执行**照旧发生**（只是不写帧）
    assert frame_total(_isolate) == 0
    assert _isolate["stream_store"].latest_run_id(TENANT, conversation_id) is None


def test_stream_path_writes_frames_in_order_with_terminal_frame(monkeypatch, _isolate) -> None:
    fake = FakeToolExecution()
    wire_execution(monkeypatch, fake, _isolate)
    conversation_id = create_conversation()

    response = send(conversation_id, invocation(), key="k-frames", path_suffix=":stream")

    assert response.status_code == 201
    run_id = response.json()["run_id"]
    frames = frames_of(_isolate, conversation_id, run_id)
    # 计划 → 工具调用 → 工具结果 → 用户消息落定 → 助手回复落定 → 终态
    assert [frame.kind for frame in frames] == [
        "plan.created",
        "tool.call",
        "tool.result",
        MESSAGE_USER_KIND,
        MESSAGE_ASSISTANT_KIND,
        "run.completed",
    ]
    assert [frame.seq for frame in frames] == [1, 2, 3, 4, 5, 6]  # 单调无跳号
    assert [frame.is_terminal for frame in frames] == [False] * 5 + [True]
    # 帧只落摘要：不落消息正文 / 参数值 / 标准输出
    assert "工具已执行完成" not in json.dumps([frame.payload for frame in frames], ensure_ascii=False)
    assert "workspace" not in json.dumps([frame.payload for frame in frames], ensure_ascii=False)
    state = _isolate["stream_store"].get_state(TENANT, conversation_id, run_id)
    assert state.status == STATUS_COMPLETED and state.is_terminal is True
    assert state.expires_at is not None
    assert state.persisted_to_message_id == response.json()["message_id"]  # 水位已回填


def test_replay_does_not_write_frames_again(monkeypatch, _isolate) -> None:
    fake = FakeToolExecution()
    wire_execution(monkeypatch, fake, _isolate)
    conversation_id = create_conversation()

    first = send(conversation_id, invocation(), key="k-replay", path_suffix=":stream")
    run_id = first.json()["run_id"]
    before = len(frames_of(_isolate, conversation_id, run_id))

    second = send(conversation_id, invocation(), key="k-replay", path_suffix=":stream")

    assert second.status_code == 201 and second.json() == first.json()  # 重放返回既有结果
    assert second.headers["X-Stream-Run-Id"] == run_id
    assert fake.calls == 1  # 不二次执行
    assert len(frames_of(_isolate, conversation_id, run_id)) == before  # 不重复写帧


# ------------------------------------------------------------ ③ SSE 读端点


def test_stream_read_delivers_ordered_events_and_closes_on_terminal(monkeypatch, _isolate) -> None:
    fake = FakeToolExecution()
    wire_execution(monkeypatch, fake, _isolate)
    conversation_id = create_conversation()
    response = send(conversation_id, invocation(), key="k-sse", path_suffix=":stream")
    run_id = response.json()["run_id"]

    status, response_headers, lines = _read_sse(
        f"/api/v1/conversations/{conversation_id}/stream?run_id={run_id}"
    )

    assert status == 200
    assert response_headers.get("content-type", "").startswith("text/event-stream")
    assert response_headers.get("cache-control") == "no-cache"
    assert response_headers.get("x-accel-buffering") == "no"
    events = _events(lines)
    assert [event["id"] for event in events] == ["1", "2", "3", "4", "5", "6"]
    assert [event["event"] for event in events] == [
        "plan.created", "tool.call", "tool.result",
        MESSAGE_USER_KIND, MESSAGE_ASSISTANT_KIND, "run.completed",
    ]
    payloads = [json.loads(event["data"]) for event in events]  # `data` 必须是可解析 JSON
    assert [item["seq"] for item in payloads] == [1, 2, 3, 4, 5, 6]
    assert payloads[-1]["is_terminal"] is True
    assert payloads[0]["kind"] == "plan.created"
    # 终态帧之后**主动关流**：响应到此结束（不再是无限流）
    assert lines[-1] == "" or events[-1]["event"] == "run.completed"


def test_stream_read_resume_does_not_redeliver(monkeypatch, _isolate) -> None:
    fake = FakeToolExecution()
    wire_execution(monkeypatch, fake, _isolate)
    conversation_id = create_conversation()
    run_id = send(conversation_id, invocation(), key="k-resume", path_suffix=":stream").json()["run_id"]

    _, _, lines = _read_sse(
        f"/api/v1/conversations/{conversation_id}/stream?run_id={run_id}&after_seq=3"
    )
    assert [event["id"] for event in _events(lines)] == ["4", "5", "6"]

    # `Last-Event-ID` 与 `after_seq` 并存 ⇒ 取 **max**（防降级重放导致重复投递）
    _, _, lines = _read_sse(
        f"/api/v1/conversations/{conversation_id}/stream?run_id={run_id}&after_seq=2",
        request_headers={**headers(), "Last-Event-ID": "5"},
    )
    assert [event["id"] for event in _events(lines)] == ["6"]

    # 起点已覆盖终态 ⇒ 无新帧、立即关流（不报错）
    status, _, lines = _read_sse(
        f"/api/v1/conversations/{conversation_id}/stream?run_id={run_id}&after_seq=99"
    )
    assert status == 200 and _events(lines) == []


def test_stream_read_defaults_to_latest_run_and_heartbeats_when_no_run(monkeypatch, _isolate) -> None:
    fake = FakeToolExecution()
    wire_execution(monkeypatch, fake, _isolate)
    conversation_id = create_conversation()  # 该会话**一次都没有 run**

    monkeypatch.setattr(main, "SSE_HEARTBEAT_SECONDS", 0.01)
    monkeypatch.setattr(main, "get_settings", lambda: _StreamSettings())

    status, _, lines = _read_sse(f"/api/v1/conversations/{conversation_id}/stream")

    assert status == 200
    assert any(line == ": hb" for line in lines), "无 run 时必须挂起并仅发心跳注释"
    assert _events(lines) == []  # 心跳是注释，不产生事件

    # 有 run 时缺省取「最新 run」（不传 run_id）
    run_id = send(conversation_id, invocation(), key="k-latest", path_suffix=":stream").json()["run_id"]
    _, _, lines = _read_sse(f"/api/v1/conversations/{conversation_id}/stream")
    assert [event["id"] for event in _events(lines)] == ["1", "2", "3", "4", "5", "6"]
    assert _isolate["stream_store"].get_state(TENANT, conversation_id, run_id) is not None


def test_stream_read_tells_unavailable_terminal_frame_for_stalled_run(monkeypatch, _isolate) -> None:
    """悬挂兜底不补写帧 ⇒ 读端按状态**显式告知**（`stream.unavailable`，终态）后关流。"""
    wire_execution(monkeypatch, FakeToolExecution(), _isolate)
    conversation_id = create_conversation()
    store = _isolate["stream_store"]
    # 只落**非终态**过程帧（模拟执行中途悬挂；终态帧会在读端直接关流，走不到状态分支）。
    assert store.append_frame(TENANT, conversation_id, "run-stalled", kind="tool.call", payload={}) is not None
    store.mark_stalled(
        cutoff=datetime.now(UTC) + timedelta(seconds=1),
        expires_at=datetime.now(UTC) + timedelta(days=7),
    )

    _, _, lines = _read_sse(f"/api/v1/conversations/{conversation_id}/stream?run_id=run-stalled")
    events = _events(lines)

    assert [event["event"] for event in events] == ["tool.call", UNAVAILABLE_KIND]
    assert json.loads(events[-1]["data"])["is_terminal"] is True
    assert json.loads(events[-1]["data"])["payload"]["reason"] == "stalled"
    assert store.get_state(TENANT, conversation_id, "run-stalled").status == STATUS_UNAVAILABLE


# ------------------------------------------------------------ ④ 权限与参数矩阵


def test_stream_endpoints_require_authentication() -> None:
    assert client.get("/api/v1/conversations/conv-1/stream").status_code == 401
    assert client.post("/api/v1/conversations/conv-1/messages:stream", json={"content": "hi"}).status_code == 401


def test_customer_admin_is_rejected_on_both_stream_endpoints(monkeypatch, _isolate) -> None:
    wire_execution(monkeypatch, FakeToolExecution(), _isolate)
    conversation_id = create_conversation()

    assert client.get(
        f"/api/v1/conversations/{conversation_id}/stream",
        headers=headers(role="customer_admin"),
    ).status_code == 403
    assert client.post(
        f"/api/v1/conversations/{conversation_id}/messages:stream",
        headers=headers(role="customer_admin"),
        json={"content": "hi"},
    ).status_code == 403


def test_stream_read_returns_404_for_other_user_and_cross_tenant(monkeypatch, _isolate) -> None:
    fake = FakeToolExecution()
    wire_execution(monkeypatch, fake, _isolate)
    conversation_id = create_conversation()
    run_id = send(conversation_id, invocation(), key="k-404", path_suffix=":stream").json()["run_id"]

    # 他人会话（非 CEO / 超管）⇒ 404（不泄露存在性）
    assert _read_sse(
        f"/api/v1/conversations/{conversation_id}/stream?run_id={run_id}",
        request_headers=headers(user_id=OTHER_USER),
    )[0] == 404
    # 跨租户 ⇒ 404
    assert _read_sse(
        f"/api/v1/conversations/{conversation_id}/stream?run_id={run_id}",
        request_headers=headers(tenant="t-other"),
    )[0] == 404
    # 未知 run（不属于该会话）⇒ 404
    assert _read_sse(
        f"/api/v1/conversations/{conversation_id}/stream?run_id=run-ghost"
    )[0] == 404


def test_stream_read_rejects_illegal_cursor_parameters(monkeypatch, _isolate) -> None:
    fake = FakeToolExecution()
    wire_execution(monkeypatch, fake, _isolate)
    conversation_id = create_conversation()

    base = f"/api/v1/conversations/{conversation_id}/stream"
    assert client.get(base, headers=headers(), params={"after_seq": "-1"}).status_code == 422
    assert client.get(base, headers=headers(), params={"after_seq": "abc"}).status_code == 422
    assert client.get(base, headers=headers(), params={"run_id": ""}).status_code == 422
    assert client.get(base, headers={**headers(), "Last-Event-ID": "abc"}).status_code == 422
    # 非法参数在**开流之前**拒绝（不是流内 500）
    assert client.get(base, headers=headers(), params={"after_seq": "not-a-number"}).headers.get(
        "content-type", ""
    ).startswith("application/json")


def test_messages_stream_keeps_archived_conflict_and_can_still_be_read(monkeypatch, _isolate) -> None:
    """归档语义与旧端点一致（`409`）；流以**终态帧**收口（不留悬挂流），且**读流仍允许**。"""
    fake = FakeToolExecution()
    wire_execution(monkeypatch, fake, _isolate)
    conversation_id = create_conversation()
    run_id = send(conversation_id, invocation(), key="k-arch", path_suffix=":stream").json()["run_id"]
    assert client.post(
        f"/api/v1/conversations/{conversation_id}/archive", headers=headers()
    ).status_code == 200

    assert send(conversation_id, invocation(), key="k-arch-2", path_suffix=":stream").status_code == 409

    # 被拒的那次执行同样以**终态帧**收口（不留悬挂流；本帧只影响读端，不改变 409 语义）
    last = [frame for frames in _isolate["stream_store"]._frames.values() for frame in frames][-1]
    assert last.kind == "run.failed" and last.is_terminal is True
    assert last.payload == {"status": "failed", "reason": "message_rejected"}

    # 归档会话可**读**流（读语义同 `GET /conversations/{id}`），且终态帧后关流
    status, _, lines = _read_sse(f"/api/v1/conversations/{conversation_id}/stream?run_id={run_id}")
    assert status == 200
    assert [event["event"] for event in _events(lines)][-1] == "run.completed"


def test_messages_stream_rejects_unknown_fields_and_empty_content(monkeypatch, _isolate) -> None:
    wire_execution(monkeypatch, FakeToolExecution(), _isolate)
    conversation_id = create_conversation()

    assert client.post(
        f"/api/v1/conversations/{conversation_id}/messages:stream",
        headers=headers(),
        json={"content": "x", "extra": 1},
    ).status_code == 422
    assert client.post(
        f"/api/v1/conversations/{conversation_id}/messages:stream",
        headers=headers(),
        json={"content": ""},
    ).status_code == 422