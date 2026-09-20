"""阶段 2：知识范围写路径的目录闸门（口径见设计文档 §14 与 §4 D5）。

要守住的性质：
    * 未纳管 / 已停用 / 非法标识一律 409，且**不能**在 403 之前生效（越权必须仍是 403）；
    * 写入时绑定键归一（去空白 + 小写），此后按归一键可读写；
    * 读路径（检索与 GET）保持不变，不受闸门影响。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import main
from app.audit.service import AuditService
from app.audit.store import InMemoryAuditStore
from app.domain import TaskStore, UserContext
from app.knowledge_policy import KnowledgeAccessRegistry
from app.main import app
from app.workforce.service import WorkforceDirectoryService
from app.workforce.store import InMemoryWorkforceDirectoryStore

client = TestClient(app)
ADMIN = UserContext("t-1", "admin-1", "super_admin")
UNMANAGED_MESSAGE = "该标识尚未纳入目录，请先在「数字员工设置」中纳管"


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    registry = KnowledgeAccessRegistry()
    directory_store = InMemoryWorkforceDirectoryStore()
    service = WorkforceDirectoryService(
        directory_store,
        audit=AuditService(InMemoryAuditStore()),
        knowledge_registry=registry,
        task_store=TaskStore(),
    )
    monkeypatch.setattr(main, "store", TaskStore())
    monkeypatch.setattr(main, "knowledge_access_registry", registry)
    monkeypatch.setattr(main, "workforce_directory_store", directory_store)
    monkeypatch.setattr(main, "workforce_directory_service", service)
    return registry, directory_store


def headers(role: str = "super_admin", user_id: str = "admin-1", tenant_id: str = "t-1") -> dict[str, str]:
    return {"X-Tenant-Id": tenant_id, "X-User-Id": user_id, "X-User-Role": role}


def put_role(role_key: str, ids: list[str], **overrides) -> object:
    return client.put(
        f"/api/v1/knowledge-access/roles/{role_key}",
        headers=headers(**overrides),
        json={"knowledge_base_ids": ids},
    )


def put_agent(agent_key: str, ids: list[str], **overrides) -> object:
    return client.put(
        f"/api/v1/knowledge-access/agents/{agent_key}",
        headers=headers(**overrides),
        json={"knowledge_base_ids": ids},
    )


def create_role(role_key: str = "content-operator", name: str = "自媒体运营岗") -> None:
    response = client.post("/api/v1/workforce/roles", headers=headers(), json={"role_key": role_key, "name": name})
    assert response.status_code == 201, response.text


def create_agent(agent_key: str = "content-writer", role_key: str = "content-operator") -> None:
    response = client.post(
        "/api/v1/workforce/agents",
        headers=headers(),
        json={"agent_key": agent_key, "name": "内容创作数字员工", "role_key": role_key},
    )
    assert response.status_code == 201, response.text


# ------------------------------------------------------------ 岗位写闸门


def test_binding_rejects_unmanaged_role_with_409() -> None:
    response = put_role("content-operator", ["kb-1"])

    assert response.status_code == 409
    assert response.json()["detail"] == UNMANAGED_MESSAGE


def test_binding_rejects_disabled_role_with_409() -> None:
    create_role()
    client.patch("/api/v1/workforce/roles/content-operator", headers=headers(), json={"status": "disabled"})

    assert put_role("content-operator", ["kb-1"]).status_code == 409


def test_binding_rejects_malformed_key_with_409_not_500() -> None:
    # 非法格式既不是目录标识、也不该变成 5xx
    assert put_role("%E8%BF%90%E8%90%A5%E5%B2%97", ["kb-1"]).status_code == 409
    assert put_role("content%20operator", ["kb-1"]).status_code == 409


def test_binding_accepts_managed_role_and_scopes_by_tenant() -> None:
    create_role()

    ok = put_role("content-operator", ["kb-2", "kb-1", "kb-1"])
    assert ok.status_code == 200
    assert ok.json() == {"binding_type": "role", "binding_key": "content-operator", "knowledge_base_ids": ["kb-1", "kb-2"]}
    assert client.get("/api/v1/knowledge-access/roles/content-operator", headers=headers()).json()["knowledge_base_ids"] == ["kb-1", "kb-2"]

    # 他租户看不到这条绑定，也没有该目录条目 → 409，不会因为「本租户有」而放行
    assert put_role("content-operator", ["kb-1"], tenant_id="t-2").status_code == 409


def test_binding_normalizes_key_on_write_and_read() -> None:
    create_role()

    written = put_role("  CONTENT-Operator  ", ["kb-1"])

    assert written.status_code == 200
    # 回显与落库都用归一键（D5）
    assert written.json()["binding_key"] == "content-operator"
    assert client.get("/api/v1/knowledge-access/roles/content-operator", headers=headers()).json()["knowledge_base_ids"] == ["kb-1"]
    assert client.get("/api/v1/knowledge-access/roles/CONTENT-OPERATOR", headers=headers()).json()["knowledge_base_ids"] == ["kb-1"]
    # roster 的绑定键也已归一（不再出现大小写变体）
    roster = client.get("/api/v1/workforce/roster", headers=headers()).json()
    assert [item["key"] for item in roster["items"]] == ["content-operator"]


# ------------------------------------------------------------ 数字员工写闸门


def test_agent_binding_requires_managed_active_agent() -> None:
    create_role()

    assert put_agent("content-writer", ["kb-1"]).status_code == 409

    create_agent()
    assert put_agent("content-writer", ["kb-1"]).status_code == 200

    client.patch("/api/v1/workforce/agents/content-writer", headers=headers(), json={"status": "disabled"})
    assert put_agent("content-writer", ["kb-2"]).status_code == 409


def test_agent_binding_blocked_when_owning_role_is_disabled() -> None:
    """口径收严（2026-09-12 真实 PG 回归后定）：岗位停用连带约束其下属员工。"""
    create_role()
    create_agent()

    client.patch("/api/v1/workforce/roles/content-operator", headers=headers(), json={"status": "disabled"})

    assert put_agent("content-writer", ["kb-1"]).status_code == 409


def test_agent_binding_accepts_managed_agent() -> None:
    create_role()
    create_agent()

    response = put_agent("Content-Writer", ["kb-3"])

    assert response.status_code == 200
    assert response.json() == {"binding_type": "agent", "binding_key": "content-writer", "knowledge_base_ids": ["kb-3"]}


# ------------------------------------------------------------ 权限优先于闸门


def test_permission_check_wins_over_directory_gate() -> None:
    """权限优先于闸门：**无知识绑定权**的角色一律 403，且响应不泄露「这个标识还没纳管」。"""
    for role in ("customer_admin", "employee", "department_lead"):
        assert put_role("content-operator", ["kb-1"], role=role).status_code == 403
        assert put_agent("content-writer", ["kb-1"], role=role).status_code == 403
        assert (
            put_role("content-operator", ["kb-1"], role=role).json()["detail"]
            == "只有企业负责人或超级管理员可以调整知识库范围"
        )


def test_ceo_passes_knowledge_gate_but_directory_gate_still_blocks() -> None:
    """**残留缺口（2026-09-19 登记，待专项裁决）**。

    矩阵 §3「知识：授权绑定」写 `ceo` ✅，知识域闸门已按矩阵放开；
    但写路径还要过**岗位目录**闸门（`app/workforce/store.py::_ensure_admin`，仅 `super_admin`）
    ⇒ `ceo` 仍**不可写**绑定。本用例钉住**当前事实**（不假装已达标），
    缺口处置（放开目录 / 修订矩阵该行 / 维持）需单独裁决。
    """
    response = put_role("content-operator", ["kb-1"], role="ceo")

    assert response.status_code == 403
    assert response.json()["detail"] == "只有超级管理员可以管理岗位与数字员工目录"


def test_gate_does_not_apply_to_reads() -> None:
    """读路径不设闸门：历史自由文本绑定仍按归一键可读（检索链路不变）。"""
    # 直接经注册表造一条「目录里没有」的绑定，读出来仍正常
    main.knowledge_access_registry.bind_role(ADMIN, "legacy-role", {"kb-legacy"})

    read = client.get("/api/v1/knowledge-access/roles/legacy-role", headers=headers())

    assert read.status_code == 200
    assert read.json()["knowledge_base_ids"] == ["kb-legacy"]
    # 但它确实在绑定侧未纳管清单里
    assert "legacy-role" in client.get("/api/v1/workforce/candidates", headers=headers()).json()["roles"]
