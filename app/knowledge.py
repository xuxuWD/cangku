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


@dataclass(frozen=True)
class KnowledgeDocumentPage:
    """文档列表的一页（上游 `GET /api/v1/knowledge-bases/{id}/knowledge` 的分页响应）。"""

    items: tuple[KnowledgeDocument, ...]
    page: int
    page_size: int
    total: int


# 上游未声明 `page_size` 上限；这是我方对单页请求量的自我保护上界（不是上游契约）。
MAX_PAGE_SIZE = 200


class UpstreamShapeError(RuntimeError):
    """上游响应形状不符合我方预期（未实调端点的兼容解析失败）⇒ 调用方按**降级**处理，不臆测。"""


@dataclass(frozen=True)
class KnowledgeBaseSummary:
    """上游知识库清单的一项（`GET /api/v1/knowledge-bases`）。

    ⚠️ 该端点**未经实调**（本机无可用上游实例）：元素里知识库标识 / 名称的**确切键名未实测确认**
    ⇒ 解析走多键兼容（见 `KNOWLEDGE_BASE_ID_KEYS` / `KNOWLEDGE_BASE_NAME_KEYS`），不假定单一形状。
    """

    knowledge_base_id: str
    name: str | None = None


# 上游元素字段名的候选键（顺序即优先级）。依据见 `docs/contracts/permissions-fake-entry-plan.md` §7.2：
# 官方文档只确证接口存在与响应是 `{success, data:[…]}`，元素内层键名未实测 ⇒ 多键兼容。
KNOWLEDGE_BASE_ID_KEYS = ("id", "knowledge_base_id", "kb_id")
KNOWLEDGE_BASE_NAME_KEYS = ("name", "title")


def _first_text(item: dict, keys: tuple[str, ...]) -> str:
    """按优先级取第一个非空字符串值（找不到 ⇒ 空串；**不编造**）。"""
    for key in keys:
        value = item.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


class WeKnoraKnowledgeAdapter:
    """Read-only WeKnora bridge with tenant and knowledge-base scoping.

    ⚠️ 租户映射口径（写明以免误用）：`tenant_id` 必须是 **WeKnora 侧的空间标识**，且调用方
    传入的 `UserContext.tenant_id` 必须与之同源（适配器靠二者相等来强制租户隔离）。工作台内部
    租户号与 WeKnora 空间号之间**没有映射表**——混用两套编号会被本适配器判为「租户范围不匹配」。
    """

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
        return self._document_from_item(item, fallback_document_id=knowledge_id)

    def list_documents(
        self,
        context: UserContext,
        knowledge_base_id: str,
        *,
        page: int = 1,
        page_size: int = 20,
        parse_status: str | None = None,
    ) -> KnowledgeDocumentPage:
        """读一个知识库的**文档列表**（分页，只读）。范围校验与检索同口径。

        上游契约（官方 `docs/api/knowledge.md`，2026-09-15 真实实例已实调该端点）：
        路径 `GET /api/v1/knowledge-bases/{id}/knowledge`；查询参数 `page`（从 1 起）、
        `page_size`、`parse_status`（`pending`/`processing`/`completed`/`failed`）等；
        响应 `{"data": [<文档>], "page", "page_size", "total", "success"}`（`data` 为**数组**）。
        用于规格 §4 N1 的存量文档导入：把上游既有文档喂进治理登记（不再依赖人工导出清单）。
        """
        if context.tenant_id != self.tenant_id:
            raise PolicyError("知识库租户范围不匹配")
        if not knowledge_base_id or knowledge_base_id not in self.knowledge_base_ids:
            raise PolicyError("请求的知识库不在当前岗位授权范围内")
        if page < 1:
            raise ValueError("page 必须从 1 开始")
        if not 1 <= page_size <= MAX_PAGE_SIZE:
            raise ValueError(f"page_size 必须在 1 到 {MAX_PAGE_SIZE} 之间")

        params: dict[str, object] = {"page": page, "page_size": page_size}
        if parse_status:
            params["parse_status"] = parse_status
        response = self.client.get(
            f"{self.base_url}/api/v1/knowledge-bases/{knowledge_base_id}/knowledge",
            headers={"X-API-Key": self.api_key, "Accept": "application/json"},
            params=params,
            timeout=self.timeout,
        )
        response.raise_for_status()
        body = response.json()
        if body.get("success") is False:
            # fail-closed：不得把上游失败静默读成「没有存量文档」
            raise RuntimeError("WeKnora 文档列表读取未完成")
        items = tuple(self._document_from_item(item) for item in body.get("data") or [])
        return KnowledgeDocumentPage(
            items=items,
            page=int(body.get("page") or page),
            page_size=int(body.get("page_size") or page_size),
            total=int(body.get("total") or len(items)),
        )

    def list_knowledge_bases(self, context: UserContext) -> tuple[KnowledgeBaseSummary, ...]:
        """读上游**知识库清单**（只读，只发 `GET`）——「权限配置」页候选的唯一真源。

        上游契约（官方 `docs/api/knowledge-base.md`，**未经实调**，见 §7.2）：路径
        `GET /api/v1/knowledge-bases`（"获取知识库列表：返回当前空间拥有的全部知识库"）；
        头 `X-API-Key`；Query 仅 `agent_id`（可选，本轮不传）；响应
        `{"success": true, "data": [<知识库>...]}`，元素字段结构同 `POST /knowledge-bases` 响应。

        **fail-closed**：上游未 2xx / `success:false` / 形状异常（`data` 非数组、元素非对象、元素缺标识）
        一律**抛错**（`httpx.HTTPError` / `RuntimeError`），由调用方降级成"取不到 + 说明原因"；
        **绝不**把上游失败静默读成"没有知识库"（那正是本专项要消掉的谎报）。
        多键兼容解析见 `KNOWLEDGE_BASE_ID_KEYS` / `KNOWLEDGE_BASE_NAME_KEYS`。

        ⚠️ 只读边界：本方法**只发 GET**，不写入、不改上游配置；`api_key` 只进请求头，绝不进返回值。
        """
        if context.tenant_id != self.tenant_id:
            raise PolicyError("知识库租户范围不匹配")
        response = self.client.get(
            f"{self.base_url}/api/v1/knowledge-bases",
            headers={"X-API-Key": self.api_key, "Accept": "application/json"},
            timeout=self.timeout,
        )
        response.raise_for_status()
        body = response.json()
        if body.get("success") is False:
            raise RuntimeError("WeKnora 知识库清单读取未完成")
        data = body.get("data")
        if not isinstance(data, list):
            raise UpstreamShapeError("WeKnora 知识库清单响应形状异常")
        summaries: list[KnowledgeBaseSummary] = []
        for item in data:
            if not isinstance(item, dict):
                raise UpstreamShapeError("WeKnora 知识库清单响应形状异常")
            knowledge_base_id = _first_text(item, KNOWLEDGE_BASE_ID_KEYS)
            if not knowledge_base_id:
                raise UpstreamShapeError("WeKnora 知识库清单响应缺少知识库标识")
            summaries.append(
                KnowledgeBaseSummary(
                    knowledge_base_id=knowledge_base_id,
                    name=_first_text(item, KNOWLEDGE_BASE_NAME_KEYS) or None,
                )
            )
        return tuple(summaries)

    def _document_from_item(self, item: dict, *, fallback_document_id: str = "") -> KnowledgeDocument:
        """把上游文档对象映射成 `KnowledgeDocument`，并**逐条**复验租户与知识库归属。"""
        if str(item.get("tenant_id")) != self.tenant_id:
            raise PolicyError("文档租户范围不匹配")
        knowledge_base_id = str(item.get("knowledge_base_id") or "")
        if knowledge_base_id not in self.knowledge_base_ids:
            raise PolicyError("文档所属知识库不在当前岗位授权范围内")
        updated_at = item.get("updated_at")
        if updated_at is not None and not isinstance(updated_at, datetime):
            updated_at = datetime.fromisoformat(str(updated_at))
        return KnowledgeDocument(
            document_id=str(item.get("id") or fallback_document_id),
            knowledge_base_id=knowledge_base_id,
            title=str(item.get("title") or item.get("file_name") or "未命名文档"),
            parse_status=str(item.get("parse_status") or "unknown"),
            enable_status=str(item.get("enable_status") or "unknown"),
            updated_at=updated_at,
        )


@dataclass(frozen=True)
class WeKnoraSearchRuntime:
    """按租户构造适配器的运行时容器（检索入口用）。

    为什么需要它：`WeKnoraKnowledgeAdapter` 的构造参数含 **`tenant_id` 与「知识库授权集上限」**
    ⇒ 一个实例只能服务**一个租户 + 一组授权范围**，**不能做成全局单例**（多租户会串范围）。
    而 `httpx.Client` 线程安全且自带连接池 ⇒ 这里只共享客户端，**按请求**给适配器：
    「本次调用已解析出的租户 + 授权集」直接作为实例参数，适配器自身的 `⊆` 校验照常生效。

    装配点见 `app/bootstrap.py::build_weknora_search_runtime`（未配置返回 `None`；只配一半启动失败）。
    """

    client: httpx.Client
    base_url: str
    api_key: str
    timeout: float

    def adapter_for(self, *, tenant_id: str, knowledge_base_ids: Iterable[str]) -> WeKnoraKnowledgeAdapter:
        """给「本租户 + 本次已授权的知识库集合」构造适配器（不新增连接、不重读配置）。"""
        return WeKnoraKnowledgeAdapter(
            tenant_id=tenant_id,
            api_key=self.api_key,
            knowledge_base_ids=knowledge_base_ids,
            base_url=self.base_url,
            client=self.client,
            timeout=self.timeout,
        )
