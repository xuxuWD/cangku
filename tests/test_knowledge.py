import httpx
import pytest
import json

from app.domain import PolicyError, UserContext
from app.knowledge import WeKnoraKnowledgeAdapter


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
