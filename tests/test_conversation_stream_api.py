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

import base64
import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app import main
from app.audit.service import AuditService
from app.audit.store import InMemoryAuditStore
from app.conversation.execution import ConversationExecutionService
from app.conversation.idempotency import (
    ExecutionIdempotencyRecord,
    InMemoryExecutionIdempotencyStore,
)
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
from app.domain import RiskLevel, Task, TaskStatus, TaskStore, UserContext
from app.main import app
from app.runtime.artifacts import InMemoryRunArtifactStore
from app.runtime.records import InMemoryRunRecordStore, RunRecord
from app.runtime.run_metrics import RunMetricsService
from app.runtime.service import RuntimeService
from app.tool_execution.body_cipher import BodyCipher
from app.tool_execution.catalog import build_tool_spec_catalog
from app.tool_execution.executor import ExecutionOutcome
from app.tool_execution.file_ops import FileChange
from app.tool_execution.service import ToolExecutionResult, ToolExecutionService
from app.tool_execution.store import InMemoryToolActionStore
from app.tool_execution.workspace import WorkspaceManager
from app.workforce.store import InMemoryWorkforceDirectoryStore

client = TestClient(app)

AGENT = "content-writer"
TENANT = "t-1"
EMPLOYEE = "u-1"
OTHER_USER = "u-2"


class FakeToolExecution:
    """打桩的工具执行入口：记录调用次数并返回受控结果（与实际执行语义无关）。"""

    def __init__(self, *, result=None, resume_result=None) -> None:
        self.calls = 0
        self.requests = []
        self.resume_calls = 0
        self._result = result if result is not None else ToolExecutionResult(outcome="executed", code=201)
        self._resume_result = resume_result

    def execute(self, request, *, actor=None, plan=None):
        self.calls += 1
        self.requests.append(request)
        return self._result

    def resume(self, *, tenant_id: str, run_id: str, approval_id: str):
        """P2c-2 §2.8：审批通过后的推进入口（打桩；返回受控结果或 `None`）。"""
        self.resume_calls += 1
        return self._resume_result


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
    # O3 派生授权：AGENT 归属人 = 会话发起人本人（`EMPLOYEE` = `u-1`），使会话对该员工**合法可用**。
    directory.create_employee(UserContext(TENANT, EMPLOYEE, "employee"), agent_key=AGENT, name="内容员工", role_key="writer")
    stream_store = InMemoryStreamStore()
    stream_writer = StreamWriter(stream_store, audit=audit, retention_days=7)
    artifact_store = InMemoryRunArtifactStore(retention_days=30)

    monkeypatch.setattr(main, "store", task_store)
    monkeypatch.setattr(main, "run_metrics_service", metrics)
    monkeypatch.setattr(main, "runtime_service", runtime)
    monkeypatch.setattr(main, "conversation_store", conv_store)
    monkeypatch.setattr(main, "conversation_service", conversations)
    monkeypatch.setattr(main, "audit_service", audit)
    monkeypatch.setattr(main, "execution_idempotency_store", idempotency)
    monkeypatch.setattr(main, "conversation_stream_store", stream_store)
    monkeypatch.setattr(main, "conversation_stream_writer", stream_writer)
    monkeypatch.setattr(main, "run_artifact_store", artifact_store)
    return {
        "tasks": task_store,
        "conversations": conversations,
        "conv_store": conv_store,
        "idempotency": idempotency,
        "directory": directory,
        "stream_store": stream_store,
        "stream_writer": stream_writer,
        "artifact_store": artifact_store,
    }


def wire_execution(monkeypatch, tool_execution, env, *, file_changes_max: int = 50) -> ConversationExecutionService:
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
        # P2c-3：与生产同口径（`WORKBENCH_FILE_CHANGES_MAX` 默认 50）。
        file_changes_max=file_changes_max,
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
    # P2c-2：执行器**未携带**有界输出时，帧 payload **不出现** output_* 键（只增、缺省不出现）
    assert not [
        key for frame in frames for key in frame.payload if key.startswith("output_")
    ]


def test_tool_result_frame_carries_bounded_output_with_secrets_masked(monkeypatch, _isolate) -> None:
    """P2c-2 §2.6：`tool.result` **只增**有界摘录；凭据在写帧网关被掩码；既有字段零变化。"""
    output = {
        "output_excerpt": "line1\nAuthorization: Bearer abcdef1234567890\n",
        "output_truncated": True,
        "output_bytes": 4000,
    }
    result = ToolExecutionResult(
        outcome="executed",
        code=201,
        summary={"status": "ok", "tool_key": "fs.list", "exit_code": 0},
        output=output,
    )
    wire_execution(monkeypatch, FakeToolExecution(result=result), _isolate)
    conversation_id = create_conversation()

    response = send(conversation_id, invocation(), key="k-output-1", path_suffix=":stream")

    assert response.status_code == 201, response.text
    run_id = response.json()["run_id"]
    frames = frames_of(_isolate, conversation_id, run_id)
    payload = next(frame.payload for frame in frames if frame.kind == "tool.result")
    assert payload["output_truncated"] is True  # 截断**显式告知**
    assert payload["output_bytes"] == 4000  # 读取到的字节数（有界读取）
    assert payload["output_excerpt"].startswith("line1")
    assert "abcdef1234567890" not in json.dumps(payload, ensure_ascii=False)  # 写帧网关统一脱敏
    # 既有字段零变化（只增）
    assert payload["summary"] == {"status": "ok", "tool_key": "fs.list", "exit_code": 0}
    assert payload["status"] == "ok" and str(payload["step_id"]).startswith("step-")


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
    assert response_headers.get("x-stream-run-id") == run_id  # P2c-2 只增：连接已解析到 run 时回传
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
    # P2c-2 只增：帧内 `run_id`（多客户端 / 「连接建立时无 run、稍后出现」据此归组）
    assert [item["run_id"] for item in payloads] == [run_id] * 6
    # 终态帧之后**主动关流**：响应到此结束（不再是无限流）
    assert lines[-1] == "" or events[-1]["event"] == "run.completed"


def test_stream_read_resolves_latest_run_for_history_session(monkeypatch, _isolate) -> None:
    """历史会话（不带 `?run_id=`）⇒ 读端以**最新 run** 为准并回传 `X-Stream-Run-Id`（P2c-2 只增）。"""
    fake = FakeToolExecution()
    wire_execution(monkeypatch, fake, _isolate)
    conversation_id = create_conversation()
    run_id = send(conversation_id, invocation(), key="k-history", path_suffix=":stream").json()["run_id"]

    status, response_headers, lines = _read_sse(f"/api/v1/conversations/{conversation_id}/stream")

    assert status == 200
    assert response_headers.get("x-stream-run-id") == run_id
    assert json.loads(_events(lines)[0]["data"])["run_id"] == run_id


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


# ------------------------------------------------------------ ⑨ 决议后推进（P2c-2 §2.8）


def _seed_pending_run(env, conversation_id: str, run_id: str, *, key: str) -> None:
    """把「该 run 由本次带键调用产生」写进幂等仓储（决议后推进靠它反查会话）。"""
    env["idempotency"].insert(
        ExecutionIdempotencyRecord(
            tenant_id=TENANT,
            actor_id=EMPLOYEE,
            conversation_id=conversation_id,
            idempotency_key=key,
            outcome="pending_approval",
            http_status=202,
            run_id=run_id,
        )
    )


def test_resume_frames_reopen_terminal_stream_and_close_it(monkeypatch, _isolate) -> None:
    """决议后推进：已终态的流**先重开**再续写（`seq` 单调）；写 `tool.result` + 终态收口。"""
    conversation_id = create_conversation()
    run_id = "run-resume-1"
    _seed_pending_run(_isolate, conversation_id, run_id, key="k-resume-1")
    store = _isolate["stream_store"]
    store.append_frame(TENANT, conversation_id, run_id, kind="tool.call", payload={"step_id": "step-1"})
    store.set_terminal(
        TENANT, conversation_id, run_id, status="completed", expires_at=datetime.now(UTC) + timedelta(hours=1)
    )
    assert store.get_state(TENANT, conversation_id, run_id).is_terminal is True

    result = ToolExecutionResult(
        outcome="executed",
        code=201,
        summary={"tool_key": "cmd.run", "status": "ok", "exit_code": 0},
        output={"output_excerpt": "done", "output_truncated": False, "output_bytes": 4},
    )
    main._resume_stream_frames(
        UserContext(TENANT, "ceo-1", "ceo"),
        run_id,
        "step-1",
        approved=True,
        run_status="completed",
        result=result,
    )

    frames = frames_of(_isolate, conversation_id, run_id)
    assert [frame.kind for frame in frames] == ["tool.call", "tool.result", "run.completed"]
    assert [frame.seq for frame in frames] == [1, 2, 3]  # 重开后 seq **继续单调**（不复用）
    assert frames[-1].is_terminal is True
    payload = frames[1].payload
    assert payload["resumed"] is True and payload["output_excerpt"] == "done"
    state = store.get_state(TENANT, conversation_id, run_id)
    assert state.status == "completed" and state.is_terminal is True and state.expires_at is not None


def test_resume_frames_are_skipped_without_stream(monkeypatch, _isolate) -> None:
    """零破坏：该 run **从未开流**（旧 `POST /messages` / `mock` 路径）⇒ 一帧不写、不建状态行。"""
    conversation_id = create_conversation()
    run_id = "run-resume-2"
    _isolate["idempotency"].insert(
        ExecutionIdempotencyRecord(
            tenant_id=TENANT,
            actor_id=EMPLOYEE,
            conversation_id=conversation_id,
            idempotency_key="k-resume-2",
            outcome="executed",
            http_status=201,
            run_id=run_id,
        )
    )

    main._resume_stream_frames(
        UserContext(TENANT, "ceo-1", "ceo"), run_id, "step-1", approved=True, run_status="completed"
    )

    assert frame_total(_isolate) == 0
    assert _isolate["stream_store"].get_state(TENANT, conversation_id, run_id) is None


def test_resume_frames_do_not_revive_unavailable_stream(monkeypatch, _isolate) -> None:
    """熔断 / 悬挂（`unavailable`）**不复活**：已显式告知「过程流不可用」，决议不追加任何帧。"""
    conversation_id = create_conversation()
    run_id = "run-resume-3"
    _seed_pending_run(_isolate, conversation_id, run_id, key="k-resume-3")
    store = _isolate["stream_store"]
    store.set_unavailable(
        TENANT, conversation_id, run_id, reason="byte_limit", expires_at=datetime.now(UTC) + timedelta(hours=1)
    )

    main._resume_stream_frames(
        UserContext(TENANT, "ceo-1", "ceo"), run_id, "step-1", approved=True, run_status="completed"
    )

    assert frame_total(_isolate) == 0
    state = store.get_state(TENANT, conversation_id, run_id)
    assert state.status == "unavailable" and state.is_terminal is True


def test_approval_decision_appends_resume_frames(monkeypatch, _isolate) -> None:
    """P2c-2 §2.8 端到端：`202` 待批 → CEO 决议通过 ⇒ 该 run 的流续写并**终态收口**。"""
    fake = FakeToolExecution(
        result=ToolExecutionResult(outcome="pending_approval", code=202, approval_id="approval-x"),
        resume_result=ToolExecutionResult(
            outcome="executed",
            code=201,
            summary={"tool_key": "fs.delete", "status": "ok", "exit_code": 0},
            output={"output_excerpt": "deleted", "output_truncated": False, "output_bytes": 7},
        ),
    )
    wire_execution(monkeypatch, fake, _isolate)
    monkeypatch.setattr(main, "tool_execution_service", fake)  # 决议端点按它触发「审批后重跑」
    conversation_id = create_conversation()
    response = send(
        conversation_id, invocation("fs.delete", {"path": "/workspace/tmp.txt"}),
        key="k-approve", path_suffix=":stream",
    )
    assert response.status_code == 202, response.text
    run_id = response.json()["run_id"]

    pending = client.get(
        f"/api/v1/runs/{run_id}/approvals", headers=headers("ceo", user_id="ceo-1")
    ).json()["items"]
    approval_id = next(item["approval_id"] for item in pending if item["status"] == "pending")

    decision = client.post(
        f"/api/v1/runs/{run_id}/approvals/{approval_id}/approval",
        headers=headers("ceo", user_id="ceo-1"),
        json={"approved": True},
    )
    assert decision.status_code == 200, decision.text
    assert fake.resume_calls == 1

    frames = frames_of(_isolate, conversation_id, run_id)
    kinds = [frame.kind for frame in frames]
    assert kinds[-2:] == ["tool.result", "run.completed"], kinds  # 推进帧 + 终态收口
    assert frames[-1].is_terminal is True
    resume_frame = frames[-2]
    assert resume_frame.payload["resumed"] is True
    assert resume_frame.payload["output_excerpt"] == "deleted"  # 有界回传随推进帧一并可见
    assert [frame.seq for frame in frames] == list(range(1, len(frames) + 1))  # seq 单调无跳号
    # 无流路径零破坏的对照组由 `test_resume_frames_are_skipped_without_stream` 覆盖。


# ------------------------------------------------------------ ⑤ P2c-3 变更记录 + 产物登记


def _change(index: int, *, kind: str = "created", diff: str | None = None) -> dict:
    payload = {
        "virtual_path": f"/workspace/{index}.txt",
        "change_kind": kind,
        "bytes": 10 + index,
        "sha256": f"sha256:{index:064d}",
    }
    if diff is not None:
        payload["diff_excerpt"] = diff
    return payload


def executed_with_changes(*changes: dict, truncated: bool = False) -> ToolExecutionResult:
    return ToolExecutionResult(
        outcome="executed",
        code=201,
        summary={"tool_key": "fs.write", "status": "ok", "exit_code": 0},
        output={
            "output_excerpt": "已写入 /workspace/0.txt（10 字节）",
            "file_changes": list(changes),
            "file_changes_truncated": truncated,
        },
    )


class _StubChangeExecutor:
    """打桩执行器：返回**真实执行器同构**的结局（含 `FileChange` 对象；不启容器）。"""

    def __init__(self, *change_payloads: dict) -> None:
        self._changes = tuple(FileChange(**payload) for payload in change_payloads)
        self.calls = 0

    def execute(self, **kwargs):  # noqa: ANN003 - 与真实执行器同签名（此处仅回填）
        self.calls += 1
        return ExecutionOutcome(
            ok=True,
            summary={"tool_key": "fs.write", "status": "ok", "exit_code": 0},
            file_changes=self._changes,
        )


def _body_key() -> str:
    return base64.b64encode(b"p2c3-test-body-encryption-key-32").decode("ascii")


def test_file_changes_land_in_frame_and_register_artifacts(monkeypatch, _isolate) -> None:
    """P2c-3 真库用例 ①（帧层）：`fs.write/overwrite/delete` 的变更记录**逐字入帧**（白名单键）。"""
    cases = [
        ("fs.write", _change(0, kind="created")),
        ("fs.overwrite", _change(1, kind="overwritten")),
        ("fs.delete", _change(2, kind="deleted")),
    ]
    for index, (tool_key, change) in enumerate(cases):
        fake = FakeToolExecution(result=executed_with_changes(change))
        wire_execution(monkeypatch, fake, _isolate)
        conversation_id = create_conversation()
        if tool_key == "fs.delete":
            params = {"path": change["virtual_path"]}
        else:
            params = {"path": change["virtual_path"], "content": "x"}
        response = send(conversation_id, invocation(tool_key, params), key=f"k-fs-{index}", path_suffix=":stream")
        assert response.status_code == 201, response.text
        run_id = response.json()["run_id"]

        frames = frames_of(_isolate, conversation_id, run_id)
        result_frame = next(frame for frame in frames if frame.kind == "tool.result")
        payload = result_frame.payload
        # 虚拟路径 / 类型 / 字节 / sha256 逐字入帧；未截断 ⇒ **不出现**截断键（零破坏）
        assert payload["file_changes"] == [change]
        assert "file_changes_truncated" not in payload


def test_approved_file_change_registers_artifact_and_reads_back(monkeypatch, _isolate, tmp_path) -> None:
    """P2c-3 判据 ①/③ 端到端（**真实执行服务** + 打桩执行器）：写文件需审批 ⇒ 决议后重跑 ⇒
    变更记录在**推进帧**可见 + **产物登记**落库 + 只读端点可取回（跨租户 `404` 由下一例覆盖）。"""
    shared_actions = InMemoryToolActionStore()
    runtime = RuntimeService(main.store, run_metrics=main.run_metrics_service, tool_actions=shared_actions)
    monkeypatch.setattr(main, "runtime_service", runtime)
    executor = _StubChangeExecutor(_change(7, kind="created", diff="hello\nworld"))
    service = ToolExecutionService(
        catalog=build_tool_spec_catalog(),
        body_cipher=BodyCipher.from_base64(_body_key()),
        executor=executor,
        workspace=WorkspaceManager(str(tmp_path / "ws")),
        tool_actions=shared_actions,
        audit=main.audit_service,
        authorize_execution=None,
        trusted_roots=(str(tmp_path),),
        file_changes_max=50,
        artifacts=_isolate["artifact_store"],
    )
    wire_execution(monkeypatch, service, _isolate)
    monkeypatch.setattr(main, "tool_execution_service", service)
    conversation_id = create_conversation()

    response = send(
        conversation_id,
        invocation("fs.write", {"path": "/workspace/7.txt", "content": "hello"}),
        key="k-artifact",
        path_suffix=":stream",
    )
    assert response.status_code == 202, response.text  # ⑥ 先落库、再阻塞
    run_id = response.json()["run_id"]
    assert _isolate["artifact_store"].list_for_run(TENANT, run_id) == []  # 尚未执行 ⇒ 无产物

    decision = client.post(
        f"/api/v1/runs/{run_id}/approvals/{response.json()['approval_id']}/approval",
        headers=headers("ceo", user_id="ceo-1"),
        json={"approved": True},
    )
    assert decision.status_code == 200, decision.text
    assert executor.calls == 1  # 决议后重跑确实执行了一次

    frames = frames_of(_isolate, conversation_id, run_id)
    resume_frame = next(frame for frame in frames if frame.kind == "tool.result")
    assert resume_frame.payload["file_changes"] == [_change(7, kind="created", diff="hello\nworld")]

    artifacts = response_artifacts(run_id)
    assert artifacts["total"] == 1
    item = artifacts["items"][0]
    assert item["virtual_path"] == "/workspace/7.txt" and item["change_kind"] == "created"
    assert item["bytes"] == 17 and item["sha256"].startswith("sha256:")
    assert set(item) == {
        "artifact_id",
        "virtual_path",
        "change_kind",
        "bytes",
        "sha256",
        "created_at",
        "expires_at",
    }  # 只读元数据：**不含**内容 / tenant_id / 宿主路径


def response_artifacts(run_id: str, *, user_id: str = EMPLOYEE, tenant: str = TENANT) -> dict:
    response = client.get(
        f"/api/v1/runs/{run_id}/artifacts", headers=headers(user_id=user_id, tenant=tenant)
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_file_changes_are_redacted_and_capped_in_frame(monkeypatch, _isolate) -> None:
    """帧侧硬边界：**脱敏**（键名 + 值形状）与**上限截断告知**（P2c-3 §2.6 沿用 P2c-2 口径）。"""
    secret = "Authorization: Bearer abcdef1234567890"
    fake = FakeToolExecution(
        result=executed_with_changes(
            _change(0, diff=f"line1\n{secret}"),
            _change(1),
            _change(2),
        )
    )
    wire_execution(monkeypatch, fake, _isolate, file_changes_max=2)
    conversation_id = create_conversation()
    response = send(
        conversation_id,
        invocation("fs.write", {"path": "/workspace/0.txt", "content": "x"}),
        key="k-cap",
        path_suffix=":stream",
    )
    assert response.status_code == 201
    run_id = response.json()["run_id"]

    payload = next(
        frame.payload for frame in frames_of(_isolate, conversation_id, run_id) if frame.kind == "tool.result"
    )
    assert len(payload["file_changes"]) == 2  # 上限截断
    assert payload["file_changes_truncated"] is True  # 必须显式告知
    serialized = json.dumps(payload, ensure_ascii=False)
    assert "abcdef1234567890" not in serialized  # 凭据形态值被掩码（同一脱敏函数）
    assert secret not in serialized


def test_artifacts_endpoint_ownership_and_retention(monkeypatch, _isolate) -> None:
    """端点归属（跨租户 / 他人 / 未知运行 `404`）与**保留期外不返回**（如实降级）。"""
    store = _isolate["artifact_store"]
    store.register(TENANT, "run-art-1", [FileChange(**_change(0))])
    # 过期行（保留期已到、尚未被清理）⇒ 不返回
    store.register(
        TENANT, "run-art-1", [FileChange(**_change(1))], now=datetime.now(UTC) - timedelta(days=40)
    )

    # 造一条本租户承载任务 + 运行记录，使归属判定通过（同 `/runs/{run_id}/metrics` 口径）
    task = Task(
        tenant_id=TENANT,
        project_id=None,
        created_by=EMPLOYEE,
        employee_key=AGENT,
        title="产物端点用例",
        risk_level=RiskLevel.LOW,
        budget=0,
        idempotency_key="artifacts-endpoint",
        request_fingerprint="fp",
        status=TaskStatus.QUEUED,
    )
    _isolate["tasks"].create(UserContext(TENANT, EMPLOYEE, "employee"), task)
    main.run_metrics_service.store.upsert(
        RunRecord(
            run_id="run-art-1",
            tenant_id=TENANT,
            task_id=task.id,
            runtime_key="mock",
            status="completed",
            started_at=datetime.now(UTC),
        )
    )

    assert response_artifacts("run-art-1")["total"] == 1  # 仅未过期的那一条

    cross = client.get("/api/v1/runs/run-art-1/artifacts", headers=headers(tenant="t-other"))
    assert cross.status_code == 404
    other_user = client.get(
        "/api/v1/runs/run-art-1/artifacts", headers=headers(user_id=OTHER_USER)
    )
    assert other_user.status_code == 404  # 他人运行（非 ceo / super_admin）不可见
    missing = client.get("/api/v1/runs/run-missing/artifacts", headers=headers())
    assert missing.status_code == 404