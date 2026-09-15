from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from .redaction import has_sensitive_key


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
    # 租户删除执行（真源 commercial-g0-design.md:114/:174「删除流程包含……审计记录」）
    COMMERCIAL_DELETION_EXECUTED = "commercial.deletion.executed"
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
