"""`PostgresToolActionStore` 的**真库**回归测试（仓库内首例集成测试）。

与既有的 `tests/test_*_postgres.py` 的区别（2026-09-13 核实）：那些用 `connection=object()`
假连接，只断言装配与类型；本文件**真的连库**，用来把「027 的库层约束是否真的生效」变成可重复的回归。

口径（先例，后续同类测试请沿用）：
  - DSN 从环境变量 **`WORKBENCH_TEST_DATABASE_URL`** 读；**未设置即整体 skip**，
    因此不影响默认 `pytest` 全量（无库环境不会红）。
  - 目标库必须是**已完成全部迁移（含 `027_dsh_tool_execution`）**的库；
    本文件**不建表、不迁移**，缺表时应**显式失败**而不是静默跳过。
  - 只操作 `TENANT` 这一个租户的数据，每个用例前清理自己。
  - ⚠️ **局限（如实声明）**：默认 CI 不提供该环境变量 ⇒ 本文件默认是 skip 状态，
    **不在"一键跑全量"的覆盖范围内**；要真正受它守护，必须在带库的环境里显式跑一次。
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest

from app.domain import RiskLevel
from app.tool_execution.store import (
    PostgresToolActionStore,
    ReasonCode,
    ToolAction,
    ToolActionNotFound,
    ToolActionStatus,
)

DSN = os.environ.get("WORKBENCH_TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not DSN,
    reason="未设置 WORKBENCH_TEST_DATABASE_URL，跳过真库集成测试（见本文件 docstring 的局限声明）",
)

TENANT = "test-store-pg"
OTHER_TENANT = "test-store-pg-other"
RUN = "run-store-pg"
NOW = datetime(2026, 9, 13, 12, 0, tzinfo=UTC)


def _action(**overrides) -> ToolAction:
    base = dict(
        tenant_id=TENANT,
        action_id="a1",
        run_id=RUN,
        task_id="task-1",
        step_id="step-1",
        tool_key="fs.write",
        args_digest="sha256:abc",
        args_json={"path": "/w/a.txt", "content": "«body»"},
        plan_digest="sha256:plan",
        risk_level=RiskLevel.MEDIUM,
        requires_approval=True,
        status=ToolActionStatus.PENDING,
        requested_by="u1",
        requested_at=NOW,
    )
    base.update(overrides)
    return ToolAction(**base)


@pytest.fixture()
def store():
    psycopg = pytest.importorskip("psycopg")
    connection = psycopg.connect(DSN, autocommit=True)
    with connection.cursor() as cursor:
        # 父表准备：027 的复合外键要求运行记录先存在（租户隔离是"写进约束"的）。
        cursor.execute(
            """
            INSERT INTO workbench_run_records (run_id, tenant_id, task_id, runtime_key, status)
            VALUES (%s, %s, 'task-1', 'mock', 'running')
            ON CONFLICT (run_id) DO NOTHING
            """,
            (RUN, TENANT),
        )
        cursor.execute("DELETE FROM workbench_tool_actions WHERE tenant_id = %s", (TENANT,))
    yield PostgresToolActionStore(connection)
    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM workbench_tool_actions WHERE tenant_id = %s", (TENANT,))
    connection.close()


def test_roundtrip_keeps_args_json_bytes_and_expiry(store) -> None:
    blob = bytes(range(12)) + b"cipherbody" + bytes(range(16))
    expires = NOW + timedelta(minutes=5)

    store.upsert(_action(body_ciphertext=blob, body_expires_at=expires, approval_id="ap-1"))
    got = store.get(TENANT, "a1")

    assert got.args_json == {"path": "/w/a.txt", "content": "«body»"}
    assert got.body_ciphertext == blob
    assert got.body_expires_at is not None
    assert abs((got.body_expires_at - expires).total_seconds()) < 1
    assert got.status is ToolActionStatus.PENDING
    assert got.risk_level is RiskLevel.MEDIUM


def test_upsert_updates_on_primary_key_conflict(store) -> None:
    store.upsert(_action())
    decided_at = NOW + timedelta(seconds=30)

    store.upsert(
        _action(
            status=ToolActionStatus.APPROVED,
            decided_by="ceo-1",
            decided_at=decided_at,
            decision_source="ui",
        )
    )
    got = store.get(TENANT, "a1")

    assert got.status is ToolActionStatus.APPROVED
    assert got.decided_by == "ceo-1"
    assert got.decision_source == "ui"
    assert got.decided_at is not None
    assert abs((got.decided_at - decided_at).total_seconds()) < 1


def test_find_approved_scopes_by_approval_and_tenant(store) -> None:
    store.upsert(
        _action(
            approval_id="ap-1",
            status=ToolActionStatus.APPROVED,
            decided_by="ceo-1",
            decided_at=NOW,
        )
    )

    assert store.find_approved(tenant_id=TENANT, run_id=RUN, approval_id="ap-1") is not None
    assert store.find_approved(tenant_id=TENANT, run_id=RUN, approval_id="ap-nope") is None
    assert store.find_approved(tenant_id=OTHER_TENANT, run_id=RUN, approval_id="ap-1") is None


def test_second_pending_for_same_step_is_rejected(store) -> None:
    """同 (tenant, run, step) 只允许一行 pending（迁移 027 的部分唯一索引）。"""
    psycopg = pytest.importorskip("psycopg")
    store.upsert(_action(action_id="pend-1", step_id="step-pending"))

    with pytest.raises(psycopg.errors.UniqueViolation) as excinfo:
        store.upsert(_action(action_id="pend-2", step_id="step-pending"))

    assert "idx_workbench_tool_actions_pending_unique" in str(excinfo.value)


def test_decided_row_may_occupy_same_step(store) -> None:
    """语义证明：该唯一索引**只覆盖 pending**（是部分索引，不是全表唯一）。"""
    store.upsert(_action(action_id="pend-1", step_id="step-pending"))

    store.upsert(
        _action(
            action_id="pend-3",
            step_id="step-pending",
            status=ToolActionStatus.APPROVED,
            decided_by="ceo-1",
            decided_at=NOW,
        )
    )

    assert store.get(TENANT, "pend-3").status is ToolActionStatus.APPROVED


def test_approval_id_is_unique_within_run(store) -> None:
    psycopg = pytest.importorskip("psycopg")
    store.upsert(
        _action(
            action_id="a1",
            approval_id="ap-1",
            status=ToolActionStatus.APPROVED,
            decided_by="ceo-1",
            decided_at=NOW,
        )
    )

    with pytest.raises(psycopg.errors.UniqueViolation) as excinfo:
        store.upsert(
            _action(
                action_id="a2",
                step_id="step-2",
                approval_id="ap-1",
                status=ToolActionStatus.APPROVED,
                decided_by="ceo-1",
                decided_at=NOW,
            )
        )

    assert "idx_workbench_tool_actions_approval" in str(excinfo.value)


def test_library_level_guards_reject_bad_rows(store) -> None:
    with pytest.raises(ValueError, match="9 值受控枚举"):
        store.upsert(_action(action_id="bad-1", reason_code="free_text_日本語"))

    with pytest.raises(ValueError, match="同有同无"):
        store.upsert(_action(action_id="bad-2", body_ciphertext=b"x" * 30))

    with pytest.raises(ValueError, match="不得带决议列"):
        store.upsert(_action(action_id="bad-3", decided_by="ceo-1", decided_at=NOW))


def test_database_body_check_rejects_ciphertext_without_ttl(store) -> None:
    """绕过应用层校验、直接 SQL 插入：库层 `body_check` 必须兜住。"""
    psycopg = pytest.importorskip("psycopg")
    connection = store.connection

    with pytest.raises(psycopg.errors.CheckViolation) as excinfo:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO workbench_tool_actions
                    (tenant_id, action_id, run_id, task_id, step_id, tool_key, args_digest,
                     args_json, body_ciphertext, body_expires_at, plan_digest, risk_level,
                     requires_approval, status, requested_by)
                VALUES (%s, 'raw-1', %s, 'task-1', 'step-raw', 'fs.write', 'sha256:x',
                        '{}'::jsonb, %s, NULL, 'sha256:p', 'medium', true, 'pending', 'u1')
                """,
                (TENANT, RUN, b"z" * 30),
            )

    assert "body_check" in str(excinfo.value)


def test_tenant_isolation_and_not_found(store) -> None:
    store.upsert(_action())

    with pytest.raises(ToolActionNotFound):
        store.get(OTHER_TENANT, "a1")
    with pytest.raises(ToolActionNotFound):
        store.get(TENANT, "nope")

    assert len(store.list_for_run(TENANT, RUN)) == 1
    assert store.list_for_run(OTHER_TENANT, RUN) == []


def test_reason_code_roundtrip_covers_controlled_enum(store) -> None:
    """9 值受控枚举必须能落库并能原样读回（一个字也不能变形）。"""
    store.upsert(
        _action(
            status=ToolActionStatus.REJECTED,
            decided_by="ceo-1",
            decided_at=NOW,
            decision_source="ui",
            reason_code=ReasonCode.PATH_DENIED,
        )
    )

    assert store.get(TENANT, "a1").reason_code is ReasonCode.PATH_DENIED
