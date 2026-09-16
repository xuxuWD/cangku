"""运行时状态的编解码：round-trip、写入即脱敏、损坏数据严格失败。

先写测试：`encode_*`/`decode_*` 必须可逆；结构不合法抛 InvalidRuntimeState，绝不静默降级。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.runtime.contracts import AgentPlan, RuntimeContext, RuntimeEvent, RuntimeEventType
from app.runtime.serialization import (
    InvalidRuntimeState,
    decode_context,
    decode_event,
    decode_plan,
    decode_state,
    encode_context,
    encode_event,
    encode_plan,
    encode_state,
)
from app.runtime.state import RuntimeState


def context() -> RuntimeContext:
    return RuntimeContext(
        tenant_id="t-1",
        user_id="u-1",
        role_key="content-operator",
        mode="product_manager",
        project_id="p-1",
        task_id="task-1",
        device_id="device:u-1",
        knowledge_scope=("kb-1", "kb-2"),
        file_scope=(),
        budget_cents=12345,
        risk_level="low",
        policy_version="policy-1",
        expires_at=datetime(2026, 9, 11, 12, 30, tzinfo=UTC),
    )


def plan() -> AgentPlan:
    return AgentPlan.from_steps(
        [
            {"step_id": "s1", "kind": "read", "tool": "knowledge.search"},
            {"step_id": "s2", "kind": "write", "tool": "file.write"},
        ]
    )


def test_context_round_trip() -> None:
    original = context()

    restored = decode_context(encode_context(original))

    assert restored == original
    assert restored.expires_at == datetime(2026, 9, 11, 12, 30, tzinfo=UTC)
    assert restored.knowledge_scope == ("kb-1", "kb-2")


def test_plan_round_trip_keeps_approval_flags() -> None:
    original = plan()

    restored = decode_plan(encode_plan(original))

    assert restored == original
    assert [step.requires_approval for step in restored.steps] == [False, True]


def test_event_round_trip_redacts_sensitive_keys_on_write() -> None:
    event = RuntimeEvent(
        run_id="run-1",
        sequence=1,
        event_type=RuntimeEventType.TOOL_RESULT,
        payload={
            "step_id": "s1",
            "nested": {"ACCESS_TOKEN": "secret-value", "safe": "ok"},
            "cookie": "session=abc",
            "plain": 7,
        },
    )

    encoded = encode_event(event)

    assert encoded["payload"]["nested"]["ACCESS_TOKEN"] == "[已隐藏]"
    assert encoded["payload"]["nested"]["safe"] == "ok"
    # 敏感键规则是「键名精确匹配（忽略大小写）」，不是子串匹配。
    assert encoded["payload"]["cookie"] == "[已隐藏]"
    assert encoded["payload"]["plain"] == 7
    assert "secret-value" not in str(encoded)
    restored = decode_event(encoded)
    assert restored.event_type is RuntimeEventType.TOOL_RESULT
    assert restored.payload["nested"]["ACCESS_TOKEN"] == "[已隐藏]"


def state() -> RuntimeState:
    value = RuntimeState(
        run_id="run-1", context=context(), plan=plan(), created_at=datetime(2026, 9, 11, 8, 0, tzinfo=UTC)
    )
    value.status = "running"
    value.completed_steps = ["s1"]
    value.approvals = {"s2": "pending"}
    value.usage = {"tool_calls": 2, "successful_tools": 1}
    # 事件不在状态行里（2026-09-16 改造）：状态行只保留事件计数。
    value.event_count = 1
    value.checkpoint = {"status": "running", "completed_steps": ["s1"], "next_step": 1}
    return value


def test_state_round_trip() -> None:
    original = state()

    restored = decode_state(encode_state(original))

    assert restored.run_id == "run-1"
    assert restored.context == original.context
    assert restored.plan == original.plan
    assert restored.status == "running"
    assert restored.completed_steps == ["s1"]
    assert restored.approvals == {"s2": "pending"}
    assert restored.usage == {"tool_calls": 2, "successful_tools": 1}
    assert restored.checkpoint == {"status": "running", "completed_steps": ["s1"], "next_step": 1}
    assert restored.created_at == datetime(2026, 9, 11, 8, 0, tzinfo=UTC)
    assert restored.event_count == 1
    # 事件不参与状态行编解码（它们是 append-only 表里的行）。
    assert "events" not in encode_state(original)


def test_state_round_trip_without_checkpoint() -> None:
    original = state()
    original.checkpoint = None

    restored = decode_state(encode_state(original))

    assert restored.checkpoint is None


def test_decode_rejects_missing_and_malformed_fields() -> None:
    good = encode_state(state())

    for key in ("run_id", "status", "context", "plan", "event_count", "created_at"):
        broken = {name: value for name, value in good.items() if name != key}
        with pytest.raises(InvalidRuntimeState):
            decode_state(broken)

    with pytest.raises(InvalidRuntimeState):
        decode_context({**encode_context(context()), "expires_at": "not-a-time"})
    with pytest.raises(InvalidRuntimeState):
        decode_context({**encode_context(context()), "budget_cents": "many"})
    with pytest.raises(InvalidRuntimeState):
        decode_plan("not-a-plan")
    with pytest.raises(InvalidRuntimeState):
        decode_event({"run_id": "run-1", "sequence": "first", "event_type": "plan.created", "payload": {}})
    with pytest.raises(InvalidRuntimeState):
        decode_event({"run_id": "run-1", "sequence": 1, "event_type": "not.an.event", "payload": {}})
    with pytest.raises(InvalidRuntimeState):
        decode_event({"run_id": "run-1", "sequence": 1, "event_type": "plan.created", "payload": []})


def test_timezone_is_preserved() -> None:
    shifted = RuntimeContext(
        tenant_id="t-1", user_id="u-1", role_key="content-operator", mode="product_manager",
        project_id=None, task_id="task-1", device_id="device:u-1", knowledge_scope=(),
        file_scope=(), budget_cents=0, risk_level="low", policy_version="policy-1",
        expires_at=datetime(2026, 9, 11, 20, 30, tzinfo=timezone(timedelta(hours=8))),
    )

    restored = decode_context(encode_context(shifted))

    assert restored.expires_at.tzinfo is not None
    assert restored.expires_at == shifted.expires_at
