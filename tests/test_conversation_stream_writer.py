"""流写入网关（P2b §2.2）测试：脱敏 / 终态 / 熔断告知 / 写失败不阻断（内存仓储 + 假审计）。"""

from __future__ import annotations

import pytest

from app.audit.models import AuditAction, build_record
from app.conversation.stream import (
    MESSAGE_ASSISTANT_KIND,
    REASON_BYTE_LIMIT,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_UNAVAILABLE,
    UNAVAILABLE_KIND,
    InMemoryStreamStore,
)
from app.conversation.stream_writer import StreamWriter

TENANT = "t-stream"
CONVERSATION = "conv-1"
RUN = "run-1"
TOOL_RESULT_KIND = "tool.result"


class RecordingAudit:
    def __init__(self) -> None:
        self.records: list = []

    def record(self, action, *, tenant_id=None, actor_id=None, target_type=None, target_id=None, detail=None):
        self.records.append(
            build_record(
                action, tenant_id=tenant_id, actor_id=actor_id, target_type=target_type,
                target_id=target_id, detail=detail or {},
            )
        )


def _writer(**kwargs) -> tuple[StreamWriter, InMemoryStreamStore, RecordingAudit]:
    store = InMemoryStreamStore(**kwargs)
    audit = RecordingAudit()
    return StreamWriter(store, audit=audit, retention_days=7), store, audit


def test_write_redacts_and_sets_terminal_expiry() -> None:
    writer, store, _ = _writer()
    frame = writer.write(
        TENANT, CONVERSATION, RUN, kind=MESSAGE_ASSISTANT_KIND, payload={"api_key": "sk-secret-value", "n": 1}
    )
    assert frame is not None and frame.seq == 1
    assert "sk-secret-value" not in str(frame.payload)  # 脱敏：不落原文

    terminal = writer.write(
        TENANT, CONVERSATION, RUN, kind=MESSAGE_ASSISTANT_KIND, payload={"message_id": "m1"}, is_terminal=True
    )
    assert terminal is not None and terminal.is_terminal
    state = store.get_state(TENANT, CONVERSATION, RUN)
    assert state is not None and state.status == STATUS_COMPLETED and state.expires_at is not None


def test_run_failed_maps_to_failed_status() -> None:
    writer, store, _ = _writer()
    writer.write(TENANT, CONVERSATION, RUN, kind="run.failed", payload={}, is_terminal=True)
    state = store.get_state(TENANT, CONVERSATION, RUN)
    assert state is not None and state.status == STATUS_FAILED


def test_frame_limit_breaker_writes_notice_frame_and_audits() -> None:
    writer, store, audit = _writer(max_frames=1)
    assert writer.write(TENANT, CONVERSATION, RUN, kind=MESSAGE_ASSISTANT_KIND, payload={"n": 1}) is not None
    # 第二帧触发熔断：返回 None，但**落一帧显式告知**（反静默丢帧）
    assert writer.write(TENANT, CONVERSATION, RUN, kind=MESSAGE_ASSISTANT_KIND, payload={"n": 2}) is None
    frames = store.list_frames(TENANT, CONVERSATION, RUN)
    assert [frame.kind for frame in frames] == [MESSAGE_ASSISTANT_KIND, UNAVAILABLE_KIND]
    assert frames[-1].is_terminal is True and frames[-1].payload["reason"] == "frame_limit"
    state = store.get_state(TENANT, CONVERSATION, RUN)
    assert state is not None and state.status == STATUS_UNAVAILABLE
    # 审计：治理事件 + 受控原因（不落正文）
    records = [record for record in audit.records if record.action is AuditAction.CONVERSATION_STREAM_UNAVAILABLE]
    assert len(records) == 1 and records[0].detail == {"reason": "frame_limit", "run_id": RUN}
    # 熔断后继续写 ⇒ 仍是 None（不复活），且告知帧不重复
    assert writer.write(TENANT, CONVERSATION, RUN, kind=MESSAGE_ASSISTANT_KIND, payload={"n": 3}) is None
    assert len(store.list_frames(TENANT, CONVERSATION, RUN)) == 2


def test_byte_limit_breaker_reason() -> None:
    writer, _, audit = _writer(max_bytes=32)
    writer.write(TENANT, CONVERSATION, RUN, kind=MESSAGE_ASSISTANT_KIND, payload={"pad": "x" * 64})  # 第一帧即超限
    records = [record for record in audit.records if record.action is AuditAction.CONVERSATION_STREAM_UNAVAILABLE]
    assert records and records[0].detail["reason"] in {"byte_limit", "frame_limit"}


def test_byte_limit_applies_to_bounded_output_excerpt() -> None:
    """P2c-2 §2.6⑤：**有界摘录同样受帧字节熔断约束**（大输出 ⇒ 告知帧 + 审计，不静默丢帧）。"""
    writer, store, audit = _writer(max_bytes=256)
    assert (
        writer.write(
            TENANT,
            CONVERSATION,
            RUN,
            kind=TOOL_RESULT_KIND,
            payload={"output_excerpt": "x" * 1024, "output_truncated": True, "output_bytes": 1024},
        )
        is None
    )
    frames = store.list_frames(TENANT, CONVERSATION, RUN)
    assert [frame.kind for frame in frames] == [UNAVAILABLE_KIND]  # 显式告知帧（终态）
    assert frames[0].is_terminal is True
    records = [record for record in audit.records if record.action is AuditAction.CONVERSATION_STREAM_UNAVAILABLE]
    assert records and records[0].detail["reason"] == REASON_BYTE_LIMIT


def test_write_failure_does_not_propagate() -> None:
    class BrokenStore:
        max_frames = 10
        max_bytes = 100

        def append_frame(self, *args, **kwargs):
            raise RuntimeError("db down")

        def append_unavailable(self, *args, **kwargs):
            raise RuntimeError("db down")

        def get_state(self, *args, **kwargs):
            return None

    audit = RecordingAudit()
    writer = StreamWriter(BrokenStore(), audit=audit, retention_days=7)
    # 不抛异常（执行继续）；审计尽力留痕（write_failed）
    assert writer.write(TENANT, CONVERSATION, RUN, kind=MESSAGE_ASSISTANT_KIND, payload={}) is None
    records = [record for record in audit.records if record.action is AuditAction.CONVERSATION_STREAM_UNAVAILABLE]
    assert records and records[0].detail["reason"] == "write_failed"


def test_watermark_delegates() -> None:
    writer, store, _ = _writer()
    writer.write(TENANT, CONVERSATION, RUN, kind=MESSAGE_ASSISTANT_KIND, payload={})
    writer.watermark(TENANT, CONVERSATION, RUN, "msg-9")
    assert store.get_state(TENANT, CONVERSATION, RUN).persisted_to_message_id == "msg-9"