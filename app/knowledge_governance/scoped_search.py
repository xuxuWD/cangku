"""检索谓词守卫组合件：`scoped_search`（规格 §2.3 / §6.4 硬要求）。

把「检索请求 WeKnora 前先做文档级 pre-filter」封装成一个可测组合件：

1. 由 `KnowledgeAccessRegistry.resolve` 得到 **knowledge_base_ids**（既有，租户内绑定）；
2. 由治理服务取该租户 **`status='published'` 且未过 `review_due_at`** 的文档集（pre-filter
   白名单，`list_published_eligible`）；
3. **白名单为空 → fail-closed**：直接返回空结果，**不请求 WeKnora**（§6.4「未登记视为
   不受控」，未登记 / 全部下线的文档绝不泄露到检索请求）；
4. 白名单非空 → 调用 WeKnora 时把白名单作为 **`knowledge_ids` 下传**（**N2 方案②**），
   返回后**仍按白名单收敛一遍**（纵深兜底）。

⚠️ N2 落点（规格 §4，2026-09-15 裁决改方案②；同日以**真实 WeKnora 实例**实测校正）：

- 上游 `POST /api/v1/knowledge-search` **确实有** `knowledge_ids` 参数（文档：「进一步限定到
  指定知识（文件）」），但**实测（WeKnora v0.8.0 + postgres 检索驱动）**：
  **只要请求同时带了 `knowledge_base_ids`（或单数 `knowledge_base_id`），上游就静默忽略
  `knowledge_ids`**——服务端 SQL 里完全没有该谓词，连「不存在的文档 id」也照常返回整库
  （fail-open，无报错、无降级提示）。只有「只给 `knowledge_ids`、不给任何 kb 参数」时过滤
  才真正下推（此时上游按文档反解出 kb 谓词）。
- ⇒ 因此本组合件的定位是：**② 下传保留（前向兼容，上游修复后自动生效）**，而
  **① 返回后收敛是当前真实生效的那道防线，属于必需而非可选**——绝不因「已下传」而放松。
  这也是「下游收敛」不能删的原因：若只保留②，在上游 v0.8.0 上未发布文档会被照常召回。
- 空白名单**绝不下传空数组**（语义不可靠），此时路径已在第 3 步短路。

不出网：本模块只依赖协议（`adapter.search` / `registry.resolve`），不 import WeKnora 适配器，
避免知识治理层反向依赖检索实现（治理层是守卫，不是第二个真源，规格 §5 风险 3）。
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from ..domain import UserContext


class SearchAdapter(Protocol):
    """检索适配器的最小接口面（`WeKnoraKnowledgeAdapter` 满足）。

    `knowledge_ids` 为**可选**文档级白名单下传口（N2 方案②）：治理层传白名单，
    未传时保持既有整库检索行为（治理关闭态 / 旧调用方）。
    """

    def search(
        self,
        context: UserContext,
        query: str,
        knowledge_base_ids: Iterable[str],
        knowledge_ids: Iterable[str] | None = None,
    ):
        ...


class BindingRegistry(Protocol):
    """知识库绑定注册表（KnowledgeAccessRegistry 满足）。"""

    def resolve(self, context: UserContext, role_key: str) -> set[str]:
        ...


def build_scoped_search(
    *,
    governance,
    registry: BindingRegistry,
    adapter: SearchAdapter,
    enabled: bool,
    document_filter=None,
    review_state_fn=None,
):
    """构造 `scoped_search(context, role_key, query)` 检索入口。

    `enabled=False`（总开关默认 false，fail-closed）时跳过文档级过滤，保持既有行为（也**不下传**
    白名单）；`enabled=True` 时把白名单作为 `knowledge_ids` **下传**（N2 方案②），返回后再按
    白名单收敛一遍：`document_filter(citations, whitelist_ids)` 默认按
    `citation.knowledge_id ∈ 白名单` 收敛（纵深兜底，可注入替换）。

    §2.5 过期提示：命中引用的 `review_status` 由**端点序列化层**按 `review_state_fn(document_id)`
    查询后并入引用视图（`review_state_fn` 默认 None = 不附加）。预过滤只放行 published，
    needs_review 文档不进白名单，该字段仅在并发窗口期（检索后 / 收敛前状态被置 needs_review）
    可能出现，且**不改引用正文**（规格红线 3）。
    """
    if not enabled:

        def scoped(context: UserContext, role_key: str, query: str):
            knowledge_base_ids = registry.resolve(context, role_key)
            if not knowledge_base_ids:
                return []
            return adapter.search(context, query, sorted(knowledge_base_ids))

        return scoped

    def _default_filter(citations, whitelist_ids):
        return [c for c in citations if c.knowledge_id in whitelist_ids]

    filter_fn = document_filter or _default_filter

    def scoped(context: UserContext, role_key: str, query: str):
        knowledge_base_ids = registry.resolve(context, role_key)
        if not knowledge_base_ids:
            return []
        whitelist = governance.list_published_eligible(context)
        whitelist_ids = {doc.document_id for doc in whitelist}
        if not whitelist_ids:
            return []  # fail-closed：白名单空，不请求 WeKnora（§6.4）
        # N2 方案②：白名单**下传**到上游检索语义内（不是只在返回后裁剪）。
        citations = adapter.search(
            context, query, sorted(knowledge_base_ids), knowledge_ids=sorted(whitelist_ids)
        )
        return filter_fn(citations, whitelist_ids)  # 纵深兜底：上游忽略过滤时仍收敛

    return scoped