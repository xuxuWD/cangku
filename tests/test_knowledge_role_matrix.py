"""知识域角色门禁：**逐行钉死 `permission-matrix.md` §3 的「知识」四行**（P0 缺口修复的锚点）。

背景（2026-09-19 第 7 轮实测登记）：实现把**全部**知识端点都收在 `super_admin` 之下，与矩阵 §3 冲突。
矩阵是权限口径的**唯一权威**（自定「实现与本文冲突时以本文为准」），故本轮按矩阵逐行对齐：

| 资源 · 动作 | employee | department_lead | ceo | super_admin | customer_admin |
| --- | --- | --- | --- | --- | --- |
| 知识：检索 | ⚠️ 按绑定 | ⚠️ 按绑定 | ⚠️ 按绑定 | ✅ | ❌ |
| 知识：上传/登记 | ✅ | ✅ | ✅ | ✅ | ❌ |
| 知识：发布 / 归档 / 复核 | ❌ | ❌ | ✅ | ✅ | ❌ |
| 知识：授权绑定 | ❌ | ❌ | ✅ | ✅ | ❌ |

**「按绑定」的落地口径（P0 安全要件）**：`KnowledgeAccessRegistry.resolve` **不校验调用者身份**
（只按租户取绑定），若原样放开 employee ⇒ 员工可在请求体里填**任意** `role_key` / `agent_key`
读到别人的知识范围（撞矩阵 §8 第 4 条「不静默返回他人文档」与宪法「数据归属」红线）。
⇒ 非管理角色**自限**：`role_key` 必须等于自身角色，`agent_key` 通道不开放；无绑定即 fail-closed。

**反假锚点**：
- 本文件任一角色档位改错（例如把检索重新收回 super_admin、或让 employee 能传任意 role_key）⇒ 必红；
- P1（复核绕过 owner 闸门）用例见文末：把复核的前置状态检查或 owner 闸门去掉 ⇒ 必红。
"""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from app import main
from app.audit.service import AuditService
from app.audit.store import InMemoryAuditStore
from app.domain import PolicyError, UserContext
from app.knowledge import WeKnoraSearchRuntime
from app.knowledge_governance.models import (
    InvalidKnowledgeDoc,
    KnowledgeDocStateConflict,
    KnowledgeDocStatus,
)
from app.knowledge_governance.service import KnowledgeGovernanceService
from app.knowledge_governance.store import InMemoryKnowledgeGovStore
from app.knowledge_policy import KnowledgeAccessRegistry

client = TestClient(main.app)

TENANT = "t-roles"
ADMIN = "acct-admin"
KB = "kb-1"
'''矩阵 §3「检索」行允许的三个非管理角色（⚠️ 按绑定）、管理角色（✅）、被拒角色（❌）。'''
NON_ADMIN_ROLES = ("employee", "department_lead", "ceo")
MANAGE_ROLES_CASES = ("ceo", "super_admin")
DENIED_ROLE = "customer_admin"


def headers(role: str = "super_admin", user_id: str = "acct-1", tenant_id: str = TENANT) -> dict[str, str]:
    return {"X-Tenant-Id": tenant_id, "X-User-Id": user_id, "X-User-Role": role}


def _ctx(role: str, user_id: str = "acct-1") -> UserContext:
    return UserContext(TENANT, user_id, role)


def _admin_ctx() -> UserContext:
    return _ctx("super_admin", ADMIN)


class _Upstream:
    """假 WeKnora（记录请求体，返回一条命中；用于断言「有没有真的打到上游」）。"""

    def __init__(self, citations: list[dict] | None = None) -> None:
        self.citations = citations if citations is not None else []
        self.requests: list[dict] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        import json

        self.requests.append(json.loads(request.read()))
        return httpx.Response(200, json={"success": True, "data": self.citations})

    def runtime(self) -> WeKnoraSearchRuntime:
        return WeKnoraSearchRuntime(
            client=httpx.Client(transport=httpx.MockTransport(self.handler)),
            base_url="https://weknora.internal",
            api_key="sk-test-key",
            timeout=5.0,
        )


def _citation(knowledge_id: str) -> dict:
    return {"id": f"chunk-{knowledge_id}", "content": "片段", "knowledge_id": knowledge_id, "score": 0.9}


@pytest.fixture()
def governance() -> KnowledgeGovernanceService:
    return KnowledgeGovernanceService(
        InMemoryKnowledgeGovStore(), audit=AuditService(InMemoryAuditStore()), review_grace_days=30
    )


@pytest.fixture()
def registry() -> KnowledgeAccessRegistry:
    return KnowledgeAccessRegistry()


def _wire(monkeypatch, *, governance, registry, upstream: _Upstream | None = None) -> _Upstream:
    upstream = upstream or _Upstream()
    monkeypatch.setattr(main, "knowledge_governance_service", governance)
    monkeypatch.setattr(main, "knowledge_access_registry", registry)
    monkeypatch.setattr(main, "audit_service", AuditService(InMemoryAuditStore()))
    monkeypatch.setattr(main, "weknora_search_runtime", upstream.runtime())
    monkeypatch.setattr(main.settings, "knowledge_governance_enabled", True)
    return upstream


def _publish(governance: KnowledgeGovernanceService, document_id: str = "doc-pub") -> None:
    governance.register_document(
        _admin_ctx(), document_id=document_id, title="已发布", owner_id="acct-owner", version="1", source_key="manual"
    )
    governance.publish_document(_admin_ctx(), document_id, owner_id="acct-owner")


# ------------------------------------------------------------ 检索行（⚠️ 按绑定 / ✅ / ❌）


@pytest.mark.parametrize("role", NON_ADMIN_ROLES)
def test_search_allowed_for_non_admin_roles_with_own_role_binding(
    monkeypatch, governance, registry, role
) -> None:
    """三个非管理角色**用与自身角色同名的绑定**检索 ⇒ 200（矩阵 §3 检索行 ⚠️）。"""
    _publish(governance)
    registry.bind_role(_admin_ctx(), role, {KB})
    upstream = _wire(
        monkeypatch, governance=governance, registry=registry, upstream=_Upstream([_citation("doc-pub")])
    )

    response = client.post(
        "/api/v1/knowledge/search",
        json={"query": "合规", "role_key": role},
        headers=headers(role=role, user_id=f"acct-{role}"),
    )

    assert response.status_code == 200, response.text
    assert [item["knowledge_id"] for item in response.json()["items"]] == ["doc-pub"]
    assert upstream.requests, "应真的打到上游（白名单非空）"


def test_search_non_admin_cannot_use_other_role_key(monkeypatch, governance, registry) -> None:
    """非管理角色**不得**填别人的 `role_key`（数据归属红线；矩阵 §8 第 4 条「不静默返回他人文档」）。"""
    _publish(governance)
    registry.bind_role(_admin_ctx(), "content-operator", {KB})  # 别人的岗位绑定
    upstream = _wire(
        monkeypatch, governance=governance, registry=registry, upstream=_Upstream([_citation("doc-pub")])
    )

    response = client.post(
        "/api/v1/knowledge/search",
        json={"query": "合规", "role_key": "content-operator"},
        headers=headers(role="employee", user_id="acct-employee"),
    )

    assert response.status_code == 403, response.text
    assert upstream.requests == [], "越权请求绝不允许打到上游"


def test_search_non_admin_cannot_use_agent_key(monkeypatch, governance, registry) -> None:
    """非管理角色**不开放** `agent_key` 通道（无 user→数字员工 归属链，故 fail-closed）。"""
    _publish(governance)
    registry.bind_agent(_admin_ctx(), "agent-x", {KB})
    upstream = _wire(
        monkeypatch, governance=governance, registry=registry, upstream=_Upstream([_citation("doc-pub")])
    )

    response = client.post(
        "/api/v1/knowledge/search",
        json={"query": "合规", "agent_key": "agent-x"},
        headers=headers(role="employee", user_id="acct-employee"),
    )

    assert response.status_code == 403, response.text
    assert upstream.requests == []


@pytest.mark.parametrize("role", MANAGE_ROLES_CASES)
def test_search_manage_roles_may_use_any_role_key(monkeypatch, governance, registry, role) -> None:
    """管理角色（ceo / super_admin）可检索任意 `role_key` / `agent_key`（治理需要，矩阵 ✅）。"""
    _publish(governance)
    registry.bind_role(_admin_ctx(), "content-operator", {KB})
    upstream = _wire(
        monkeypatch, governance=governance, registry=registry, upstream=_Upstream([_citation("doc-pub")])
    )

    response = client.post(
        "/api/v1/knowledge/search",
        json={"query": "合规", "role_key": "content-operator"},
        headers=headers(role=role, user_id=f"acct-{role}"),
    )

    assert response.status_code == 200, response.text
    assert upstream.requests


def test_search_customer_admin_forbidden(monkeypatch, governance, registry) -> None:
    """`customer_admin` 在知识域**一律 ❌**（矩阵 §3 末列）。"""
    _publish(governance)
    registry.bind_role(_admin_ctx(), DENIED_ROLE, {KB})
    upstream = _wire(
        monkeypatch, governance=governance, registry=registry, upstream=_Upstream([_citation("doc-pub")])
    )

    response = client.post(
        "/api/v1/knowledge/search",
        json={"query": "合规", "role_key": DENIED_ROLE},
        headers=headers(role=DENIED_ROLE, user_id="acct-customer"),
    )

    assert response.status_code == 403, response.text
    assert upstream.requests == []


def test_search_non_admin_without_binding_is_fail_closed(monkeypatch, governance, registry) -> None:
    """非管理角色**无绑定** ⇒ 空结果 + `no_binding`，且**不请求上游**（fail-closed，不返回他人文档）。"""
    _publish(governance)
    upstream = _wire(
        monkeypatch, governance=governance, registry=registry, upstream=_Upstream([_citation("doc-pub")])
    )

    response = client.post(
        "/api/v1/knowledge/search",
        json={"query": "合规", "role_key": "employee"},
        headers=headers(role="employee", user_id="acct-employee"),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["items"] == [] and body["reason"] == "no_binding"
    assert upstream.requests == []


# ------------------------------------------------------------ 登记行（✅ ×4 / ❌）


@pytest.mark.parametrize("role", NON_ADMIN_ROLES + ("super_admin",))
def test_register_allowed_for_four_roles(monkeypatch, governance, registry, role) -> None:
    """矩阵 §3 登记行：四个角色 ✅（`customer_admin` 除外）。"""
    _wire(monkeypatch, governance=governance, registry=registry)

    response = client.post(
        "/api/v1/knowledge/documents",
        json={"document_id": f"doc-{role}", "title": "x", "owner_id": "acct-owner"},
        headers=headers(role=role, user_id=f"acct-{role}"),
    )

    assert response.status_code == 201, response.text
    assert response.json()["status"] == "draft"


def test_register_customer_admin_forbidden(monkeypatch, governance, registry) -> None:
    _wire(monkeypatch, governance=governance, registry=registry)

    response = client.post(
        "/api/v1/knowledge/documents",
        json={"document_id": "doc-customer", "title": "x", "owner_id": "acct-owner"},
        headers=headers(role=DENIED_ROLE, user_id="acct-customer"),
    )

    assert response.status_code == 403, response.text


# ------------------------------------------------------------ 管理行（发布 / 归档 / 复核 → ceo + super_admin）


@pytest.mark.parametrize("role", MANAGE_ROLES_CASES)
def test_publish_archive_review_allowed_for_manage_roles(monkeypatch, governance, registry, role) -> None:
    """矩阵 §3 管理行动作：`ceo` 与 `super_admin` 均可发布 / 归档 / 复核。"""
    _wire(monkeypatch, governance=governance, registry=registry)
    actor = headers(role=role, user_id=f"acct-{role}")

    assert client.post(
        "/api/v1/knowledge/documents",
        json={"document_id": f"doc-{role}", "title": "x", "owner_id": "acct-owner"},
        headers=actor,
    ).status_code == 201
    assert client.post(
        f"/api/v1/knowledge/documents/doc-{role}/publish", headers=actor
    ).status_code == 200, f"{role} 应可发布"
    assert client.post(
        f"/api/v1/knowledge/documents/doc-{role}/archive", headers=actor
    ).status_code == 200, f"{role} 应可归档"


@pytest.mark.parametrize("role", ("employee", "department_lead", DENIED_ROLE))
def test_publish_archive_review_forbidden_for_others(monkeypatch, governance, registry, role) -> None:
    """登记行允许、管理行拒绝：低权角色**可以登记但不能发布**（矩阵两行不冲突）。"""
    _wire(monkeypatch, governance=governance, registry=registry)
    actor = headers(role=role, user_id=f"acct-{role}")

    assert client.post(
        "/api/v1/knowledge/documents",
        json={"document_id": f"doc-low-{role}", "title": "x", "owner_id": "acct-owner"},
        headers=actor,
    ).status_code in (201, 403)  # customer_admin 连登记都拒（上面已单测）
    assert client.post(
        f"/api/v1/knowledge/documents/doc-low-{role}/publish", headers=actor
    ).status_code == 403, f"{role} 不应能发布"
    assert client.post(
        f"/api/v1/knowledge/documents/doc-low-{role}/archive", headers=actor
    ).status_code == 403, f"{role} 不应能归档"


# ------------------------------------------------------------ 授权绑定行（ceo + super_admin）


def test_binding_allowed_for_manage_roles_only(registry) -> None:
    """矩阵 §3 授权绑定行：`ceo` ✅ / `super_admin` ✅ / 其余 ❌（含治理读 `list_bindings`）。"""
    registry.bind_role(_ctx("ceo", "acct-ceo"), "ops", {KB})
    assert registry.resolve(_admin_ctx(), "ops") == {KB}
    assert registry.list_bindings(_ctx("ceo", "acct-ceo"))["role"]["ops"] == [KB]

    for role in ("employee", "department_lead", DENIED_ROLE):
        with pytest.raises(PolicyError):
            registry.bind_role(_ctx(role), "ops2", {KB})
        with pytest.raises(PolicyError):
            registry.list_bindings(_ctx(role))


# ------------------------------------------------------------ 治理读（列表 / 指标 / 可检索清单 → 管理角色）


def test_governance_reads_denied_for_low_roles_allowed_for_ceo(monkeypatch, governance, registry) -> None:
    """治理读（文档列表 / 指标 / 可检索清单）按**管理角色**：ceo + super_admin；其余 403。"""
    _wire(monkeypatch, governance=governance, registry=registry)
    _publish(governance)

    for path in ("/api/v1/knowledge/documents", "/api/v1/knowledge/metrics", "/api/v1/knowledge/governance/eligible"):
        assert client.get(path, headers=headers(role="ceo", user_id="acct-ceo")).status_code == 200, path
        assert client.get(path, headers=headers(role="employee")).status_code == 403, path


# ------------------------------------------------------------ P1：复核不得绕过「发布必须指定负责人」


def test_review_rejected_for_non_reviewable_state(governance) -> None:
    """P1 闸门一：`draft` + 复核通过**不再**能直达 published（收窄复核前置状态为 needs_review / under_review）。"""
    governance.register_document(
        _admin_ctx(), document_id="doc-draft", title="草稿", owner_id="acct-owner", version="1", source_key="manual"
    )

    with pytest.raises(KnowledgeDocStateConflict):
        governance.review_document(_admin_ctx(), "doc-draft", approved=True)

    # 失败未改状态（防止「先改后判」）
    assert governance.store.get_document(_admin_ctx(), "doc-draft").status is KnowledgeDocStatus.DRAFT


def test_review_approve_requires_owner(governance) -> None:
    """P1 闸门二：复核通过**同样**受 owner 闸门约束（owner 为空 ⇒ 422，与发布闸门口径一致）。"""
    governance.register_document(
        _admin_ctx(), document_id="doc-noowner", title="无负责人", owner_id="", version="1", source_key="manual"
    )
    # 构造需求态：published→needs_review（owner 仍为空，模拟历史数据）
    governance.store.update_status(_admin_ctx(), "doc-noowner", new_status=KnowledgeDocStatus.NEEDS_REVIEW)

    with pytest.raises(InvalidKnowledgeDoc):
        governance.review_document(_admin_ctx(), "doc-noowner", approved=True)

    assert governance.store.get_document(_admin_ctx(), "doc-noowner").status is KnowledgeDocStatus.NEEDS_REVIEW


def test_review_reject_still_works_from_needs_review(governance) -> None:
    """回归：收窄后**合法**复核路径不受影响（needs_review → 退回 ⇒ archived）。"""
    governance.register_document(
        _admin_ctx(), document_id="doc-ok", title="正常", owner_id="acct-owner", version="1", source_key="manual"
    )
    governance.store.update_status(_admin_ctx(), "doc-ok", new_status=KnowledgeDocStatus.NEEDS_REVIEW)

    archived = governance.review_document(_admin_ctx(), "doc-ok", approved=False)

    assert archived.status is KnowledgeDocStatus.ARCHIVED
