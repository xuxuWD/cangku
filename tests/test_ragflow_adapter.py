from datetime import UTC, datetime, timedelta

import pytest

from app.runtime.adapters import FakeTransport, RAGFlowAdapter, TransportError
from app.runtime.contracts import RuntimeContext


def make_context(*, knowledge_scope: tuple[str, ...] = ("kb-1",)) -> RuntimeContext:
    return RuntimeContext(
        tenant_id="t1",
        user_id="u1",
        role_key="role",
        mode="product_manager",
        project_id="p1",
        task_id="task-1",
        device_id="device-1",
        knowledge_scope=knowledge_scope,
        file_scope=("D:/staging/project-1",),
        budget_cents=100,
        risk_level="low",
        policy_version="policy-1",
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )


def test_search_sends_context_scope_and_maps_citations() -> None:
    transport = FakeTransport(
        knowledge_items=[
            {
                "document_id": "doc-1",
                "knowledge_base_id": "kb-1",
                "title": "手册",
                "snippet": "先断电。",
                "score": 0.8,
            }
        ]
    )
    citations = RAGFlowAdapter(transport, "https://ragflow").search(
        context=make_context(knowledge_scope=("kb-1",)), query="设备故障", limit=5
    )
    assert citations[0].document_id == "doc-1"
    assert transport.requests[-1]["tenant_id"] == "t1"
    assert transport.requests[-1]["knowledge_base_ids"] == ["kb-1"]
    assert transport.requests[-1]["action"] == "knowledge_search"
    assert transport.requests[-1]["endpoint"] == "https://ragflow"


@pytest.mark.parametrize("query", ["", "x" * 2001])
def test_search_rejects_invalid_query(query: str) -> None:
    with pytest.raises(ValueError):
        RAGFlowAdapter(FakeTransport(), "https://ragflow").search(
            context=make_context(), query=query
        )


@pytest.mark.parametrize("limit", [0, 51, True, 1.5])
def test_search_rejects_invalid_limit(limit: object) -> None:
    with pytest.raises(ValueError):
        RAGFlowAdapter(FakeTransport(), "https://ragflow").search(
            context=make_context(), query="查询", limit=limit  # type: ignore[arg-type]
        )


def test_search_returns_empty_for_empty_knowledge_scope() -> None:
    transport = FakeTransport(knowledge_items=[{"document_id": "wrong"}])
    result = RAGFlowAdapter(transport, "https://ragflow").search(
        context=make_context(knowledge_scope=()), query="查询"
    )
    assert result == []
    assert transport.requests == []


def test_search_rejects_missing_reference_fields() -> None:
    transport = FakeTransport(
        knowledge_items=[{"document_id": "doc-1", "knowledge_base_id": "kb-1"}]
    )
    with pytest.raises(TransportError, match="引用"):
        RAGFlowAdapter(transport, "https://ragflow").search(
            context=make_context(), query="查询"
        )


def test_search_rejects_cross_tenant_or_out_of_scope_items_without_partial_results() -> None:
    transport = FakeTransport(
        knowledge_items=[
            {
                "tenant_id": "other",
                "document_id": "doc-1",
                "knowledge_base_id": "kb-1",
                "title": "手册",
                "snippet": "内容",
            }
        ]
    )
    with pytest.raises(TransportError, match="范围"):
        RAGFlowAdapter(transport, "https://ragflow").search(context=make_context(), query="查询")


def test_search_rejects_out_of_scope_knowledge_base() -> None:
    transport = FakeTransport(
        knowledge_items=[
            {
                "document_id": "doc-1",
                "knowledge_base_id": "kb-other",
                "title": "手册",
                "snippet": "内容",
            }
        ]
    )
    with pytest.raises(TransportError, match="范围"):
        RAGFlowAdapter(transport, "https://ragflow").search(
            context=make_context(), query="查询"
        )


def test_search_rejects_invalid_response_shape_and_score() -> None:
    transport = FakeTransport(knowledge_items=[])
    for response in (None, [], "bad", {"items": "bad"}):
        transport.knowledge_search = lambda _endpoint, _payload, response=response: response  # type: ignore[method-assign]
        with pytest.raises(TransportError, match="响应格式"):
            RAGFlowAdapter(transport, "https://ragflow").search(
                context=make_context(), query="查询"
            )

    transport.knowledge_search = lambda _endpoint, _payload: {
        "items": [
            {
                "document_id": "doc-1",
                "knowledge_base_id": "kb-1",
                "title": "手册",
                "snippet": "内容",
                "score": "bad",
            }
        ]
    }  # type: ignore[method-assign]
    with pytest.raises(TransportError, match="分数"):
        RAGFlowAdapter(transport, "https://ragflow").search(
            context=make_context(), query="查询"
        )

    transport.knowledge_search = lambda _endpoint, _payload: {
        "items": [
            {
                "document_id": "doc-1",
                "knowledge_base_id": "kb-1",
                "title": "手册",
                "snippet": "内容",
                "score": True,
            }
        ]
    }  # type: ignore[method-assign]
    with pytest.raises(TransportError, match="分数"):
        RAGFlowAdapter(transport, "https://ragflow").search(
            context=make_context(), query="查询"
        )


def test_ragflow_adapter_exposes_read_only_search_only() -> None:
    adapter = RAGFlowAdapter(FakeTransport(), "https://ragflow")
    assert hasattr(adapter, "search")
    assert not hasattr(adapter, "write")
    assert not hasattr(adapter, "delete")
    assert not hasattr(adapter, "index")
