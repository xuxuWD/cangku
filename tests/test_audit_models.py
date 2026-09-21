import pytest

from app.audit.models import AuditAction, AuditDetailNotAllowed, AuditRecord, build_record


def test_build_record_defaults_and_identity() -> None:
    record = build_record(
        AuditAction.ACCOUNT_LOGIN_SUCCEEDED,
        tenant_id="t-1",
        actor_id="acct-1",
        target_type="account",
        target_id="acct-1",
        phone_masked="138****0001",
    )

    assert record.record_id.startswith("audit-")
    assert record.occurred_at.tzinfo is not None
    assert record.detail == {}
    assert record.action is AuditAction.ACCOUNT_LOGIN_SUCCEEDED


def test_action_values_are_stable_strings() -> None:
    assert AuditAction.ACCOUNT_LOGIN_LOCKED.value == "account.login.locked"
    assert AuditAction.PLAN_RUN_STARTED.value == "plan.run_started"
    assert AuditAction.DEAD_LETTER_NOTIFIED.value == "dead_letter.notified"
    assert AuditAction.DEAD_LETTER_NOTIFICATION_FAILED.value == "dead_letter.notification_failed"
    assert AuditAction.CONTENT_SOURCE_SCRAPED.value == "content.source.scraped"
    assert AuditAction.CONTENT_PUBLICATION_REQUESTED.value == "content.publication.requested"
    assert AuditAction.CONTENT_PUBLICATION_SUCCEEDED.value == "content.publication.succeeded"
    assert AuditAction.CONTENT_PUBLICATION_MANUAL_TAKEOVER.value == "content.publication.manual_takeover"
    assert AuditAction.CONTENT_PUBLICATION_VERIFIED.value == "content.publication.verified"
    assert AuditAction.ACCOUNT_SSO_LOGIN_SUCCEEDED.value == "account.sso.login.succeeded"
    assert AuditAction.ACCOUNT_SSO_LOGIN_REJECTED.value == "account.sso.login.rejected"
    assert AuditAction.ACCOUNT_SSO_IDENTITY_BOUND.value == "account.sso.identity.bound"
    assert AuditAction.ACCOUNT_SSO_MFA_REQUIRED.value == "account.sso.mfa_required"
    assert AuditAction.INBOX_WRITE_FAILED.value == "inbox.write_failed"
    assert AuditAction.RUN_NOTIFY_SKIPPED.value == "run.notify_skipped"
    assert AuditAction.RUN_APPROVAL_DECIDED.value == "run.approval_decided"
    assert AuditAction.WORKFORCE_ROLE_CREATED.value == "workforce.role.created"
    assert AuditAction.WORKFORCE_ROLE_UPDATED.value == "workforce.role.updated"
    assert AuditAction.WORKFORCE_ROLE_DISABLED.value == "workforce.role.disabled"
    assert AuditAction.WORKFORCE_AGENT_CREATED.value == "workforce.agent.created"
    assert AuditAction.WORKFORCE_AGENT_UPDATED.value == "workforce.agent.updated"
    assert AuditAction.WORKFORCE_AGENT_DISABLED.value == "workforce.agent.disabled"
    assert AuditAction.CONVERSATION_CREATED.value == "conversation.created"
    assert AuditAction.CONVERSATION_ARCHIVED.value == "conversation.archived"
    assert AuditAction.CONVERSATION_MESSAGE_SENT.value == "conversation.message.sent"
    assert AuditAction.WORKFORCE_AGENT_CONFIG_READ.value == "workforce.agent.config.read"
    assert AuditAction.WORKFORCE_AGENT_CONFIG_UPDATED.value == "workforce.agent.config.updated"
    assert AuditAction.WORKFORCE_AGENT_CONFIG_REJECTED.value == "workforce.agent.config.rejected"
    assert AuditAction.TOOL_EXECUTED.value == "tool.executed"
    assert AuditAction.TOOL_BLOCKED.value == "tool.blocked"
    assert AuditAction.COMMERCIAL_RETENTION_UPDATED.value == "commercial.retention.updated"
    assert AuditAction.COMMERCIAL_DELETION_EXECUTED.value == "commercial.deletion.executed"
    # P3 记忆层（2026-09-15）：新增四个动作码，值必须稳定为契约字符串。
    assert AuditAction.MEMORY_FACT_CREATED.value == "memory.fact.created"
    assert AuditAction.MEMORY_FACT_SUPERSEDED.value == "memory.fact.superseded"
    assert AuditAction.MEMORY_RULE_CREATED.value == "memory.rule.created"
    assert AuditAction.MEMORY_PROFILE_UPDATED.value == "memory.profile.updated"
    # P4 技能层（2026-09-15）：新增五个动作码，值必须稳定为契约字符串。
    assert AuditAction.SKILL_SUBMITTED.value == "skill.submitted"
    assert AuditAction.SKILL_APPROVED.value == "skill.approved"
    assert AuditAction.SKILL_REJECTED.value == "skill.rejected"
    assert AuditAction.SKILL_ENABLED.value == "skill.enabled"
    assert AuditAction.SKILL_DISABLED.value == "skill.disabled"
    # 知识治理层（2026-09-15）：新增五个动作码，值必须稳定为契约字符串（knowledge-governance §2.7）。
    assert AuditAction.KNOWLEDGE_DOC_REGISTERED.value == "knowledge.doc.registered"
    assert AuditAction.KNOWLEDGE_DOC_PUBLISHED.value == "knowledge.doc.published"
    assert AuditAction.KNOWLEDGE_DOC_ARCHIVED.value == "knowledge.doc.archived"
    assert AuditAction.KNOWLEDGE_DOC_REVIEWED.value == "knowledge.doc.reviewed"
    assert AuditAction.KNOWLEDGE_DOC_REVIEW_DUE.value == "knowledge.doc.review_due"
    assert AuditAction.KNOWLEDGE_SEARCH_BLOCKED.value == "knowledge.search.blocked"
    # P6a 自进化·评测集（2026-09-16）：两个动作码，值必须稳定为契约字符串（self-evolution-p6 §2.9）。
    assert AuditAction.EVOLUTION_CASE_CHANGED.value == "evolution.case.changed"
    assert AuditAction.EVOLUTION_EVAL_COMPLETED.value == "evolution.eval.completed"
    # P5a CRM（2026-09-17）：十七个动作码，值必须稳定为契约字符串（crm-p5a-design §2.10）。
    assert AuditAction.CRM_ACCOUNT_CREATED.value == "crm.account.created"
    assert AuditAction.CRM_CONTACT_CREATED.value == "crm.contact.created"
    assert AuditAction.CRM_LEAD_CONVERTED.value == "crm.lead.converted"
    assert AuditAction.CRM_OPPORTUNITY_CREATED.value == "crm.opportunity.created"
    assert AuditAction.CRM_OPPORTUNITY_STAGE_CHANGED.value == "crm.opportunity.stage_changed"
    assert AuditAction.CRM_ACTIVITY_LOGGED.value == "crm.activity.logged"
    assert AuditAction.CRM_QUOTE_CREATED.value == "crm.quote.created"
    assert AuditAction.CRM_QUOTE_CONFIRMED.value == "crm.quote.confirmed"
    assert AuditAction.CRM_QUOTE_CONVERTED.value == "crm.quote.converted"
    assert AuditAction.CRM_QUOTE_VOIDED.value == "crm.quote.voided"
    assert AuditAction.CRM_CONTRACT_CREATED.value == "crm.contract.created"
    assert AuditAction.CRM_CONTRACT_SIGNED.value == "crm.contract.signed"
    assert AuditAction.CRM_CONTRACT_VOIDED.value == "crm.contract.voided"
    assert AuditAction.CRM_CONTRACT_PAYMENT_REGISTERED.value == "crm.contract.payment_registered"
    assert AuditAction.CRM_INSIGHT_GENERATED.value == "crm.insight.generated"
    assert AuditAction.CRM_SENSITIVE_REVEALED.value == "crm.sensitive.revealed"
    assert AuditAction.CRM_HEALTH_RECOMPUTED.value == "crm.health.recomputed"
    # P2b 实时流（2026-09-17）：一个动作码（熔断 / 写失败 / 悬挂兜底治理事件）。
    assert AuditAction.CONVERSATION_STREAM_UNAVAILABLE.value == "conversation.stream.unavailable"
    # P2c-4（2026-09-17）：四个动作码（模式变更 / 本人导出 / 物理删除 / 模式拒绝执行）。
    assert AuditAction.CONVERSATION_MODE_CHANGED.value == "conversation.mode.changed"
    assert AuditAction.CONVERSATION_EXPORTED.value == "conversation.exported"
    assert AuditAction.CONVERSATION_DELETED.value == "conversation.deleted"
    assert AuditAction.CONVERSATION_EXECUTION_REJECTED.value == "conversation.execution.rejected"
    # P2c-6（2026-09-17）：两个动作码（会话成员添加 / 撤销）。
    assert AuditAction.CONVERSATION_MEMBER_ADDED.value == "conversation.member.added"
    assert AuditAction.CONVERSATION_MEMBER_REMOVED.value == "conversation.member.removed"
    # S2（2026-09-18）：一个动作码（运行验收决议；**只记结论，不落理由正文**）。
    assert AuditAction.RUN_ACCEPTANCE_DECIDED.value == "run.acceptance_decided"
    # S2 沉淀入口（2026-09-19）：一个动作码（存成任务；只记 task_id，标题正文不落审计）。
    assert AuditAction.RUN_PROMOTED_TO_TASK.value == "run.promoted_to_task"
    # B-3（2026-09-19）：一个动作码（租户删除确认；确认人是独立于「申请」的显式动作）。
    assert AuditAction.COMMERCIAL_DELETION_CONFIRMED.value == "commercial.deletion.confirmed"
    # B-4 选项 C（2026-09-19）：一个动作码（保留策略执行；只记各面行数与结转净额，仅在有清理时写入）。
    assert AuditAction.COMMERCIAL_RETENTION_PURGED.value == "commercial.retention.purged"
    # 第 13 轮（2026-09-21）：一个动作码（审计导出留痕；明细只记 `format` / `rows` / `filters`）。
    assert AuditAction.AUDIT_EXPORTED.value == "audit.exported"
    assert len(set(AuditAction)) == 95


def test_build_record_rejects_undeclared_detail_keys() -> None:
    for bad in (
        {"password": "x"},
        {"apiKey": "x"},
        {"unknown": "x"},
        {"nested": {"accessToken": "x"}},
    ):
        with pytest.raises(AuditDetailNotAllowed):
            build_record(AuditAction.PLAN_PROPOSED, tenant_id="t-1", detail=bad)


def test_build_record_allows_every_declared_detail_key() -> None:
    from app.audit.models import ALLOWED_DETAIL_KEYS

    record = build_record(
        AuditAction.PLAN_RUN_STARTED,
        tenant_id="t-1",
        detail={key: "v" for key in ALLOWED_DETAIL_KEYS},
    )

    assert set(record.detail) == set(ALLOWED_DETAIL_KEYS)


def test_build_record_accepts_bounded_structured_detail() -> None:
    record = build_record(
        AuditAction.PLAN_RUN_STARTED,
        tenant_id="t-1",
        detail={"runtime_key": "mock", "step_count": 3},
    )

    assert record.detail == {"runtime_key": "mock", "step_count": 3}


def test_build_record_rejects_sensitive_keys_inside_detail_values() -> None:
    # 判定依据：顶层白名单挡不住「允许的键里塞嵌套结构」，值必须递归检查敏感键。
    for bad in (
        {"reason": {"api_key": "x"}},
        {"reason": {"apiKey": "x"}},
        {"reason": [{"access_token": "x"}]},
        {"reason": {"stage": {"cookie": "x"}}},
        {"proposed_value": {"sessionId": "x"}},
        {"reason": {"credentials": {"bearer": "x"}}},
    ):
        with pytest.raises(AuditDetailNotAllowed):
            build_record(AuditAction.PLAN_PROPOSED, tenant_id="t-1", detail=bad)


def test_build_record_accepts_nested_detail_without_sensitive_keys() -> None:
    detail = {
        "reason": {"stage": "review", "count": 2},
        "proposed_value": [{"runtime": "mock", "steps": 3}],
    }

    record = build_record(AuditAction.ORCHESTRATION_PROPOSED, tenant_id="t-1", detail=detail)

    assert record.detail == detail


def test_build_record_keeps_top_level_allowlist_authority() -> None:
    # 回归：顶层键由白名单显式允许，`runtime_key` 词元含 `key` 也不得被启发式误伤。
    record = build_record(
        AuditAction.PLAN_RUN_STARTED, tenant_id="t-1", detail={"runtime_key": "mock"}
    )

    assert record.detail == {"runtime_key": "mock"}


def test_build_record_rejects_nested_key_token_even_under_allowed_key() -> None:
    # 刻意行为：嵌套结构一律按敏感键启发式判定，因此嵌套的 `runtime_key` 也会被拒（fail-closed）。
    with pytest.raises(AuditDetailNotAllowed):
        build_record(
            AuditAction.PLAN_RUN_STARTED,
            tenant_id="t-1",
            detail={"reason": {"runtime_key": "mock"}},
        )
