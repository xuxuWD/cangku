"""运行时状态的编解码：把内存对象与 JSONB 列互相转换。

约定：
- 时间统一用带时区的 ISO 8601 字符串；
- 事件 payload 在**编码时**就按共享的敏感键规则脱敏，数据库不长期保存凭据类键；
- 结构不合法（缺字段、类型不符、时间无法解析、事件类型未知）一律抛
  `InvalidRuntimeState`——不做「读不到就用默认值」的静默降级，否则损坏状态会被当成新运行。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from .contracts import AgentPlan, RuntimeContext, RuntimeEvent, RuntimeEventType, redact_payload
from .state import RuntimeState

# 列顺序：与 PostgresRuntimeStateStore 的 SELECT/INSERT 完全一致。
# 注意（2026-09-16「运行事件有界」改造）：事件**不在状态行里**——它们存在 append-only 的
# `workbench_runtime_events`（见 migrations/034）。状态行只保留事件计数 `event_count`。
STATE_COLUMNS = (
    "run_id",
    "tenant_id",
    "task_id",
    "status",
    "context",
    "plan",
    "event_count",
    "completed_steps",
    "approvals",
    "usage",
    "checkpoint",
    "created_at",
)

_CONTEXT_FIELDS = (
    "tenant_id",
    "user_id",
    "role_key",
    "mode",
    "project_id",
    "task_id",
    "device_id",
    "budget_cents",
    "risk_level",
    "policy_version",
)


class InvalidRuntimeState(ValueError):
    """运行时状态的持久化结构不合法（缺字段、类型不符或时间无法解析）。"""


def _require_mapping(value: Any, *, what: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise InvalidRuntimeState(f"{what} 不是对象结构")
    return value


def _require_str(payload: Mapping[str, Any], key: str, *, what: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or value == "":
        raise InvalidRuntimeState(f"{what} 的 {key} 必须是非空字符串")
    return value


def _optional_str(payload: Mapping[str, Any], key: str, *, what: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise InvalidRuntimeState(f"{what} 的 {key} 必须是字符串或空")
    return value


def _require_int(payload: Mapping[str, Any], key: str, *, what: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise InvalidRuntimeState(f"{what} 的 {key} 必须是整数")
    return value


def _str_tuple(payload: Mapping[str, Any], key: str, *, what: str) -> tuple[str, ...]:
    value = payload.get(key)
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise InvalidRuntimeState(f"{what} 的 {key} 必须是字符串数组")
    return tuple(value)


def _str_list(value: Any, *, what: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise InvalidRuntimeState(f"{what} 必须是字符串数组")
    return list(value)


def _str_dict(value: Any, *, what: str) -> dict[str, str]:
    if not isinstance(value, Mapping) or any(not isinstance(item, str) for item in value.values()):
        raise InvalidRuntimeState(f"{what} 必须是字符串到字符串的对象")
    return {str(key): str(item) for key, item in value.items()}


def _usage_dict(value: Any) -> dict[str, int]:
    if not isinstance(value, Mapping):
        raise InvalidRuntimeState("usage 必须是对象")
    result: dict[str, int] = {}
    for key, item in value.items():
        if isinstance(item, bool) or not isinstance(item, int):
            raise InvalidRuntimeState("usage 的值必须是整数")
        result[str(key)] = item
    return result


def _parse_time(value: Any, *, what: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as exc:
            raise InvalidRuntimeState(f"{what} 不是合法的 ISO 8601 时间") from exc
    else:
        raise InvalidRuntimeState(f"{what} 必须是时间或 ISO 8601 字符串")
    if parsed.tzinfo is None:
        raise InvalidRuntimeState(f"{what} 必须带时区")
    return parsed


def encode_context(context: RuntimeContext) -> dict[str, Any]:
    payload: dict[str, Any] = {field: getattr(context, field) for field in _CONTEXT_FIELDS}
    payload["knowledge_scope"] = list(context.knowledge_scope)
    payload["file_scope"] = list(context.file_scope)
    payload["expires_at"] = context.expires_at.isoformat()
    return payload


def decode_context(value: Any) -> RuntimeContext:
    payload = _require_mapping(value, what="context")
    return RuntimeContext(
        tenant_id=_require_str(payload, "tenant_id", what="context"),
        user_id=_require_str(payload, "user_id", what="context"),
        role_key=_require_str(payload, "role_key", what="context"),
        mode=_require_str(payload, "mode", what="context"),
        project_id=_optional_str(payload, "project_id", what="context"),
        task_id=_require_str(payload, "task_id", what="context"),
        device_id=_require_str(payload, "device_id", what="context"),
        knowledge_scope=_str_tuple(payload, "knowledge_scope", what="context"),
        file_scope=_str_tuple(payload, "file_scope", what="context"),
        budget_cents=_require_int(payload, "budget_cents", what="context"),
        risk_level=_require_str(payload, "risk_level", what="context"),
        policy_version=_require_str(payload, "policy_version", what="context"),
        expires_at=_parse_time(payload.get("expires_at"), what="context 的 expires_at"),
    )


def encode_plan(plan: AgentPlan) -> list[dict[str, Any]]:
    return [
        {
            "step_id": step.step_id,
            "kind": step.kind,
            "tool": step.tool,
            "requires_approval": step.requires_approval,
        }
        for step in plan.steps
    ]


def decode_plan(value: Any) -> AgentPlan:
    if not isinstance(value, list):
        raise InvalidRuntimeState("plan 必须是数组")
    steps: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        raw = _require_mapping(item, what=f"plan[{index}]")
        steps.append(
            {
                "step_id": _require_str(raw, "step_id", what=f"plan[{index}]"),
                "kind": _require_str(raw, "kind", what=f"plan[{index}]"),
                "tool": _require_str(raw, "tool", what=f"plan[{index}]"),
                "requires_approval": bool(raw.get("requires_approval", False)),
            }
        )
    return AgentPlan.from_steps(steps)


def encode_event(event: RuntimeEvent) -> dict[str, Any]:
    return {
        "run_id": event.run_id,
        "sequence": event.sequence,
        "event_type": event.event_type.value,
        "payload": redact_payload(event.payload),
    }


def decode_event(value: Any) -> RuntimeEvent:
    payload = _require_mapping(value, what="event")
    raw_type = _require_str(payload, "event_type", what="event")
    try:
        event_type = RuntimeEventType(raw_type)
    except ValueError as exc:
        raise InvalidRuntimeState(f"event 的 event_type 未知：{raw_type}") from exc
    raw_payload = payload.get("payload")
    if not isinstance(raw_payload, Mapping):
        raise InvalidRuntimeState("event 的 payload 必须是对象")
    return RuntimeEvent(
        run_id=_require_str(payload, "run_id", what="event"),
        sequence=_require_int(payload, "sequence", what="event"),
        event_type=event_type,
        payload=dict(raw_payload),
    )


def encode_state(state: RuntimeState) -> dict[str, Any]:
    return {
        "run_id": state.run_id,
        "tenant_id": state.context.tenant_id,
        "task_id": state.context.task_id,
        "status": state.status,
        "context": encode_context(state.context),
        "plan": encode_plan(state.plan),
        "event_count": state.event_count,
        "completed_steps": list(state.completed_steps),
        "approvals": dict(state.approvals),
        "usage": dict(state.usage),
        "checkpoint": dict(state.checkpoint) if state.checkpoint is not None else None,
        "created_at": state.created_at.isoformat(),
    }


def decode_state(row: Mapping[str, Any]) -> RuntimeState:
    payload = _require_mapping(row, what="runtime_state")
    for column in STATE_COLUMNS:
        if column not in payload:
            raise InvalidRuntimeState(f"runtime_state 缺少列：{column}")
    raw_checkpoint = payload["checkpoint"]
    if raw_checkpoint is not None and not isinstance(raw_checkpoint, Mapping):
        raise InvalidRuntimeState("runtime_state 的 checkpoint 必须是对象或空")
    state = RuntimeState(
        run_id=_require_str(payload, "run_id", what="runtime_state"),
        context=decode_context(payload["context"]),
        plan=decode_plan(payload["plan"]),
        event_count=_require_int(payload, "event_count", what="runtime_state"),
        completed_steps=_str_list(payload["completed_steps"], what="runtime_state 的 completed_steps"),
        status=_require_str(payload, "status", what="runtime_state"),
        checkpoint=dict(raw_checkpoint) if raw_checkpoint is not None else None,
        approvals=_str_dict(payload["approvals"], what="runtime_state 的 approvals"),
        usage=_usage_dict(payload["usage"]),
        created_at=_parse_time(payload["created_at"], what="runtime_state 的 created_at"),
    )
    return state
