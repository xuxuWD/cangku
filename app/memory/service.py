"""记忆服务层：书写 / 检索 / 画像业务逻辑 + 成本熔断 + 审计。

口径见 `docs/superpowers/specs/2026-09-15-memory-layer-p3-design.md` §2。
职责边界：服务端解析作用域（§2.3，客户端传的 scope 一律忽略并重算）、Embedding 编码、
每日成本熔断（§2.8，本期仅 create path 检查）、审计落点。仓储层的归属校验同样保留
（双保险，与对话层一致）。

⚠️ 动作码（"memory.fact.created" 等）与明细键（memory_id / scope / owner_kind / rule_key / version）
已由主代理加入 `app/audit/models.py` 的 `AuditAction` 与 `ALLOWED_DETAIL_KEYS`，本模块经 `AuditAction` 枚举引用。
"""

from __future__ import annotations

from ..audit.models import AuditAction
from ..domain import UserContext
from .embedding import EmbeddingAdapter, EmbeddingUnavailable
from .models import (
    EMBEDDING_DIMENSIONS,
    MemoryBudgetExceeded,
    MemoryFact,
    MemoryRule,
    MemoryScope,
    ensure_can_manage,
    normalize_owner_kind,
    normalize_scope,
)
from .store import MemoryStore

# 每日成本熔断动作码前缀（本模块审计使用）。
_FACT_CREATED = AuditAction.MEMORY_FACT_CREATED
_FACT_SUPERSEDED = AuditAction.MEMORY_FACT_SUPERSEDED
_RULE_CREATED = AuditAction.MEMORY_RULE_CREATED
_PROFILE_UPDATED = AuditAction.MEMORY_PROFILE_UPDATED


class MemoryService:
    def __init__(
        self,
        store: MemoryStore,
        embedding: EmbeddingAdapter,
        *,
        audit=None,
        daily_budget_cents: int = 0,
    ) -> None:
        self.store = store
        self.embedding = embedding
        self.audit = audit
        self.daily_budget_cents = daily_budget_cents
        # §2.9.3：本期在服务启动期内按调用近似累计；生产真实口径走「用量账本」（整数分），
        # 未接线时以本实例累计作为每日预算闸门。
        self._accrued_cents = 0

    # ------------------------------------------------------------ 成本熔断（§2.8）

    def _check_budget(self) -> None:
        """每日预算闸门：`daily_budget_cents` ≤ 0 表示不设限；已超则抛 429。"""
        if self.daily_budget_cents > 0 and self._accrued_cents >= self.daily_budget_cents:
            raise MemoryBudgetExceeded("今日记忆写入成本已超过每日预算")

    # ------------------------------------------------------------ 事实类

    def create_fact(
        self,
        context: UserContext,
        *,
        content: str,
        scope,
        owner_kind: str = "user",
        owner_id: str | None = None,
        idempotency_key: str,
    ) -> MemoryFact:
        """书写事实类记忆：归属校验 → 预算闸门 → Embedding 编码 → 落库 → 审计。

        服务端校验 scope 必须为合法枚举（§2.3），客户端传非法枚举 → 422。
        Embedding 失败抛 `EmbeddingUnavailable`（502，fail-closed，§2.5）。
        """
        kind = normalize_owner_kind(owner_kind)
        target_owner = owner_id or context.user_id
        ensure_can_manage(context, kind, target_owner)
        # 预算检查（本期仅 create path，§2.9.3）。
        self._check_budget()
        # 作用域合法性校验：非法枚举在此抛 InvalidMemory（422）。
        clean_scope = normalize_scope(scope)
        vector = tuple(self.embedding.embed(content))
        # 维度复核（fail-closed，§2.2/§3.3 反假）：任何实现返回非 1024 维一律拒绝写入，
        # 防止换 adapter 后「维度写死 1024」的表结构被悄悄破坏。
        if len(vector) != EMBEDDING_DIMENSIONS:
            raise EmbeddingUnavailable(
                f"Embedding 返回维度 {len(vector)}，期望 {EMBEDDING_DIMENSIONS}（fail-closed，拒绝写入）"
            )
        fact = self.store.create_fact(
            context,
            content=content,
            scope=clean_scope,
            owner_kind=kind,
            owner_id=target_owner,
            idempotency_key=idempotency_key,
            embedding=vector,
        )
        self._accrued_cents += 1
        self._record(
            context,
            _FACT_CREATED,
            fact.memory_id,
            {"memory_id": fact.memory_id, "scope": fact.scope.value, "owner_kind": fact.owner_kind.value},
        )
        return fact

    def supersede_fact(self, context: UserContext, memory_id: str) -> MemoryFact:
        """作废事实类记忆（supersede 链）；本人或 admin，他人 → 404。"""
        fact = self.store.supersede_fact(context, memory_id)
        self._record(
            context,
            _FACT_SUPERSEDED,
            fact.memory_id,
            {"memory_id": fact.memory_id, "scope": fact.scope.value, "owner_kind": fact.owner_kind.value},
        )
        return fact

    def list_facts(
        self,
        context: UserContext,
        *,
        owner_kind: str = "user",
        owner_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[MemoryFact], int]:
        return self.store.list_facts(
            context, owner_kind=owner_kind, owner_id=owner_id, limit=limit, offset=offset
        )

    def search_facts(
        self, context: UserContext, *, query: str, scope=None, limit: int = 20
    ) -> list[MemoryFact]:
        """语义检索：Embedding 编码 query → 向量 KNN（§2.6）。

        §2.3 / §2.6：客户端传入的 `scope` **一律忽略并重算**（不调用 normalize_scope，
        避免以客户端值兜底）；本阶段服务端解析结果固定为 user 档（本人）。
        """
        resolved_scope = MemoryScope.USER
        query_embedding = tuple(self.embedding.embed(query))
        return self.store.search_facts(context, query_embedding, scope=resolved_scope, limit=limit)

    # ------------------------------------------------------------ 规则类

    def create_rule(
        self,
        context: UserContext,
        *,
        rule_key: str,
        content: str,
        scope,
        owner_kind: str,
        owner_id: str,
    ) -> MemoryRule:
        """书写规则类记忆：同一 (owner, rule_key) 已有 active → supersede 旧版并 version+1（版本快照 §2.4）。"""
        clean_scope = normalize_scope(scope)
        rule = self.store.create_rule(
            context,
            rule_key=rule_key,
            content=content,
            scope=clean_scope,
            owner_kind=owner_kind,
            owner_id=owner_id,
        )
        self._record(
            context,
            _RULE_CREATED,
            rule.memory_id,
            {"rule_key": rule.rule_key, "version": rule.version, "scope": rule.scope.value, "owner_kind": rule.owner_kind.value},
        )
        return rule

    # ------------------------------------------------------------ 身份类画像

    def set_profile_key(
        self,
        context: UserContext,
        *,
        key: str,
        value: str,
        owner_kind: str = "user",
        owner_id: str | None = None,
    ) -> None:
        """覆写画像键（§2.4 身份类人工覆写同键直接更新，记审计）。"""
        self.store.set_profile_key(
            context, key=key, value=value, owner_kind=owner_kind, owner_id=owner_id
        )
        self._record(context, _PROFILE_UPDATED, key, {"scope": "profile", "owner_kind": owner_kind})

    def get_profile(
        self,
        context: UserContext,
        *,
        owner_kind: str = "user",
        owner_id: str | None = None,
    ) -> dict[str, str]:
        """读取画像（KV，不进向量检索）；本人或 VIEW_ANY。"""
        return self.store.get_profile(context, owner_kind=owner_kind, owner_id=owner_id)

    # ------------------------------------------------------------ 内部

    def _record(self, context: UserContext, action: AuditAction, target_id: str, detail: dict[str, object]) -> None:
        if self.audit is None:
            return
        self.audit.record(
            action,
            tenant_id=context.tenant_id,
            actor_id=context.user_id,
            target_type="memory",
            target_id=target_id,
            detail=detail,
        )