from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from .redaction import has_sensitive_key
from ..domain import PolicyError, UserContext


class AuditAction(StrEnum):
    ACCOUNT_REGISTRATION_REQUESTED = "account.registration.requested"
    ACCOUNT_REGISTRATION_APPROVED = "account.registration.approved"
    ACCOUNT_REGISTRATION_REJECTED = "account.registration.rejected"
    ACCOUNT_LOGIN_SUCCEEDED = "account.login.succeeded"
    ACCOUNT_LOGIN_FAILED = "account.login.failed"
    ACCOUNT_LOGIN_LOCKED = "account.login.locked"
    ACCOUNT_PASSWORD_CHANGED = "account.password.changed"
    ACCOUNT_PASSWORD_RESET = "account.password.reset"
    ACCOUNT_TOTP_ENROLLED = "account.totp.enrolled"
    ACCOUNT_TOTP_CONFIRMED = "account.totp.confirmed"
    ACCOUNT_TOTP_RESET = "account.totp.reset"
    ACCOUNT_TOTP_ENROLLMENT_REQUIRED = "account.totp.enrollment_required"
    ACCOUNT_SSO_LOGIN_SUCCEEDED = "account.sso.login.succeeded"
    ACCOUNT_SSO_LOGIN_REJECTED = "account.sso.login.rejected"
    ACCOUNT_SSO_IDENTITY_BOUND = "account.sso.identity.bound"
    ACCOUNT_SSO_MFA_REQUIRED = "account.sso.mfa_required"
    PLAN_PROPOSED = "plan.proposed"
    PLAN_APPROVED = "plan.approved"
    PLAN_REJECTED = "plan.rejected"
    PLAN_RUN_STARTED = "plan.run_started"
    ORCHESTRATION_PROPOSED = "orchestration.proposed"
    ORCHESTRATION_APPROVED = "orchestration.approved"
    ORCHESTRATION_REJECTED = "orchestration.rejected"
    DEAD_LETTER_NOTIFIED = "dead_letter.notified"
    DEAD_LETTER_NOTIFICATION_FAILED = "dead_letter.notification_failed"
    CONTENT_SOURCE_SCRAPED = "content.source.scraped"
    CONTENT_PUBLICATION_REQUESTED = "content.publication.requested"
    CONTENT_PUBLICATION_SUCCEEDED = "content.publication.succeeded"
    CONTENT_PUBLICATION_MANUAL_TAKEOVER = "content.publication.manual_takeover"
    CONTENT_PUBLICATION_VERIFIED = "content.publication.verified"
    INBOX_WRITE_FAILED = "inbox.write_failed"
    RUN_NOTIFY_SKIPPED = "run.notify_skipped"
    RUN_APPROVAL_DECIDED = "run.approval_decided"
    # S2 人工验收：只记结论与当时的结构判定，**不落理由正文**（正文只进决议表）。
    RUN_ACCEPTANCE_DECIDED = "run.acceptance_decided"
    # S2 沉淀入口（存成任务，迁移 042）：审计只记 task_id，标题正文不落审计。
    RUN_PROMOTED_TO_TASK = "run.promoted_to_task"
    WORKFORCE_ROLE_CREATED = "workforce.role.created"
    WORKFORCE_ROLE_UPDATED = "workforce.role.updated"
    WORKFORCE_ROLE_DISABLED = "workforce.role.disabled"
    WORKFORCE_AGENT_CREATED = "workforce.agent.created"
    WORKFORCE_AGENT_UPDATED = "workforce.agent.updated"
    WORKFORCE_AGENT_DISABLED = "workforce.agent.disabled"
    CONVERSATION_CREATED = "conversation.created"
    CONVERSATION_ARCHIVED = "conversation.archived"
    CONVERSATION_MESSAGE_SENT = "conversation.message.sent"
    WORKFORCE_AGENT_CONFIG_READ = "workforce.agent.config.read"
    WORKFORCE_AGENT_CONFIG_UPDATED = "workforce.agent.config.updated"
    WORKFORCE_AGENT_CONFIG_REJECTED = "workforce.agent.config.rejected"
    # 段二（dsh 接入段）工具执行：⑨ 成功 / 被拒（含黑名单、路径、参数拒）
    TOOL_EXECUTED = "tool.executed"
    TOOL_BLOCKED = "tool.blocked"
    # 商业化保留策略变更（真源 commercial-g0-design.md:118「任何保留策略变化都写入审计」）
    COMMERCIAL_RETENTION_UPDATED = "commercial.retention.updated"
    # 商业化保留策略**执行**（B-4 选项 C，2026-09-19）：worker 按策略清理过期数据的逐租户留痕。
    # 只记受控值（各面删除行数、结转净额整数分、两个截止时刻 ISO），**仅在本轮确有清理/结转时写入**
    # （空转不落审计 —— 审计面不可删除，不能被心跳噪声占满）。
    COMMERCIAL_RETENTION_PURGED = "commercial.retention.purged"
    # 租户删除执行（真源 commercial-g0-design.md:114/:174「删除流程包含……审计记录」）
    COMMERCIAL_DELETION_EXECUTED = "commercial.deletion.executed"
    # 租户删除确认（B-3 补丁，真源「删除前必须生成最终导出包并记录确认人」：
    # 确认人是一次**显式确认动作**，独立于「申请」，消除「确认人 = 发起人」的默认假设）
    COMMERCIAL_DELETION_CONFIRMED = "commercial.deletion.confirmed"
    # P3 记忆层（真源 specs/2026-09-15-memory-layer-p3-design.md §2.7）：
    # 只记标识与受控枚举（scope / owner_kind / rule_key / version），**不记记忆正文**。
    MEMORY_FACT_CREATED = "memory.fact.created"
    MEMORY_FACT_SUPERSEDED = "memory.fact.superseded"
    MEMORY_RULE_CREATED = "memory.rule.created"
    MEMORY_PROFILE_UPDATED = "memory.profile.updated"
    # P4 技能层（真源 specs/2026-09-15-skill-layer-p4-design.md §2.4）：
    # 只记技能键/版本/来源/员工标识，**不记包正文与 description**。
    SKILL_SUBMITTED = "skill.submitted"
    SKILL_APPROVED = "skill.approved"
    SKILL_REJECTED = "skill.rejected"
    SKILL_ENABLED = "skill.enabled"
    SKILL_DISABLED = "skill.disabled"
    # 知识治理层（真源 specs/2026-09-15-knowledge-governance-design.md §2.7）：
    # 只记文档标识/标题/状态/负责人/版本/来源（**不落正文**）。
    KNOWLEDGE_DOC_REGISTERED = "knowledge.doc.registered"
    KNOWLEDGE_DOC_PUBLISHED = "knowledge.doc.published"
    KNOWLEDGE_DOC_ARCHIVED = "knowledge.doc.archived"
    KNOWLEDGE_DOC_REVIEWED = "knowledge.doc.reviewed"
    KNOWLEDGE_DOC_REVIEW_DUE = "knowledge.doc.review_due"
    # 检索入口被守卫拦截（无绑定 / 白名单空，§2.3 fail-closed 路径）。只记 `role_key`/`agent_key`/`reason`，
    # **绝不记查询正文**（自由文本 + 可能含个人信息，与「只记受控枚举」口径冲突）。
    KNOWLEDGE_SEARCH_BLOCKED = "knowledge.search.blocked"
    # P6a 自进化·评测集（真源 specs/2026-09-16-self-evolution-p6-design.md §2.9）：
    # 用例变更与评测运行完成；只记标识 / 状态 / 计数 / 指纹，**不记用例内容与期望正文**。
    EVOLUTION_CASE_CHANGED = "evolution.case.changed"
    EVOLUTION_EVAL_COMPLETED = "evolution.eval.completed"
    # P5a CRM（真源 specs/2026-09-17-crm-p5a-design.md §2.10，最小集 17 条）：
    # 只记标识与受控枚举（**不落正文 / PII / 敏感字段值**）；`from_stage` / `to_stage` /
    # `field_name` 为受控枚举，不得写入自由文本。
    CRM_ACCOUNT_CREATED = "crm.account.created"
    CRM_CONTACT_CREATED = "crm.contact.created"
    CRM_LEAD_CONVERTED = "crm.lead.converted"
    CRM_OPPORTUNITY_CREATED = "crm.opportunity.created"
    CRM_OPPORTUNITY_STAGE_CHANGED = "crm.opportunity.stage_changed"
    CRM_ACTIVITY_LOGGED = "crm.activity.logged"
    CRM_QUOTE_CREATED = "crm.quote.created"
    CRM_QUOTE_CONFIRMED = "crm.quote.confirmed"
    CRM_QUOTE_CONVERTED = "crm.quote.converted"
    CRM_QUOTE_VOIDED = "crm.quote.voided"
    CRM_CONTRACT_CREATED = "crm.contract.created"
    CRM_CONTRACT_SIGNED = "crm.contract.signed"
    CRM_CONTRACT_VOIDED = "crm.contract.voided"
    CRM_CONTRACT_PAYMENT_REGISTERED = "crm.contract.payment_registered"
    CRM_INSIGHT_GENERATED = "crm.insight.generated"
    CRM_SENSITIVE_REVEALED = "crm.sensitive.revealed"
    CRM_HEALTH_RECOMPUTED = "crm.health.recomputed"
    # P2b 实时流（真源 specs/2026-09-17-realtime-stream-p2b-design.md §1.4）：
    # 熔断 / 写失败 / 悬挂兜底的治理事件；明细只记 `reason`（受控枚举）+ `run_id`。
    CONVERSATION_STREAM_UNAVAILABLE = "conversation.stream.unavailable"
    # P2c-4（真源 specs/2026-09-17-frontend-interaction-p2c-design.md §2.9 / §2.11）：
    # 模式变更 / 导出 / 物理删除 / `ask` 模式拒绝执行；明细只记受控枚举与计数，**不落正文**。
    CONVERSATION_MODE_CHANGED = "conversation.mode.changed"
    CONVERSATION_EXPORTED = "conversation.exported"
    CONVERSATION_DELETED = "conversation.deleted"
    CONVERSATION_EXECUTION_REJECTED = "conversation.execution.rejected"
    # P2c-6 会话协作：成员增删（只记标识与授权档，**不记**正文 / 姓名 / 手机号）
    CONVERSATION_MEMBER_ADDED = "conversation.member.added"
    CONVERSATION_MEMBER_REMOVED = "conversation.member.removed"


class AuditDetailNotAllowed(ValueError):
    """审计明细包含敏感字段，已拒绝写入。"""


ALLOWED_DETAIL_KEYS = frozenset(
    {
        "reason",
        "provider",
        "role",
        "step_count",
        "generator",
        "runtime_key",
        "run_id",
        "failure_count",
        "bootstrap",
        "tenant_assigned_at_approval",
        "data_classification",
        "kind",
        "current_value",
        "proposed_value",
        "run_count",
        "event_id",
        "attempts",
        "channel",
        "domain",
        "status",
        "target",
        "receipt_id",
        # 岗位/数字员工目录变更（标识与变更字段名都是服务端声明值，不含自由文本）
        "role_key",
        "agent_key",
        "changed_fields",
        # 对话层（只记标识与角色，绝不记消息正文或提示词正文）
        "conversation_id",
        "message_id",
        "stub",
        # 配置被拒时记录被拒字段名
        "rejected_fields",
        # 运行审批的授权来源（服务端判定的受控枚举，非自由文本）
        "authorized_by_source",
        # 服务端生成的任务标识（S2 沉淀入口：只记标识，不记用户填写的标题正文）
        "task_id",
        # 工具执行（Y3 最小集：工具标识与风险档，均为服务端声明的受控值）
        "tool_key",
        "risk_level",
        # P3 记忆层（只记标识与受控枚举，不记正文；口径见 memory-layer-p3-design §2.7）
        "memory_id",
        "scope",
        "owner_kind",
        "rule_key",
        "version",
        # P4 技能层（只记技能键/版本/来源/员工标识/内容指纹/审核结论，不记包正文；口径见 skill-layer-p4-design §2.4）
        "skill_key",
        "agent_key",
        "source_key",
        "license",
        "content_sha256",
        "approved",
        # 知识治理层（只记文档标识/标题/状态/负责人/版本/来源，不落正文；口径见 knowledge-governance §2.7）
        "document_id",
        "title",
        "status",
        "owner_id",
        "version",
        "source_key",
        # P6a 自进化·评测集（只记标识 / 状态 / 计数 / 指纹，不记用例内容；口径见 self-evolution-p6 §2.9）
        "case_id",
        "eval_run_id",
        "case_count",
        "pass_count",
        "suite_digest",
        # P5a CRM（只记标识与受控枚举，不落正文 / PII / 敏感字段值；口径见 crm-p5a-design §2.10）
        "account_id",
        "contact_id",
        "lead_id",
        "opportunity_id",
        "quote_id",
        "contract_id",
        "insight_id",
        "activity_id",
        "from_stage",
        "to_stage",
        "amount_cents",
        "field_name",
        "recomputed_count",
        # 租户删除（B-3）：确认人标识与「按策略清场了哪些面」——均为服务端声明值，不含自由文本
        "confirmed_by",
        "cleared_categories",
        # 保留策略**执行**（B-4 选项 C）：各面删除行数与结转净额（整数）、两个截止时刻（ISO 字符串）——
        # 全为服务端计算值，无自由文本。
        "runs_deleted",
        "tasks_deleted",
        "proposals_deleted",
        "usage_carried_units",
        "usage_carried_cents",
        "cutoff",
        "usage_cutoff",
        "create_opportunity",
        "model_key",
        # P2c-4（会话模式 / 导出 / 物理删除）：模式为受控枚举、计数为整数，**均不含正文**。
        "from_mode",
        "to_mode",
        "mode",
        "conversation_count",
        "message_count",
        "frame_count",
        "stream_state_count",
        "idempotency_count",
        "truncated",
        # P2c-6 会话协作：成员标识 / 授权档 / 是否发起人（均为服务端声明的受控值，不含姓名与手机号）
        "member_id",
        "permission",
        "is_owner",
        # S2 人工验收（只记结论文本与「是否写了理由」的布尔，**不落理由正文**）
        "decision",
        "structural_verdict",
        "reason_present",
    }
)


@dataclass(frozen=True)
class AuditRecord:
    action: AuditAction
    tenant_id: str | None = None
    actor_id: str | None = None
    target_type: str | None = None
    target_id: str | None = None
    phone_masked: str | None = None
    detail: dict[str, object] = field(default_factory=dict)
    record_id: str = field(default_factory=lambda: f"audit-{uuid4().hex[:12]}")
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))


def build_record(
    action: AuditAction,
    *,
    tenant_id: str | None = None,
    actor_id: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    phone_masked: str | None = None,
    detail: dict[str, object] | None = None,
) -> AuditRecord:
    """构造审计记录；明细采用白名单，只允许服务端声明的字段，未知字段一律拒绝。

    顶层键以白名单为准（因此 ``runtime_key`` 这类含 ``key`` 词元的合法键不会被误伤）；
    键值内部若出现嵌套结构，则按 ``redaction.has_sensitive_key`` 递归检查敏感键，
    命中即拒绝——防止把凭据塞进「已允许的键」里写进审计。
    """
    payload = dict(detail or {})
    undeclared = {str(key) for key in payload if key not in ALLOWED_DETAIL_KEYS}
    if undeclared:
        raise AuditDetailNotAllowed("审计明细包含未声明的字段")
    if any(has_sensitive_key(value) for value in payload.values()):
        raise AuditDetailNotAllowed("审计明细的嵌套结构中包含敏感字段")
    return AuditRecord(
        action=action,
        tenant_id=tenant_id,
        actor_id=actor_id,
        target_type=target_type,
        target_id=target_id,
        phone_masked=phone_masked,
        detail=payload,
    )


# ------------------------------------------------------------ 审计查询的角色分档（第 10 轮）

# 可查看审计记录的业务角色：口径 = `permission-matrix.md` §3「审计：查询」
# （`employee` ⚠️仅本人相关 / `department_lead` ✅ / `ceo` ✅ / `super_admin` ✅；`customer_admin` ❌）。
# 2026-09-20 第 10 轮：实现原只收 `{ceo, super_admin}`（其余 403），与矩阵冲突（与第 7 / 8 轮同一类），
# 按「实现向矩阵对齐、不改矩阵口径」修复。
AUDIT_READ_ROLES = frozenset({"employee", "department_lead", "ceo", "super_admin"})
# 「仅本人相关」档：只能看到自己作为**操作者**的记录。
AUDIT_SELF_SCOPED_ROLES = frozenset({"employee"})


def can_read_audits(context: UserContext) -> bool:
    """是否可查看审计记录（四个业务角色；`customer_admin` ❌）。"""
    return context.role in AUDIT_READ_ROLES


def ensure_can_read_audits(context: UserContext) -> None:
    """审计查询前置判定；否则 403。

    文案刻意用「当前岗位…」：原「只有 CEO 或超级管理员可以查看审计日志」在分档放开后已不成立。
    """
    if not can_read_audits(context):
        raise PolicyError("当前岗位不能查看审计日志")


def is_self_scoped_audit(context: UserContext) -> bool:
    """该角色是否只能看「本人相关」记录（矩阵 §3：`employee` ⚠️）。"""
    return context.role in AUDIT_SELF_SCOPED_ROLES


def resolve_actor_filter(context: UserContext, requested: str | None) -> str | None:
    """把调用方给的 `actor_id` 解析为**服务端最终生效**的过滤值。

    - 管理三档（`department_lead` / `ceo` / `super_admin`）：原样返回（本租户内自由筛选）；
    - `employee`（自限）：强制 `actor_id = 自己`；**显式传他人 ⇒ `PolicyError`（403 + 原文）**。

    为什么不"静默忽略"：静默忽略会让调用方以为筛选生效（结果看起来"没有别人的记录"），
    同时把越权尝试掩盖成正常请求 —— 与第 7 轮知识域「自身角色自限」同一手法：显式拒绝并给原因。
    """
    if not is_self_scoped_audit(context):
        return requested
    if requested is not None and requested != context.user_id:
        raise PolicyError("只能查看本人的审计记录，不能按他人筛选")
    return context.user_id
