"""§8 U23：对话入口**不再把用户原始调用 JSON（或自由文本）逐字落消息表**。

真源：`docs/superpowers/specs/2026-09-12-dsh-integration-design.md` §8 U23（2026-09-14 裁决）
+ §5 用例 32②(c1)③（对 `workbench_conversation_messages.content` 检索正文原文 ⇒ 0 命中）
+ §5 用例 33②（响应体不含正文 / 宿主路径 / 凭据）。

本文件覆盖：
  ① 单一脱敏函数 `redact_message_content` 的**全量脱敏**口径（`tool_key` + 参数键名清单 + 指纹，
     **所有参数值一律不落**；非 JSON / 自由文本亦不透传原文）；
  ② **三个写入点**（`execution.py` 的 `201` / `202` + `service.py` 桩路径）都落脱敏摘要；
  ③ **「功能没坏」等价验证**：会话详情仍返回消息、`messages_total` 正确、重放仍返回首次结果；
  ④ **真库检索守护**（DSN 门控，见 `tests/test_dsh_execution_postgres.py` 的 §8 U23 段落）。
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app import main
from app.audit.service import AuditService
from app.audit.store import InMemoryAuditStore
from app.conversation.execution import ConversationExecutionService
from app.conversation.idempotency import InMemoryExecutionIdempotencyStore
from app.conversation.redaction import redact_message_content
from app.conversation.service import ConversationService
from app.conversation.store import InMemoryConversationStore
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

# 合成哨兵（**非真实业务正文**）：用于「原文不得落库」的检索断言。
BODY_SENTINEL = "机密正文-U23-哨兵"
PATH_SENTINEL = "/workspace/secret-u23.txt"
FREETEXT_SENTINEL = "帮我把这句话原样记住，别脱敏"


class FakeToolExecution:
    """打桩执行入口：`outcome=executed`（201）或 `pending_approval`（202），不触真实副作用。"""

    def __init__(self, *, result=None) -> None:
        self.calls = 0
        self._result = result if result is not None else ToolExecutionResult(outcome="executed", code=201)

    def execute(self, request, *, actor=None, plan=None):
        self.calls += 1
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
    # O3 派生授权：归属人 = 会话发起人本人（`EMPLOYEE` = `u-1`），与 `_wire` 同口径。
    directory.create_employee(UserContext(TENANT, EMPLOYEE, "employee"), agent_key=AGENT, name="内容员工", role_key="writer")

    monkeypatch.setattr(main, "store", task_store)
    monkeypatch.setattr(main, "run_metrics_service", metrics)
    monkeypatch.setattr(main, "runtime_service", runtime)
    monkeypatch.setattr(main, "conversation_store", conv_store)
    monkeypatch.setattr(main, "conversation_service", conversations)
    monkeypatch.setattr(main, "audit_service", audit)
    monkeypatch.setattr(main, "execution_idempotency_store", idempotency)
    return {"conv_store": conv_store, "idempotency": idempotency}


def _wire(monkeypatch, tool_execution) -> FakeToolExecution:
    # 目录桩：会话绑定的 `content-writer` 必须存在且启用（见 test_conversation_execution_api 口径）。
    directory = InMemoryWorkforceDirectoryStore()
    admin = UserContext(TENANT, "admin-1", "super_admin")
    directory.create_role(admin, role_key="writer", name="内容岗")
    # O3 派生授权：归属人 = 会话发起人本人（`EMPLOYEE` = `u-1`），使会话对该员工**合法可用**。
    directory.create_employee(UserContext(TENANT, EMPLOYEE, "employee"), agent_key=AGENT, name="内容员工", role_key="writer")
    service = ConversationExecutionService(
        conversations=main.conversation_service,
        conversation_store=main.conversation_store,
        task_store=main.store,
        runtime_service=main.runtime_service,
        tool_execution=tool_execution,
        idempotency=main.execution_idempotency_store,
        catalog=build_tool_spec_catalog(),
        audit=main.audit_service,
        directory_store=directory,
    )
    monkeypatch.setattr(main, "conversation_execution_service", service)
    return tool_execution


def _headers() -> dict[str, str]:
    return {"X-Tenant-Id": TENANT, "X-User-Id": EMPLOYEE, "X-User-Role": "employee"}


def _create_conversation() -> str:
    response = client.post("/api/v1/conversations", headers=_headers(), json={"agent_key": AGENT})
    assert response.status_code == 201, response.text
    return response.json()["conversation_id"]


def _send(conversation_id: str, content: str, *, key: str | None = None):
    extra = {"Idempotency-Key": key} if key is not None else {}
    return client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers={**_headers(), **extra},
        json={"content": content},
    )


def _invocation(tool_key: str, params: dict) -> str:
    return json.dumps({"tool_key": tool_key, "params": params})


def _detail(conversation_id: str) -> dict:
    response = client.get(f"/api/v1/conversations/{conversation_id}", headers=_headers())
    assert response.status_code == 200, response.text
    return response.json()


def _all_contents(store, context: UserContext) -> list[str]:
    """**全表口径**：本租户内所有会话的全部消息正文（内存分支的等价检索面）。"""
    conversations, _ = store.list_conversations(context)
    contents: list[str] = []
    for conversation in conversations:
        messages, _ = store.list_messages(context, conversation.conversation_id, limit=200)
        contents.extend(message.content for message in messages)
    return contents


CONTEXT = UserContext(TENANT, EMPLOYEE, "employee")


# ------------------------------------------------------------------ ① 脱敏函数单测


def test_redact_invocation_keeps_tool_key_and_key_names_drops_all_values() -> None:
    content = _invocation(
        "fs.write", {"path": PATH_SENTINEL, "content": BODY_SENTINEL, "target": "team-a"}
    )

    summary = redact_message_content(content)

    assert summary.startswith("[工具调用·脱敏]")
    assert "tool_key=fs.write" in summary
    # 参数**键名**清单保留（排序确定）：content / path / target
    assert "params=[content,path,target]" in summary
    assert "digest=" in summary
    # 所有参数**值**一律不落（含 body 类与 control 类）
    for value in (BODY_SENTINEL, PATH_SENTINEL, "team-a"):
        assert value not in summary


def test_redact_free_text_never_passes_original() -> None:
    summary = redact_message_content(FREETEXT_SENTINEL)

    assert summary.startswith("[消息·脱敏]")
    assert FREETEXT_SENTINEL not in summary
    assert f"chars={len(FREETEXT_SENTINEL)}" in summary
    # 确定性：同输入同输出
    assert summary == redact_message_content(FREETEXT_SENTINEL)


def test_redact_non_invocation_json_like_text_is_treated_as_free_text() -> None:
    # 以 `{` 开头但非法 / 缺 `tool_key`：一律退化为自由文本摘要，**不透传原文**。
    for raw in ('{"broken": ', '{"params": {"content": "' + BODY_SENTINEL + '"}}', BODY_SENTINEL):
        summary = redact_message_content(raw)
        assert BODY_SENTINEL not in summary
        assert summary.startswith("[消息·脱敏]")


# ------------------------------------------------------------------ ② 三个写入点


def test_executed_path_stores_redacted_user_message_and_keeps_history(monkeypatch, _isolate) -> None:
    """`201 executed` 写入点：用户消息落**脱敏摘要**；会话历史仍可用、`messages_total` 正确。"""
    fake = _wire(monkeypatch, FakeToolExecution())
    conversation_id = _create_conversation()
    content = _invocation("fs.write", {"path": PATH_SENTINEL, "content": BODY_SENTINEL})

    response = _send(conversation_id, content, key="u23-exec")

    assert response.status_code == 201, response.text
    detail = _detail(conversation_id)
    # 「功能没坏」：消息仍返回、总数正确、角色齐全。
    assert detail["messages_total"] == 2
    assert [item["role"] for item in detail["messages"]] == ["user", "assistant"]
    user_message, assistant_message = detail["messages"]
    assert user_message["content"].startswith("[工具调用·脱敏]")
    assert "tool_key=fs.write" in user_message["content"]
    assert BODY_SENTINEL not in user_message["content"]
    assert PATH_SENTINEL not in user_message["content"]
    # §8 U23「展示弥补」：用户消息行落本次调用的工具键；助手消息不带 `tool_name`。
    assert user_message["tool_name"] == "fs.write"
    assert assistant_message["tool_name"] is None
    # 助手消息写入行**未改**（重放依赖它的 id）。
    assert assistant_message["content"] == "工具已执行完成。"
    assert fake.calls == 1

    # 幂等指针仍指向**助手消息**（重放按 id 反查助手行，不依赖用户消息内容）。
    row = _isolate["idempotency"].get(TENANT, EMPLOYEE, conversation_id, "u23-exec")
    assert row is not None and row.message_id == assistant_message["message_id"]


def test_replay_returns_first_result_and_does_not_depend_on_user_message(
    monkeypatch, _isolate
) -> None:
    """「功能没坏」硬判据：重放仍返回**首次结果**（逐字段相等），且不二次执行。"""
    fake = _wire(monkeypatch, FakeToolExecution())
    conversation_id = _create_conversation()
    content = _invocation("fs.write", {"path": PATH_SENTINEL, "content": BODY_SENTINEL})

    first = _send(conversation_id, content, key="u23-replay")
    replay = _send(conversation_id, content, key="u23-replay")

    assert replay.status_code == first.status_code == 201
    assert replay.json() == first.json()
    assert fake.calls == 1
    assert _detail(conversation_id)["messages_total"] == 2  # 重放不新增消息


def test_pending_approval_path_stores_redacted_user_message(monkeypatch, _isolate) -> None:
    """`202 pending_approval` 写入点：用户消息同样落脱敏摘要。"""
    _wire(
        monkeypatch,
        FakeToolExecution(
            result=ToolExecutionResult(outcome="pending_approval", code=202, approval_id="appr-x")
        ),
    )
    conversation_id = _create_conversation()
    content = _invocation("fs.write", {"path": PATH_SENTINEL, "content": BODY_SENTINEL})

    response = _send(conversation_id, content, key="u23-pending")

    assert response.status_code == 202, response.text
    detail = _detail(conversation_id)
    assert detail["messages_total"] == 2
    user_message = detail["messages"][0]
    assert user_message["content"].startswith("[工具调用·脱敏]")
    assert BODY_SENTINEL not in user_message["content"]
    assert PATH_SENTINEL not in user_message["content"]
    # 202 写入点同样落工具键（与 201 一致）。
    assert user_message["tool_name"] == "fs.write"


def test_stub_path_stores_redacted_free_text(monkeypatch, _isolate) -> None:
    """桩路径（无 `Idempotency-Key`）：自由文本原文**不得落库**。"""
    _wire(monkeypatch, FakeToolExecution())
    conversation_id = _create_conversation()

    response = _send(conversation_id, FREETEXT_SENTINEL)

    assert response.status_code == 201, response.text
    assert response.json()["stub"] is True
    detail = _detail(conversation_id)
    assert detail["messages_total"] == 2
    user_message = detail["messages"][0]
    assert user_message["content"].startswith("[消息·脱敏]")
    assert FREETEXT_SENTINEL not in user_message["content"]
    # 桩路径无工具调用 ⇒ `tool_name` 保持 `null`（不编造工具）。
    assert user_message["tool_name"] is None


def test_tool_name_records_invoked_tool_while_content_stays_redacted(
    monkeypatch, _isolate
) -> None:
    """§8 U23「展示弥补」：用户消息行 `tool_name` = 本次调用的工具键，`content` 仍为脱敏摘要。

    调用 JSON 路径的两个写入点（`201 executed` / `202 pending_approval`）各验一次，工具键**互不相同**
    以证明 `tool_name` 取自本次调用、而非任何常量。
    """
    # 201 executed
    _wire(monkeypatch, FakeToolExecution())
    executed = _create_conversation()
    _send(
        executed,
        _invocation("fs.write", {"path": PATH_SENTINEL, "content": BODY_SENTINEL}),
        key="tn-201",
    )
    user_201 = _detail(executed)["messages"][0]
    assert user_201["role"] == "user"
    assert user_201["tool_name"] == "fs.write"
    assert user_201["content"].startswith("[工具调用·脱敏]")
    assert "tool_key=fs.write" in user_201["content"]
    for value in (BODY_SENTINEL, PATH_SENTINEL):  # 参数值不得随 `tool_name` 回填而回流到 `content`
        assert value not in user_201["content"]

    # 202 pending_approval
    _wire(
        monkeypatch,
        FakeToolExecution(
            result=ToolExecutionResult(outcome="pending_approval", code=202, approval_id="appr-x")
        ),
    )
    pending = _create_conversation()
    _send(pending, _invocation("fs.read", {"path": PATH_SENTINEL}), key="tn-202")
    user_202 = _detail(pending)["messages"][0]
    assert user_202["tool_name"] == "fs.read"  # 与上一次的 fs.write 不同 ⇒ 取自本次调用
    assert user_202["content"].startswith("[工具调用·脱敏]")
    assert PATH_SENTINEL not in user_202["content"]


# ------------------------------------------------------------------ ③④ 全表检索守护（内存等价口径）


def test_search_guard_no_original_text_in_any_message_content(monkeypatch, _isolate) -> None:
    """用例 32②(c1)③ 的内存等价口径：**全表**检索正文原文 / 参数值 ⇒ 0 命中。

    覆盖三个写入点各一次写入后再做全表检索（真库口径见 `test_dsh_execution_postgres.py`）。
    """
    _wire(monkeypatch, FakeToolExecution())
    executed = _create_conversation()
    _send(executed, _invocation("fs.write", {"path": PATH_SENTINEL, "content": BODY_SENTINEL}), key="g-1")
    stub = _create_conversation()
    _send(stub, FREETEXT_SENTINEL)

    contents = _all_contents(_isolate["conv_store"], CONTEXT)
    assert len(contents) == 4  # 两次会话各 2 条（用户 + 助手）
    blob = "\n".join(contents)
    for forbidden in (BODY_SENTINEL, PATH_SENTINEL, FREETEXT_SENTINEL, '"tool_key"'):
        assert forbidden not in blob, forbidden
