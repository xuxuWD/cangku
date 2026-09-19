"""`PostgresRunArtifactStore` 的**真库**回归（P2c-3 产物登记，迁移 037）。

口径（沿用 `tests/test_conversation_stream_postgres.py` 先例）：
  - DSN 从 `WORKBENCH_TEST_DATABASE_URL` 读；未设置即整体 skip。
  - 目标库必须已完成全部迁移（含 037）；本文件**不建表、不迁移**。
  - 只操作本文件声明的租户；每个用例前后自清。

重点（规格 §4「P2c-3 真库用例」的 store 层部分）：
  ① 登记写入 + 读回（虚拟路径 / 类型 / 字节 / sha256，**不含内容**）；
  ② **跨租户拒写**（复合外键 `(tenant_id, run_id)` 父行不存在 ⇒ 直接拒绝）；
  ③ 租户隔离读（同 run_id 不同租户互不可见）；
  ④ **保留期**：到期行不再返回；清理**只清登记表**（运行记录行数不变）；
  ⑤ 清理**逐租户**执行且只删过期行（未过期行保留）。
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest

from app.runtime.artifacts import PostgresRunArtifactStore
from app.tool_execution.file_ops import FileChange

DSN = os.environ.get("WORKBENCH_TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not DSN,
    reason="未设置 WORKBENCH_TEST_DATABASE_URL，跳过真库集成测试（见本文件 docstring 的局限声明）",
)

TENANT = "test-artifacts-pg"
TENANT_OTHER = "test-artifacts-pg-other"
RUN = "run-artifacts-1"
RUN_OTHER = "run-artifacts-other"


def _purge(connection) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "DELETE FROM workbench_run_artifacts WHERE tenant_id IN (%s, %s)",
            (TENANT, TENANT_OTHER),
        )
        cursor.execute(
            "DELETE FROM workbench_run_records WHERE tenant_id IN (%s, %s)",
            (TENANT, TENANT_OTHER),
        )


def _ensure_run(connection, tenant_id: str, run_id: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO workbench_run_records (run_id, tenant_id, task_id, runtime_key, status)
            VALUES (%s, %s, %s, 'mock', 'completed')
            ON CONFLICT (run_id) DO NOTHING
            """,
            (run_id, tenant_id, f"task-{run_id}"),
        )


def _change(index: int, *, kind: str = "created") -> FileChange:
    return FileChange(
        virtual_path=f"/workspace/{index}.txt",
        change_kind=kind,
        bytes=10 + index,
        sha256=f"sha256:{index:064d}",
    )


@pytest.fixture()
def env():
    psycopg = pytest.importorskip("psycopg")
    connection = psycopg.connect(DSN, autocommit=True)
    _purge(connection)
    _ensure_run(connection, TENANT, RUN)
    _ensure_run(connection, TENANT_OTHER, RUN_OTHER)
    yield PostgresRunArtifactStore(connection, retention_days=30), connection
    _purge(connection)
    connection.close()


# ------------------------------------------------------------ ① 登记与读回


def test_register_and_read_back_metadata_only(env) -> None:
    store, connection = env
    reference = datetime.now(UTC)
    assert store.register(
        TENANT,
        RUN,
        [_change(0, kind="created")],
        now=reference,
    ) == 1
    assert store.register(TENANT, RUN, [_change(1, kind="overwritten")], now=reference + timedelta(seconds=1)) == 1

    rows = store.list_for_run(TENANT, RUN)
    assert [row.virtual_path for row in rows] == ["/workspace/0.txt", "/workspace/1.txt"]
    assert [row.change_kind for row in rows] == ["created", "overwritten"]
    assert rows[0].bytes == 10 and rows[0].sha256 == f"sha256:{0:064d}"
    assert rows[0].expires_at is not None  # 写端已按保留期落 `expires_at`
    view = rows[0].to_view()
    assert set(view) == {
        "artifact_id",
        "virtual_path",
        "change_kind",
        "bytes",
        "sha256",
        "created_at",
        "expires_at",
    }
    assert "tenant_id" not in view
    # 库里**只有元数据**：任何列都不含内容原文
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT virtual_path, change_kind, sha256 FROM workbench_run_artifacts "
            "WHERE tenant_id = %s AND run_id = %s",
            (TENANT, RUN),
        )
        stored = cursor.fetchall()
    assert len(stored) == 2
    assert all(not str(row).startswith("sha256:content") for row in stored)


def test_register_empty_or_invalid_changes_fails_closed(env) -> None:
    store, _connection = env
    assert store.register(TENANT, RUN, []) == 0
    with pytest.raises(ValueError):
        store.register(
            TENANT,
            RUN,
            [FileChange(virtual_path="relative.txt", change_kind="created", bytes=1, sha256="sha256:x")],
        )
    with pytest.raises(ValueError):
        store.register(
            TENANT,
            RUN,
            [FileChange(virtual_path="/workspace/a.txt", change_kind="renamed", bytes=1, sha256="sha256:x")],
        )
    assert store.list_for_run(TENANT, RUN) == []  # 整批不写（不写半批）


# ------------------------------------------------------------ ② 跨租户拒写


def test_cross_tenant_write_is_rejected_by_composite_foreign_key(env) -> None:
    """复合外键 `(tenant_id, run_id)`：他租户冒充写**本租户的 run** ⇒ 父行不存在 ⇒ 拒绝。"""
    store, _connection = env
    with pytest.raises(Exception) as excinfo:
        store.register(TENANT_OTHER, RUN, [_change(0)])
    message = str(excinfo.value)
    assert "workbench_run_records" in message or "violates foreign key" in message
    assert store.list_for_run(TENANT_OTHER, RUN) == []


# ------------------------------------------------------------ ③ 租户隔离读


def test_list_is_tenant_scoped(env) -> None:
    store, _connection = env
    store.register(TENANT, RUN, [_change(0)])
    store.register(TENANT_OTHER, RUN_OTHER, [_change(1)])

    assert [row.bytes for row in store.list_for_run(TENANT, RUN)] == [10]
    assert [row.bytes for row in store.list_for_run(TENANT_OTHER, RUN_OTHER)] == [11]
    assert store.list_for_run(TENANT, RUN_OTHER) == []  # 同 run_id 不同租户互不可见
    assert store.list_for_run(TENANT_OTHER, RUN) == []


# ------------------------------------------------------------ ④ 保留期与清理


def test_expired_rows_are_not_returned_and_purge_only_clears_artifacts(env) -> None:
    store, connection = env
    store.register(TENANT, RUN, [_change(0)])
    store.register(TENANT, RUN, [_change(1)], now=datetime.now(UTC) - timedelta(days=40))

    rows = store.list_for_run(TENANT, RUN)
    assert [row.bytes for row in rows] == [10]  # 过期行不再返回（保留期外如实降级）

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM workbench_run_records WHERE tenant_id = %s", (TENANT,)
        )
        runs_before = int(cursor.fetchone()[0])

    removed = store.purge_expired(cutoff=datetime.now(UTC))
    assert removed == 1  # 只删过期那一行（未过期行保留）

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM workbench_run_artifacts WHERE tenant_id = %s AND run_id = %s",
            (TENANT, RUN),
        )
        remaining = int(cursor.fetchone()[0])
        cursor.execute(
            "SELECT count(*) FROM workbench_run_records WHERE tenant_id = %s", (TENANT,)
        )
        runs_after = int(cursor.fetchone()[0])
    assert remaining == 1
    assert runs_after == runs_before  # **只清登记表**：运行记录不受影响
    assert len(store.list_for_run(TENANT, RUN)) == 1


# ------------------------------------------------------------ B-2c：按租户列出（导出读取通道）


def test_list_for_tenant_scopes_counts_and_hides_expired(env) -> None:
    """导出读取通道：按租户过滤 + **过期行不入包**（口径与 `list_for_run` 一致）+ 计数与分页。"""
    store, _connection = env
    store.register(TENANT, RUN, [_change(0), _change(1)])
    store.register(TENANT_OTHER, RUN_OTHER, [_change(2)])
    # 造一行已过期：以「保留期为负」登记 ⇒ `expires_at` 落在过去（等价于已过保留期）。
    store.register(TENANT, RUN, [_change(3)], now=datetime.now(UTC) - timedelta(days=40))

    rows, total = store.list_for_tenant(TENANT, limit=10, offset=0)

    assert total == 2  # 过期行不计入总数
    assert {row.virtual_path for row in rows} == {"/workspace/0.txt", "/workspace/1.txt"}
    assert all(row.tenant_id == TENANT for row in rows)

    page, same_total = store.list_for_tenant(TENANT, limit=1, offset=1)

    assert same_total == 2 and len(page) == 1

    # 到期边界与 `list_for_run` 同口径：`expires_at` 到了就不返回（保留期内才可见）。
    future = datetime.now(UTC) + timedelta(days=40)
    assert store.list_for_tenant(TENANT, limit=10, offset=0, now=future)[0] == []