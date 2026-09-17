"""`PostgresStreamStore` 的**真库**回归（P2b 实时流，迁移 036）。

口径（沿用 `tests/test_memory_postgres.py` 先例）：
  - DSN 从 `WORKBENCH_TEST_DATABASE_URL` 读；未设置即整体 skip。
  - 目标库必须已完成全部迁移（含 036）；本文件**不建表、不迁移**。
  - 只操作本文件声明的租户；每个用例前后自清。

重点（规格 §4 的 store 层部分）：① 序号单调且无跳号；② 续播真增量；③ 跨租户复合外键拒写；
④ 双上限熔断返回 None（不落帧）；⑤ 清理**只清流帧**（消息表行数不变）；⑥ 悬挂兜底收口；
⑦ 熔断后**重开流可读到** `stream.unavailable` **终态帧**（反静默丢帧）+ 审计留痕；
⑧ 凭据形态 payload **落库为掩码**且掩码幂等（重复脱敏 hash 不变）。

⚠️ **依赖端点的用例**（`messages:stream` 与 SSE 读端点、零破坏哨兵、幂等重放不重复写帧）
不在本文件：它们需要整条对话链路走真库（跨仓储 + 随机会话 id），与 DSN 门控的定位不符；
落在内存链路的 `tests/test_conversation_stream_api.py`（同口径用例名可对照）。
"""

from __future__ import annotations

import json
import os
from datetime import timedelta

import pytest

from app.conversation.stream import (
    MESSAGE_ASSISTANT_KIND,
    STATUS_STREAMING,
    STATUS_UNAVAILABLE,
    UNAVAILABLE_KIND,
    PostgresStreamStore,
    _now,
)
from app.conversation.stream_writer import StreamWriter

TOOL_RESULT_KIND = "tool.result"

DSN = os.environ.get("WORKBENCH_TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not DSN,
    reason="未设置 WORKBENCH_TEST_DATABASE_URL，跳过真库集成测试（见本文件 docstring 的局限声明）",
)

TENANT = "test-stream-pg"
TENANT_OTHER = "test-stream-pg-other"
CONVERSATION = "conv-stream-1"
CONVERSATION_OTHER = "conv-stream-other"
RUN = "run-stream-1"
OPERATOR = "acct-stream-op"


def _purge(connection) -> None:
    with connection.cursor() as cursor:
        for table in (
            "workbench_conversation_stream_frames",
            "workbench_conversation_stream_state",
            "workbench_conversation_messages",
            "workbench_conversations",
        ):
            cursor.execute(
                f"DELETE FROM {table} WHERE tenant_id = %s OR tenant_id = %s", (TENANT, TENANT_OTHER)
            )


def _ensure_conversations(connection) -> None:
    with connection.cursor() as cursor:
        for tenant_id, conversation_id in (
            (TENANT, CONVERSATION),
            (TENANT, CONVERSATION_OTHER),
            (TENANT_OTHER, CONVERSATION),
        ):
            cursor.execute(
                """
                INSERT INTO workbench_conversations (tenant_id, conversation_id, operator_id, status)
                VALUES (%s, %s, %s, 'active') ON CONFLICT DO NOTHING
                """,
                (tenant_id, conversation_id, OPERATOR),
            )


@pytest.fixture()
def env():
    psycopg = pytest.importorskip("psycopg")
    connection = psycopg.connect(DSN, autocommit=True)
    _purge(connection)
    _ensure_conversations(connection)
    yield PostgresStreamStore(connection), connection
    _purge(connection)
    connection.close()


# ------------------------------------------------------------ ① 序号与终态


def test_sequence_is_monotonic_and_terminal_is_last(env) -> None:
    store, _ = env
    assert store.append_frame(TENANT, CONVERSATION, RUN, kind=MESSAGE_ASSISTANT_KIND, payload={"n": 1}) is not None
    assert store.append_frame(TENANT, CONVERSATION, RUN, kind=MESSAGE_ASSISTANT_KIND, payload={"n": 2}) is not None
    terminal = store.append_frame(
        TENANT, CONVERSATION, RUN, kind=MESSAGE_ASSISTANT_KIND, payload={"n": 3}, is_terminal=True
    )
    assert terminal is not None and terminal.seq == 3

    frames = store.list_frames(TENANT, CONVERSATION, RUN)
    assert [frame.seq for frame in frames] == [1, 2, 3]          # 无跳号
    assert [frame.is_terminal for frame in frames] == [False, False, True]  # 终态为末帧
    state = store.get_state(TENANT, CONVERSATION, RUN)
    assert state is not None and state.last_seq == 3 and state.frame_count == 3
    assert state.byte_count > 0


# ------------------------------------------------------------ ② 续播真增量


def test_incremental_replay_after_seq(env) -> None:
    store, _ = env
    for index in range(1, 6):
        store.append_frame(TENANT, CONVERSATION, RUN, kind=MESSAGE_ASSISTANT_KIND, payload={"n": index})
    frames = store.list_frames(TENANT, CONVERSATION, RUN, after_seq=3)
    assert [frame.seq for frame in frames] == [4, 5]
    # 越界起点不报错（返回空）
    assert store.list_frames(TENANT, CONVERSATION, RUN, after_seq=99) == []


# ------------------------------------------------------------ ③ 跨租户拒写


def test_cross_tenant_conversation_rejected(env) -> None:
    store, _ = env
    psycopg = pytest.importorskip("psycopg")
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        # (他租户 tenant_id, 本租户已有的 conversation_id) 组合在库中不存在 ⇒ 复合外键拒绝
        store.append_frame(TENANT_OTHER, CONVERSATION_OTHER, RUN, kind=MESSAGE_ASSISTANT_KIND, payload={})


# ------------------------------------------------------------ ④ 双上限熔断


def test_frame_and_byte_limits_return_none(env) -> None:
    store, connection = env
    store.max_frames = 2
    assert store.append_frame(TENANT, CONVERSATION, RUN, kind=MESSAGE_ASSISTANT_KIND, payload={"n": 1}) is not None
    assert store.append_frame(TENANT, CONVERSATION, RUN, kind=MESSAGE_ASSISTANT_KIND, payload={"n": 2}) is not None
    # 超帧数上限 ⇒ 返回 None（**不落帧**；由写入网关追加告知帧并置 unavailable）
    assert store.append_frame(TENANT, CONVERSATION, RUN, kind=MESSAGE_ASSISTANT_KIND, payload={"n": 3}) is None
    assert len(store.list_frames(TENANT, CONVERSATION, RUN)) == 2

    # 超字节上限（新 run）
    store.max_frames = 2000
    store.max_bytes = 10
    assert store.append_frame(TENANT, CONVERSATION, "run-bytes", kind=MESSAGE_ASSISTANT_KIND, payload={"big": "x" * 100}) is None


# ------------------------------------------------------------ ⑤ 清理只清流帧


def test_purge_expired_only_touches_stream_tables(env) -> None:
    store, connection = env
    store.append_frame(TENANT, CONVERSATION, RUN, kind=MESSAGE_ASSISTANT_KIND, payload={"n": 1}, is_terminal=True)
    store.set_terminal(
        TENANT, CONVERSATION, RUN, status="completed", expires_at=_now() - timedelta(seconds=1)
    )
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO workbench_conversation_messages "
            "(tenant_id, message_id, conversation_id, role, content) VALUES (%s, %s, %s, 'assistant', 'x')",
            (TENANT, "msg-keep", CONVERSATION),
        )

    purged = store.purge_expired(cutoff=_now())
    assert purged == 1
    assert store.get_state(TENANT, CONVERSATION, RUN) is None
    assert store.list_frames(TENANT, CONVERSATION, RUN) == []
    # 消息表不受影响（**只清流帧**）
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT COUNT(*) FROM workbench_conversation_messages WHERE tenant_id = %s", (TENANT,)
        )
        assert int(cursor.fetchone()[0]) == 1


# ------------------------------------------------------------ ⑥ 悬挂兜底


def test_mark_stalled_closes_silent_runs(env) -> None:
    store, _ = env
    store.append_frame(TENANT, CONVERSATION, RUN, kind=MESSAGE_ASSISTANT_KIND, payload={"n": 1})
    changed = store.mark_stalled(cutoff=_now() + timedelta(seconds=1), expires_at=_now() + timedelta(days=7))
    assert changed == 1
    state = store.get_state(TENANT, CONVERSATION, RUN)
    assert state is not None and state.status == STATUS_UNAVAILABLE and state.is_terminal is True
    assert state.expires_at is not None
    # 已终态后再跑不重复处理
    assert store.mark_stalled(cutoff=_now() + timedelta(seconds=1), expires_at=_now()) == 0


# ------------------------------------------------------------ 附：活跃 run 解析与水位置位


def test_latest_run_prefers_active_and_watermark_persists(env) -> None:
    store, _ = env
    store.append_frame(TENANT, CONVERSATION, "run-old", kind=MESSAGE_ASSISTANT_KIND, payload={}, is_terminal=True)
    store.set_terminal(TENANT, CONVERSATION, "run-old", status="completed", expires_at=_now() + timedelta(days=7))
    store.append_frame(TENANT, CONVERSATION, "run-new", kind=MESSAGE_ASSISTANT_KIND, payload={})
    assert store.latest_run_id(TENANT, CONVERSATION) == "run-new"
    assert store.get_state(TENANT, CONVERSATION, "run-new").status == STATUS_STREAMING

    store.persist_watermark(TENANT, CONVERSATION, "run-new", "msg-1")
    assert store.get_state(TENANT, CONVERSATION, "run-new").persisted_to_message_id == "msg-1"


# ------------------------------------------------------------ ⑦ 熔断告知帧可读（反静默丢帧）


class _RecordingAudit:
    """最小审计桩：只记录动作码与明细（不依赖审计仓储）。"""

    def __init__(self) -> None:
        self.records: list[tuple[object, dict]] = []

    def record(self, action, *, tenant_id=None, actor_id=None, target_type=None, target_id=None, detail=None):
        self.records.append((action, dict(detail or {})))


def test_breaker_notice_frame_is_readable_after_reopen(env) -> None:
    """熔断 ⇒ 状态 `unavailable` + **显式告知帧**（重开流可读到终态帧）+ 审计留痕（§4 用例 4）。"""
    store, _ = env
    audit = _RecordingAudit()
    store.max_frames = 1
    writer = StreamWriter(store, audit=audit, retention_days=7)

    assert writer.write(TENANT, CONVERSATION, RUN, kind=MESSAGE_ASSISTANT_KIND, payload={"n": 1}) is not None
    # 第二帧超限 ⇒ 写入网关返回 None，但**不静默丢帧**：落一帧告知帧
    assert writer.write(TENANT, CONVERSATION, RUN, kind=MESSAGE_ASSISTANT_KIND, payload={"n": 2}) is None

    frames = store.list_frames(TENANT, CONVERSATION, RUN)  # 「重开流」按 seq 从头读
    assert [frame.kind for frame in frames] == [MESSAGE_ASSISTANT_KIND, UNAVAILABLE_KIND]
    assert frames[-1].is_terminal is True and frames[-1].payload == {"reason": "frame_limit"}
    state = store.get_state(TENANT, CONVERSATION, RUN)
    assert state is not None and state.status == STATUS_UNAVAILABLE and state.is_terminal is True
    assert state.expires_at is not None
    # 审计：治理事件 + 受控 reason（不落正文）
    assert [detail for _action, detail in audit.records] == [{"reason": "frame_limit", "run_id": RUN}]
    # 熔断后**不再写帧**（不复活、告知帧不重复）
    assert writer.write(TENANT, CONVERSATION, RUN, kind=MESSAGE_ASSISTANT_KIND, payload={"n": 3}) is None
    assert len(store.list_frames(TENANT, CONVERSATION, RUN)) == 2


# ------------------------------------------------------------ ⑧ 脱敏落库（掩码 + 幂等）


def test_credential_shaped_payload_is_masked_in_database(env) -> None:
    """凭据形态（敏感键 / `Bearer` / `sk-` 前缀 / `TOKEN=`）⇒ **落库即掩码**；重复脱敏幂等。"""
    from app.runtime.contracts import redact_payload

    store, _ = env
    writer = StreamWriter(store, audit=None, retention_days=7)
    payload = {
        "tool_key": "fs.read",
        "api_key": "sk-live-abcdef123456",
        "note": "Authorization: Bearer abcdef1234567890",
        "cmd": "export TOKEN=sk-abcdef123456",
        "n": 1,
    }
    assert writer.write(TENANT, CONVERSATION, RUN, kind=TOOL_RESULT_KIND, payload=payload) is not None

    stored = store.list_frames(TENANT, CONVERSATION, RUN)[0].payload
    text = json.dumps(stored, ensure_ascii=False)
    for secret in ("sk-live-abcdef123456", "abcdef1234567890", "sk-abcdef123456"):
        assert secret not in text, f"凭据形态未掩码：{secret}"
    assert "[已隐藏]" in text
    # 非敏感字段原样保留（判据不误伤）
    assert stored["tool_key"] == "fs.read" and stored["n"] == 1
    # 掩码**幂等**：再脱敏一次逐字节不变（掩码产物不再被模式命中）
    assert redact_payload(stored) == stored


def test_redacted_summary_extras_survive_masking(env) -> None:
    """工具结果的摘要口径（摘要 + `args_digest` + `sha256`）在帧里**原样保留**（不是敏感键）。"""
    store, _ = env
    writer = StreamWriter(store, audit=None, retention_days=7)
    payload = {
        "step_id": "step-1",
        "tool_key": "fs.list",
        "status": "ok",
        "summary": {"tool_key": "fs.list", "status": "ok"},
        "args_digest": "sha256:" + "a" * 64,
        "sha256": "sha256:" + "b" * 64,
    }
    assert writer.write(TENANT, CONVERSATION, RUN, kind=TOOL_RESULT_KIND, payload=payload) is not None

    stored = store.list_frames(TENANT, CONVERSATION, RUN)[0].payload
    assert stored["args_digest"] == "sha256:" + "a" * 64
    assert stored["sha256"] == "sha256:" + "b" * 64
    assert stored["summary"] == {"tool_key": "fs.list", "status": "ok"}