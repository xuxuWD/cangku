"""知识治理服务层：登记 / 发布（发布闸门）/ 归档 / 复核 / 到期扫描 + 检索谓词守卫 + 指标 + 审计。

口径见 `docs/superpowers/specs/2026-09-15-knowledge-governance-design.md` §2。
职责边界：发布闸门（§1.2 C，owner 非空 + status 合法）、状态机迁移（`transition_allowed`）、
检索谓词守卫白名单（§2.3 pre-filter）、Freshness 指标（§2.4）、审计落点。
仓储层的租户隔离保留（双保险，与记忆 / 技能层一致）；管理动作统一走 `ensure_can_manage`，
读指标走 `ensure_can_read_metrics`（均仅 super_admin）。

⚠️ 动作码（"knowledge.doc.registered" / "knowledge.doc.published" /
"knowledge.doc.archived" / "knowledge.doc.reviewed" / "knowledge.doc.review_due"）
与明细键（document_id / title / status / owner_id / version / source_key）
须已由主代理加入 `app/audit/models.py` 的 `AuditAction` 与 `ALLOWED_DETAIL_KEYS`；
本模块刻意**不 import `AuditAction` 枚举**，直接写字符串字面量，`audit.record` 按枚举/字符串兼容。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from ..audit.models import AuditAction
from ..domain import PolicyError, UserContext
from .models import (
    InvalidKnowledgeDoc,
    KnowledgeDoc,
    KnowledgeDocStatus,
    KnowledgeDocStateConflict,
    ensure_can_manage,
    ensure_can_read_metrics,
    normalize_document_id,
    normalize_owner_id,
    normalize_source_key,
    normalize_title,
    normalize_version,
    transition_allowed,
)
from .store import KnowledgeGovStore

# 审计动作码（枚举成员；须已在 AuditAction 注册，见 app/audit/models.py §2.7）。
_ACTION_REGISTERED = AuditAction.KNOWLEDGE_DOC_REGISTERED
_ACTION_PUBLISHED = AuditAction.KNOWLEDGE_DOC_PUBLISHED
_ACTION_ARCHIVED = AuditAction.KNOWLEDGE_DOC_ARCHIVED
_ACTION_REVIEWED = AuditAction.KNOWLEDGE_DOC_REVIEWED
_ACTION_REVIEW_DUE = AuditAction.KNOWLEDGE_DOC_REVIEW_DUE

# worker 系统路径的操作者标识（beat 任务没有用户；审计按租户逐条写，actor 恒为它）。
# 刻意**不**伪装成超级管理员：该上下文只用于租户作用域与审计记录，若被误用到权限判定路径
# 会直接 fail-closed（"system" 不在 MANAGE_ROLES）。
SYSTEM_ACTOR_ID = "system:worker"
SYSTEM_ROLE = "system"


def _utcnow() -> datetime:
    return datetime.now(UTC)


class KnowledgeGovernanceService:
    """知识治理层领域核心的编排入口；审计缺省跳过（audit=None）。"""

    def __init__(
        self,
        store: KnowledgeGovStore,
        *,
        audit=None,
        review_grace_days: int = 30,
    ) -> None:
        self.store = store
        self.audit = audit
        # 复核通过刷新 review_due_at 的宽限天数（§2.6 WORKBENCH_KNOWLEDGE_REVIEW_GRACE_DAYS，默认 30）。
        self.review_grace_days = int(review_grace_days)

    # ------------------------------------------------------------ 生命周期

    def register_document(
        self,
        context: UserContext,
        *,
        document_id: str,
        title: str = "",
        owner_id: str = "",
        version: str = "1",
        source_key: str = "manual",
    ) -> KnowledgeDoc:
        """登记文档：管理动作 → 字段归一 → status=draft 入注册表 → 审计。

        §3.1 正常流程 1：登记即 `draft`，owner 此刻可空（发布闸门在发布时才强制）。
        """
        ensure_can_manage(context)
        clean = KnowledgeDoc(
            tenant_id=context.tenant_id,
            document_id=normalize_document_id(document_id),
            title=normalize_title(title),
            owner_id=normalize_owner_id(owner_id),
            status=KnowledgeDocStatus.DRAFT,
            version=normalize_version(version),
            source_key=normalize_source_key(source_key),
            registered_by=context.user_id,
        )
        saved = self.store.register_document(context, doc=clean)
        self._record(
            context,
            _ACTION_REGISTERED,
            saved.document_id,
            {
                "document_id": saved.document_id,
                "title": saved.title,
                "status": saved.status.value,
                "owner_id": saved.owner_id,
                "version": saved.version,
                "source_key": saved.source_key,
            },
        )
        return saved

    def publish_document(
        self,
        context: UserContext,
        document_id: str,
        *,
        owner_id: str | None = None,
    ) -> KnowledgeDoc:
        """发布（§1.2 C 发布闸门）：owner 必须非空 + draft→published 状态机合法。

        owner 取调用方 `owner_id` 优先，否则回退既有行 owner；两者皆空 → 422；
        状态非法（非 draft）→ 409；成功后刷新 `last_reviewed_at`。
        **发布即置 `review_due_at = 发布时刻 + review_grace_days`**（N6 裁决 A，2026-09-15）：
        每篇发布文档从上线起就进入复核周期，首轮到期由到期扫描（手动端点 / worker beat）触发；
        未设 due 的文档不计入到期（§2.6，仅存量 / 迁移数据可能为空）。
        """
        ensure_can_manage(context)
        doc = self.store.get_document(context, document_id)
        resolved_owner = (owner_id if owner_id is not None else "").strip() or doc.owner_id.strip()
        if not resolved_owner:
            raise InvalidKnowledgeDoc("发布必须指定负责人（owner）")
        if not transition_allowed(doc.status, KnowledgeDocStatus.PUBLISHED):
            raise KnowledgeDocStateConflict("当前状态不能发布（仅 draft 可发布）")
        published_at = _utcnow()
        saved = self.store.update_status(
            context,
            document_id,
            new_status=KnowledgeDocStatus.PUBLISHED,
            owner_id=resolved_owner,
            last_reviewed_at=published_at,
            review_due_at=published_at + timedelta(days=self.review_grace_days),
        )
        self._record(
            context,
            _ACTION_PUBLISHED,
            saved.document_id,
            {"document_id": saved.document_id, "status": saved.status.value, "owner_id": saved.owner_id},
        )
        return saved

    def archive_document(self, context: UserContext, document_id: str) -> KnowledgeDoc:
        """归档（draft / published / under_review / needs_review → archived，§2.2「any → 归档」）。

        **`draft` 可直接归档**（登记后即判废，无需先发布；2026-09-15 口径裁定，§3.2 旧表笔误已更正）；
        仅 `archived` 终态出发被状态机拦截 → 409。
        """
        ensure_can_manage(context)
        doc = self.store.get_document(context, document_id)
        if not transition_allowed(doc.status, KnowledgeDocStatus.ARCHIVED):
            raise KnowledgeDocStateConflict("当前状态不能归档")
        saved = self.store.update_status(
            context, document_id, new_status=KnowledgeDocStatus.ARCHIVED
        )
        self._record(
            context,
            _ACTION_ARCHIVED,
            saved.document_id,
            {"document_id": saved.document_id, "status": saved.status.value},
        )
        return saved

    def review_document(
        self,
        context: UserContext,
        document_id: str,
        *,
        approved: bool,
    ) -> KnowledgeDoc:
        """人工复核（§2.2）：under_review / needs_review → published（通过）或 archived（判废）。

        通过时刷新 `last_reviewed_at` 并把 `review_due_at` 顺延 `review_grace_days`；判废走 archived。
        """
        ensure_can_manage(context)
        doc = self.store.get_document(context, document_id)
        target = KnowledgeDocStatus.PUBLISHED if approved else KnowledgeDocStatus.ARCHIVED
        if not transition_allowed(doc.status, target):
            raise KnowledgeDocStateConflict("当前状态不能进入该复核结果")
        now_ts = _utcnow()
        if approved:
            saved = self.store.update_status(
                context,
                document_id,
                new_status=KnowledgeDocStatus.PUBLISHED,
                last_reviewed_at=now_ts,
                review_due_at=now_ts + timedelta(days=self.review_grace_days),
            )
        else:
            saved = self.store.update_status(
                context, document_id, new_status=KnowledgeDocStatus.ARCHIVED
            )
        self._record(
            context,
            _ACTION_REVIEWED,
            saved.document_id,
            {
                "document_id": saved.document_id,
                "status": saved.status.value,
                "approved": bool(approved),
            },
        )
        return saved

    def mark_due(self, context: UserContext, document_id: str, *, now=None) -> KnowledgeDoc:
        """手动触发到期：published 且 review_due_at≤now → needs_review（§2.2 事件触发）。

        幂等：非 published / 未到期 → 原样返回并在本方法不审计（重复调用不重复置位）。
        `now` 可注入用于测试。
        """
        ensure_can_manage(context)
        ts = now or _utcnow()
        doc = self.store.get_document(context, document_id)
        if doc.status is not KnowledgeDocStatus.PUBLISHED:
            return doc  # 已 needs_review / 其他状态：幂等 no-op
        if doc.review_due_at is None or doc.review_due_at > ts:
            return doc  # 未到期：no-op
        updated = self.store.mark_review_due(context, document_id, now=ts)
        if updated is None:
            return doc  # 竞态：已被置位
        self._record(
            context,
            _ACTION_REVIEW_DUE,
            updated.document_id,
            {"document_id": updated.document_id, "status": updated.status.value},
        )
        return updated

    def scan_review_due(self, context: UserContext, *, now=None) -> int:
        """批量到期扫描（§2.2 / §4 N3 手动触发端点）：挨个置 needs_review，返回置位数。

        基于 `list_needs_review`（published 且已到期）候选；`mark_review_due` 半幂等，
        已置 needs_review 的不会再次进入候选，重复扫描不重复计数。
        """
        ensure_can_manage(context)
        ts = now or _utcnow()
        candidates = self.store.list_needs_review(context, now=ts)
        count = 0
        for doc in candidates:
            updated = self.store.mark_review_due(context, doc.document_id, now=ts)
            if updated is None:
                continue
            count += 1
            self._record(
                context,
                _ACTION_REVIEW_DUE,
                updated.document_id,
                {"document_id": updated.document_id, "status": updated.status.value},
            )
        return count

    # ------------------------------------------------------------ 检索谓词守卫 & 指标

    def scan_review_due_across_tenants(self, *, now=None, limit: int = 500) -> dict[str, int]:
        """**worker 系统路径**（§4 N3）：跨租户到期扫描，把 published 且过 `review_due_at` 的文档置 needs_review。

        与 `scan_review_due`（手动端点用）的三点刻意差异：

        1. **无用户上下文**：beat 任务没有操作者，故不走 `ensure_can_manage`——本方法**不经 HTTP 暴露**，
           只有 worker 装配（`app.worker.configure_runtime`）会拿到服务实例；
        2. **跨租户**：候选来自 `store.list_due_across_tenants`（唯一跨租户查询），写回逐条回到
           租户作用域（`mark_review_due` 带该文档的 tenant_id）；
        3. **审计 actor 固定** `system:worker`，**按租户逐条**写 `knowledge.doc.review_due`
           （不合并、不跨租户串写；每个租户各得一条自己的审计）。

        **审计缺失即拒绝（N7 裁决 B，2026-09-15）**：周期任务是**无人值守**路径，静默不落痕等于
        「治理动作不可追溯」（§2.7）⇒ 未配置审计通道时**直接抛错、且不做任何写库**
        （与 `commercial.set_retention`「没有审计通道就拒绝变更」同口径）；worker 任务会因此显式
        失败（日志可见），而不是安静地把文档置位却没留痕。

        幂等：候选只含 published 且已到期；已置 needs_review 的不再进候选，重复执行不重复计数。
        返回 `{"candidates": n, "flipped": n}`（供 beat 观测；`flipped` 是实际置位数）。
        """
        if self.audit is None:
            raise PolicyError("到期扫描必须写入审计（未配置审计通道）——请为 worker 装配注入 audit")
        ts = now or _utcnow()
        candidates = self.store.list_due_across_tenants(now=ts, limit=limit)
        flipped = 0
        for doc in candidates:
            context = UserContext(doc.tenant_id, SYSTEM_ACTOR_ID, SYSTEM_ROLE)
            updated = self.store.mark_review_due(context, doc.document_id, now=ts)
            if updated is None:
                continue  # 竞态（已被人工置位 / 状态已变）：跳过，不计入
            flipped += 1
            self._record(
                context,
                _ACTION_REVIEW_DUE,
                updated.document_id,
                {"document_id": updated.document_id, "status": updated.status.value},
            )
        return {"candidates": len(candidates), "flipped": flipped}

    def list_documents(
        self,
        context: UserContext,
        *,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[KnowledgeDoc], int]:
        """知识文档列表（管理动作，仅 super_admin；必须分页）。

        状态过滤可选（draft / published / needs_review / under_review / archived）；
        返回 (items, total)，total 为全量计数（分页前）。
        """
        ensure_can_manage(context)
        return self.store.list_documents(context, status=status, limit=limit, offset=offset)

    def list_published_eligible(self, context: UserContext, *, now=None) -> list[KnowledgeDoc]:
        """检索谓词守卫白名单（§2.3 pre-filter）：published 且未过期。

        `scoped_search` 组件在请求 WeKnora 前取此集合；空则 fail-closed 直接返回空结果。
        """
        return self.store.list_published_eligible(context, now=now or _utcnow())

    def metrics(self, context: UserContext) -> dict:
        """Freshness Index（§2.4）：published / needs_review / archived / total + freshness_ratio。

        freshness_ratio = published / total（按期复核率）；total=0 时取 1.0。仅 super_admin。
        """
        ensure_can_read_metrics(context)
        docs = self.store.list_all_for_tenant(context.tenant_id)
        total = len(docs)
        published = sum(1 for d in docs if d.status is KnowledgeDocStatus.PUBLISHED)
        needs_review = sum(1 for d in docs if d.status is KnowledgeDocStatus.NEEDS_REVIEW)
        archived = sum(1 for d in docs if d.status is KnowledgeDocStatus.ARCHIVED)
        freshness = (published / total) if total else 1.0
        return {
            "published": published,
            "needs_review": needs_review,
            "archived": archived,
            "total": total,
            "freshness_ratio": freshness,
        }

    # ------------------------------------------------------------ 内部

    def _record(self, context: UserContext, action: str, target_id: str, detail: dict[str, object]) -> None:
        if self.audit is None:
            return
        self.audit.record(
            action,
            tenant_id=context.tenant_id,
            actor_id=context.user_id,
            target_type="knowledge",
            target_id=target_id,
            detail=detail,
        )