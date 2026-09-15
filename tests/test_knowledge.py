import httpx
import pytest
import json

from app.domain import PolicyError, UserContext
from app.knowledge import WeKnoraKnowledgeAdapter
from app.knowledge_policy import KnowledgeAccessRegistry


def test_weknora_adapter_returns_citations_for_allowed_knowledge_bases() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/knowledge-search"
        assert request.headers["X-API-Key"] == "scoped-key"
        assert json.loads(request.read()) == {"query": "如何报销", "knowledge_base_ids": ["kb-1"]}
        return httpx.Response(
            200,
            json={
                "success": True,
                "data": [
                    {
                        "id": "chunk-1",
                        "content": "报销需要提交发票。",
                        "knowledge_id": "doc-1",
                        "knowledge_title": "财务制度",
                        "knowledge_filename": "finance.md",
                        "score": 0.93,
                    }
                ],
            },
        )

    adapter = WeKnoraKnowledgeAdapter(
        tenant_id="t-1",
        api_key="scoped-key",
        knowledge_base_ids={"kb-1"},
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        base_url="https://weknora.internal",
    )

    result = adapter.search(UserContext("t-1", "u-1", "employee"), "如何报销", ["kb-1"])

    assert result[0].citation_id == "chunk-1"
    assert result[0].content == "报销需要提交发票。"
    assert result[0].source_title == "财务制度"


def test_weknora_adapter_rejects_cross_tenant_or_unknown_knowledge_base() -> None:
    adapter = WeKnoraKnowledgeAdapter(
        tenant_id="t-1",
        api_key="scoped-key",
        knowledge_base_ids={"kb-1"},
        client=httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"data": []}))),
        base_url="https://weknora.internal",
    )

    with pytest.raises(PolicyError):
        adapter.search(UserContext("t-2", "u-1", "employee"), "问题", ["kb-1"])
    with pytest.raises(PolicyError):
        adapter.search(UserContext("t-1", "u-1", "employee"), "问题", ["kb-other"])


def test_weknora_adapter_reads_document_metadata_with_scope_validation() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/knowledge/doc-1"
        return httpx.Response(
            200,
            json={
                "success": True,
                "data": {
                    "id": "doc-1",
                    "tenant_id": "t-1",
                    "knowledge_base_id": "kb-1",
                    "title": "财务制度",
                    "parse_status": "completed",
                    "enable_status": "enabled",
                    "updated_at": "2026-09-05T10:00:00+08:00",
                },
            },
        )

    adapter = WeKnoraKnowledgeAdapter(
        tenant_id="t-1",
        api_key="scoped-key",
        knowledge_base_ids={"kb-1"},
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        base_url="https://weknora.internal",
    )

    document = adapter.read_document(UserContext("t-1", "u-1", "employee"), "doc-1")

    assert document.document_id == "doc-1"
    assert document.knowledge_base_id == "kb-1"
    assert document.title == "财务制度"
    assert document.parse_status == "completed"


def test_weknora_adapter_pushes_knowledge_ids_when_provided() -> None:
    """N2 方案②：显式传入文档级白名单时，作为 `knowledge_ids` 下传（pre-filter 落到上游检索语义内）。"""
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.read()))
        return httpx.Response(200, json={"success": True, "data": []})

    adapter = WeKnoraKnowledgeAdapter(
        tenant_id="t-1",
        api_key="scoped-key",
        knowledge_base_ids={"kb-1"},
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        base_url="https://weknora.internal",
    )

    adapter.search(
        UserContext("t-1", "u-1", "employee"), "如何报销", ["kb-1"], knowledge_ids=["doc-2", "doc-1", "doc-2"]
    )

    # 去重且只下传指定文档；知识库范围仍在（上游要求至少一个 kb 参数）
    assert seen[0]["knowledge_ids"] == ["doc-2", "doc-1"]
    assert seen[0]["knowledge_base_ids"] == ["kb-1"]


def test_weknora_adapter_omits_empty_knowledge_ids() -> None:
    """未传 / 空白名单**不得**下传空数组——空数组的语义在上游不可靠，静默放宽是安全回归。"""
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.read()))
        return httpx.Response(200, json={"success": True, "data": []})

    adapter = WeKnoraKnowledgeAdapter(
        tenant_id="t-1",
        api_key="scoped-key",
        knowledge_base_ids={"kb-1"},
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        base_url="https://weknora.internal",
    )

    context = UserContext("t-1", "u-1", "employee")
    adapter.search(context, "如何报销", ["kb-1"])
    adapter.search(context, "如何报销", ["kb-1"], knowledge_ids=[])

    assert all("knowledge_ids" not in body for body in seen)


def test_weknora_adapter_resolves_scope_from_role_registry() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert json.loads(request.read())["knowledge_base_ids"] == ["kb-1"]
        return httpx.Response(200, json={"success": True, "data": []})

    adapter = WeKnoraKnowledgeAdapter(
        tenant_id="t-1",
        api_key="scoped-key",
        knowledge_base_ids={"kb-1"},
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        base_url="https://weknora.internal",
    )
    registry = KnowledgeAccessRegistry()
    registry.bind_role(UserContext("t-1", "admin", "super_admin"), "content-operator", {"kb-1"})

    assert adapter.search_for_role(UserContext("t-1", "u-1", "employee"), "content-operator", "问题", registry) == []
    assert calls == 1
    assert adapter.search_for_role(UserContext("t-1", "u-1", "employee"), "unknown-role", "问题", registry) == []
    assert calls == 1
