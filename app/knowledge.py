from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
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


@dataclass(frozen=True)
class KnowledgeDocument:
    document_id: str
    knowledge_base_id: str
    title: str
    parse_status: str
    enable_status: str
    updated_at: datetime | None


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
        knowledge_ids: Iterable[str] | None = None,
    ) -> list[KnowledgeCitation]:
        requested = list(dict.fromkeys(knowledge_base_ids))
        if context.tenant_id != self.tenant_id:
            raise PolicyError("知识库租户范围不匹配")
        if not query.strip():
            raise PolicyError("知识库搜索内容不能为空")
        if not requested or not set(requested).issubset(self.knowledge_base_ids):
            raise PolicyError("请求的知识库不在当前岗位授权范围内")

        payload: dict[str, object] = {"query": query, "knowledge_base_ids": requested}
        # N2 方案②（2026-09-15 裁决）：文档级白名单作为 `knowledge_ids` 下传给上游
        # （上游文档语义：「进一步限定到指定知识（文件）」）。
        #
        # ⚠️ 真实实例实测（WeKnora v0.8.0 + postgres 检索驱动，2026-09-15）：**只要请求里带了
        # `knowledge_base_ids`（或单数 `knowledge_base_id`），上游就静默忽略 `knowledge_ids`**
        # ——服务端 SQL 里完全没有该谓词，未知 id 也照常返回整库（fail-open，无报错、无降级提示）。
        # 只有「只给 `knowledge_ids`、不给任何 kb 参数」时该过滤才真正下推到 SQL。
        # ⇒ 本参数**保留为前向兼容的下传口**（上游修复后即生效），但**绝不能**因为「已下传」
        # 而放松下游白名单收敛——真实生效的防线是 `scoped_search` 的返回后收敛（①）。
        # 见 `scoped_search.py` 模块 docstring 与规格 §4 N2。
        scoped_knowledge_ids = list(dict.fromkeys(knowledge_ids or []))
        if scoped_knowledge_ids:
            payload["knowledge_ids"] = scoped_knowledge_ids

        response = self.client.post(
            f"{self.base_url}/api/v1/knowledge-search",
            headers={"X-API-Key": self.api_key, "Accept": "application/json"},
            json=payload,
            timeout=self.timeout,
        )
        response.raise_for_status()
        body = response.json()
        if body.get("success") is False:
            raise RuntimeError("WeKnora 知识检索未完成")
        return [
            KnowledgeCitation(
                citation_id=str(item["id"]),
                content=str(item.get("content") or ""),
                source_title=str(item.get("knowledge_title") or item.get("knowledge_filename") or "未命名来源"),
                knowledge_id=str(item.get("knowledge_id") or ""),
                score=float(item["score"]) if item.get("score") is not None else None,
            )
            for item in body.get("data", [])
        ]

    def search_for_role(self, context: UserContext, role_key: str, query: str, registry) -> list[KnowledgeCitation]:
        knowledge_base_ids = registry.resolve(context, role_key)
        if not knowledge_base_ids:
            return []
        return self.search(context, query, sorted(knowledge_base_ids))

    def read_document(self, context: UserContext, knowledge_id: str) -> KnowledgeDocument:
        if context.tenant_id != self.tenant_id:
            raise PolicyError("知识库租户范围不匹配")
        if not knowledge_id.strip():
            raise PolicyError("文档标识不能为空")
        response = self.client.get(
            f"{self.base_url}/api/v1/knowledge/{knowledge_id}",
            headers={"X-API-Key": self.api_key, "Accept": "application/json"},
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        item = payload.get("data") or {}
        if payload.get("success") is False:
            raise RuntimeError("WeKnora 文档读取未完成")
        if str(item.get("tenant_id")) != self.tenant_id:
            raise PolicyError("文档租户范围不匹配")
        knowledge_base_id = str(item.get("knowledge_base_id") or "")
        if knowledge_base_id not in self.knowledge_base_ids:
            raise PolicyError("文档所属知识库不在当前岗位授权范围内")
        updated_at = item.get("updated_at")
        if updated_at is not None and not isinstance(updated_at, datetime):
            updated_at = datetime.fromisoformat(str(updated_at))
        return KnowledgeDocument(
            document_id=str(item.get("id") or knowledge_id),
            knowledge_base_id=knowledge_base_id,
            title=str(item.get("title") or item.get("file_name") or "未命名文档"),
            parse_status=str(item.get("parse_status") or "unknown"),
            enable_status=str(item.get("enable_status") or "unknown"),
            updated_at=updated_at,
        )
