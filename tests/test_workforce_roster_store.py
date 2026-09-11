"""岗位与数字员工清单的两个数据源：知识范围绑定清单 + 任务数聚合。

先写测试：绑定清单只含本租户且仅 super_admin 可读；任务数按 employee_key 分组。
"""

from __future__ import annotations

from itertools import count

import pytest

from app.domain import PolicyError, RiskLevel, Task, TaskStatus, TaskStore, UserContext
from app.knowledge_policy import KnowledgeAccessRegistry, PostgresKnowledgeAccessRegistry

ADMIN = UserContext("t-1", "admin-1", "super_admin")
OTHER_ADMIN = UserContext("t-2", "admin-2", "super_admin")
_SEQ = count(1)


def make_task(store: TaskStore, *, tenant_id: str = "t-1", employee_key: str = "content-operator") -> Task:
    task = Task(
        tenant_id=tenant_id,
        project_id=None,
        created_by="u-1",
        employee_key=employee_key,
        title="任务",
        risk_level=RiskLevel.LOW,
        budget=1,
        idempotency_key=f"id-{next(_SEQ)}",
        request_fingerprint="fp",
        status=TaskStatus.QUEUED,
    )
    store.create(UserContext(tenant_id, "u-1", "employee"), task)
    return task


# ------------------------------------------------------------ 绑定清单


def test_list_bindings_groups_by_type_and_scopes_tenant() -> None:
    registry = KnowledgeAccessRegistry()
    registry.bind_role(ADMIN, "content-operator", {"kb-2", "kb-1"})
    registry.bind_agent(ADMIN, "content-writer", {"kb-3"})
    registry.bind_role(OTHER_ADMIN, "other-role", {"kb-9"})

    bindings = registry.list_bindings(ADMIN)

    assert bindings == {"role": {"content-operator": ["kb-1", "kb-2"]}, "agent": {"content-writer": ["kb-3"]}}


def test_list_bindings_requires_super_admin() -> None:
    registry = KnowledgeAccessRegistry()
    registry.bind_role(ADMIN, "content-operator", {"kb-1"})

    with pytest.raises(PolicyError):
        registry.list_bindings(UserContext("t-1", "ceo-1", "ceo"))


def test_list_bindings_is_empty_without_data() -> None:
    assert KnowledgeAccessRegistry().list_bindings(ADMIN) == {"role": {}, "agent": {}}


class RecordingCursor:
    def __init__(self, rows: list[object]) -> None:
        self.rows = list(rows)
        self.statements: list[tuple[str, tuple | None]] = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, statement, params=None):
        self.statements.append((statement, params))

    def fetchall(self):
        return self.rows.pop(0)

    def fetchone(self):
        return self.rows.pop(0)


class RecordingConnection:
    def __init__(self, rows: list[object]) -> None:
        self.cursor_instance = RecordingCursor(rows)

    def transaction(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def cursor(self):
        return self.cursor_instance


def test_postgres_list_bindings_groups_rows() -> None:
    connection = RecordingConnection([[("role", "content-operator", "kb-1"), ("role", "content-operator", "kb-2"), ("agent", "writer", "kb-3")]])
    registry = PostgresKnowledgeAccessRegistry(connection)

    bindings = registry.list_bindings(ADMIN)

    statement, params = connection.cursor_instance.statements[0]
    assert "FROM workbench_knowledge_access_bindings" in statement
    assert "tenant_id = %s" in statement
    assert params == ("t-1",)
    assert bindings == {"role": {"content-operator": ["kb-1", "kb-2"]}, "agent": {"writer": ["kb-3"]}}


def test_postgres_list_bindings_requires_super_admin() -> None:
    registry = PostgresKnowledgeAccessRegistry(RecordingConnection([[]]))

    with pytest.raises(PolicyError):
        registry.list_bindings(UserContext("t-1", "ceo-1", "ceo"))


# ------------------------------------------------------------ 任务数聚合


def test_memory_task_counts_group_by_employee_key_and_tenant() -> None:
    store = TaskStore()
    make_task(store, employee_key="content-operator")
    make_task(store, employee_key="content-operator")
    make_task(store, employee_key="content-writer")
    make_task(store, tenant_id="t-2", employee_key="content-operator")

    counts = store.count_by_employee("t-1")

    assert counts == {"content-operator": 2, "content-writer": 1}
    assert store.count_by_employee("t-3") == {}


def test_postgres_task_counts_build_sql() -> None:
    from app.repository import PostgresTaskRepository

    connection = RecordingConnection([[("content-operator", 2), ("content-writer", 1)]])
    repository = PostgresTaskRepository(connection)

    counts = repository.count_by_employee("t-1")

    statement, params = connection.cursor_instance.statements[0]
    assert "SELECT employee_key, COUNT(*)" in statement
    assert "FROM workbench_tasks" in statement
    assert "GROUP BY employee_key" in statement
    assert params == ("t-1",)
    assert counts == {"content-operator": 2, "content-writer": 1}
