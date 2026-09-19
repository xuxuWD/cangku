-- =========================================================================
-- 租户 schema 基线 DDL（S0 生成物 · 自动生成，请勿手工编辑）
-- 生成器：tenant_schema.py/1.1.0（scripts/tenant_schema.py build-template）
-- 生成日期：2026-09-19（UTC）
-- 生成命令：py scripts/tenant_schema.py build-template
--           -> docker exec wb-test-postgres-1 pg_dump -U workbench_test --schema-only --no-owner --no-privileges --dbname=workbench_test
-- 源库：容器 wb-test-postgres-1 / 库 workbench_test / schema public（PostgreSQL 16.15）
-- 表数：51（= classification.json 的 tenant_schema 集合）
-- 索引数：53
-- 约束数：98
-- 序列数（CREATE SEQUENCE，均由 A 组表拥有）：2
-- SET DEFAULT nextval 条数：2
-- ${PLATFORM_SCHEMA} 改写：4 处（指向 B/C 组平台表的外键）
-- 说明：纯 DDL，不做 IF NOT EXISTS 幂等化；幂等由「单事务应用 + 版本台账」保证（S1 实现）。
-- 说明：属于 A 组表的序列随表入租户 schema（去 public 限定），保证自增行为与 public 一致。
-- 说明：语句内的 public.vector / public.vector_cosine_ops 等扩展对象按方案不做占位符改写。
-- =========================================================================
CREATE TABLE workbench_accounts (
    account_id text NOT NULL,
    phone text NOT NULL,
    password_hash text NOT NULL,
    "position" text NOT NULL,
    full_name text NOT NULL,
    email text,
    role text,
    tenant_id text,
    status text NOT NULL,
    requested_at timestamp with time zone DEFAULT now() NOT NULL,
    reviewed_at timestamp with time zone,
    reviewed_by text,
    rejection_reason text,
    totp_secret text,
    totp_confirmed_at timestamp with time zone,
    totp_last_step bigint,
    sso_provider text,
    sso_subject text,
    CONSTRAINT workbench_accounts_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'approved'::text, 'rejected'::text])))
);

CREATE TABLE workbench_audit_events (
    id bigint NOT NULL,
    task_id text NOT NULL,
    tenant_id text NOT NULL,
    action text NOT NULL,
    actor_id text NOT NULL,
    actor_role text NOT NULL,
    occurred_at timestamp with time zone DEFAULT now() NOT NULL
);

CREATE SEQUENCE workbench_audit_events_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE workbench_audit_events_id_seq OWNED BY workbench_audit_events.id;

CREATE TABLE workbench_content_publications (
    publication_id text NOT NULL,
    tenant_id text NOT NULL,
    task_id text NOT NULL,
    revision integer NOT NULL,
    target text NOT NULL,
    idempotency_key text NOT NULL,
    status text NOT NULL,
    receipt_id text,
    error text,
    created_by text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    verified_at timestamp with time zone,
    CONSTRAINT workbench_content_publications_status_check CHECK ((status = ANY (ARRAY['succeeded'::text, 'manual_takeover'::text, 'pending'::text])))
);

CREATE TABLE workbench_conversation_members (
    tenant_id text NOT NULL,
    conversation_id text NOT NULL,
    member_id text NOT NULL,
    permission text NOT NULL,
    added_by text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT workbench_conversation_members_permission_check CHECK ((permission = ANY (ARRAY['read'::text, 'write'::text])))
);

CREATE TABLE workbench_conversation_messages (
    tenant_id text NOT NULL,
    message_id text NOT NULL,
    conversation_id text NOT NULL,
    role text NOT NULL,
    content text NOT NULL,
    tool_name text,
    tool_call_id text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    sender_id text,
    CONSTRAINT workbench_conversation_messages_role_check CHECK ((role = ANY (ARRAY['user'::text, 'assistant'::text, 'tool'::text, 'system'::text])))
);

CREATE TABLE workbench_conversation_stream_frames (
    tenant_id text NOT NULL,
    conversation_id text NOT NULL,
    run_id text NOT NULL,
    seq integer NOT NULL,
    kind text NOT NULL,
    payload jsonb DEFAULT '{}'::jsonb NOT NULL,
    is_terminal boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

CREATE TABLE workbench_conversation_stream_state (
    tenant_id text NOT NULL,
    conversation_id text NOT NULL,
    run_id text NOT NULL,
    last_seq integer DEFAULT 0 NOT NULL,
    frame_count integer DEFAULT 0 NOT NULL,
    byte_count bigint DEFAULT 0 NOT NULL,
    is_terminal boolean DEFAULT false NOT NULL,
    status text DEFAULT 'streaming'::text NOT NULL,
    persisted_to_message_id text,
    expires_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT workbench_conversation_stream_state_status_check CHECK ((status = ANY (ARRAY['streaming'::text, 'completed'::text, 'failed'::text, 'unavailable'::text])))
);

CREATE TABLE workbench_conversations (
    tenant_id text NOT NULL,
    conversation_id text NOT NULL,
    agent_key text,
    operator_id text NOT NULL,
    title text DEFAULT ''::text NOT NULL,
    status text NOT NULL,
    dsh_session_id text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    mode text DEFAULT 'craft'::text NOT NULL,
    deleted_at timestamp with time zone,
    CONSTRAINT workbench_conversations_mode_check CHECK ((mode = ANY (ARRAY['ask'::text, 'plan'::text, 'goal'::text, 'craft'::text]))),
    CONSTRAINT workbench_conversations_status_check CHECK ((status = ANY (ARRAY['active'::text, 'archived'::text])))
);

CREATE TABLE workbench_crm_accounts (
    tenant_id text NOT NULL,
    account_id text NOT NULL,
    name text NOT NULL,
    industry text DEFAULT ''::text NOT NULL,
    source text DEFAULT 'manual'::text NOT NULL,
    owner_id text NOT NULL,
    status text DEFAULT 'active'::text NOT NULL,
    custom_fields jsonb DEFAULT '{}'::jsonb NOT NULL,
    health_score integer,
    health_band text,
    health_computed_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    deleted_at timestamp with time zone,
    CONSTRAINT workbench_crm_accounts_check CHECK (((health_score IS NULL) = (health_band IS NULL))),
    CONSTRAINT workbench_crm_accounts_health_band_check CHECK ((health_band = ANY (ARRAY['green'::text, 'yellow'::text, 'red'::text]))),
    CONSTRAINT workbench_crm_accounts_health_score_check CHECK (((health_score >= 0) AND (health_score <= 100))),
    CONSTRAINT workbench_crm_accounts_source_check CHECK ((source = ANY (ARRAY['manual'::text, 'lead_converted'::text, 'api'::text]))),
    CONSTRAINT workbench_crm_accounts_status_check CHECK ((status = ANY (ARRAY['active'::text, 'inactive'::text])))
);

CREATE TABLE workbench_crm_activities (
    tenant_id text NOT NULL,
    activity_id text NOT NULL,
    kind text NOT NULL,
    subject text DEFAULT ''::text NOT NULL,
    content text DEFAULT ''::text NOT NULL,
    account_id text,
    contact_id text,
    opportunity_id text,
    owner_id text NOT NULL,
    status text DEFAULT 'done'::text NOT NULL,
    due_at timestamp with time zone,
    occurred_at timestamp with time zone DEFAULT now() NOT NULL,
    reminded_on date,
    created_by_kind text DEFAULT 'human'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    deleted_at timestamp with time zone,
    CONSTRAINT workbench_crm_activities_created_by_kind_check CHECK ((created_by_kind = ANY (ARRAY['human'::text, 'agent'::text]))),
    CONSTRAINT workbench_crm_activities_kind_check CHECK ((kind = ANY (ARRAY['call'::text, 'meeting'::text, 'email'::text, 'note'::text, 'task'::text]))),
    CONSTRAINT workbench_crm_activities_status_check CHECK ((status = ANY (ARRAY['planned'::text, 'done'::text, 'cancelled'::text])))
);

CREATE TABLE workbench_crm_contacts (
    tenant_id text NOT NULL,
    contact_id text NOT NULL,
    account_id text,
    name text NOT NULL,
    title text DEFAULT ''::text NOT NULL,
    phone text DEFAULT ''::text NOT NULL,
    email text DEFAULT ''::text NOT NULL,
    is_primary boolean DEFAULT false NOT NULL,
    birthday date,
    owner_id text NOT NULL,
    custom_fields jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    deleted_at timestamp with time zone
);

CREATE TABLE workbench_crm_contracts (
    tenant_id text NOT NULL,
    contract_id text NOT NULL,
    account_id text NOT NULL,
    quote_id text,
    opportunity_id text,
    contract_no text NOT NULL,
    title text NOT NULL,
    status text DEFAULT 'draft'::text NOT NULL,
    amount_cents bigint DEFAULT 0 NOT NULL,
    paid_cents bigint DEFAULT 0 NOT NULL,
    starts_on date,
    ends_on date,
    document_object_key text DEFAULT ''::text NOT NULL,
    signed_at timestamp with time zone,
    owner_id text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    deleted_at timestamp with time zone,
    CONSTRAINT workbench_crm_contracts_amount_cents_check CHECK ((amount_cents >= 0)),
    CONSTRAINT workbench_crm_contracts_check CHECK ((paid_cents <= amount_cents)),
    CONSTRAINT workbench_crm_contracts_check1 CHECK (((status = 'signed'::text) = (signed_at IS NOT NULL))),
    CONSTRAINT workbench_crm_contracts_paid_cents_check CHECK ((paid_cents >= 0)),
    CONSTRAINT workbench_crm_contracts_status_check CHECK ((status = ANY (ARRAY['draft'::text, 'pending_sign'::text, 'signed'::text, 'voided'::text, 'expired'::text])))
);

CREATE TABLE workbench_crm_field_defs (
    tenant_id text NOT NULL,
    object_key text NOT NULL,
    field_key text NOT NULL,
    label text NOT NULL,
    field_type text NOT NULL,
    required boolean DEFAULT false NOT NULL,
    options jsonb DEFAULT '[]'::jsonb NOT NULL,
    active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT workbench_crm_field_defs_field_key_check CHECK ((field_key ~ '^[a-z][a-z0-9_]{0,63}$'::text)),
    CONSTRAINT workbench_crm_field_defs_field_type_check CHECK ((field_type = ANY (ARRAY['text'::text, 'number'::text, 'date'::text, 'select'::text, 'bool'::text]))),
    CONSTRAINT workbench_crm_field_defs_object_key_check CHECK ((object_key = ANY (ARRAY['account'::text, 'contact'::text, 'lead'::text, 'opportunity'::text, 'activity'::text])))
);

CREATE TABLE workbench_crm_insights (
    tenant_id text NOT NULL,
    insight_id text NOT NULL,
    account_id text NOT NULL,
    kind text DEFAULT 'followup_plan'::text NOT NULL,
    input_digest text NOT NULL,
    content jsonb NOT NULL,
    evidence_refs jsonb DEFAULT '[]'::jsonb NOT NULL,
    dropped_refs jsonb DEFAULT '[]'::jsonb NOT NULL,
    model_key text NOT NULL,
    generated_by text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT workbench_crm_insights_kind_check CHECK ((kind = ANY (ARRAY['followup_plan'::text, 'account_review'::text])))
);

CREATE TABLE workbench_crm_leads (
    tenant_id text NOT NULL,
    lead_id text NOT NULL,
    name text NOT NULL,
    company text DEFAULT ''::text NOT NULL,
    phone text DEFAULT ''::text NOT NULL,
    email text DEFAULT ''::text NOT NULL,
    source text DEFAULT 'manual'::text NOT NULL,
    owner_id text NOT NULL,
    status text DEFAULT 'open'::text NOT NULL,
    converted_account_id text,
    converted_contact_id text,
    converted_opportunity_id text,
    custom_fields jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    deleted_at timestamp with time zone,
    CONSTRAINT workbench_crm_leads_status_check CHECK ((status = ANY (ARRAY['open'::text, 'converted'::text, 'dropped'::text])))
);

CREATE TABLE workbench_crm_opportunities (
    tenant_id text NOT NULL,
    opportunity_id text NOT NULL,
    account_id text NOT NULL,
    name text NOT NULL,
    stage text DEFAULT 'qualification'::text NOT NULL,
    amount_cents bigint DEFAULT 0 NOT NULL,
    expected_close date,
    owner_id text NOT NULL,
    stage_entered_at timestamp with time zone DEFAULT now() NOT NULL,
    closed_at timestamp with time zone,
    custom_fields jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    deleted_at timestamp with time zone,
    CONSTRAINT workbench_crm_opportunities_amount_cents_check CHECK ((amount_cents >= 0)),
    CONSTRAINT workbench_crm_opportunities_check CHECK (((stage = ANY (ARRAY['won'::text, 'lost'::text])) = (closed_at IS NOT NULL))),
    CONSTRAINT workbench_crm_opportunities_stage_check CHECK ((stage = ANY (ARRAY['qualification'::text, 'proposal'::text, 'negotiation'::text, 'won'::text, 'lost'::text])))
);

CREATE TABLE workbench_crm_opportunity_stage_events (
    tenant_id text NOT NULL,
    event_id text NOT NULL,
    opportunity_id text NOT NULL,
    from_stage text,
    to_stage text NOT NULL,
    amount_cents bigint DEFAULT 0 NOT NULL,
    actor_id text NOT NULL,
    occurred_at timestamp with time zone DEFAULT now() NOT NULL
);

CREATE TABLE workbench_crm_quote_lines (
    tenant_id text NOT NULL,
    quote_id text NOT NULL,
    line_no integer NOT NULL,
    description text NOT NULL,
    qty numeric(12,3) NOT NULL,
    unit_price_cents bigint NOT NULL,
    tax_rate_bp integer DEFAULT 0 NOT NULL,
    line_subtotal_cents bigint NOT NULL,
    line_tax_cents bigint NOT NULL,
    CONSTRAINT workbench_crm_quote_lines_line_no_check CHECK ((line_no >= 1)),
    CONSTRAINT workbench_crm_quote_lines_line_subtotal_cents_check CHECK ((line_subtotal_cents >= 0)),
    CONSTRAINT workbench_crm_quote_lines_line_tax_cents_check CHECK ((line_tax_cents >= 0)),
    CONSTRAINT workbench_crm_quote_lines_qty_check CHECK ((qty > (0)::numeric)),
    CONSTRAINT workbench_crm_quote_lines_tax_rate_bp_check CHECK (((tax_rate_bp >= 0) AND (tax_rate_bp <= 10000))),
    CONSTRAINT workbench_crm_quote_lines_unit_price_cents_check CHECK ((unit_price_cents >= 0))
);

CREATE TABLE workbench_crm_quotes (
    tenant_id text NOT NULL,
    quote_id text NOT NULL,
    account_id text NOT NULL,
    opportunity_id text,
    quote_no text NOT NULL,
    status text DEFAULT 'draft'::text NOT NULL,
    subtotal_cents bigint DEFAULT 0 NOT NULL,
    tax_cents bigint DEFAULT 0 NOT NULL,
    total_cents bigint DEFAULT 0 NOT NULL,
    valid_until date,
    confirmed_at timestamp with time zone,
    converted_contract_id text,
    owner_id text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    deleted_at timestamp with time zone,
    CONSTRAINT workbench_crm_quotes_check CHECK (((status = ANY (ARRAY['confirmed'::text, 'converted'::text])) = (confirmed_at IS NOT NULL))),
    CONSTRAINT workbench_crm_quotes_status_check CHECK ((status = ANY (ARRAY['draft'::text, 'confirmed'::text, 'converted'::text, 'voided'::text]))),
    CONSTRAINT workbench_crm_quotes_subtotal_cents_check CHECK ((subtotal_cents >= 0)),
    CONSTRAINT workbench_crm_quotes_tax_cents_check CHECK ((tax_cents >= 0)),
    CONSTRAINT workbench_crm_quotes_total_cents_check CHECK ((total_cents >= 0))
);

CREATE TABLE workbench_crm_targets (
    tenant_id text NOT NULL,
    target_id text NOT NULL,
    owner_id text NOT NULL,
    period_month date NOT NULL,
    amount_target_cents bigint DEFAULT 0 NOT NULL,
    count_target integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    deleted_at timestamp with time zone,
    CONSTRAINT workbench_crm_targets_amount_target_cents_check CHECK ((amount_target_cents >= 0)),
    CONSTRAINT workbench_crm_targets_count_target_check CHECK ((count_target >= 0))
);

CREATE TABLE workbench_dead_letters (
    event_id text NOT NULL,
    tenant_id text NOT NULL,
    aggregate_type text NOT NULL,
    aggregate_id text NOT NULL,
    version integer NOT NULL,
    sequence bigint NOT NULL,
    dedupe_key text NOT NULL,
    action text NOT NULL,
    payload jsonb DEFAULT '{}'::jsonb NOT NULL,
    attempts integer DEFAULT 1 NOT NULL,
    last_error text NOT NULL,
    occurred_at timestamp with time zone NOT NULL,
    recorded_at timestamp with time zone DEFAULT now() NOT NULL,
    replayed_at timestamp with time zone,
    replayed_by text,
    notified_at timestamp with time zone,
    CONSTRAINT workbench_dead_letters_attempts_check CHECK ((attempts > 0))
);

CREATE TABLE workbench_digital_employees (
    tenant_id text NOT NULL,
    agent_key text NOT NULL,
    name text NOT NULL,
    description text DEFAULT ''::text NOT NULL,
    role_key text NOT NULL,
    status text NOT NULL,
    created_by text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    system_prompt text DEFAULT ''::text NOT NULL,
    model_key text DEFAULT ''::text NOT NULL,
    temperature numeric(3,2) DEFAULT 0.20 NOT NULL,
    tool_allowlist jsonb DEFAULT '[]'::jsonb NOT NULL,
    memory_policy jsonb DEFAULT '{}'::jsonb NOT NULL,
    autonomy_level text DEFAULT 'approval_for_risky'::text NOT NULL,
    risk_threshold text DEFAULT 'high'::text NOT NULL,
    approval_timeout_minutes integer DEFAULT 60 NOT NULL,
    daily_budget_cents bigint DEFAULT 0 NOT NULL,
    CONSTRAINT workbench_digital_employees_approval_timeout_minutes_check CHECK (((approval_timeout_minutes >= 5) AND (approval_timeout_minutes <= 10080))),
    CONSTRAINT workbench_digital_employees_autonomy_level_check CHECK ((autonomy_level = ANY (ARRAY['approval_for_all'::text, 'approval_for_risky'::text, 'full_auto'::text]))),
    CONSTRAINT workbench_digital_employees_daily_budget_cents_check CHECK ((daily_budget_cents >= 0)),
    CONSTRAINT workbench_digital_employees_risk_threshold_check CHECK ((risk_threshold = ANY (ARRAY['low'::text, 'medium'::text, 'high'::text, 'critical'::text]))),
    CONSTRAINT workbench_digital_employees_status_check CHECK ((status = ANY (ARRAY['active'::text, 'disabled'::text]))),
    CONSTRAINT workbench_digital_employees_temperature_check CHECK (((temperature >= 0.00) AND (temperature <= 2.00)))
);

CREATE TABLE workbench_eval_case_results (
    tenant_id text NOT NULL,
    eval_run_id text NOT NULL,
    case_id text NOT NULL,
    passed boolean NOT NULL,
    detail jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

CREATE TABLE workbench_eval_cases (
    tenant_id text NOT NULL,
    case_id text NOT NULL,
    suite_key text NOT NULL,
    source text DEFAULT 'manual'::text NOT NULL,
    status text DEFAULT 'draft'::text NOT NULL,
    input_snapshot jsonb NOT NULL,
    input_digest text NOT NULL,
    expectation jsonb DEFAULT '{}'::jsonb NOT NULL,
    superseded_by text,
    created_by text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT workbench_eval_cases_source_check CHECK ((source = ANY (ARRAY['run_trace'::text, 'manual'::text, 'regression'::text]))),
    CONSTRAINT workbench_eval_cases_status_check CHECK ((status = ANY (ARRAY['draft'::text, 'published'::text, 'archived'::text])))
);

CREATE TABLE workbench_eval_runs (
    tenant_id text NOT NULL,
    eval_run_id text NOT NULL,
    subject text NOT NULL,
    suite_key text NOT NULL,
    suite_digest text NOT NULL,
    status text DEFAULT 'completed'::text NOT NULL,
    case_count integer DEFAULT 0 NOT NULL,
    pass_count integer DEFAULT 0 NOT NULL,
    cost_cents integer DEFAULT 0 NOT NULL,
    created_by text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT workbench_eval_runs_case_count_check CHECK ((case_count >= 0)),
    CONSTRAINT workbench_eval_runs_check CHECK ((pass_count <= case_count)),
    CONSTRAINT workbench_eval_runs_cost_cents_check CHECK ((cost_cents >= 0)),
    CONSTRAINT workbench_eval_runs_pass_count_check CHECK ((pass_count >= 0)),
    CONSTRAINT workbench_eval_runs_status_check CHECK ((status = ANY (ARRAY['completed'::text, 'aborted'::text])))
);

CREATE TABLE workbench_event_outbox (
    event_id text NOT NULL,
    tenant_id text NOT NULL,
    aggregate_type text NOT NULL,
    aggregate_id text NOT NULL,
    version integer NOT NULL,
    sequence bigint NOT NULL,
    dedupe_key text NOT NULL,
    action text NOT NULL,
    payload jsonb DEFAULT '{}'::jsonb NOT NULL,
    occurred_at timestamp with time zone DEFAULT now() NOT NULL,
    published_at timestamp with time zone,
    attempts integer DEFAULT 0 NOT NULL,
    last_error text
);

CREATE TABLE workbench_execution_idempotency (
    tenant_id text NOT NULL,
    actor_id text NOT NULL,
    conversation_id text NOT NULL,
    idempotency_key text NOT NULL,
    message_id text,
    run_id text,
    approval_id text,
    outcome text NOT NULL,
    http_status integer NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT workbench_execution_idempotency_outcome_check CHECK ((outcome = ANY (ARRAY['executed'::text, 'pending_approval'::text, 'rejected'::text, 'failed'::text]))),
    CONSTRAINT workbench_execution_idempotency_result_check CHECK ((((outcome = 'executed'::text) AND (http_status = 201)) OR ((outcome = 'pending_approval'::text) AND (http_status = 202)) OR ((outcome = 'rejected'::text) AND (http_status = ANY (ARRAY[403, 404, 409, 422]))) OR ((outcome = 'failed'::text) AND (http_status = ANY (ARRAY[502, 504])))))
);

CREATE TABLE workbench_inbox_items (
    inbox_id text NOT NULL,
    tenant_id text NOT NULL,
    recipient_id text NOT NULL,
    kind text NOT NULL,
    title text NOT NULL,
    target_type text,
    target_id text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    read_at timestamp with time zone,
    target_conversation_id text,
    target_approval_id text
);

CREATE TABLE workbench_job_roles (
    tenant_id text NOT NULL,
    role_key text NOT NULL,
    name text NOT NULL,
    description text DEFAULT ''::text NOT NULL,
    status text NOT NULL,
    created_by text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT workbench_job_roles_status_check CHECK ((status = ANY (ARRAY['active'::text, 'disabled'::text])))
);

CREATE TABLE workbench_knowledge_access_audits (
    id bigint NOT NULL,
    tenant_id text NOT NULL,
    binding_type text NOT NULL,
    binding_key text NOT NULL,
    old_knowledge_base_ids jsonb DEFAULT '[]'::jsonb NOT NULL,
    new_knowledge_base_ids jsonb DEFAULT '[]'::jsonb NOT NULL,
    actor_id text NOT NULL,
    occurred_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT workbench_knowledge_access_audits_binding_type_check CHECK ((binding_type = ANY (ARRAY['role'::text, 'agent'::text])))
);

CREATE SEQUENCE workbench_knowledge_access_audits_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE workbench_knowledge_access_audits_id_seq OWNED BY workbench_knowledge_access_audits.id;

CREATE TABLE workbench_knowledge_access_bindings (
    tenant_id text NOT NULL,
    binding_type text NOT NULL,
    binding_key text NOT NULL,
    knowledge_base_id text NOT NULL,
    granted_by text NOT NULL,
    granted_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT workbench_knowledge_access_bindings_binding_type_check CHECK ((binding_type = ANY (ARRAY['role'::text, 'agent'::text])))
);

CREATE TABLE workbench_knowledge_documents (
    tenant_id text NOT NULL,
    document_id text NOT NULL,
    title text DEFAULT ''::text NOT NULL,
    owner_id text DEFAULT ''::text NOT NULL,
    status text DEFAULT 'draft'::text NOT NULL,
    version text DEFAULT '1'::text NOT NULL,
    source_key text DEFAULT 'manual'::text NOT NULL,
    last_reviewed_at timestamp with time zone,
    review_due_at timestamp with time zone,
    registered_by text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT workbench_knowledge_documents_status_check CHECK ((status = ANY (ARRAY['draft'::text, 'published'::text, 'under_review'::text, 'needs_review'::text, 'archived'::text])))
);

CREATE TABLE workbench_memory_facts (
    tenant_id text NOT NULL,
    memory_id text NOT NULL,
    owner_kind text NOT NULL,
    owner_id text NOT NULL,
    scope text NOT NULL,
    content text NOT NULL,
    embedding public.vector(1024),
    status text DEFAULT 'active'::text NOT NULL,
    superseded_by text,
    idempotency_key text NOT NULL,
    created_by text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT workbench_memory_facts_owner_kind_check CHECK ((owner_kind = ANY (ARRAY['user'::text, 'agent'::text]))),
    CONSTRAINT workbench_memory_facts_scope_check CHECK ((scope = ANY (ARRAY['user'::text, 'role'::text, 'project'::text, 'organization'::text]))),
    CONSTRAINT workbench_memory_facts_status_check CHECK ((status = ANY (ARRAY['active'::text, 'superseded'::text])))
);

CREATE TABLE workbench_memory_profile_keys (
    tenant_id text NOT NULL,
    owner_kind text NOT NULL,
    owner_id text NOT NULL,
    profile_key text NOT NULL,
    value text NOT NULL,
    created_by text NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT workbench_memory_profile_keys_owner_kind_check CHECK ((owner_kind = ANY (ARRAY['user'::text, 'agent'::text])))
);

CREATE TABLE workbench_memory_rules (
    tenant_id text NOT NULL,
    memory_id text NOT NULL,
    owner_kind text NOT NULL,
    owner_id text NOT NULL,
    scope text NOT NULL,
    content text NOT NULL,
    rule_key text NOT NULL,
    version integer DEFAULT 1 NOT NULL,
    status text DEFAULT 'active'::text NOT NULL,
    superseded_by text,
    created_by text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT workbench_memory_rules_owner_kind_check CHECK ((owner_kind = ANY (ARRAY['user'::text, 'agent'::text]))),
    CONSTRAINT workbench_memory_rules_scope_check CHECK ((scope = ANY (ARRAY['user'::text, 'role'::text, 'project'::text, 'organization'::text]))),
    CONSTRAINT workbench_memory_rules_status_check CHECK ((status = ANY (ARRAY['active'::text, 'superseded'::text])))
);

CREATE TABLE workbench_orchestration_proposals (
    proposal_id text NOT NULL,
    tenant_id text NOT NULL,
    kind text NOT NULL,
    current_value text NOT NULL,
    proposed_value text NOT NULL,
    rationale text NOT NULL,
    metrics_snapshot jsonb DEFAULT '{}'::jsonb NOT NULL,
    status text NOT NULL,
    created_by text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    reviewed_by text,
    reviewed_at timestamp with time zone,
    rejection_reason text,
    CONSTRAINT workbench_orchestration_proposals_status_check CHECK ((status = ANY (ARRAY['pending_review'::text, 'approved'::text, 'rejected'::text])))
);

CREATE TABLE workbench_plan_proposals (
    proposal_id text NOT NULL,
    task_id text NOT NULL,
    tenant_id text NOT NULL,
    goal text NOT NULL,
    steps jsonb DEFAULT '[]'::jsonb NOT NULL,
    generator_key text NOT NULL,
    generator_model text,
    created_by text NOT NULL,
    idempotency_key text NOT NULL,
    status text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    reviewed_by text,
    reviewed_at timestamp with time zone,
    rejection_reason text,
    run_id text,
    CONSTRAINT workbench_plan_proposals_status_check CHECK ((status = ANY (ARRAY['pending_review'::text, 'approved'::text, 'rejected'::text])))
);

CREATE TABLE workbench_plan_versions (
    tenant_id text NOT NULL,
    plan_key text NOT NULL,
    version integer NOT NULL,
    limits jsonb NOT NULL,
    overage_policy jsonb DEFAULT '{}'::jsonb NOT NULL,
    effective_at timestamp with time zone NOT NULL
);

CREATE TABLE workbench_retention_policies (
    tenant_id text NOT NULL,
    policy jsonb NOT NULL,
    updated_by text NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);

CREATE TABLE workbench_run_acceptance_decisions (
    tenant_id text NOT NULL,
    run_id text NOT NULL,
    decision_id text NOT NULL,
    decision text NOT NULL,
    reason text DEFAULT ''::text NOT NULL,
    idempotency_key text NOT NULL,
    decided_by text NOT NULL,
    decided_by_role text NOT NULL,
    structural_verdict text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT workbench_run_acceptance_decisions_decision_check CHECK ((decision = ANY (ARRAY['confirmed'::text, 'rejected'::text]))),
    CONSTRAINT workbench_run_acceptance_decisions_structural_verdict_check CHECK ((structural_verdict = ANY (ARRAY['met'::text, 'unmet'::text]))),
    CONSTRAINT workbench_run_acceptance_reason_required CHECK (((decision <> 'rejected'::text) OR (length(reason) > 0)))
);

CREATE TABLE workbench_run_artifacts (
    tenant_id text NOT NULL,
    run_id text NOT NULL,
    artifact_id text NOT NULL,
    virtual_path text NOT NULL,
    change_kind text NOT NULL,
    bytes bigint DEFAULT 0 NOT NULL,
    sha256 text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    expires_at timestamp with time zone,
    CONSTRAINT workbench_run_artifacts_bytes_check CHECK ((bytes >= 0)),
    CONSTRAINT workbench_run_artifacts_change_kind_check CHECK ((change_kind = ANY (ARRAY['created'::text, 'overwritten'::text, 'deleted'::text])))
);

CREATE TABLE workbench_run_promotions (
    tenant_id text NOT NULL,
    run_id text NOT NULL,
    task_id text NOT NULL,
    title text NOT NULL,
    promoted_by text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

CREATE TABLE workbench_run_records (
    run_id text NOT NULL,
    tenant_id text NOT NULL,
    task_id text NOT NULL,
    proposal_id text,
    runtime_key text NOT NULL,
    status text NOT NULL,
    step_count integer DEFAULT 0 NOT NULL,
    completed_step_count integer DEFAULT 0 NOT NULL,
    tool_calls integer DEFAULT 0 NOT NULL,
    successful_tools integer DEFAULT 0 NOT NULL,
    knowledge_hits integer DEFAULT 0 NOT NULL,
    latency_ms integer DEFAULT 0 NOT NULL,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    finished_at timestamp with time zone,
    finish_reason text,
    execution_authorized_at timestamp with time zone,
    execution_authorized_by text,
    authorized_plan_digest text,
    CONSTRAINT workbench_run_records_execution_authorization_check CHECK ((((execution_authorized_at IS NULL) = (execution_authorized_by IS NULL)) AND ((execution_authorized_at IS NULL) = (authorized_plan_digest IS NULL))))
);

CREATE TABLE workbench_runtime_events (
    run_id text NOT NULL,
    tenant_id text NOT NULL,
    sequence integer NOT NULL,
    event_type text NOT NULL,
    payload jsonb DEFAULT '{}'::jsonb NOT NULL,
    occurred_at timestamp with time zone DEFAULT now() NOT NULL
);

CREATE TABLE workbench_runtime_states (
    run_id text NOT NULL,
    tenant_id text NOT NULL,
    task_id text NOT NULL,
    status text NOT NULL,
    context jsonb NOT NULL,
    plan jsonb NOT NULL,
    completed_steps jsonb DEFAULT '[]'::jsonb NOT NULL,
    approvals jsonb DEFAULT '{}'::jsonb NOT NULL,
    usage jsonb DEFAULT '{}'::jsonb NOT NULL,
    checkpoint jsonb,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    event_count integer DEFAULT 0 NOT NULL
);

CREATE TABLE workbench_skill_bindings (
    tenant_id text NOT NULL,
    agent_key text NOT NULL,
    skill_key text NOT NULL,
    status text DEFAULT 'active'::text NOT NULL,
    created_by text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT workbench_skill_bindings_status_check CHECK ((status = ANY (ARRAY['active'::text, 'disabled'::text])))
);

CREATE TABLE workbench_skills (
    tenant_id text NOT NULL,
    skill_key text NOT NULL,
    version text NOT NULL,
    name text NOT NULL,
    description text NOT NULL,
    license text NOT NULL,
    allowed_tools jsonb NOT NULL,
    status text DEFAULT 'submitted'::text NOT NULL,
    source_key text NOT NULL,
    content_sha256 text NOT NULL,
    owner_id text NOT NULL,
    reviewed_by text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    content_body text DEFAULT ''::text NOT NULL,
    CONSTRAINT workbench_skills_status_check CHECK ((status = ANY (ARRAY['submitted'::text, 'approved'::text, 'rejected'::text, 'enabled'::text, 'disabled'::text])))
);

CREATE TABLE workbench_tasks (
    id text NOT NULL,
    tenant_id text NOT NULL,
    project_id text,
    created_by text NOT NULL,
    employee_key text NOT NULL,
    title text NOT NULL,
    risk_level text NOT NULL,
    budget numeric(18,6),
    idempotency_key text NOT NULL,
    request_fingerprint text NOT NULL,
    status text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    budget_cents bigint,
    CONSTRAINT workbench_tasks_budget_at_least_one CHECK (((budget IS NOT NULL) OR (budget_cents IS NOT NULL))),
    CONSTRAINT workbench_tasks_budget_cents_non_negative CHECK (((budget_cents IS NULL) OR (budget_cents >= 0))),
    CONSTRAINT workbench_tasks_budget_check CHECK ((budget >= (0)::numeric)),
    CONSTRAINT workbench_tasks_risk_level_check CHECK ((risk_level = ANY (ARRAY['low'::text, 'medium'::text, 'high'::text, 'critical'::text]))),
    CONSTRAINT workbench_tasks_status_check CHECK ((status = ANY (ARRAY['queued'::text, 'pending_approval'::text, 'cancelled'::text])))
);

CREATE TABLE workbench_tool_actions (
    tenant_id text NOT NULL,
    action_id text NOT NULL,
    approval_id text,
    run_id text NOT NULL,
    task_id text NOT NULL,
    step_id text NOT NULL,
    tool_key text NOT NULL,
    args_digest text NOT NULL,
    args_json jsonb NOT NULL,
    body_ciphertext bytea,
    body_expires_at timestamp with time zone,
    plan_digest text NOT NULL,
    risk_level text NOT NULL,
    requires_approval boolean NOT NULL,
    status text NOT NULL,
    requested_by text NOT NULL,
    requested_at timestamp with time zone DEFAULT now() NOT NULL,
    decided_by text,
    decided_at timestamp with time zone,
    decision_source text,
    reason_code text,
    CONSTRAINT workbench_tool_actions_body_check CHECK ((((body_ciphertext IS NULL) AND (body_expires_at IS NULL)) OR ((body_ciphertext IS NOT NULL) AND (body_expires_at IS NOT NULL)))),
    CONSTRAINT workbench_tool_actions_decision_check CHECK ((((status = 'pending'::text) AND (decided_by IS NULL) AND (decided_at IS NULL)) OR ((status <> 'pending'::text) AND (decided_by IS NOT NULL) AND (decided_at IS NOT NULL)))),
    CONSTRAINT workbench_tool_actions_risk_level_check CHECK ((risk_level = ANY (ARRAY['low'::text, 'medium'::text, 'high'::text, 'critical'::text]))),
    CONSTRAINT workbench_tool_actions_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'approved'::text, 'rejected'::text, 'expired'::text])))
);

CREATE TABLE workbench_usage_ledger (
    id text NOT NULL,
    tenant_id text NOT NULL,
    idempotency_key text NOT NULL,
    units bigint NOT NULL,
    cost_cents bigint NOT NULL,
    reversal_of text,
    reason text,
    actor_id text,
    occurred_at timestamp with time zone DEFAULT now() NOT NULL
);

CREATE TABLE workbench_workspaces (
    id text NOT NULL,
    tenant_id text NOT NULL,
    name text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

ALTER TABLE ONLY workbench_audit_events ALTER COLUMN id SET DEFAULT nextval('workbench_audit_events_id_seq'::regclass);

ALTER TABLE ONLY workbench_knowledge_access_audits ALTER COLUMN id SET DEFAULT nextval('workbench_knowledge_access_audits_id_seq'::regclass);

ALTER TABLE ONLY workbench_accounts
    ADD CONSTRAINT workbench_accounts_phone_key UNIQUE (phone);

ALTER TABLE ONLY workbench_accounts
    ADD CONSTRAINT workbench_accounts_pkey PRIMARY KEY (account_id);

ALTER TABLE ONLY workbench_audit_events
    ADD CONSTRAINT workbench_audit_events_pkey PRIMARY KEY (id);

ALTER TABLE ONLY workbench_content_publications
    ADD CONSTRAINT workbench_content_publications_pkey PRIMARY KEY (publication_id);

ALTER TABLE ONLY workbench_content_publications
    ADD CONSTRAINT workbench_content_publications_tenant_id_idempotency_key_key UNIQUE (tenant_id, idempotency_key);

ALTER TABLE ONLY workbench_conversation_members
    ADD CONSTRAINT workbench_conversation_members_pkey PRIMARY KEY (tenant_id, conversation_id, member_id);

ALTER TABLE ONLY workbench_conversation_messages
    ADD CONSTRAINT workbench_conversation_messages_pkey PRIMARY KEY (tenant_id, message_id);

ALTER TABLE ONLY workbench_conversation_stream_frames
    ADD CONSTRAINT workbench_conversation_stream_frames_pkey PRIMARY KEY (tenant_id, conversation_id, run_id, seq);

ALTER TABLE ONLY workbench_conversation_stream_state
    ADD CONSTRAINT workbench_conversation_stream_state_pkey PRIMARY KEY (tenant_id, conversation_id, run_id);

ALTER TABLE ONLY workbench_conversations
    ADD CONSTRAINT workbench_conversations_pkey PRIMARY KEY (tenant_id, conversation_id);

ALTER TABLE ONLY workbench_crm_accounts
    ADD CONSTRAINT workbench_crm_accounts_pkey PRIMARY KEY (tenant_id, account_id);

ALTER TABLE ONLY workbench_crm_activities
    ADD CONSTRAINT workbench_crm_activities_pkey PRIMARY KEY (tenant_id, activity_id);

ALTER TABLE ONLY workbench_crm_contacts
    ADD CONSTRAINT workbench_crm_contacts_pkey PRIMARY KEY (tenant_id, contact_id);

ALTER TABLE ONLY workbench_crm_contracts
    ADD CONSTRAINT workbench_crm_contracts_pkey PRIMARY KEY (tenant_id, contract_id);

ALTER TABLE ONLY workbench_crm_contracts
    ADD CONSTRAINT workbench_crm_contracts_tenant_id_contract_no_key UNIQUE (tenant_id, contract_no);

ALTER TABLE ONLY workbench_crm_field_defs
    ADD CONSTRAINT workbench_crm_field_defs_pkey PRIMARY KEY (tenant_id, object_key, field_key);

ALTER TABLE ONLY workbench_crm_insights
    ADD CONSTRAINT workbench_crm_insights_pkey PRIMARY KEY (tenant_id, insight_id);

ALTER TABLE ONLY workbench_crm_leads
    ADD CONSTRAINT workbench_crm_leads_pkey PRIMARY KEY (tenant_id, lead_id);

ALTER TABLE ONLY workbench_crm_opportunities
    ADD CONSTRAINT workbench_crm_opportunities_pkey PRIMARY KEY (tenant_id, opportunity_id);

ALTER TABLE ONLY workbench_crm_opportunity_stage_events
    ADD CONSTRAINT workbench_crm_opportunity_stage_events_pkey PRIMARY KEY (tenant_id, event_id);

ALTER TABLE ONLY workbench_crm_quote_lines
    ADD CONSTRAINT workbench_crm_quote_lines_pkey PRIMARY KEY (tenant_id, quote_id, line_no);

ALTER TABLE ONLY workbench_crm_quotes
    ADD CONSTRAINT workbench_crm_quotes_pkey PRIMARY KEY (tenant_id, quote_id);

ALTER TABLE ONLY workbench_crm_quotes
    ADD CONSTRAINT workbench_crm_quotes_tenant_id_quote_no_key UNIQUE (tenant_id, quote_no);

ALTER TABLE ONLY workbench_crm_targets
    ADD CONSTRAINT workbench_crm_targets_pkey PRIMARY KEY (tenant_id, target_id);

ALTER TABLE ONLY workbench_crm_targets
    ADD CONSTRAINT workbench_crm_targets_tenant_id_owner_id_period_month_key UNIQUE (tenant_id, owner_id, period_month);

ALTER TABLE ONLY workbench_dead_letters
    ADD CONSTRAINT workbench_dead_letters_pkey PRIMARY KEY (event_id);

ALTER TABLE ONLY workbench_dead_letters
    ADD CONSTRAINT workbench_dead_letters_tenant_id_dedupe_key_key UNIQUE (tenant_id, dedupe_key);

ALTER TABLE ONLY workbench_digital_employees
    ADD CONSTRAINT workbench_digital_employees_pkey PRIMARY KEY (tenant_id, agent_key);

ALTER TABLE ONLY workbench_eval_case_results
    ADD CONSTRAINT workbench_eval_case_results_pkey PRIMARY KEY (tenant_id, eval_run_id, case_id);

ALTER TABLE ONLY workbench_eval_cases
    ADD CONSTRAINT workbench_eval_cases_pkey PRIMARY KEY (tenant_id, case_id);

ALTER TABLE ONLY workbench_eval_runs
    ADD CONSTRAINT workbench_eval_runs_pkey PRIMARY KEY (tenant_id, eval_run_id);

ALTER TABLE ONLY workbench_event_outbox
    ADD CONSTRAINT workbench_event_outbox_dedupe_key_key UNIQUE (dedupe_key);

ALTER TABLE ONLY workbench_event_outbox
    ADD CONSTRAINT workbench_event_outbox_pkey PRIMARY KEY (event_id);

ALTER TABLE ONLY workbench_execution_idempotency
    ADD CONSTRAINT workbench_execution_idempotency_pkey PRIMARY KEY (tenant_id, actor_id, conversation_id, idempotency_key);

ALTER TABLE ONLY workbench_inbox_items
    ADD CONSTRAINT workbench_inbox_items_pkey PRIMARY KEY (inbox_id);

ALTER TABLE ONLY workbench_job_roles
    ADD CONSTRAINT workbench_job_roles_pkey PRIMARY KEY (tenant_id, role_key);

ALTER TABLE ONLY workbench_knowledge_access_audits
    ADD CONSTRAINT workbench_knowledge_access_audits_pkey PRIMARY KEY (id);

ALTER TABLE ONLY workbench_knowledge_access_bindings
    ADD CONSTRAINT workbench_knowledge_access_bindings_pkey PRIMARY KEY (tenant_id, binding_type, binding_key, knowledge_base_id);

ALTER TABLE ONLY workbench_knowledge_documents
    ADD CONSTRAINT workbench_knowledge_documents_pkey PRIMARY KEY (tenant_id, document_id);

ALTER TABLE ONLY workbench_memory_facts
    ADD CONSTRAINT workbench_memory_facts_pkey PRIMARY KEY (tenant_id, memory_id);

ALTER TABLE ONLY workbench_memory_profile_keys
    ADD CONSTRAINT workbench_memory_profile_keys_pkey PRIMARY KEY (tenant_id, owner_kind, owner_id, profile_key);

ALTER TABLE ONLY workbench_memory_rules
    ADD CONSTRAINT workbench_memory_rules_pkey PRIMARY KEY (tenant_id, memory_id);

ALTER TABLE ONLY workbench_orchestration_proposals
    ADD CONSTRAINT workbench_orchestration_proposals_pkey PRIMARY KEY (proposal_id);

ALTER TABLE ONLY workbench_plan_proposals
    ADD CONSTRAINT workbench_plan_proposals_pkey PRIMARY KEY (proposal_id);

ALTER TABLE ONLY workbench_plan_proposals
    ADD CONSTRAINT workbench_plan_proposals_tenant_id_task_id_idempotency_key_key UNIQUE (tenant_id, task_id, idempotency_key);

ALTER TABLE ONLY workbench_plan_versions
    ADD CONSTRAINT workbench_plan_versions_pkey PRIMARY KEY (tenant_id, plan_key, version);

ALTER TABLE ONLY workbench_retention_policies
    ADD CONSTRAINT workbench_retention_policies_pkey PRIMARY KEY (tenant_id);

ALTER TABLE ONLY workbench_run_acceptance_decisions
    ADD CONSTRAINT workbench_run_acceptance_decisions_pkey PRIMARY KEY (tenant_id, run_id, decision_id);

ALTER TABLE ONLY workbench_run_acceptance_decisions
    ADD CONSTRAINT workbench_run_acceptance_idem_unique UNIQUE (tenant_id, idempotency_key);

ALTER TABLE ONLY workbench_run_artifacts
    ADD CONSTRAINT workbench_run_artifacts_pkey PRIMARY KEY (tenant_id, run_id, artifact_id);

ALTER TABLE ONLY workbench_run_promotions
    ADD CONSTRAINT workbench_run_promotions_pkey PRIMARY KEY (tenant_id, run_id);

ALTER TABLE ONLY workbench_run_records
    ADD CONSTRAINT workbench_run_records_pkey PRIMARY KEY (run_id);

ALTER TABLE ONLY workbench_run_records
    ADD CONSTRAINT workbench_run_records_run_tenant_unique UNIQUE (run_id, tenant_id);

ALTER TABLE ONLY workbench_runtime_events
    ADD CONSTRAINT workbench_runtime_events_pkey PRIMARY KEY (run_id, sequence);

ALTER TABLE ONLY workbench_runtime_states
    ADD CONSTRAINT workbench_runtime_states_pkey PRIMARY KEY (run_id);

ALTER TABLE ONLY workbench_skill_bindings
    ADD CONSTRAINT workbench_skill_bindings_pkey PRIMARY KEY (tenant_id, agent_key, skill_key);

ALTER TABLE ONLY workbench_skills
    ADD CONSTRAINT workbench_skills_pkey PRIMARY KEY (tenant_id, skill_key, version);

ALTER TABLE ONLY workbench_tasks
    ADD CONSTRAINT workbench_tasks_id_tenant_id_key UNIQUE (id, tenant_id);

ALTER TABLE ONLY workbench_tasks
    ADD CONSTRAINT workbench_tasks_pkey PRIMARY KEY (id);

ALTER TABLE ONLY workbench_tasks
    ADD CONSTRAINT workbench_tasks_tenant_id_created_by_idempotency_key_key UNIQUE (tenant_id, created_by, idempotency_key);

ALTER TABLE ONLY workbench_tool_actions
    ADD CONSTRAINT workbench_tool_actions_pkey PRIMARY KEY (tenant_id, action_id);

ALTER TABLE ONLY workbench_usage_ledger
    ADD CONSTRAINT workbench_usage_ledger_pkey PRIMARY KEY (id);

ALTER TABLE ONLY workbench_usage_ledger
    ADD CONSTRAINT workbench_usage_ledger_tenant_id_idempotency_key_key UNIQUE (tenant_id, idempotency_key);

ALTER TABLE ONLY workbench_workspaces
    ADD CONSTRAINT workbench_workspaces_pkey PRIMARY KEY (id);

ALTER TABLE ONLY workbench_workspaces
    ADD CONSTRAINT workbench_workspaces_tenant_id_id_key UNIQUE (tenant_id, id);

CREATE INDEX idx_eval_cases_digest ON workbench_eval_cases USING btree (tenant_id, suite_key, input_digest);

CREATE INDEX idx_eval_cases_suite ON workbench_eval_cases USING btree (tenant_id, suite_key, status);

CREATE INDEX idx_knowledge_docs_review_due ON workbench_knowledge_documents USING btree (tenant_id, status, review_due_at);

CREATE INDEX idx_knowledge_docs_status ON workbench_knowledge_documents USING btree (tenant_id, status);

CREATE INDEX idx_memory_facts_hnsw ON workbench_memory_facts USING hnsw (embedding public.vector_cosine_ops);

CREATE INDEX idx_memory_facts_owner ON workbench_memory_facts USING btree (tenant_id, owner_kind, owner_id, scope, status);

CREATE INDEX idx_memory_profile_keys_owner ON workbench_memory_profile_keys USING btree (tenant_id, owner_kind, owner_id);

CREATE UNIQUE INDEX idx_memory_rules_active_by_key ON workbench_memory_rules USING btree (tenant_id, owner_kind, owner_id, rule_key) WHERE (status = 'active'::text);

CREATE INDEX idx_memory_rules_owner ON workbench_memory_rules USING btree (tenant_id, owner_kind, owner_id, scope, status);

CREATE INDEX idx_wb_crm_accounts_owner ON workbench_crm_accounts USING btree (tenant_id, owner_id, status) WHERE (deleted_at IS NULL);

CREATE INDEX idx_wb_crm_activities_due ON workbench_crm_activities USING btree (tenant_id, owner_id, due_at) WHERE ((status = 'planned'::text) AND (deleted_at IS NULL));

CREATE INDEX idx_wb_crm_activities_timeline ON workbench_crm_activities USING btree (tenant_id, account_id, occurred_at DESC);

CREATE INDEX idx_wb_crm_contacts_account ON workbench_crm_contacts USING btree (tenant_id, account_id) WHERE (deleted_at IS NULL);

CREATE INDEX idx_wb_crm_stage_events_opportunity ON workbench_crm_opportunity_stage_events USING btree (tenant_id, opportunity_id, occurred_at);

CREATE INDEX idx_wb_run_acceptance_run ON workbench_run_acceptance_decisions USING btree (tenant_id, run_id, created_at DESC, decision_id);

CREATE INDEX idx_wb_run_artifacts_expires ON workbench_run_artifacts USING btree (expires_at);

CREATE INDEX idx_wb_run_artifacts_run ON workbench_run_artifacts USING btree (tenant_id, run_id, created_at, artifact_id);

CREATE INDEX idx_wb_stream_frames_created_at ON workbench_conversation_stream_frames USING btree (created_at);

CREATE INDEX idx_wb_stream_frames_replay ON workbench_conversation_stream_frames USING btree (tenant_id, conversation_id, run_id, seq);

CREATE INDEX idx_wb_stream_state_expires ON workbench_conversation_stream_state USING btree (expires_at);

CREATE INDEX idx_wb_stream_state_stalled ON workbench_conversation_stream_state USING btree (status, updated_at);

CREATE INDEX idx_workbench_accounts_status ON workbench_accounts USING btree (status, requested_at DESC);

CREATE INDEX idx_workbench_content_publications_task ON workbench_content_publications USING btree (tenant_id, task_id, created_at DESC);

CREATE INDEX idx_workbench_conversation_members_member ON workbench_conversation_members USING btree (tenant_id, member_id);

CREATE INDEX idx_workbench_conversation_messages_conversation ON workbench_conversation_messages USING btree (tenant_id, conversation_id, created_at);

CREATE INDEX idx_workbench_conversations_operator ON workbench_conversations USING btree (tenant_id, operator_id, status);

CREATE INDEX idx_workbench_dead_letters_pending ON workbench_dead_letters USING btree (tenant_id, recorded_at) WHERE (replayed_at IS NULL);

CREATE INDEX idx_workbench_digital_employees_role ON workbench_digital_employees USING btree (tenant_id, role_key);

CREATE INDEX idx_workbench_event_outbox_pending ON workbench_event_outbox USING btree (published_at, occurred_at) WHERE (published_at IS NULL);

CREATE INDEX idx_workbench_execution_idempotency_run ON workbench_execution_idempotency USING btree (tenant_id, run_id) WHERE (run_id IS NOT NULL);

CREATE INDEX idx_workbench_inbox_items_created_at ON workbench_inbox_items USING btree (created_at);

CREATE INDEX idx_workbench_inbox_items_recipient ON workbench_inbox_items USING btree (tenant_id, recipient_id, created_at DESC);

CREATE INDEX idx_workbench_inbox_items_unread ON workbench_inbox_items USING btree (tenant_id, recipient_id, read_at);

CREATE INDEX idx_workbench_job_roles_status ON workbench_job_roles USING btree (tenant_id, status);

CREATE INDEX idx_workbench_knowledge_access_audits_lookup ON workbench_knowledge_access_audits USING btree (tenant_id, occurred_at DESC);

CREATE INDEX idx_workbench_knowledge_access_lookup ON workbench_knowledge_access_bindings USING btree (tenant_id, binding_type, binding_key);

CREATE INDEX idx_workbench_orchestration_proposals_created ON workbench_orchestration_proposals USING btree (tenant_id, created_at DESC);

CREATE INDEX idx_workbench_orchestration_proposals_status ON workbench_orchestration_proposals USING btree (tenant_id, status);

CREATE INDEX idx_workbench_plan_proposals_status ON workbench_plan_proposals USING btree (tenant_id, status);

CREATE INDEX idx_workbench_plan_proposals_task ON workbench_plan_proposals USING btree (tenant_id, task_id, created_at DESC);

CREATE INDEX idx_workbench_run_records_runtime ON workbench_run_records USING btree (tenant_id, runtime_key);

CREATE INDEX idx_workbench_run_records_task ON workbench_run_records USING btree (tenant_id, task_id, started_at DESC);

CREATE INDEX idx_workbench_runtime_events_occurred_at ON workbench_runtime_events USING btree (occurred_at);

CREATE INDEX idx_workbench_runtime_events_tenant_run ON workbench_runtime_events USING btree (tenant_id, run_id, sequence);

CREATE INDEX idx_workbench_runtime_states_task ON workbench_runtime_states USING btree (tenant_id, task_id);

CREATE INDEX idx_workbench_runtime_states_tenant ON workbench_runtime_states USING btree (tenant_id, created_at DESC);

CREATE INDEX idx_workbench_skill_bindings_skill ON workbench_skill_bindings USING btree (tenant_id, skill_key, status);

CREATE INDEX idx_workbench_skills_status ON workbench_skills USING btree (tenant_id, status);

CREATE INDEX idx_workbench_tasks_tenant_created ON workbench_tasks USING btree (tenant_id, created_at DESC);

CREATE UNIQUE INDEX idx_workbench_tool_actions_approval ON workbench_tool_actions USING btree (tenant_id, run_id, approval_id) WHERE (approval_id IS NOT NULL);

CREATE UNIQUE INDEX idx_workbench_tool_actions_pending_unique ON workbench_tool_actions USING btree (tenant_id, run_id, step_id) WHERE (status = 'pending'::text);

CREATE INDEX idx_workbench_tool_actions_run ON workbench_tool_actions USING btree (tenant_id, run_id, requested_at DESC);

CREATE INDEX idx_workbench_usage_tenant_time ON workbench_usage_ledger USING btree (tenant_id, occurred_at);

ALTER TABLE ONLY workbench_audit_events
    ADD CONSTRAINT workbench_audit_events_task_id_fkey FOREIGN KEY (task_id) REFERENCES workbench_tasks(id) ON DELETE CASCADE;

ALTER TABLE ONLY workbench_audit_events
    ADD CONSTRAINT workbench_audit_events_task_id_tenant_id_fkey FOREIGN KEY (task_id, tenant_id) REFERENCES workbench_tasks(id, tenant_id) ON DELETE CASCADE;

ALTER TABLE ONLY workbench_conversation_members
    ADD CONSTRAINT workbench_conversation_members_tenant_id_conversation_id_fkey FOREIGN KEY (tenant_id, conversation_id) REFERENCES workbench_conversations(tenant_id, conversation_id) ON DELETE CASCADE;

ALTER TABLE ONLY workbench_conversation_messages
    ADD CONSTRAINT workbench_conversation_messages_tenant_id_conversation_id_fkey FOREIGN KEY (tenant_id, conversation_id) REFERENCES workbench_conversations(tenant_id, conversation_id);

ALTER TABLE ONLY workbench_conversation_stream_frames
    ADD CONSTRAINT workbench_conversation_stream_fr_tenant_id_conversation_id_fkey FOREIGN KEY (tenant_id, conversation_id) REFERENCES workbench_conversations(tenant_id, conversation_id);

ALTER TABLE ONLY workbench_conversation_stream_state
    ADD CONSTRAINT workbench_conversation_stream_st_tenant_id_conversation_id_fkey FOREIGN KEY (tenant_id, conversation_id) REFERENCES workbench_conversations(tenant_id, conversation_id);

ALTER TABLE ONLY workbench_crm_activities
    ADD CONSTRAINT workbench_crm_activities_tenant_id_account_id_fkey FOREIGN KEY (tenant_id, account_id) REFERENCES workbench_crm_accounts(tenant_id, account_id);

ALTER TABLE ONLY workbench_crm_activities
    ADD CONSTRAINT workbench_crm_activities_tenant_id_contact_id_fkey FOREIGN KEY (tenant_id, contact_id) REFERENCES workbench_crm_contacts(tenant_id, contact_id);

ALTER TABLE ONLY workbench_crm_activities
    ADD CONSTRAINT workbench_crm_activities_tenant_id_opportunity_id_fkey FOREIGN KEY (tenant_id, opportunity_id) REFERENCES workbench_crm_opportunities(tenant_id, opportunity_id);

ALTER TABLE ONLY workbench_crm_contacts
    ADD CONSTRAINT workbench_crm_contacts_tenant_id_account_id_fkey FOREIGN KEY (tenant_id, account_id) REFERENCES workbench_crm_accounts(tenant_id, account_id);

ALTER TABLE ONLY workbench_crm_contracts
    ADD CONSTRAINT workbench_crm_contracts_tenant_id_account_id_fkey FOREIGN KEY (tenant_id, account_id) REFERENCES workbench_crm_accounts(tenant_id, account_id);

ALTER TABLE ONLY workbench_crm_contracts
    ADD CONSTRAINT workbench_crm_contracts_tenant_id_opportunity_id_fkey FOREIGN KEY (tenant_id, opportunity_id) REFERENCES workbench_crm_opportunities(tenant_id, opportunity_id);

ALTER TABLE ONLY workbench_crm_contracts
    ADD CONSTRAINT workbench_crm_contracts_tenant_id_quote_id_fkey FOREIGN KEY (tenant_id, quote_id) REFERENCES workbench_crm_quotes(tenant_id, quote_id);

ALTER TABLE ONLY workbench_crm_insights
    ADD CONSTRAINT workbench_crm_insights_tenant_id_account_id_fkey FOREIGN KEY (tenant_id, account_id) REFERENCES workbench_crm_accounts(tenant_id, account_id);

ALTER TABLE ONLY workbench_crm_opportunities
    ADD CONSTRAINT workbench_crm_opportunities_tenant_id_account_id_fkey FOREIGN KEY (tenant_id, account_id) REFERENCES workbench_crm_accounts(tenant_id, account_id);

ALTER TABLE ONLY workbench_crm_opportunity_stage_events
    ADD CONSTRAINT workbench_crm_opportunity_stage_e_tenant_id_opportunity_id_fkey FOREIGN KEY (tenant_id, opportunity_id) REFERENCES workbench_crm_opportunities(tenant_id, opportunity_id);

ALTER TABLE ONLY workbench_crm_quote_lines
    ADD CONSTRAINT workbench_crm_quote_lines_tenant_id_quote_id_fkey FOREIGN KEY (tenant_id, quote_id) REFERENCES workbench_crm_quotes(tenant_id, quote_id);

ALTER TABLE ONLY workbench_crm_quotes
    ADD CONSTRAINT workbench_crm_quotes_tenant_id_account_id_fkey FOREIGN KEY (tenant_id, account_id) REFERENCES workbench_crm_accounts(tenant_id, account_id);

ALTER TABLE ONLY workbench_crm_quotes
    ADD CONSTRAINT workbench_crm_quotes_tenant_id_opportunity_id_fkey FOREIGN KEY (tenant_id, opportunity_id) REFERENCES workbench_crm_opportunities(tenant_id, opportunity_id);

ALTER TABLE ONLY workbench_digital_employees
    ADD CONSTRAINT workbench_digital_employees_tenant_id_role_key_fkey FOREIGN KEY (tenant_id, role_key) REFERENCES workbench_job_roles(tenant_id, role_key);

ALTER TABLE ONLY workbench_eval_case_results
    ADD CONSTRAINT workbench_eval_case_results_tenant_id_case_id_fkey FOREIGN KEY (tenant_id, case_id) REFERENCES workbench_eval_cases(tenant_id, case_id);

ALTER TABLE ONLY workbench_eval_case_results
    ADD CONSTRAINT workbench_eval_case_results_tenant_id_eval_run_id_fkey FOREIGN KEY (tenant_id, eval_run_id) REFERENCES workbench_eval_runs(tenant_id, eval_run_id);

ALTER TABLE ONLY workbench_execution_idempotency
    ADD CONSTRAINT workbench_execution_idempotency_tenant_id_conversation_id_fkey FOREIGN KEY (tenant_id, conversation_id) REFERENCES workbench_conversations(tenant_id, conversation_id);

ALTER TABLE ONLY workbench_execution_idempotency
    ADD CONSTRAINT workbench_execution_idempotency_tenant_id_message_id_fkey FOREIGN KEY (tenant_id, message_id) REFERENCES workbench_conversation_messages(tenant_id, message_id);

ALTER TABLE ONLY workbench_execution_idempotency
    ADD CONSTRAINT workbench_execution_idempotency_tenant_id_run_id_fkey FOREIGN KEY (tenant_id, run_id) REFERENCES workbench_run_records(tenant_id, run_id);

ALTER TABLE ONLY workbench_plan_versions
    ADD CONSTRAINT workbench_plan_versions_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES ${PLATFORM_SCHEMA}.workbench_tenants(id);

ALTER TABLE ONLY workbench_retention_policies
    ADD CONSTRAINT workbench_retention_policies_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES ${PLATFORM_SCHEMA}.workbench_tenants(id);

ALTER TABLE ONLY workbench_run_acceptance_decisions
    ADD CONSTRAINT workbench_run_acceptance_decisions_tenant_id_run_id_fkey FOREIGN KEY (tenant_id, run_id) REFERENCES workbench_run_records(tenant_id, run_id);

ALTER TABLE ONLY workbench_run_artifacts
    ADD CONSTRAINT workbench_run_artifacts_tenant_id_run_id_fkey FOREIGN KEY (tenant_id, run_id) REFERENCES workbench_run_records(tenant_id, run_id);

ALTER TABLE ONLY workbench_run_promotions
    ADD CONSTRAINT workbench_run_promotions_tenant_id_run_id_fkey FOREIGN KEY (tenant_id, run_id) REFERENCES workbench_run_records(tenant_id, run_id) ON DELETE CASCADE;

ALTER TABLE ONLY workbench_tool_actions
    ADD CONSTRAINT workbench_tool_actions_tenant_id_run_id_fkey FOREIGN KEY (tenant_id, run_id) REFERENCES workbench_run_records(tenant_id, run_id);

ALTER TABLE ONLY workbench_usage_ledger
    ADD CONSTRAINT workbench_usage_ledger_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES ${PLATFORM_SCHEMA}.workbench_tenants(id);

ALTER TABLE ONLY workbench_workspaces
    ADD CONSTRAINT workbench_workspaces_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES ${PLATFORM_SCHEMA}.workbench_tenants(id);
