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
