from __future__ import annotations

from typing import Any

from ..contracts import KnowledgeCitation, RuntimeContext
from .common import TransportError


class RAGFlowAdapter:
    """Read-only adapter for scoped RAGFlow knowledge retrieval."""

    def __init__(self, transport: Any, endpoint: str) -> None:
        self.transport = transport
        self.endpoint = endpoint

    def search(
        self,
        *,
        context: RuntimeContext,
        query: str,
        limit: int = 10,
    ) -> list[KnowledgeCitation]:
        if not isinstance(query, str) or not 1 <= len(query) <= 2000:
            raise ValueError("查询长度必须在 1 到 2000 个字符之间")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 50:
            raise ValueError("检索条数必须在 1 到 50 之间")
        if not context.knowledge_scope:
            return []

        payload = {
            "tenant_id": context.tenant_id,
            "knowledge_base_ids": list(context.knowledge_scope),
            "query": query,
            "limit": limit,
        }
        data = self.transport.knowledge_search(self.endpoint, payload)
        if not isinstance(data, dict):
            raise TransportError("RAGFlow 引用响应格式无效")
        items = data.get("items")
        if not isinstance(items, list):
            raise TransportError("RAGFlow 引用响应格式无效")

        citations: list[KnowledgeCitation] = []
        for item in items:
            if not isinstance(item, dict):
                raise TransportError("RAGFlow 引用响应格式无效")
            if item.get("tenant_id", context.tenant_id) != context.tenant_id:
                raise TransportError("RAGFlow 返回结果超出租户范围")

            document_id = item.get("document_id")
            knowledge_base_id = item.get("knowledge_base_id")
            title = item.get("title")
            snippet = item.get("snippet")
            if not all(
                isinstance(value, str) and value
                for value in (document_id, knowledge_base_id, title, snippet)
            ):
                raise TransportError("RAGFlow 引用字段缺失")
            if knowledge_base_id not in context.knowledge_scope:
                raise TransportError("RAGFlow 返回结果超出知识库范围")

            score = item.get("score")
            if score is not None and (
                isinstance(score, bool) or not isinstance(score, (int, float))
            ):
                raise TransportError("RAGFlow 引用分数格式无效")
            citations.append(
                KnowledgeCitation(
                    document_id=document_id,
                    knowledge_base_id=knowledge_base_id,
                    title=title,
                    snippet=snippet,
                    score=score,
                )
            )
        return citations
