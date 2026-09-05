from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import httpx

from .domain import PolicyError, UserContext


@dataclass(frozen=True)
class KnowledgeCitation:
    citation_id: str
    content: str
    source_title: str
    knowledge_id: str
    score: float | None = None


class WeKnoraKnowledgeAdapter:
    """Read-only WeKnora bridge with tenant and knowledge-base scoping."""

    def __init__(
        self,
        *,
        tenant_id: str,
        api_key: str,
        knowledge_base_ids: Iterable[str],
        base_url: str,
        client: httpx.Client | None = None,
        timeout: float = 30.0,
    ) -> None:
        if not api_key:
            raise ValueError("WeKnora API Key 不能为空")
        self.tenant_id = tenant_id
        self.api_key = api_key
        self.knowledge_base_ids = frozenset(knowledge_base_ids)
        self.base_url = base_url.rstrip("/")
        self.client = client or httpx.Client(timeout=timeout)
        self.timeout = timeout

    def search(
        self,
        context: UserContext,
        query: str,
        knowledge_base_ids: Iterable[str],
    ) -> list[KnowledgeCitation]:
        requested = list(dict.fromkeys(knowledge_base_ids))
        if context.tenant_id != self.tenant_id:
            raise PolicyError("知识库租户范围不匹配")
        if not query.strip():
            raise PolicyError("知识库搜索内容不能为空")
        if not requested or not set(requested).issubset(self.knowledge_base_ids):
            raise PolicyError("请求的知识库不在当前岗位授权范围内")

        response = self.client.post(
            f"{self.base_url}/api/v1/knowledge-search",
            headers={"X-API-Key": self.api_key, "Accept": "application/json"},
            json={"query": query, "knowledge_base_ids": requested},
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("success") is False:
            raise RuntimeError("WeKnora 知识检索未完成")
        return [
            KnowledgeCitation(
                citation_id=str(item["id"]),
                content=str(item.get("content") or ""),
                source_title=str(item.get("knowledge_title") or item.get("knowledge_filename") or "未命名来源"),
                knowledge_id=str(item.get("knowledge_id") or ""),
                score=float(item["score"]) if item.get("score") is not None else None,
            )
            for item in payload.get("data", [])
        ]
