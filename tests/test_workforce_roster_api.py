"""岗位与数字员工清单接口：权限矩阵、三源并集、任务数与租户隔离。"""

from __future__ import annotations

from itertools import count

import pytest
from fastapi.testclient import TestClient

from app import main
from app.domain import RiskLevel, Task, TaskStatus, TaskStore, UserContext
from app.knowledge_policy import KnowledgeAccessRegistry
from app.main import app

client = TestClient(app)
ADMIN = UserContext("t-1", "admin-1", "super_admin")
_SEQ = count(1)


def add_task(store: TaskStore, *, employee_key: str, tenant_id: str = "t-1") -> None:
    task = Task(
        tenant_id=tenant_id,
        project_id=None,
        created_by="u-1",
        employee_key=employee_key,
        title="任务",
        risk_level=RiskLevel.LOW,
        budget=1,
        idempotency_key=f"roster-{next(_SEQ)}",
        request_fingerprint="fp",
        status=TaskStatus.QUEUED,
    )
    store.create(UserContext(tenant_id, "u-1", "employee"), task)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    task_store = TaskStore()
    registry = KnowledgeAccessRegistry()
    registry.bind_role(ADMIN, "content-operator", {"kb-1"})
    registry.bind_agent(ADMIN, "content-writer", {"kb-2"})
    # 只被任务引用、没有任何知识范围绑定的标识
    add_task(task_store, employee_key="content-operator")
    add_task(task_store, employee_key="content-operator")
    add_task(task_store, employee_key="unbound-agent")
    add_task(task_store, employee_key="other-tenant-agent", tenant_id="t-2")
    monkeypatch.setattr(main, "store", task_store)
    monkeypatch.setattr(main, "knowledge_access_registry", registry)
    return task_store, registry


def headers(role: str = "super_admin", user_id: str = "admin-1", tenant_id: str = "t-1") -> dict[str, str]:
    return {"X-Tenant-Id": tenant_id, "X-User-Id": user_id, "X-User-Role": role}


def test_roster_merges_three_sources() -> None:
    response = client.get("/api/v1/workforce/roster", headers=headers())

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    # 顺序由 test_roster_sorts_by_task_count_then_key 覆盖，这里只比对内容。
    by_key = {item["key"]: item for item in body["items"]}
    assert by_key == {
        "content-operator": {
            "key": "content-operator",
            "role_knowledge_base_ids": ["kb-1"],
            "agent_knowledge_base_ids": [],
            "task_count": 2,
        },
        "content-writer": {
            "key": "content-writer",
            "role_knowledge_base_ids": [],
            "agent_knowledge_base_ids": ["kb-2"],
            "task_count": 0,
        },
        "unbound-agent": {
            "key": "unbound-agent",
            "role_knowledge_base_ids": [],
            "agent_knowledge_base_ids": [],
            "task_count": 1,
        },
    }


def test_roster_sorts_by_task_count_then_key() -> None:
    body = client.get("/api/v1/workforce/roster", headers=headers()).json()

    assert [(item["key"], item["task_count"]) for item in body["items"]] == [
        ("content-operator", 2),
        ("unbound-agent", 1),
        ("content-writer", 0),
    ]


def test_roster_requires_super_admin() -> None:
    assert client.get("/api/v1/workforce/roster").status_code == 401
    assert client.get("/api/v1/workforce/roster", headers=headers(role="ceo")).status_code == 403
    assert client.get("/api/v1/workforce/roster", headers=headers(role="employee")).status_code == 403


def test_roster_is_scoped_to_the_calling_tenant() -> None:
    body = client.get("/api/v1/workforce/roster", headers=headers(tenant_id="t-2")).json()

    assert body["items"] == [
        {
            "key": "other-tenant-agent",
            "role_knowledge_base_ids": [],
            "agent_knowledge_base_ids": [],
            "task_count": 1,
        }
    ]


def test_roster_is_read_only_and_carries_no_pii() -> None:
    for method in ("post", "put", "delete", "patch"):
        assert getattr(client, method)("/api/v1/workforce/roster", headers=headers()).status_code == 405

    body = client.get("/api/v1/workforce/roster", headers=headers()).json()
    # 只返回这四个字段：不含账号、手机号或其它 PII。
    assert set(body) == {"items", "total"}
    assert set(body["items"][0]) == {
        "key",
        "role_knowledge_base_ids",
        "agent_knowledge_base_ids",
        "task_count",
    }
