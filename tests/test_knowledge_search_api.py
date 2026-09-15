"""知识检索入口 `POST /api/v1/knowledge/search` 的接口级测试（规格 §2.3 检索谓词守卫接线）。

口径：本入口是**治理层唯一的生产检索路径**——它把 `build_scoped_search` 谓词守卫接进 HTTP，
使「未登记 / 未发布文档不可检索」在真实链路上生效。因此这里的用例就是**门禁锚点**：

- 正常流程：只返回白名单内文档；`knowledge_ids` 确实下传；`agent_key` 走数字员工绑定。
- 临界值：query/limit 边界；无绑定与白名单空两种「空结果」**都不请求上游**（fail-closed）。
- 异常与非法输入：身份缺失 401 / 非管理员 403 / 未知字段 422 / 互斥校验 422 / 未配置 503 /
  治理关闭 503 / 上游超时 504 / 上游失败 502（且**不回显上游地址与密钥**）。
- 反假锚点：见各用例 docstring（改坏对应实现必须变红）。
"""

from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app import main
from app.audit.models import AuditAction
from app.audit.service import AuditService
from app.audit.store import InMemoryAuditStore
from app.domain import UserContext
from app.knowledge import WeKnoraSearchRuntime
from app.knowledge_governance.service import KnowledgeGovernanceService
from app.knowledge_governance.store import InMemoryKnowledgeGovStore
from app.knowledge_policy import KnowledgeAccessRegistry

client = TestClient(main.app)

TENANT = "t-search"
ADMIN = "acct-admin"
KB = "kb-1"
ROLE_KEY = "content-operator"


def headers(role: str = "super_admin", user_id: str = ADMIN, tenant_id: str = TENANT) -> dict[str, str]:
    return {"X-Tenant-Id": tenant_id, "X-User-Id": user_id, "X-User-Role": role}


def _admin() -> UserContext:
    return UserContext(TENANT, ADMIN, "super_admin")


class _Upstream:
    """假 WeKnora（httpx.MockTransport）：记录请求体，可配置引用与失败模式。"""

    def __init__(
        self,
        citations: list[dict] | None = None,
        *,
        status: int = 200,
        success: bool = True,
        timeout: bool = False,
    ) -> None:
        self.citations = citations or []
        self.status = status
        self.success = success
        self.timeout = timeout
        self.requests: list[dict] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(json.loads(request.read()))
        if self.timeout:
            raise httpx.TimeoutException("upstream timeout", request=request)
        if self.status != 200:
            return httpx.Response(self.status, json={"error": "boom"})
        return httpx.Response(200, json={"success": self.success, "data": self.citations})

    def runtime(self) -> WeKnoraSearchRuntime:
        return WeKnoraSearchRuntime(
            client=httpx.Client(transport=httpx.MockTransport(self.handler)),
            base_url="https://weknora.internal",
            api_key="sk-test-key",
            timeout=5.0,
        )


def _citation(citation_id: str, knowledge_id: str, content: str = "片段内容") -> dict:
    return {
        "id": citation_id,
        "content": content,
        "knowledge_id": knowledge_id,
        "knowledge_title": "来源标题",
        "score": 0.9,
    }


@pytest.fixture()
def governance() -> KnowledgeGovernanceService:
    return KnowledgeGovernanceService(
        InMemoryKnowledgeGovStore(), audit=AuditService(InMemoryAuditStore()), review_grace_days=30
    )


@pytest.fixture()
def audit() -> AuditService:
    return AuditService(InMemoryAuditStore())


@pytest.fixture()
def registry() -> KnowledgeAccessRegistry:
    return KnowledgeAccessRegistry()


def _wire(monkeypatch, *, governance, registry, audit, upstream=None, enabled=True) -> _Upstream:
    """按既有 `_isolate` 范式替换模块级装配（端点每次请求重新读取这些全局）。"""
    upstream = upstream or _Upstream()
    monkeypatch.setattr(main, "knowledge_governance_service", governance)
    monkeypatch.setattr(main, "knowledge_access_registry", registry)
    monkeypatch.setattr(main, "audit_service", audit)
    monkeypatch.setattr(main, "weknora_search_runtime", upstream.runtime())
    monkeypatch.setattr(main.settings, "knowledge_governance_enabled", enabled)
    return upstream


def _publish(governance: KnowledgeGovernanceService, document_id: str, title: str = "已发布文档") -> None:
    governance.register_document(
        _admin(), document_id=document_id, title=title, owner_id="acct-owner", version="1", source_key="manual"
    )
    governance.publish_document(_admin(), document_id, owner_id="acct-owner")


def _bind_role(registry: KnowledgeAccessRegistry, role_key: str = ROLE_KEY, kb: str = KB) -> None:
    registry.bind_role(_admin(), role_key, {kb})


def _blocked_records(audit: AuditService) -> list:
    records, _total = audit.query(TENANT, actions=[AuditAction.KNOWLEDGE_SEARCH_BLOCKED])
    return records


def _search(payload: dict, **kwargs) -> httpx.Response:
    return client.post("/api/v1/knowledge/search", json=payload, headers=kwargs.pop("headers", headers()))


# ------------------------------------------------------------ 正常流程

def test_search_returns_only_published_documents(monkeypatch, governance, registry, audit) -> None:
    """只返回白名单（published 且未过期）内文档，且把白名单作为 `knowledge_ids` 下传。

    反假锚点：删掉返回后收敛（只留下传）⇒ 未发布的 `doc-draft` 会出现在结果里，本用例必红。
    """
    _bind_role(registry)
    _publish(governance, "doc-pub")
    governance.register_document(
        _admin(), document_id="doc-draft", title="草稿", owner_id="acct-owner", version="1", source_key="manual"
    )
    upstream = _wire(
        monkeypatch,
        governance=governance,
        registry=registry,
        audit=audit,
        upstream=_Upstream([_citation("chunk-1", "doc-pub"), _citation("chunk-2", "doc-draft")]),
    )

    response = _search({"query": "报销流程", "role_key": ROLE_KEY})

    assert response.status_code == 200
    body = response.json()
    assert [item["knowledge_id"] for item in body["items"]] == ["doc-pub"]
    assert body["items"][0]["content"] == "片段内容"
    assert body["total"] == 1 and body["truncated"] is False and body["reason"] is None
    assert upstream.requests[0]["knowledge_ids"] == ["doc-pub"]  # 方案②：下传
    assert upstream.requests[0]["knowledge_base_ids"] == [KB]


def test_search_uses_agent_binding_when_agent_key_given(monkeypatch, governance, registry, audit) -> None:
    """`agent_key` 走数字员工绑定（`registry.resolve` 在给 agent_key 时不看 role_key）。"""
    registry.bind_agent(_admin(), "agent-x", {KB})
    _publish(governance, "doc-pub")
    upstream = _wire(
        monkeypatch,
        governance=governance,
        registry=registry,
        audit=audit,
        upstream=_Upstream([_citation("chunk-1", "doc-pub")]),
    )

    response = _search({"query": "报销流程", "agent_key": "agent-x"})

    assert response.status_code == 200
    assert [item["knowledge_id"] for item in response.json()["items"]] == ["doc-pub"]
    assert len(upstream.requests) == 1


def test_limit_truncates_and_marks_truncated(monkeypatch, governance, registry, audit) -> None:
    """`limit` 只做服务端截断：total 仍是收敛后总数，超出部分丢弃并置 `truncated`。"""
    _bind_role(registry)
    _publish(governance, "doc-pub")
    upstream = _wire(
        monkeypatch,
        governance=governance,
        registry=registry,
        audit=audit,
        upstream=_Upstream([_citation(f"chunk-{i}", "doc-pub") for i in range(3)]),
    )

    response = _search({"query": "报销流程", "role_key": ROLE_KEY, "limit": 2})

    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 2 and body["total"] == 3 and body["truncated"] is True
    assert upstream.requests[0].get("limit") is None  # limit 不下传上游（top_k 语义未核实）


def test_empty_hits_reports_no_hits_reason(monkeypatch, governance, registry, audit) -> None:
    """白名单非空但上游无命中 ⇒ 空结果 + `reason=no_hits`（与「被守卫拦住」区分）。"""
    _bind_role(registry)
    _publish(governance, "doc-pub")
    upstream = _wire(monkeypatch, governance=governance, registry=registry, audit=audit, upstream=_Upstream([]))

    response = _search({"query": "报销流程", "role_key": ROLE_KEY})

    assert response.status_code == 200
    assert response.json()["reason"] == "no_hits"
    assert len(upstream.requests) == 1
    assert _blocked_records(audit) == []  # 正常检索不落审计


# ------------------------------------------------------------ 临界值

def test_query_length_boundaries(monkeypatch, governance, registry, audit) -> None:
    """query 边界：1 / 500 通过；空与 501 字符被拒（422）。"""
    _bind_role(registry)
    _publish(governance, "doc-pub")
    _wire(monkeypatch, governance=governance, registry=registry, audit=audit, upstream=_Upstream([]))

    assert _search({"query": "x", "role_key": ROLE_KEY}).status_code == 200
    assert _search({"query": "x" * 500, "role_key": ROLE_KEY}).status_code == 200
    assert _search({"query": "", "role_key": ROLE_KEY}).status_code == 422
    assert _search({"query": "x" * 501, "role_key": ROLE_KEY}).status_code == 422


def test_limit_boundaries(monkeypatch, governance, registry, audit) -> None:
    """limit 边界：1 / 50 通过；0 与 51 被拒（422）。"""
    _bind_role(registry)
    _publish(governance, "doc-pub")
    _wire(monkeypatch, governance=governance, registry=registry, audit=audit, upstream=_Upstream([]))

    assert _search({"query": "x", "role_key": ROLE_KEY, "limit": 1}).status_code == 200
    assert _search({"query": "x", "role_key": ROLE_KEY, "limit": 50}).status_code == 200
    assert _search({"query": "x", "role_key": ROLE_KEY, "limit": 0}).status_code == 422
    assert _search({"query": "x", "role_key": ROLE_KEY, "limit": 51}).status_code == 422


def test_unbound_key_returns_empty_without_upstream(monkeypatch, governance, registry, audit) -> None:
    """岗位没有任何知识库绑定 ⇒ 空结果且**不请求上游**；并落一条 blocked 审计（reason=no_binding）。"""
    _publish(governance, "doc-pub")  # 有已发布文档，但没有任何绑定
    upstream = _wire(
        monkeypatch,
        governance=governance,
        registry=registry,
        audit=audit,
        upstream=_Upstream([_citation("chunk-1", "doc-pub")]),
    )

    response = _search({"query": "报销流程", "role_key": ROLE_KEY})

    assert response.status_code == 200
    body = response.json()
    assert body["items"] == [] and body["reason"] == "no_binding"
    assert upstream.requests == []
    records = _blocked_records(audit)
    assert len(records) == 1 and records[0].detail["reason"] == "no_binding"
    assert records[0].detail["role_key"] == ROLE_KEY


def test_empty_whitelist_short_circuits_upstream(monkeypatch, governance, registry, audit) -> None:
    """有绑定但**白名单为空** ⇒ fail-closed：0 结果且**上游零请求**（反假锚点：删掉短路必红）。"""
    _bind_role(registry)
    governance.register_document(
        _admin(), document_id="doc-draft", title="草稿", owner_id="acct-owner", version="1", source_key="manual"
    )
    upstream = _wire(
        monkeypatch,
        governance=governance,
        registry=registry,
        audit=audit,
        upstream=_Upstream([_citation("chunk-1", "doc-draft")]),
    )

    response = _search({"query": "报销流程", "role_key": ROLE_KEY})

    assert response.status_code == 200
    assert response.json()["reason"] == "empty_whitelist"
    assert upstream.requests == []
    records = _blocked_records(audit)
    assert len(records) == 1 and records[0].detail["reason"] == "empty_whitelist"


# ------------------------------------------------------------ 异常与非法输入

def test_requires_exactly_one_of_role_key_or_agent_key(monkeypatch, governance, registry, audit) -> None:
    """`role_key` / `agent_key` 必须**恰好给一个**（都传或都不传都 422）。"""
    _bind_role(registry)
    upstream = _wire(monkeypatch, governance=governance, registry=registry, audit=audit)

    assert _search({"query": "x", "role_key": ROLE_KEY, "agent_key": "agent-x"}).status_code == 422
    assert _search({"query": "x"}).status_code == 422
    assert upstream.requests == []


def test_unknown_fields_rejected(monkeypatch, governance, registry, audit) -> None:
    """未知字段一律 422：客户端**不得**自带租户/知识库范围（白名单口径 + 防扩权）。"""
    _bind_role(registry)
    upstream = _wire(monkeypatch, governance=governance, registry=registry, audit=audit)

    assert _search({"query": "x", "role_key": ROLE_KEY, "tenant_id": "t-other"}).status_code == 422
    assert _search({"query": "x", "role_key": ROLE_KEY, "knowledge_base_ids": [KB]}).status_code == 422
    assert upstream.requests == []


def test_non_admin_403_and_no_upstream(monkeypatch, governance, registry, audit) -> None:
    """仅 super_admin 可调（反假锚点：去掉管理闸门 ⇒ 本用例必红）。"""
    _bind_role(registry)
    _publish(governance, "doc-pub")
    upstream = _wire(monkeypatch, governance=governance, registry=registry, audit=audit)

    response = _search({"query": "报销流程", "role_key": ROLE_KEY}, headers=headers(role="employee"))

    assert response.status_code == 403
    assert upstream.requests == []


def test_missing_identity_401() -> None:
    """无身份 ⇒ 401（不进入任何业务分支）。"""
    assert client.post("/api/v1/knowledge/search", json={"query": "x", "role_key": ROLE_KEY}).status_code == 401


def test_cross_tenant_binding_returns_empty(monkeypatch, governance, registry, audit) -> None:
    """跨租户：绑定在 t-search 下，换租户请求 ⇒ 空结果且不请求上游（不泄露存在性）。"""
    _bind_role(registry)
    _publish(governance, "doc-pub")
    upstream = _wire(monkeypatch, governance=governance, registry=registry, audit=audit)

    response = _search(
        {"query": "报销流程", "role_key": ROLE_KEY}, headers=headers(tenant_id="t-other")
    )

    assert response.status_code == 200
    assert response.json() == {
        "items": [],
        "total": 0,
        "limit": 10,
        "truncated": False,
        "reason": "no_binding",
    }
    assert upstream.requests == []


def test_weknora_unconfigured_503(monkeypatch, governance, registry, audit) -> None:
    """未配置 WeKnora ⇒ 503（治理开启不等于检索可用；不返回空结果以免被读成「没查到」）。"""
    _bind_role(registry)
    _publish(governance, "doc-pub")
    _wire(monkeypatch, governance=governance, registry=registry, audit=audit)
    monkeypatch.setattr(main, "weknora_search_runtime", None)

    response = _search({"query": "报销流程", "role_key": ROLE_KEY})

    assert response.status_code == 503
    assert "weknora" not in response.text.lower()


def test_guard_disabled_503(monkeypatch, governance, registry, audit) -> None:
    """治理开关关闭 ⇒ 503（不提供「无守卫的检索入口」，避免造旁路）。"""
    _bind_role(registry)
    _publish(governance, "doc-pub")
    upstream = _wire(monkeypatch, governance=governance, registry=registry, audit=audit, enabled=False)

    response = _search({"query": "报销流程", "role_key": ROLE_KEY})

    assert response.status_code == 503
    assert upstream.requests == []


def test_upstream_timeout_504(monkeypatch, governance, registry, audit) -> None:
    """上游超时 ⇒ 504，且响应体**不回显**上游地址/密钥（只进日志）。"""
    _bind_role(registry)
    _publish(governance, "doc-pub")
    _wire(
        monkeypatch,
        governance=governance,
        registry=registry,
        audit=audit,
        upstream=_Upstream(timeout=True),
    )

    response = _search({"query": "报销流程", "role_key": ROLE_KEY})

    assert response.status_code == 504
    assert "weknora.internal" not in response.text and "sk-test-key" not in response.text


def test_upstream_failure_502(monkeypatch, governance, registry, audit) -> None:
    """上游非 2xx 或 `success:false` ⇒ 502（不得吞异常返回空结果）。"""
    _bind_role(registry)
    _publish(governance, "doc-pub")
    _wire(monkeypatch, governance=governance, registry=registry, audit=audit, upstream=_Upstream(status=500))
    assert _search({"query": "报销流程", "role_key": ROLE_KEY}).status_code == 502

    _wire(monkeypatch, governance=governance, registry=registry, audit=audit, upstream=_Upstream(success=False))
    response = _search({"query": "报销流程", "role_key": ROLE_KEY})
    assert response.status_code == 502
    assert "weknora.internal" not in response.text and "sk-test-key" not in response.text


def test_blocked_audit_never_records_query_text(monkeypatch, governance, registry, audit) -> None:
    """拦截审计只记受控字段（role_key / reason），**绝不记 query 正文**。"""
    _bind_role(registry)
    secret_query = "员工张三的手机号是 13800000000"
    _wire(monkeypatch, governance=governance, registry=registry, audit=audit)

    _search({"query": secret_query, "role_key": ROLE_KEY})

    records = _blocked_records(audit)
    assert len(records) == 1
    detail = records[0].detail
    assert "query" not in detail
    assert secret_query not in json.dumps(detail, ensure_ascii=False)


# ------------------------------------------------------------ 配置装配（启动期 fail-closed）

def test_half_configured_runtime_fails_at_startup() -> None:
    """只配一半（有 url 无 key / 反之）⇒ **启动即失败**；两者皆空 ⇒ 返回 None（端点 503）。"""
    from app.bootstrap import build_weknora_search_runtime
    from app.settings import Settings

    assert build_weknora_search_runtime(Settings()) is None
    with pytest.raises(ValueError):
        build_weknora_search_runtime(Settings(WEKNORA_BASE_URL="https://weknora.internal"))
    with pytest.raises(ValueError):
        build_weknora_search_runtime(Settings(WEKNORA_API_KEY="sk-x"))

    runtime = build_weknora_search_runtime(
        Settings(WEKNORA_BASE_URL="https://weknora.internal", WEKNORA_API_KEY="sk-x")
    )
    assert runtime is not None and runtime.base_url == "https://weknora.internal"
    runtime.client.close()