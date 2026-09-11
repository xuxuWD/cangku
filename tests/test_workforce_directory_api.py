"""岗位/数字员工目录接口：权限矩阵、标识不可改、岗位可用性、分页、租户隔离、审计。"""

from __future__ import annotations

from itertools import count

import pytest
from fastapi.testclient import TestClient

from app import main
from app.audit.models import AuditAction
from app.audit.service import AuditService
from app.audit.store import InMemoryAuditStore
from app.domain import RiskLevel, Task, TaskStatus, TaskStore, UserContext
from app.knowledge_policy import KnowledgeAccessRegistry
from app.main import app
from app.workforce.service import WorkforceDirectoryService
from app.workforce.store import InMemoryWorkforceDirectoryStore

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
        idempotency_key=f"dir-{next(_SEQ)}",
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
    add_task(task_store, employee_key="content-operator")
    add_task(task_store, employee_key="unbound-agent")
    audit_store = InMemoryAuditStore()
    audit = AuditService(audit_store)
    directory_store = InMemoryWorkforceDirectoryStore()
    service = WorkforceDirectoryService(
        directory_store, audit=audit, knowledge_registry=registry, task_store=task_store
    )
    monkeypatch.setattr(main, "store", task_store)
    monkeypatch.setattr(main, "knowledge_access_registry", registry)
    monkeypatch.setattr(main, "audit_service", audit)
    monkeypatch.setattr(main, "workforce_directory_store", directory_store)
    monkeypatch.setattr(main, "workforce_directory_service", service)
    return directory_store, audit_store


def headers(role: str = "super_admin", user_id: str = "admin-1", tenant_id: str = "t-1") -> dict[str, str]:
    return {"X-Tenant-Id": tenant_id, "X-User-Id": user_id, "X-User-Role": role}


def create_role(role_key: str = "content-operator", name: str = "自媒体运营岗", **extra) -> dict:
    response = client.post("/api/v1/workforce/roles", headers=headers(), json={"role_key": role_key, "name": name, **extra})
    assert response.status_code == 201, response.text
    return response.json()


def create_agent(agent_key: str = "content-writer", role_key: str = "content-operator") -> dict:
    response = client.post(
        "/api/v1/workforce/agents",
        headers=headers(),
        json={"agent_key": agent_key, "name": "内容创作数字员工", "role_key": role_key},
    )
    assert response.status_code == 201, response.text
    return response.json()


# ------------------------------------------------------------ 岗位


def test_create_role_returns_normalized_view_and_lists_it() -> None:
    created = create_role(role_key="  Content-Operator  ")

    assert created["role_key"] == "content-operator"
    assert created["name"] == "自媒体运营岗"
    assert created["status"] == "active"
    assert created["created_by"] == "admin-1"
    # 不含任何 PII 字段
    assert set(created) == {"role_key", "name", "description", "status", "created_by", "created_at", "updated_at"}

    body = client.get("/api/v1/workforce/roles", headers=headers()).json()
    assert body["total"] == 1
    assert body["limit"] == 50
    assert body["offset"] == 0
    assert [item["role_key"] for item in body["items"]] == ["content-operator"]


def test_create_role_maps_duplicate_and_invalid_inputs() -> None:
    create_role()

    assert client.post("/api/v1/workforce/roles", headers=headers(), json={"role_key": "Content-Operator", "name": "重复"}).status_code == 409
    assert client.post("/api/v1/workforce/roles", headers=headers(), json={"role_key": "运营岗", "name": "非法标识"}).status_code == 422
    assert client.post("/api/v1/workforce/roles", headers=headers(), json={"role_key": "content-ops", "name": "   "}).status_code == 422


def test_update_role_cannot_change_identity_and_maps_missing_key() -> None:
    create_role()

    # 标识不在更新模型里：传了直接 422，避免静默忽略
    assert client.patch("/api/v1/workforce/roles/content-operator", headers=headers(), json={"role_key": "other"}).status_code == 422
    assert client.patch("/api/v1/workforce/roles/content-operator", headers=headers(), json={"status": "paused"}).status_code == 422
    assert client.patch("/api/v1/workforce/roles/nobody", headers=headers(), json={"name": "新名字"}).status_code == 404

    updated = client.patch("/api/v1/workforce/roles/content-operator", headers=headers(), json={"name": "内容运营岗", "status": "disabled"})
    assert updated.status_code == 200
    assert updated.json()["role_key"] == "content-operator"
    assert updated.json()["name"] == "内容运营岗"
    assert updated.json()["status"] == "disabled"

    filtered = client.get("/api/v1/workforce/roles", headers=headers(), params={"status": "active"}).json()
    assert filtered["total"] == 0
    assert client.get("/api/v1/workforce/roles", headers=headers(), params={"status": "paused"}).status_code == 422


# ------------------------------------------------------------ 数字员工


def test_create_employee_requires_available_role() -> None:
    # 岗位还不存在
    assert client.post("/api/v1/workforce/agents", headers=headers(), json={"agent_key": "content-writer", "name": "员工", "role_key": "content-operator"}).status_code == 409

    create_role()
    assert create_agent()["role_key"] == "content-operator"
    # 同标识重复创建
    assert client.post("/api/v1/workforce/agents", headers=headers(), json={"agent_key": "content-writer", "name": "重复", "role_key": "content-operator"}).status_code == 409

    client.patch("/api/v1/workforce/roles/content-operator", headers=headers(), json={"status": "disabled"})
    assert client.post("/api/v1/workforce/agents", headers=headers(), json={"agent_key": "geo-analyst", "name": "停用岗位", "role_key": "content-operator"}).status_code == 409


def test_update_employee_can_move_role_but_not_identity() -> None:
    create_role()
    create_role(role_key="geo-operator", name="GEO 运营岗")
    create_agent()

    moved = client.patch("/api/v1/workforce/agents/content-writer", headers=headers(), json={"role_key": "geo-operator"})
    assert moved.status_code == 200
    assert moved.json()["role_key"] == "geo-operator"
    assert moved.json()["agent_key"] == "content-writer"

    assert client.patch("/api/v1/workforce/agents/content-writer", headers=headers(), json={"agent_key": "other"}).status_code == 422

    client.patch("/api/v1/workforce/roles/geo-operator", headers=headers(), json={"status": "disabled"})
    assert client.patch("/api/v1/workforce/agents/content-writer", headers=headers(), json={"role_key": "geo-operator"}).status_code == 409


def test_list_agents_filters_and_paginates() -> None:
    create_role()
    create_role(role_key="geo-operator", name="GEO 运营岗")
    create_agent(agent_key="content-writer", role_key="content-operator")
    create_agent(agent_key="geo-analyst", role_key="geo-operator")
    create_agent(agent_key="geo-reporter", role_key="geo-operator")
    client.patch("/api/v1/workforce/agents/geo-reporter", headers=headers(), json={"status": "disabled"})

    by_role = client.get("/api/v1/workforce/agents", headers=headers(), params={"role_key": "geo-operator"}).json()
    assert by_role["total"] == 2
    assert [item["agent_key"] for item in by_role["items"]] == ["geo-analyst", "geo-reporter"]

    active = client.get("/api/v1/workforce/agents", headers=headers(), params={"status": "active"}).json()
    assert active["total"] == 2

    page = client.get("/api/v1/workforce/agents", headers=headers(), params={"limit": 1, "offset": 1}).json()
    assert page["total"] == 3
    assert page["limit"] == 1
    assert page["offset"] == 1
    assert [item["agent_key"] for item in page["items"]] == ["geo-analyst"]

    assert client.get("/api/v1/workforce/agents", headers=headers(), params={"limit": 0}).status_code == 422


# ------------------------------------------------------------ 权限与租户隔离


def test_directory_endpoints_require_super_admin() -> None:
    assert client.get("/api/v1/workforce/roles").status_code == 401
    assert client.post("/api/v1/workforce/roles", json={"role_key": "content-operator", "name": "岗位"}).status_code == 401
    assert client.get("/api/v1/workforce/candidates").status_code == 401

    for role in ("ceo", "customer_admin", "employee", "department_lead"):
        assert client.get("/api/v1/workforce/roles", headers=headers(role=role)).status_code == 403
        assert client.get("/api/v1/workforce/agents", headers=headers(role=role)).status_code == 403
        assert client.get("/api/v1/workforce/candidates", headers=headers(role=role)).status_code == 403
        assert client.post("/api/v1/workforce/roles", headers=headers(role=role), json={"role_key": "content-operator", "name": "岗位"}).status_code == 403
        assert client.patch("/api/v1/workforce/roles/content-operator", headers=headers(role=role), json={"name": "岗位"}).status_code == 403


def test_directory_is_scoped_to_the_calling_tenant() -> None:
    create_role()

    other = client.get("/api/v1/workforce/roles", headers=headers(tenant_id="t-2")).json()
    assert other["items"] == []
    assert other["total"] == 0
    # 他租户既看不到也改不了（按不存在处理，不泄露存在性）
    assert client.patch("/api/v1/workforce/roles/content-operator", headers=headers(tenant_id="t-2"), json={"name": "越权"}).status_code == 404
    assert client.post("/api/v1/workforce/agents", headers=headers(tenant_id="t-2"), json={"agent_key": "content-writer", "name": "越权", "role_key": "content-operator"}).status_code == 409


# ------------------------------------------------------------ 未纳管候选


def test_candidates_list_unmanaged_identifiers_then_shrink_after_adoption() -> None:
    before = client.get("/api/v1/workforce/candidates", headers=headers()).json()

    # 岗位候选来自知识范围的 role 绑定；员工候选来自 agent 绑定 ∪ 任务里出现过的标识
    assert before == {"roles": ["content-operator"], "agents": ["content-operator", "content-writer", "unbound-agent"]}

    create_role()
    create_agent()
    after = client.get("/api/v1/workforce/candidates", headers=headers()).json()

    # content-operator 作为「岗位」已纳管，但任务里仍把它当作 employee_key 使用，
    # 因此它仍留在员工候选里（命名不对齐是已登记的已知限制，不在这里静默合并）。
    assert after == {"roles": [], "agents": ["content-operator", "unbound-agent"]}


# ------------------------------------------------------------ 审计


def test_directory_changes_are_audited() -> None:
    create_role()
    create_agent()
    client.patch("/api/v1/workforce/roles/content-operator", headers=headers(), json={"status": "disabled"})

    records, total = main.audit_service.query("t-1", actions=[AuditAction.WORKFORCE_ROLE_CREATED])
    assert total == 1
    assert records[0].actor_id == "admin-1"
    assert records[0].target_type == "job_role"
    assert records[0].target_id == "content-operator"
    assert records[0].detail["role_key"] == "content-operator"
    assert records[0].detail["changed_fields"] == ["role_key", "name"]

    disabled, _ = main.audit_service.query("t-1", actions=[AuditAction.WORKFORCE_ROLE_DISABLED])
    assert disabled[0].detail["changed_fields"] == ["status"]

    agents, _ = main.audit_service.query("t-1", actions=[AuditAction.WORKFORCE_AGENT_CREATED])
    assert agents[0].detail["agent_key"] == "content-writer"
    assert agents[0].target_type == "digital_employee"
