"""检索谓词守卫组合件：`scoped_search`（规格 §2.3 / §6.4 硬要求）。

把「检索请求 WeKnora 前先做文档级 pre-filter」封装成一个可测组合件：

1. 由 `KnowledgeAccessRegistry.resolve` 得到 **knowledge_base_ids**（既有，租户内绑定）；
2. 由治理服务取该租户 **`status='published'` 且未过 `review_due_at`** 的文档集（pre-filter
   白名单，`list_published_eligible`）；
3. **白名单为空 → fail-closed**：直接返回空结果，**不请求 WeKnora**（§6.4「未登记视为
   不受控」，未登记 / 全部下线的文档绝不泄露到检索请求）；
4. 白名单非空 → 调用 WeKnora，返回后按文档白名单**收敛结果**（N2 方案①）。

⚠️ N2 落点说明（规格 §4）：WeKnora 检索是**知识库级**（只传 `knowledge_base_ids`，没有
文档级过滤参数），因此文档级过滤在**返回后收敛**是「接口面限制的兜底，不是设计偏好」。
代码上把「可下传文档级白名单」抽象成一个 `document_filter` 注入点：上游一旦支持文档级
参数，只替换注入函数即可，谓词守卫的语义（未发布 / 过期不再可见）保持恒定。

不出网：本模块只依赖协议（`adapter.search` / `registry.resolve`），不 import WeKnora 适配器，
避免知识治理层反向依赖检索实现（治理层是守卫，不是第二个真源，规格 §5 风险 3）。
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from ..domain import UserContext


class SearchAdapter(Protocol):
    """检索适配器的最小接口面（WeKnoraKnowledgeAdapter 满足）。"""

    def search(self, context: UserContext, query: str, knowledge_base_ids: Iterable[str]):
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

    `enabled=False`（总开关默认 false，fail-closed）时跳过文档级过滤，保持既有行为；
    `document_filter(citations, whitelist_ids)` 默认按 `citation.knowledge_id ∈ 白名单` 收敛
    （N2 方案①：返回后收敛，接口面限制的兜底）。

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
        citations = adapter.search(context, query, sorted(knowledge_base_ids))
        return filter_fn(citations, whitelist_ids)

    return scoped