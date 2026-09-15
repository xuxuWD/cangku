"""知识治理层测试（规格 docs/superpowers/specs/2026-09-15-knowledge-governance-design.md §3）。

覆盖：正常流程（查库验证数据正确）、临界/异常与非法输入、反假测试、检索谓词守卫。
以服务层直连为主（内存仓储），API 层以 TestClient 验证 HTTP 语义映射。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import main
from app.audit.service import AuditService
from app.audit.store import InMemoryAuditStore
from app.domain import PolicyError, UserContext
from app.knowledge_governance.models import (
    InvalidKnowledgeDoc,
    KnowledgeDocNotFound,
    KnowledgeDocStateConflict,
    KnowledgeDocStatus,
    transition_allowed,
)
from app.knowledge_governance.scoped_search import build_scoped_search
from app.knowledge_governance.service import KnowledgeGovernanceService
from app.knowledge_governance.store import InMemoryKnowledgeGovStore
from app.main import app

client = TestClient(app)

TENANT = "t-1"
ALICE = "acct-alice"     # 普通员工
ADMIN = "acct-admin"     # super_admin


@pytest.fixture()
def service() -> KnowledgeGovernanceService:
    return KnowledgeGovernanceService(
        InMemoryKnowledgeGovStore(),
        audit=AuditService(InMemoryAuditStore()),
        review_grace_days=30,
    )


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    svc = KnowledgeGovernanceService(
        InMemoryKnowledgeGovStore(),
        audit=AuditService(InMemoryAuditStore()),
        review_grace_days=30,
    )
    monkeypatch.setattr(main, "knowledge_governance_service", svc)
    return svc


def _actor(user_id: str = ALICE, role: str = "employee") -> UserContext:
    return UserContext(TENANT, user_id, role)


def _admin() -> UserContext:
    return _actor(ADMIN, "super_admin")


def headers(role: str = "super_admin", user_id: str = ADMIN, tenant_id: str = TENANT) -> dict[str, str]:
    return {"X-Tenant-Id": tenant_id, "X-User-Id": user_id, "X-User-Role": role}


def _register(service, *, document_id: str = "doc-1", owner_id: str = "acct-owner", title: str = "报销制度"):
    """便捷：登记一篇文档并返回。"""
    return service.register_document(
        _admin(),
        document_id=document_id,
        title=title,
        owner_id=owner_id,
        version="1",
        source_key="manual",
    )


def _publish(service, document_id: str = "doc-1", *, owner_id: str | None = None):
    return service.publish_document(_admin(), document_id, owner_id=owner_id)


# ------------------------------------------------------------ 正常流程（查库验证数据正确）

def test_register_creates_draft_and_idempotent(service: KnowledgeGovernanceService) -> None:
    """登记 → 表内 status='draft'，owner/source_key 正确；同 (tenant, document_id) 幂等返回既有。"""
    doc = _register(service, document_id="doc-a", owner_id="acct-owner", title="差旅报销")
    # 查库验证
    stored = service.store.get_document(_admin(), "doc-a")
    assert stored.status is KnowledgeDocStatus.DRAFT
    assert stored.owner_id == "acct-owner"
    assert stored.source_key == "manual"
    assert stored.title == "差旅报销"

    # 幂等：同键重复登记 → 同一对象、不新增
    second = _register(service, document_id="doc-a", owner_id="acct-other", title="改标题")
    assert second.document_id == doc.document_id
    assert second.title == "差旅报销"  # 不覆盖既有


def test_publish_gate_and_lifecycle(service: KnowledgeGovernanceService) -> None:
    """发布（owner 闸门）→ published；到期扫描 → needs_review；复核通过 → published + 时间刷新。"""
    doc = _register(service, document_id="doc-b", owner_id="acct-owner")
    published = _publish(service, "doc-b")
    assert published.status is KnowledgeDocStatus.PUBLISHED
    assert published.owner_id == "acct-owner"
    assert published.last_reviewed_at is not None
    # 查库验证
    assert service.store.get_document(_admin(), "doc-b").status is KnowledgeDocStatus.PUBLISHED

    # 到期扫描：默认 review_due_at 为 None → 不置 needs_review
    count = service.scan_review_due(_admin())
    assert count == 0

    # 手动置到期再扫描
    service.store.update_status(_admin(), "doc-b", new_status=KnowledgeDocStatus.NEEDS_REVIEW)
    eligible_after = service.list_published_eligible(_admin())
    assert all(d.document_id != "doc-b" for d in eligible_after)

    # 复核通过 → 回 published，last_reviewed_at 刷新 / review_due_at 顺延宽限
    reviewed = service.review_document(_admin(), "doc-b", approved=True)
    assert reviewed.status is KnowledgeDocStatus.PUBLISHED
    assert reviewed.review_due_at is not None
    assert reviewed.last_reviewed_at is not None


def test_archive_is_terminal_and_leaves_eligible(service: KnowledgeGovernanceService) -> None:
    """Publish → archive 终态；归档文档从检索谓词白名单下线。"""
    _register(service, document_id="doc-c", owner_id="acct-owner")
    _publish(service, "doc-c")
    archived = service.archive_document(_admin(), "doc-c")
    assert archived.status is KnowledgeDocStatus.ARCHIVED
    assert all(d.document_id != "doc-c" for d in service.list_published_eligible(_admin()))


def test_review_judgement_archives(service: KnowledgeGovernanceService) -> None:
    """人工判废：needs_review → archived。"""
    _register(service, document_id="doc-d", owner_id="acct-owner")
    _publish(service, "doc-d")
    service.store.update_status(_admin(), "doc-d", new_status=KnowledgeDocStatus.NEEDS_REVIEW)
    archived = service.review_document(_admin(), "doc-d", approved=False)
    assert archived.status is KnowledgeDocStatus.ARCHIVED


# ------------------------------------------------------------ 临界 / 异常与非法输入

def test_non_admin_forbidden(service: KnowledgeGovernanceService) -> None:
    """普通员工登记 / 发布 / 改状态 / 复核 / 读指标 → PolicyError。"""
    employee = _actor()
    with pytest.raises(PolicyError):
        service.register_document(
            employee, document_id="doc-x", title="x", owner_id="o", version="1", source_key="manual"
        )
    with pytest.raises(PolicyError):
        service.list_documents(employee)
    with pytest.raises(PolicyError):
        service.metrics(employee)  # 内部已 ensure_can_read_metrics


def test_publish_requires_owner(service: KnowledgeGovernanceService) -> None:
    """发布无 owner（调用方与既有都空）→ InvalidKnowledgeDoc。"""
    service.register_document(
        _admin(), document_id="doc-n", title="a", owner_id="", version="1", source_key="manual"
    )
    with pytest.raises(InvalidKnowledgeDoc):
        service.publish_document(_admin(), "doc-n", owner_id=None)


def test_state_machine_forbids_illegal_transitions(service: KnowledgeGovernanceService) -> None:
    """归档可走 draft→archived 判废（any→archived，§2.2，2026-09-15 裁定）；archived 为终态。"""
    # 登记后未发布也可直接判废（§2.2「any → 归档 → archived」）
    service.register_document(
        _admin(), document_id="doc-e", title="e", owner_id="acct-owner", version="1", source_key="manual"
    )
    archived = service.archive_document(_admin(), "doc-e")
    assert archived.status is KnowledgeDocStatus.ARCHIVED

    # archived 是终态：不能再发布 / 再复核
    with pytest.raises(KnowledgeDocStateConflict):
        service.publish_document(_admin(), "doc-e", owner_id="acct-owner")
    with pytest.raises(KnowledgeDocStateConflict):
        service.review_document(_admin(), "doc-e", approved=True)

    # mark_due：published 且已到期 → needs_review；未到期 / 非 published → no-op（幂等）
    service.register_document(
        _admin(), document_id="doc-f", title="f", owner_id="acct-owner", version="1", source_key="manual"
    )
    service.publish_document(_admin(), "doc-f", owner_id="acct-owner")
    unchanged = service.mark_due(_admin(), "doc-f")  # 未设 review_due_at → 不到期，no-op
    assert unchanged.status is KnowledgeDocStatus.PUBLISHED

    with pytest.raises(KnowledgeDocNotFound):
        service.store.get_document(_admin(), "doc-does-not-exist")


def test_transition_matrix_locks_section_2_2_ruling() -> None:
    """状态机矩阵**逐边**锁定（2026-09-15 裁定：§2.2「any → archived」为准，draft 可直接归档）。

    全量 25 条边逐一断言（反假锚点）：把 `draft→archived` 判为非法、或放开 `archived` 终态，
    本用例必须变红。口径见规格 §2.2「口径裁定」段与 §3.3 反假条款。
    """
    S = KnowledgeDocStatus
    allowed = {
        (S.DRAFT, S.PUBLISHED), (S.DRAFT, S.ARCHIVED),  # 发布 / 登记后直接判废
        (S.PUBLISHED, S.UNDER_REVIEW), (S.PUBLISHED, S.NEEDS_REVIEW), (S.PUBLISHED, S.ARCHIVED),
        (S.UNDER_REVIEW, S.NEEDS_REVIEW), (S.UNDER_REVIEW, S.PUBLISHED), (S.UNDER_REVIEW, S.ARCHIVED),
        (S.NEEDS_REVIEW, S.PUBLISHED), (S.NEEDS_REVIEW, S.ARCHIVED), (S.NEEDS_REVIEW, S.UNDER_REVIEW),
    }
    for current in S:
        for target in S:
            assert transition_allowed(current, target) is ((current, target) in allowed), (current, target)


def test_list_documents_paginated_and_filtered(service: KnowledgeGovernanceService) -> None:
    """列表分页 + status 过滤。"""
    for i in range(5):
        _register(service, document_id=f"doc-list-{i}", owner_id="acct-owner")
    items, total = service.list_documents(_admin(), limit=2, offset=0)
    assert len(items) == 2
    assert total == 5
    filtered, filtered_total = service.list_documents(_admin(), status="draft")
    assert filtered_total == 5
    empty, empty_total = service.list_documents(_admin(), status="published")
    assert empty_total == 0


# ------------------------------------------------------------ 检索谓词守卫（§2.3 / §6.4）

class _FakeRegistry:
    def __init__(self, kb_ids):
        self._ids = set(kb_ids)

    def resolve(self, context, role_key):
        return self._ids


class _SpyAdapter:
    """记录是否被调用；返回可配置的引用列表。"""

    def __init__(self, citations=None):
        self.calls = 0
        self.citations = citations or []

    def search(self, context, query, knowledge_base_ids):
        self.calls += 1
        return self.citations


def test_scoped_search_fail_closed_when_whitelist_empty(service: KnowledgeGovernanceService) -> None:
    """治理开启 + 白名单空 → 直接返回空结果，**不请求 WeKnora**（反假：删掉守卫则调用发生）。"""
    adapter = _SpyAdapter()
    scoped = build_scoped_search(
        governance=service, registry=_FakeRegistry(["kb-1"]), adapter=adapter, enabled=True
    )
    result = scoped(_admin(), "content-operator", "报销")
    assert result == []
    assert adapter.calls == 0  # fail-closed：绝不请求


def test_scoped_search_whitelist_blocks_unregistered_docs(service: KnowledgeGovernanceService) -> None:
    """仅发布文档在案 → 白名单非空；未发布 / 未知文档被收敛剔除（只发布可检索）。"""
    _register(service, document_id="doc-g", owner_id="acct-owner")
    _publish(service, "doc-g")  # doc-g 在案且 published
    _register(service, document_id="doc-draft", owner_id="acct-owner")  # 保持 draft
    adapter = _SpyAdapter(citations=[
        _citation("chunk-1", "doc-g", "报销需要提交发票。"),
        _citation("chunk-2", "doc-draft", "未发布的机密。"),
        _citation("chunk-3", "doc-unknown", "未登记的机密。"),
    ])
    scoped = build_scoped_search(
        governance=service, registry=_FakeRegistry(["kb-1"]), adapter=adapter, enabled=True
    )
    result = scoped(_admin(), "content-operator", "报销")
    assert [c.citation_id for c in result] == ["chunk-1"]  # draft / 未知文档被收敛剔除
    assert adapter.calls == 1


def test_scoped_search_converges_after_search(service: KnowledgeGovernanceService) -> None:
    """published 未过期在案 → 放行；过期/未登记 → 收敛剔除。"""
    _register(service, document_id="doc-h", owner_id="acct-owner")
    _publish(service, "doc-h")
    adapter = _SpyAdapter(citations=[
        _citation("c1", "doc-h", "已发布内容"),
        _citation("c2", "doc-expired", "过期文档"),
    ])
    scoped = build_scoped_search(
        governance=service, registry=_FakeRegistry(["kb-1"]), adapter=adapter, enabled=True
    )
    result = scoped(_admin(), "content-operator", "报销")
    assert [c.citation_id for c in result] == ["c1"]


def test_scoped_search_disabled_keeps_legacy_behavior(service: KnowledgeGovernanceService) -> None:
    """治理开关关闭 → 与今天完全一致：不过滤（直接透传并请求）。"""
    adapter = _SpyAdapter(citations=[_citation("c1", "doc-any", "任意文档")])
    scoped = build_scoped_search(
        governance=service, registry=_FakeRegistry(["kb-1"]), adapter=adapter, enabled=False
    )
    result = scoped(_admin(), "content-operator", "报销")
    assert adapter.calls == 1
    assert len(result) == 1


def _citation(citation_id: str, knowledge_id: str, content: str) -> object:
    """构造一个最小引用假牌（duck typing：只需 knowledge_id / citation_id）。"""

    class FakeCitation:
        def __init__(self):
            self.citation_id = citation_id
            self.knowledge_id = knowledge_id
            self.content = content
            self.source_title = "来源"
            self.score = 0.9

    return FakeCitation()


# ------------------------------------------------------------ 反假测试（防安全回归）

def test_antifake_draft_must_not_appear_in_whitelist(service: KnowledgeGovernanceService) -> None:
    """故意把 status != published 的文档留在白名单 → 本用例必须变红。"""
    _register(service, document_id="doc-anti", owner_id="acct-owner")  # draft，未发布
    eligible = service.list_published_eligible(_admin())
    # 反假意志：若实现犯蠢把 draft 放进白名单，断言变红
    assert all(d.status is KnowledgeDocStatus.PUBLISHED for d in eligible)


def test_antifake_needs_review_is_excluded(service: KnowledgeGovernanceService) -> None:
    """故意拿未复核的 needs_review 文档做检索 → 谓词排除（必须不可见）。"""
    _register(service, document_id="doc-anti2", owner_id="acct-owner")
    _publish(service, "doc-anti2")
    service.store.update_status(_admin(), "doc-anti2", new_status=KnowledgeDocStatus.NEEDS_REVIEW)
    assert all(d.document_id != "doc-anti2" for d in service.list_published_eligible(_admin()))


# ------------------------------------------------------------ API 层 HTTP 语义（规格 §3.2）

def test_api_register_and_status_codes(service: KnowledgeGovernanceService) -> None:
    resp = client.post(
        "/api/v1/knowledge/documents",
        headers=headers(),
        json={"document_id": "api-doc-1", "title": "API文档", "owner_id": "acct-owner"},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["status"] == "draft"

    # 普通员工 → 403
    resp = client.post(
        "/api/v1/knowledge/documents",
        headers=headers(role="employee", user_id=ALICE),
        json={"document_id": "api-doc-2", "title": "x", "owner_id": "o"},
    )
    assert resp.status_code == 403

    # 未知字段 → 422
    resp = client.post(
        "/api/v1/knowledge/documents",
        headers=headers(),
        json={"document_id": "api-doc-3", "owner_id": "o", "evil": 1},
    )
    assert resp.status_code == 422

    # 超长 document_id → 422
    resp = client.post(
        "/api/v1/knowledge/documents",
        headers=headers(),
        json={"document_id": "x" * 200, "owner_id": "o"},
    )
    assert resp.status_code == 422


def test_api_publish_without_owner_422_and_conflict_409(service: KnowledgeGovernanceService) -> None:
    client.post(
        "/api/v1/knowledge/documents",
        headers=headers(),
        json={"document_id": "api-doc-10", "owner_id": ""},
    )
    resp = client.post("/api/v1/knowledge/documents/api-doc-10/publish", headers=headers())
    assert resp.status_code == 422  # 发布无 owner

    client.post(
        "/api/v1/knowledge/documents",
        headers=headers(),
        json={"document_id": "api-doc-11", "owner_id": "acct-owner"},
    )
    resp = client.post(
        "/api/v1/knowledge/documents/api-doc-11/publish", headers=headers(), params={"owner_id": "acct-owner"}
    )
    assert resp.status_code == 200
    # 重复发布（非 draft）→ 409
    resp = client.post(
        "/api/v1/knowledge/documents/api-doc-11/publish", headers=headers(), params={"owner_id": "acct-owner"}
    )
    assert resp.status_code == 409


def test_api_metrics_and_eligible_super_admin_only(service: KnowledgeGovernanceService) -> None:
    client.post(
        "/api/v1/knowledge/documents",
        headers=headers(),
        json={"document_id": "api-m", "owner_id": "acct-owner"},
    )
    client.post("/api/v1/knowledge/documents/api-m/publish", headers=headers(), params={"owner_id": "acct-owner"})

    resp = client.get("/api/v1/knowledge/metrics", headers=headers())
    assert resp.status_code == 200
    body = resp.json()
    assert body["published"] == 1
    assert body["total"] == 1
    assert body["freshness_ratio"] == 1.0

    # 普通员工读指标 → 403
    resp = client.get("/api/v1/knowledge/metrics", headers=headers(role="employee", user_id=ALICE))
    assert resp.status_code == 403

    resp = client.get("/api/v1/knowledge/governance/eligible", headers=headers())
    assert resp.status_code == 200
    assert resp.json()["total"] == 1
    # 普通员工读白名单 → 403
    resp = client.get("/api/v1/knowledge/governance/eligible", headers=headers(role="employee", user_id=ALICE))
    assert resp.status_code == 403


def test_api_review_scan_and_review(service: KnowledgeGovernanceService) -> None:
    client.post(
        "/api/v1/knowledge/documents",
        headers=headers(),
        json={"document_id": "api-r", "owner_id": "acct-owner"},
    )
    client.post("/api/v1/knowledge/documents/api-r/publish", headers=headers(), params={"owner_id": "acct-owner"})
    resp = client.post("/api/v1/knowledge/review-scan", headers=headers())
    assert resp.status_code == 200
    assert resp.json() == {"reviewed_due": 0}  # 未设 review_due_at → 不到期

    # 未知文档 → 404
    resp = client.get("/api/v1/knowledge/documents/api-missing", headers=headers())
    assert resp.status_code == 404

    # 越权读列表 → 403
    resp = client.get("/api/v1/knowledge/documents", headers=headers(role="employee", user_id=ALICE))
    assert resp.status_code == 403