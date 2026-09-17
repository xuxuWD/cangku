from __future__ import annotations

import atexit
import hashlib
import json
import logging
import time
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import NoReturn

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .audit.logging import configure_audit_logging
from .audit.models import AuditAction
from .audit.redaction import mask_phone
from .bootstrap import allowed_tool_names, build_account_service, build_agent_config_service, build_audit_service, build_commercial_components, build_content_generator, build_content_publisher, build_content_scraper, build_content_store, build_conversation_execution_service, build_conversation_member_store, build_conversation_service, build_conversation_store, build_conversation_stream_store, build_conversation_stream_writer, build_crm_service, build_dead_letter_store, build_event_bus, build_evolution_service, build_exec_callback_guard, build_execution_idempotency_store, build_inbox_service, build_knowledge_access_registry, build_knowledge_governance_service, build_login_rate_limiter, build_memory_service, build_orchestration_proposal_service, build_planner_service, build_publication_service, build_run_metrics, build_runtime_service, build_runtime_state_store, build_run_artifact_store, build_session_revocation_store, build_skills_service, build_task_repository, build_tool_action_store, build_tool_execution, build_weknora_search_runtime, build_workforce_directory_store, registered_model_keys
from .events import EventEnvelope
from .inbox import InboxItem, InboxNotFound
# P5a CRM（真源 specs/2026-09-17-crm-p5a-design.md §2.12）：路由层只做校验 / 视图 / 异常映射。
from .crm.followup import FollowupPlanError
from .crm.masking import mask_record
from .crm.models import CrmNotFound, CrmStateConflict, InvalidCrm
from .domain import (
    AuditEvent,
    IdempotencyConflict,
    PolicyError,
    RiskLevel,
    Task,
    TaskNotFound,
    TaskStatus,
    TaskStateConflict,
    UserContext,
    ensure_can_approve,
    ensure_can_create,
)
from .accounts.models import (
    AccountConflict,
    AccountNotFound,
    AccountStateConflict,
    AccountStatus,
    BootstrapDenied,
    LoginFailed,
    RegistrationRequest,
    TotpInvalid,
    TotpNotEnrolled,
    TotpRequired,
)
from .accounts.passwords import PasswordPolicyError
from .accounts.rate_limit import LoginRateLimited
from .accounts.sso import SsoError, SsoNotConfigured
from .accounts.sso_store import SsoStateNotFound
from .auth import FULL_SCOPE, SSO_PENDING_SCOPE, TOTP_ENROLLMENT_SCOPE, create_access_token, verify_access_token
from .settings import get_settings, resolve_cors_options, validate_runtime_settings
from .runtime.authorization import ExecutionNotAuthorized
from .runtime.contracts import ApprovalAlreadyDecided, ApprovalNotFound, RunNotDecidable, RuntimeEventType
from .tool_execution.errors import ToolExecutionError
from .tool_execution.catalog import build_tool_spec_catalog
from .tool_execution.active_execution import ActiveExecutionRegistry
from .tool_execution.callback_guard import CallbackRateLimiter, shared_secret_matches
from .tool_execution.token_binding import BindingDenied, TokenBindingStore
from .tool_execution.cleanup import build_body_cleanup_task, build_orphan_cleanup_task
from .runtime.policy import ApprovalRequired, PolicyDenied
from .runtime.acceptance import evaluate_acceptance
from .runtime.records import FinishReason, RunRecordNotFound
from .runtime.service import RunAccessDenied, RunApprovalDenied
from .content.models import ContentBriefInput, ContentStatus, SourceInput
from .content.service import ContentNotFound, ContentService, ExportNotAllowed, RevisionConflict, ScrapeNotConfigured
from .content.scraper import ScrapeDenied, ScrapeFailed
from .content.publication_service import PublicationNotAllowed
from .content.publication_store import PublicationNotFound
from .content.publisher import PublicationFailed, PublicationNotConfigured
from .commercial.lifecycle import (
    CommercialLifecycleService,
    DeletionNotPending,
    ExportPackageExpired,
    LifecycleJob,
)
from .commercial.repository import ResourceNotFound
from .commercial.tenant import Actor, CommercialPolicyError
from .agent_services import ModelNotAllowed
from .approvals import ApprovalsService
from .planner.models import (
    PlanGenerationError,
    PlanProposalNotFound,
    PlanProposalStateConflict,
    PlannerAccessDenied,
    PlannerNotConfigured,
    UnknownTool,
)
from .orchestration.models import (
    OrchestrationProposalNotFound,
    OrchestrationProposalStateConflict,
)
from .workforce import (
    DigitalEmployee,
    DirectoryConflict,
    DirectoryError,
    DirectoryNotFound,
    DirectoryNotManaged,
    InvalidDirectoryKey,
    InvalidDirectoryName,
    JobRole,
    RoleNotAvailable,
    WorkforceDirectoryService,
)
from .memory.models import (
    InvalidMemory,
    MemoryBudgetExceeded,
    MemoryFact,
    MemoryNotFound,
    MemoryRule,
    MemoryStateConflict,
)
from .memory.embedding import EmbeddingUnavailable
from .memory.service import MemoryService
from .skills.models import (
    InvalidSkillPackage,
    Skill,
    SkillMemoryUnavailable,
    SkillNotFound,
    SkillSourceDenied,
    SkillStateConflict,
)
from .skills.service import SkillService
from .evolution.models import (
    EvalCase,
    EvalCaseNotFound,
    EvalCaseStateConflict,
    EvalCostExceeded,
    EvalDisabled,
    EvalRun,
    EvalSuiteEmpty,
    EvalSuiteTooLarge,
    InvalidEvalCase,
    UnknownEvalSubject,
)
from .evolution.service import EvolutionService
from .knowledge_governance.models import (
    InvalidKnowledgeDoc,
    KnowledgeDoc,
    KnowledgeDocNotFound,
    KnowledgeDocStateConflict,
    ensure_can_read_metrics as ensure_knowledge_metrics_read,
)
from .knowledge_governance.scoped_search import build_scoped_search
from .knowledge_governance.service import KnowledgeGovernanceService
from .conversation import (
    Conversation,
    ConversationMessage,
    ConversationNotFound,
    ConversationStateConflict,
    ConversationStatus,
    InvalidConversation,
    MessageRole,
    ensure_can_converse,
    normalize_mode,
)
from .conversation.execution import (
    ConversationExecutionError,
    bounded_output_fields,
    summary_digest,
)
from .conversation.stream import (
    REASON_STALLED,
    STATUS_UNAVAILABLE,
    UNAVAILABLE_KIND,
)


app = FastAPI(title="公司数字员工工作台", version="0.1.0")
logger = logging.getLogger(__name__)
settings = get_settings()
validate_runtime_settings(settings)
# 跨源部署：development 走本机来源正则；其他环境仅在显式配置允许来源时注册 CORS。
cors_options = resolve_cors_options(settings)
if cors_options is not None:
    app.add_middleware(CORSMiddleware, **cors_options)
configure_audit_logging(settings.log_level)
audit_service = build_audit_service(settings)
login_rate_limiter = build_login_rate_limiter(settings)
session_revocation_store = build_session_revocation_store(settings)
inbox_service = build_inbox_service(settings, audit=audit_service)
store = build_task_repository(settings)
event_bus = build_event_bus(settings)
dead_letter_store = build_dead_letter_store(settings, event_bus=event_bus, audit=audit_service)
knowledge_access_registry = build_knowledge_access_registry(settings)
# 知识治理层（规格 docs/superpowers/specs/2026-09-15-knowledge-governance-design.md §2）：
# 总开关默认 false（fail-closed）——关闭时不作文档级过滤，保持既有检索行为。
knowledge_governance_service = build_knowledge_governance_service(settings, audit=audit_service)
# 知识检索入口（规格 §2.3 接线）：WeKnora 只读服务运行时。未配置 ⇒ None（端点 503）；
# 只配一半 ⇒ 装配期抛错（起栈即失败）。客户端共享，适配器按请求构造（见运行时容器）。
weknora_search_runtime = build_weknora_search_runtime(settings)
if weknora_search_runtime is not None:
    # 进程退出时关闭共享客户端（FastAPI 0.136 已移除 `add_event_handler`，`on_event` 已弃用 ⇒ 用 atexit）。
    atexit.register(weknora_search_runtime.client.close)
workforce_directory_store = build_workforce_directory_store(settings)
workforce_directory_service = WorkforceDirectoryService(
    workforce_directory_store,
    audit=audit_service,
    knowledge_registry=knowledge_access_registry,
    task_store=store,
)
# P2c-6 会话协作：成员表仓储（迁移 039）与对话仓储**共用同一实例**——
# 读路径「本人 ∪ 成员」在仓储层生效，服务层的成员增删与参与者列表也读同一份数据。
conversation_member_store = build_conversation_member_store(settings)
conversation_store = build_conversation_store(settings, members=conversation_member_store)
# P3 记忆层（规格 docs/superpowers/specs/2026-09-15-memory-layer-p3-design.md §2.5/§2.8）：
# 嵌入式服务开发环境缺 default 时由装配层回退到 FakeEmbeddingAdapter（仅验证链路）。
memory_service = build_memory_service(settings, audit=audit_service)
# P5a CRM（真源 specs/2026-09-17-crm-p5a-design.md，已评审 2026-09-17）：
# 跟进计划生成器缺省 Mock（**不编造建议**，输出「依据不足」）；真实模型网关接入属部署装配
# （本期未接，登记为未验证——不得声称已具备真实 LLM 建议能力）。
crm_service = build_crm_service(settings, audit=audit_service)
# P4 技能层（规格 docs/superpowers/specs/2026-09-15-skill-layer-p4-design.md §2.3/§2.4）：
# 来源白名单为空 = 技能层关闭（可登记、不可启用，fail-closed）；allowed-tools 与执行目录取交集。
# M3 打通：注入 P3 记忆服务实例 → 技能经验沉淀入事实类记忆（memory_service 已在上面装配）。
skills_service = build_skills_service(settings, audit=audit_service, memory=memory_service)
# P6a 自进化·评测集（规格 2026-09-16-self-evolution-p6-design.md §2.8）：总开关默认 false（fail-closed）——
# 关闭时不装配任何评测组件（管理端点 503、CLI 拒绝执行）；开启时按存储模式自建仓储（内存仅 development）。
evolution_service: EvolutionService | None = build_evolution_service(settings, audit=audit_service)
agent_config_service = build_agent_config_service(
    settings, store=workforce_directory_store, audit=audit_service
)
run_metrics_service = build_run_metrics(settings)
runtime_state_store = build_runtime_state_store(settings)
# 027 待批动作仓储：RuntimeService 与 tool_execution 复用**同一实例**（§4.1.6-2 不得建两个实例）；
# backend=mock（默认）时为 None——不存在真实执行，RuntimeService 保持既有行为（§4.1.7-5）。
tool_action_store = build_tool_action_store(settings)
# 商业化仓储（租户 / 用量账本 / 生命周期）：在 `runtime_service` 之前装配，因为运行终态
# 记账（`RuntimeService._record_usage_on_terminal`）与 `GET /api/v1/commercial/usage`
# **必须读同一账本实例**——否则接口读到的恒为 0。
# N2：把记忆层仓储注入生命周期服务（同一实例）→ 导出载荷含 memories、租户删除物理清场。
commercial_repository, commercial_usage, commercial_lifecycle = build_commercial_components(
    settings, audit=audit_service, memory_store=memory_service.store
)
# 段二-4 对话入口路由（§3.7 Y2 / §3.2 第四条）：幂等行落 027 的 `workbench_execution_idempotency`。
# P2c-6：提前装配——运行级读路径的成员可见性（`_member_can_read_run`）需要「运行 → 会话」反查，
# 而该回调要注入下面的 `runtime_service`（**只放松读路径**，控制类动作不使用）。
execution_idempotency_store = build_execution_idempotency_store(settings)


def _member_can_read_run(context: UserContext, run_id: str) -> bool:
    """**会话成员**能否读该运行（P2c-6 裁定 ⑤：仅运行级读端点使用）。

    链路：`run_id` → 幂等行反查 `conversation_id` → 成员表 `permission_for` 非空 ⇒ `True`；
    非对话触发的运行（无幂等行）/ 非成员 / **任何异常**一律 `False`（fail-closed，不猜测、不放松）。
    控制类动作（pause / resume / cancel / 决议）**绝不**走这里。
    """
    try:
        record = execution_idempotency_store.find_by_run(context.tenant_id, run_id)
        conversation_id = getattr(record, "conversation_id", None)
        if not conversation_id:
            return False
        return (
            conversation_member_store.permission_for(
                context.tenant_id, str(conversation_id), context.user_id
            )
            is not None
        )
    except Exception:  # noqa: BLE001 - 判定不可用 ⇒ 不放松
        return False


runtime_service = build_runtime_service(
    settings,
    store=store,
    run_metrics=run_metrics_service,
    state_store=runtime_state_store,
    tool_actions=tool_action_store,
    usage_ledger=commercial_usage,
    member_run_reader=_member_can_read_run,
)
# ②④ 的权威状态（§3.5 P1 第 3 条 / §8 U24）：**装配期单例**，`build_tool_execution`
# （mint 侧写：`TokenBindingStore.record` + `ActiveExecutionRegistry.register`）与
# `build_exec_callback_guard`（判定侧读）**必须共用同一实例**，否则 ②④ 恒 `403`。
exec_authority_store = TokenBindingStore()
exec_authority_registry = ActiveExecutionRegistry()
# 段二（dsh 接入段）：backend=mock 时为 None；backend=dsh 且缺件时记 error 但不退进程（§4.1.6-2/-3）。
# P2c-3 产物登记（运行级元数据）与只读端点共用**同一实例**（登记了就能查到；保留期在此注入）。
run_artifact_store = build_run_artifact_store(settings)
tool_execution_service = build_tool_execution(
    settings,
    run_metrics=run_metrics_service,
    audit=audit_service,
    runtime_service=runtime_service,
    tool_actions=tool_action_store,
    token_store=exec_authority_store,
    token_registry=exec_authority_registry,
    artifacts=run_artifact_store,
)
# 孤儿容器清扫（§3.3 生命周期 / §8 U17 ⑥）：启动时 + 按 WORKBENCH_BODY_CLEANUP_INTERVAL_SECONDS
# 周期，**跑在 API 进程内**；未启用真实执行（backend=mock）时不注册（不引入后台线程）。
orphan_cleanup_task = build_orphan_cleanup_task(settings, tool_execution_service)
if orphan_cleanup_task is not None:
    app.add_event_handler("startup", orphan_cleanup_task.start)
    app.add_event_handler("shutdown", orphan_cleanup_task.stop)
# 正文密文 TTL 清理 + 审批超时置 expired（§4.1.5 / §4.1.6-8）：与孤儿清扫**同批**（同处注册、
# 同款周期循环、同一个 WORKBENCH_BODY_CLEANUP_INTERVAL_SECONDS）；backend=mock 时不注册。
body_cleanup_task = build_body_cleanup_task(settings, tool_execution_service, audit_service)
if body_cleanup_task is not None:
    app.add_event_handler("startup", body_cleanup_task.start)
    app.add_event_handler("shutdown", body_cleanup_task.stop)
# 段二-4 对话入口路由的幂等仓储已在上方（`runtime_service` 之前）装配 —— 见 `_member_can_read_run`。
# P2b 实时流（规格 §2.2/§2.3/§2.4）：流仓储 + 写入网关。**只有 `messages:stream` 路径写帧**；
# 旧 `POST /messages` 走 `handle_message(stream=False)` ⇒ 零帧（零破坏哨兵）。
conversation_stream_store = build_conversation_stream_store(settings)
conversation_stream_writer = build_conversation_stream_writer(
    settings, store=conversation_stream_store, audit=audit_service
)
# P2c-4 §2.11：会话服务需要流 / 幂等仓储（物理删除的按序跨仓储清理）⇒ 在两者装配之后构造。
# P2c-6：账号仓储提前装配（会话协作要按账号 id 校验成员合法性并解析 display_name）——
# 与 `ApprovalsService` 复用**同一实例**，不建第二个。
account_service, account_repository = build_account_service(
    settings, audit=audit_service, login_limiter=login_rate_limiter
)
conversation_service = build_conversation_service(
    settings,
    store=conversation_store,
    audit=audit_service,
    stream_store=conversation_stream_store,
    idempotency_store=execution_idempotency_store,
    members=conversation_member_store,
    accounts=account_repository,
)
conversation_execution_service = build_conversation_execution_service(
    settings,
    conversations=conversation_service,
    conversation_store=conversation_store,
    task_store=store,
    runtime_service=runtime_service,
    tool_execution=tool_execution_service,
    idempotency=execution_idempotency_store,
    audit=audit_service,
    directory_store=workforce_directory_store,
    stream_writer=conversation_stream_writer,
)
# 段二（dsh 接入段）执行回调接收 + ②④ 判定（§3.5 P1 第 3 条 / §8 U21 裁决「候选②」）：
# 边车是**无状态纯转发**，②④ 判定落回**工作台**的权威状态处——`expected` 从工作台权威状态重建
# （`ActiveExecutionRegistry`，**绝不取自请求体**），与令牌自持绑定做 `constant-time` 比对。
workbench_callback_guard = build_exec_callback_guard(
    settings,
    audit=audit_service,
    store=exec_authority_store,
    registry=exec_authority_registry,
)
# 边车 → 工作台 的限流（§8 U21 裁决：`100` rps，超限 `429`）；进程内令牌桶（多副本为「每副本」口径）。
exec_callback_limiter = CallbackRateLimiter(rate_per_second=100.0)
content_store = build_content_store(settings)
content_service = ContentService(
    task_store=store,
    runtime_service=runtime_service,
    content_store=content_store,
    knowledge_registry=knowledge_access_registry,
    content_generator=build_content_generator(settings),
    scraper=build_content_scraper(settings),
    audit=audit_service,
)
content_publisher = build_content_publisher(settings)
publication_service = build_publication_service(
    settings,
    content_store=content_store,
    publisher=content_publisher,
    audit=audit_service,
    inbox=inbox_service,
)
planner_service, planner_store = build_planner_service(
    settings, task_store=store, runtime_service=runtime_service, audit=audit_service
)
orchestration_service = build_orchestration_proposal_service(
    settings, metrics=run_metrics_service, audit=audit_service
)
# `account_service` / `account_repository` 已在会话服务装配处提前构建（P2c-6 复用同一实例）。
approvals_service = ApprovalsService(
    task_store=store,
    proposal_store=planner_store,
    account_service=account_service,
    run_approvals=runtime_service,
)


def publish_task_event(task: Task, action: str, actor: UserContext) -> None:
    if settings.storage_backend == "postgres":
        return
    event_bus.publish(
        EventEnvelope(
            event_id=f"{task.id}:{action}:1",
            tenant_id=task.tenant_id,
            aggregate_type="task",
            aggregate_id=task.id,
            version=1,
            sequence=len(event_bus.read("system", after_sequence=0)) + 1,
            dedupe_key=f"{task.id}:{action}:1",
            action=action,
            occurred_at=datetime.now(UTC),
            payload={"status": task.status.value, "actor_id": actor.user_id},
        )
    )


class TaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    employee_key: str = Field(min_length=1, max_length=100)
    risk_level: RiskLevel = RiskLevel.LOW
    budget: float = Field(default=0, ge=0)
    idempotency_key: str = Field(min_length=1, max_length=200)
    project_id: str | None = Field(default=None, max_length=100)


class TaskView(BaseModel):
    id: str
    tenant_id: str
    project_id: str | None
    created_by: str
    employee_key: str
    title: str
    risk_level: RiskLevel
    budget: float
    idempotency_key: str
    status: TaskStatus
    audit_count: int


class DeadLetterView(BaseModel):
    event_id: str
    tenant_id: str
    action: str
    aggregate_id: str
    attempts: int
    error: str
    recorded_at: datetime
    replayed_at: datetime | None
    replayed_by: str | None
    notified_at: datetime | None


class CollaborationDynamicView(BaseModel):
    event_id: str
    aggregate_id: str
    action: str
    title: str
    employee_key: str
    status: TaskStatus
    tenant_id: str
    project_id: str | None
    created_by: str
    occurred_at: datetime


class KnowledgeAccessUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    knowledge_base_ids: list[str] = Field(default_factory=list, max_length=100)


class RuntimeRunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    runtime_key: str = Field(default="mock", min_length=1, max_length=80)
    mode: str = Field(default="product_manager", pattern="^(product_manager|fde)$")
    steps: list[dict[str, object]] = Field(default_factory=list, max_length=50)


class RuntimeAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=1, max_length=500)


class RuntimeRunView(BaseModel):
    run_id: str
    runtime_key: str
    policy_version: str
    status: str


class RunMetricsView(BaseModel):
    run_id: str
    task_id: str
    proposal_id: str | None
    runtime_key: str
    status: str
    step_count: int
    completed_step_count: int
    tool_calls: int
    successful_tools: int
    knowledge_hits: int
    latency_ms: int
    started_at: datetime
    finished_at: datetime | None
    finish_reason: str | None = None


class RuntimeApprovalCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: dict[str, object]


class ContentSource(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(default="", max_length=2048)
    excerpt: str = Field(min_length=1, max_length=20_000)


class ContentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    topic: str = Field(min_length=1, max_length=200)
    sources: list[ContentSource] = Field(default_factory=list, max_length=20)
    knowledge_references: list[str] = Field(default_factory=list, max_length=100)
    idempotency_key: str = Field(min_length=1, max_length=200)


class ContentDraftUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=300)
    summary: str = Field(min_length=1, max_length=2_000)
    body_markdown: str = Field(min_length=1, max_length=50_000)
    image_suggestions: list[str] = Field(default_factory=list, max_length=20)


class ContentConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1)


class ContentRegeneration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=1, max_length=200)


class ScrapeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(min_length=1, max_length=2048)


def _content_view(record) -> dict[str, object]:
    draft = record.draft
    return {
        "task_id": record.task_id,
        "run_id": record.run_id,
        "status": draft.status.value,
        "revision": draft.revision,
        "topic": record.brief.topic,
        "sources": [{"url": item.url, "excerpt": item.excerpt} for item in record.brief.sources],
        "knowledge_references": list(record.brief.knowledge_references),
        "draft": {
            "draft_id": draft.draft_id, "title": draft.title, "summary": draft.summary,
            "body_markdown": draft.body_markdown, "image_suggestions": draft.image_suggestions,
            "citations": [{"url": item.url} for item in draft.citations],
            "template_version": draft.template_version,
            "confirmed_by": draft.confirmed_by, "confirmed_at": draft.confirmed_at,
        },
        "audits": [{"action": item.action, "actor_id": item.actor_id, "occurred_at": item.occurred_at} for item in record.audits],
    }


class CommercialTenantView(BaseModel):
    tenant_id: str
    name: str
    owner_id: str
    status: str
    created_at: datetime


class CommercialUsageView(BaseModel):
    tenant_id: str
    units: int
    cost_cents: int


class LifecycleJobView(BaseModel):
    job_id: str
    tenant_id: str
    kind: str
    status: str
    requested_by: str
    requested_at: datetime
    execute_after: datetime | None = None
    final_exported: bool = False


class ExportPackageView(BaseModel):
    """导出包取回视图（组 10.7）：脱敏载荷 + 过期时刻（管理台按 `expires_at` 提示有效期）。"""

    package_id: str
    tenant_id: str
    job_id: str | None = None
    created_at: datetime
    expires_at: datetime
    payload: dict[str, object]


TOTP_ENROLLMENT_ALLOWED: frozenset[tuple[str, str]] = frozenset(
    {
        ("POST", "/api/v1/auth/me/totp"),
        ("POST", "/api/v1/auth/me/totp/confirmation"),
        ("POST", "/api/v1/auth/logout"),
        ("GET", "/api/v1/health"),
    }
)

# SSO 受限令牌（scope=sso_pending）只允许完成应用内二次验证与健康检查。
SSO_PENDING_ALLOWED: frozenset[str] = frozenset(
    {"/api/v1/auth/sso/verification", "/api/v1/auth/logout", "/api/v1/health"}
)


def current_user(
    request: Request,
    tenant_id: str | None = Header(default=None, alias="X-Tenant-Id"),
    user_id: str | None = Header(default=None, alias="X-User-Id"),
    role: str | None = Header(default=None, alias="X-User-Role"),
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> UserContext:
    context: UserContext | None = None
    if settings.env != "development":
        if not settings.auth_secret or not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="请使用有效的登录凭证")
        try:
            context = verify_access_token(authorization.removeprefix("Bearer "), settings.auth_secret)
        except ValueError as exc:
            raise HTTPException(status_code=401, detail="登录凭证无效") from exc
    elif authorization and authorization.startswith("Bearer ") and settings.auth_secret:
        try:
            context = verify_access_token(authorization.removeprefix("Bearer "), settings.auth_secret)
        except ValueError as exc:
            raise HTTPException(status_code=401, detail="登录凭证无效") from exc
    if context is None:
        if not tenant_id or not user_id or not role:
            raise HTTPException(status_code=401, detail="缺少登录身份信息")
        context = UserContext(tenant_id=tenant_id, user_id=user_id, role=role)
    if context.token_id:
        # 服务端撤销名单：登出后同一令牌立即失效。查询失败必须 fail-closed。
        try:
            revoked = session_revocation_store.is_revoked(context.token_id)
        except Exception as exc:  # noqa: BLE001 存储故障不能降级为放行
            raise HTTPException(status_code=503, detail="会话状态暂时无法校验，请稍后重试") from exc
        if revoked:
            raise HTTPException(status_code=401, detail="登录凭证已失效，请重新登录")
    if context.scope == TOTP_ENROLLMENT_SCOPE and (request.method, request.url.path) not in TOTP_ENROLLMENT_ALLOWED:
        raise HTTPException(status_code=403, detail="账号需要先完成动态口令绑定")
    if context.scope == SSO_PENDING_SCOPE and request.url.path not in SSO_PENDING_ALLOWED:
        raise HTTPException(status_code=403, detail="请先完成动态验证码校验")
    return context


def _ensure_commercial_admin(context: UserContext) -> None:
    if context.role == "super_admin":
        return
    if context.role == "customer_admin" and commercial_repository.is_customer_admin(context.tenant_id, context.user_id):
        return
    raise CommercialPolicyError("只有客户管理员或超级管理员可以管理租户商业化设置")


def _lifecycle_view(job: LifecycleJob) -> LifecycleJobView:
    return LifecycleJobView(
        job_id=job.id,
        tenant_id=job.tenant_id,
        kind=job.kind,
        status=job.status,
        requested_by=job.requested_by,
        requested_at=job.requested_at,
        execute_after=job.execute_after,
        final_exported=job.final_exported,
    )


def to_view(task: Task) -> TaskView:
    return TaskView(
        id=task.id,
        tenant_id=task.tenant_id,
        project_id=task.project_id,
        created_by=task.created_by,
        employee_key=task.employee_key,
        title=task.title,
        risk_level=task.risk_level,
        budget=task.budget,
        idempotency_key=task.idempotency_key,
        status=task.status,
        audit_count=len(task.audits),
    )


@app.get("/api/v1/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "company-workbench"}


# ------------------------------------------------ 执行回调接收（边车纯转发 → 工作台判定）
# §3.5 P1 第 3 条 ②④ / §8 U21 裁决「候选②：边车纯转发 + 判定回工作台」。
# 本端点是**内网服务对服务**调用面（不挂用户认证依赖）：鉴权走 `X-Exec-Callback-Key` 预共享密钥。
WORKBENCH_EXEC_CALLBACK_PATH = "/api/v1/internal/exec-callback"


def _callback_bearer(raw: str | None) -> str:
    """从 `Authorization` 头取短期令牌（只解析，不做判定）。"""
    if not raw:
        return ""
    prefix, _, value = raw.partition(" ")
    return value.strip() if prefix.lower() == "bearer" else ""


def _callback_payload(raw: bytes) -> dict[str, object]:
    """解析转发来的回调用载荷；非 JSON / 非对象一律当空（判定不依赖它）。"""
    if not raw:
        return {}
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _callback_text(payload: dict[str, object], key: str) -> str | None:
    value = payload.get(key)
    return value if isinstance(value, str) and value else None


@app.post(WORKBENCH_EXEC_CALLBACK_PATH)
async def receive_exec_callback(request: Request) -> dict[str, str]:
    """接收边车转发的执行回调，并在**工作台权威状态**处做 ②④ 判定（fail-closed）。

    - 限流：`100` rps（超限 `429`；进程内令牌桶）；
    - 鉴权：`X-Exec-Callback-Key` 预共享密钥（`constant-time` 比对；**缺失 / 不匹配即拒**）；
    - ②④：`expected` 从工作台权威状态重建（**绝不取自请求体**），与令牌自持绑定恒时比对，
      不匹配 / 跨租户 / 旧代次 / 未知令牌 → `403`（**不泄露存在性**）+ 记审计（复用 `tool.blocked`）。
    """
    if not exec_callback_limiter.allow():
        raise HTTPException(status_code=429, detail="回调过于频繁")
    provided = request.headers.get("X-Exec-Callback-Key")
    if not shared_secret_matches(settings.exec_callback_shared_secret, provided):
        raise HTTPException(status_code=403, detail="forbidden")
    payload = _callback_payload(await request.body())
    try:
        workbench_callback_guard.authorize(
            token=_callback_bearer(request.headers.get("Authorization")),
            session_id=request.query_params.get("session_id", ""),
            run_id=_callback_text(payload, "run_id"),
            tool_key=_callback_text(payload, "tool_key"),
        )
    except BindingDenied:
        raise HTTPException(status_code=403, detail="forbidden") from None
    return {"status": "accepted"}



@app.post("/api/v1/content-tasks", status_code=status.HTTP_201_CREATED)
def create_content_task(payload: ContentCreate, response: Response, context: UserContext = Depends(current_user)) -> dict[str, object]:
    existing = content_service.content_store.find_by_idempotency(context.tenant_id, context.user_id, payload.idempotency_key)
    try:
        record = content_service.create(
            actor=context,
            payload=ContentBriefInput(
                topic=payload.topic,
                sources=[SourceInput(url=item.url, excerpt=item.excerpt) for item in payload.sources],
                knowledge_references=payload.knowledge_references,
            ),
            idempotency_key=payload.idempotency_key,
        )
    except IdempotencyConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ContentNotFound as exc:
        raise HTTPException(status_code=404, detail="内容任务不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if existing is not None:
        response.status_code = status.HTTP_200_OK
    return _content_view(record)


@app.get("/api/v1/content-tasks")
def list_content_tasks(
    status_filter: str | None = Query(default=None, alias="status"),
    page: int = Query(default=1),
    page_size: int = Query(default=20),
    context: UserContext = Depends(current_user),
) -> dict[str, object]:
    allowed_statuses = {ContentStatus.REVIEWING, ContentStatus.FAILED, ContentStatus.CONFIRMED}
    if status_filter is not None:
        try:
            requested_status = ContentStatus(status_filter)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="不支持的内容任务状态") from exc
        if requested_status not in allowed_statuses:
            raise HTTPException(status_code=400, detail="不支持的内容任务状态")
    else:
        requested_status = None
    try:
        result = content_service.list(
            actor=context, status=requested_status, page=page, page_size=page_size,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    result["items"] = [
        {
            "task_id": item.task_id,
            "topic": item.topic,
            "status": item.status.value,
            "created_by": item.created_by,
            "created_at": item.created_at,
            "updated_at": item.updated_at,
            "run_id": item.run_id,
        }
        for item in result["items"]
    ]
    return result


@app.get("/api/v1/content-tasks/{task_id}")
def get_content_task(task_id: str, context: UserContext = Depends(current_user)) -> dict[str, object]:
    try:
        return _content_view(content_service.get(actor=context, task_id=task_id))
    except ContentNotFound as exc:
        raise HTTPException(status_code=404, detail="内容任务不存在") from exc


@app.post("/api/v1/content-tasks/{task_id}/regenerations")
def regenerate_content_task(task_id: str, payload: ContentRegeneration, context: UserContext = Depends(current_user)) -> dict[str, object]:
    try:
        return _content_view(content_service.regenerate(actor=context, task_id=task_id, idempotency_key=payload.idempotency_key))
    except ContentNotFound as exc:
        raise HTTPException(status_code=404, detail="内容任务不存在") from exc
    except RevisionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.put("/api/v1/content-tasks/{task_id}/draft")
def update_content_draft(task_id: str, payload: ContentDraftUpdate, context: UserContext = Depends(current_user)) -> dict[str, object]:
    try:
        content_service.update_draft(
            actor=context, task_id=task_id, revision=payload.revision, title=payload.title,
            summary=payload.summary, body_markdown=payload.body_markdown,
            image_suggestions=payload.image_suggestions,
        )
        return _content_view(content_service.get(actor=context, task_id=task_id))
    except ContentNotFound as exc:
        raise HTTPException(status_code=404, detail="内容任务不存在") from exc
    except RevisionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/v1/content-tasks/{task_id}/confirmation")
def confirm_content_task(task_id: str, payload: ContentConfirmation, context: UserContext = Depends(current_user)) -> dict[str, object]:
    try:
        content_service.confirm(actor=context, task_id=task_id, revision=payload.revision)
        return _content_view(content_service.get(actor=context, task_id=task_id))
    except ContentNotFound as exc:
        raise HTTPException(status_code=404, detail="内容任务不存在") from exc
    except RevisionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.delete("/api/v1/content-tasks/{task_id}/confirmation")
def revoke_content_confirmation(task_id: str, context: UserContext = Depends(current_user)) -> dict[str, object]:
    try:
        content_service.revoke_confirmation(actor=context, task_id=task_id)
        return _content_view(content_service.get(actor=context, task_id=task_id))
    except ContentNotFound as exc:
        raise HTTPException(status_code=404, detail="内容任务不存在") from exc
    except RevisionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/v1/content-tasks/{task_id}/export.md")
def export_content_task(task_id: str, context: UserContext = Depends(current_user)) -> Response:
    try:
        content = content_service.export_markdown(actor=context, task_id=task_id)
    except ContentNotFound as exc:
        raise HTTPException(status_code=404, detail="内容任务不存在") from exc
    except ExportNotAllowed as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return Response(
        content=content,
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="content-{task_id}.md"'},
    )


@app.post("/api/v1/content-sources/scrape")
def scrape_content_source(payload: ScrapeRequest, context: UserContext = Depends(current_user)) -> dict[str, object]:
    try:
        document = content_service.scrape_source(context, payload.url)
    except ScrapeNotConfigured as exc:
        raise HTTPException(status_code=503, detail="未配置抓取白名单，抓取功能未启用") from exc
    except ScrapeDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ScrapeFailed as exc:
        raise HTTPException(status_code=502, detail="抓取失败") from exc
    return {
        "url": document.url,
        "title": document.title,
        "text": document.text,
        "truncated": document.truncated,
        "content_type": document.content_type,
        "fetched_at": document.fetched_at,
    }


class PublicationView(BaseModel):
    publication_id: str
    task_id: str
    revision: int
    target: str
    status: str
    receipt_id: str | None
    error: str | None
    created_at: datetime
    verified_at: datetime | None


def _publication_view(record) -> PublicationView:
    return PublicationView(
        publication_id=record.publication_id,
        task_id=record.task_id,
        revision=record.revision,
        target=record.target,
        status=record.status,
        receipt_id=record.receipt_id,
        error=record.error,
        created_at=record.created_at,
        verified_at=record.verified_at,
    )


@app.post("/api/v1/content-tasks/{task_id}/publications", status_code=status.HTTP_201_CREATED)
def create_content_publication(
    task_id: str, context: UserContext = Depends(current_user)
) -> PublicationView:
    try:
        record = publication_service.publish(context, task_id)
    except (ContentNotFound, PublicationNotFound) as exc:
        raise HTTPException(status_code=404, detail="内容任务不存在") from exc
    except PublicationNotAllowed as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PublicationNotConfigured as exc:
        raise HTTPException(status_code=503, detail="未配置发布渠道，发布功能未启用") from exc
    except PublicationFailed as exc:
        raise HTTPException(status_code=502, detail="发布失败，已转入人工接管，请勿自动重发") from exc
    return _publication_view(record)


@app.get("/api/v1/content-tasks/{task_id}/publications")
def list_content_publications(
    task_id: str, context: UserContext = Depends(current_user)
) -> dict[str, object]:
    try:
        records = publication_service.list(context, task_id)
    except ContentNotFound as exc:
        raise HTTPException(status_code=404, detail="内容任务不存在") from exc
    return {"items": [_publication_view(record) for record in records]}


@app.post("/api/v1/content-publications/{publication_id}/verification")
def verify_content_publication(
    publication_id: str, context: UserContext = Depends(current_user)
) -> PublicationView:
    try:
        record = publication_service.verify(context, publication_id)
    except (ContentNotFound, PublicationNotFound) as exc:
        raise HTTPException(status_code=404, detail="发布记录不存在") from exc
    except PublicationNotConfigured as exc:
        raise HTTPException(status_code=503, detail="未配置发布渠道，发布功能未启用") from exc
    except PublicationFailed as exc:
        raise HTTPException(status_code=502, detail="回执核对失败") from exc
    return _publication_view(record)


@app.get("/api/v1/commercial/tenant", response_model=CommercialTenantView)
def get_commercial_tenant(context: UserContext = Depends(current_user)) -> CommercialTenantView:
    try:
        _ensure_commercial_admin(context)
        tenant = commercial_repository.get_tenant(context.tenant_id)
    except CommercialPolicyError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ResourceNotFound as exc:
        raise HTTPException(status_code=404, detail="租户不存在") from exc
    return CommercialTenantView(
        tenant_id=tenant.id,
        name=tenant.name,
        owner_id=tenant.owner_id,
        status=tenant.status.value,
        created_at=tenant.created_at,
    )


@app.get("/api/v1/commercial/usage", response_model=CommercialUsageView)
def get_commercial_usage(context: UserContext = Depends(current_user)) -> CommercialUsageView:
    try:
        _ensure_commercial_admin(context)
        commercial_repository.get_tenant(context.tenant_id)
    except CommercialPolicyError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ResourceNotFound as exc:
        raise HTTPException(status_code=404, detail="租户不存在") from exc
    return CommercialUsageView(
        tenant_id=context.tenant_id,
        units=commercial_usage.total(context.tenant_id),
        cost_cents=commercial_usage.total_cost_cents(context.tenant_id),
    )


@app.post("/api/v1/commercial/exports", response_model=LifecycleJobView, status_code=status.HTTP_202_ACCEPTED)
def request_commercial_export(context: UserContext = Depends(current_user)) -> LifecycleJobView:
    try:
        job = commercial_lifecycle.request_export(Actor(context.user_id, context.role), context.tenant_id)
    except CommercialPolicyError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ResourceNotFound as exc:
        raise HTTPException(status_code=404, detail="租户不存在") from exc
    return _lifecycle_view(job)


@app.get("/api/v1/commercial/exports/{package_id}", response_model=ExportPackageView)
def get_commercial_export_package(
    package_id: str, context: UserContext = Depends(current_user)
) -> ExportPackageView:
    """取回本租户导出包（admin-only，契约「GET /api/v1/commercial/exports/{package_id}」）。

    租户由登录上下文解析（客户端不能指定）；跨租户 / 不存在统一 `404`「导出包不存在」。
    ⚠️ 捕获顺序：`ExportPackageExpired` **必须先于** `CommercialPolicyError` 捕获
    （过期继承策略错误族但语义是 `404` 而非 `403`；先例：`DeletionNotPending` → `409`）。
    过期包由 worker 周期任务 `export-packages-purge` 物理清理（本端点不触发清理）。
    """
    try:
        package = commercial_lifecycle.get_export_package(
            Actor(context.user_id, context.role), context.tenant_id, package_id
        )
    except ExportPackageExpired as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CommercialPolicyError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ResourceNotFound as exc:
        raise HTTPException(status_code=404, detail="导出包不存在") from exc
    return ExportPackageView(
        package_id=package.id,
        tenant_id=package.tenant_id,
        job_id=package.job_id,
        created_at=package.created_at,
        expires_at=package.expires_at,
        payload=package.payload,
    )


@app.post("/api/v1/commercial/deletion-requests", response_model=LifecycleJobView, status_code=status.HTTP_202_ACCEPTED)
def request_commercial_deletion(context: UserContext = Depends(current_user)) -> LifecycleJobView:
    try:
        job = commercial_lifecycle.request_delete(Actor(context.user_id, context.role), context.tenant_id)
    except CommercialPolicyError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ResourceNotFound as exc:
        raise HTTPException(status_code=404, detail="租户不存在") from exc
    return _lifecycle_view(job)


@app.post("/api/v1/commercial/deletion-requests/cancel", response_model=LifecycleJobView)
def cancel_commercial_deletion(context: UserContext = Depends(current_user)) -> LifecycleJobView:
    try:
        job = commercial_lifecycle.cancel_delete(Actor(context.user_id, context.role), context.tenant_id)
    except DeletionNotPending as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except CommercialPolicyError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ResourceNotFound as exc:
        raise HTTPException(status_code=404, detail="租户不存在") from exc
    return _lifecycle_view(job)


@app.get("/api/v1/commercial/lifecycle/{job_id}", response_model=LifecycleJobView)
def get_commercial_lifecycle(job_id: str, context: UserContext = Depends(current_user)) -> LifecycleJobView:
    try:
        _ensure_commercial_admin(context)
        job = commercial_lifecycle.get_job(job_id)
        if job.tenant_id != context.tenant_id:
            raise ResourceNotFound(job_id)
    except CommercialPolicyError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ResourceNotFound as exc:
        raise HTTPException(status_code=404, detail="生命周期任务不存在") from exc
    return _lifecycle_view(job)


@app.get("/api/v1/runtimes/health")
def runtime_health(context: UserContext = Depends(current_user)) -> dict[str, dict[str, object]]:
    if context.role not in {"ceo", "super_admin"}:
        raise HTTPException(status_code=403, detail="只有 CEO 或超级管理员可以查看运行时状态")
    return runtime_service.registry.health()


@app.get("/api/v1/dead-letters", response_model=list[DeadLetterView])
def list_dead_letters(context: UserContext = Depends(current_user)) -> list[DeadLetterView]:
    try:
        items = dead_letter_store.list(context)
    except PolicyError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return [
        DeadLetterView(
            event_id=item.event_id,
            tenant_id=item.event.tenant_id,
            action=item.event.action,
            aggregate_id=item.event.aggregate_id,
            attempts=item.attempts,
            error=item.error,
            recorded_at=item.recorded_at,
            replayed_at=item.replayed_at,
            replayed_by=item.replayed_by,
            notified_at=item.notified_at,
        )
        for item in items
    ]


@app.post("/api/v1/dead-letters/{event_id}/replay")
def replay_dead_letter(event_id: str, context: UserContext = Depends(current_user)) -> dict[str, str]:
    try:
        result = dead_letter_store.replay(context, event_id)
    except PolicyError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="死信事件不存在") from exc
    return {"status": result, "event_id": event_id}


def _ensure_knowledge_admin(context: UserContext) -> None:
    if context.role != "super_admin":
        raise PolicyError("只有超级管理员可以调整知识库范围")


class WorkforceRosterItem(BaseModel):
    key: str
    role_knowledge_base_ids: list[str]
    agent_knowledge_base_ids: list[str]
    task_count: int


class WorkforceRosterView(BaseModel):
    items: list[WorkforceRosterItem]
    total: int


@app.get("/api/v1/workforce/roster", response_model=WorkforceRosterView)
def workforce_roster(context: UserContext = Depends(current_user)) -> WorkforceRosterView:
    """岗位与数字员工清单（只读）。

    数据来自三个事实源的并集：知识范围里的岗位绑定、数字员工绑定、以及任务中出现过的
    `employee_key`；不含账号 PII，也不提供增删改（编辑走「知识权限管理」）。
    """
    if context.role != "super_admin":
        raise HTTPException(status_code=403, detail="只有超级管理员可以查看岗位与数字员工清单")
    bindings = knowledge_access_registry.list_bindings(context)
    counts = store.count_by_employee(context.tenant_id)
    keys = set(bindings["role"]) | set(bindings["agent"]) | set(counts)
    items = [
        WorkforceRosterItem(
            key=key,
            role_knowledge_base_ids=bindings["role"].get(key, []),
            agent_knowledge_base_ids=bindings["agent"].get(key, []),
            task_count=counts.get(key, 0),
        )
        for key in keys
    ]
    items.sort(key=lambda item: (-item.task_count, item.key))
    return WorkforceRosterView(items=items, total=len(items))


def _require_workforce_directory_admin(context: UserContext) -> None:
    if context.role != "super_admin":
        raise HTTPException(status_code=403, detail="只有超级管理员可以管理岗位与数字员工目录")


def _workforce_status_query(value: str | None) -> str | None:
    if value is None:
        return None
    if value not in ("active", "disabled"):
        raise HTTPException(status_code=422, detail="状态只能是 active 或 disabled")
    return value


def _raise_directory_http(exc: Exception) -> NoReturn:
    """把目录领域异常映射成 HTTP 语义；子类先判，避免被基类 `DirectoryError` 截走。"""
    if isinstance(exc, (DirectoryConflict, RoleNotAvailable)):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, (InvalidDirectoryKey, InvalidDirectoryName)):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if isinstance(exc, DirectoryNotFound):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, DirectoryError):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if isinstance(exc, PolicyError):
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    raise exc


class JobRoleView(BaseModel):
    role_key: str
    name: str
    description: str
    status: str
    created_by: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


class JobRoleListView(BaseModel):
    items: list[JobRoleView]
    total: int
    limit: int
    offset: int


class JobRoleCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role_key: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=60)
    description: str = Field(default="", max_length=200)


class JobRoleUpdateRequest(BaseModel):
    """只允许改中文名、描述与状态；标识不在模型里，传了会因 `extra=forbid` 直接 422。"""

    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=60)
    description: str | None = Field(default=None, max_length=200)
    status: str | None = None


class DigitalEmployeeView(BaseModel):
    agent_key: str
    name: str
    description: str
    role_key: str
    status: str
    created_by: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


class DigitalEmployeeListView(BaseModel):
    items: list[DigitalEmployeeView]
    total: int
    limit: int
    offset: int


class DigitalEmployeeCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_key: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=60)
    role_key: str = Field(min_length=1, max_length=64)
    description: str = Field(default="", max_length=200)


class DigitalEmployeeUpdateRequest(BaseModel):
    """`agent_key` 是身份、不可改；`role_key` 是「所属岗位」，可以换岗（会校验岗位可用）。"""

    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=60)
    description: str | None = Field(default=None, max_length=200)
    role_key: str | None = Field(default=None, min_length=1, max_length=64)
    status: str | None = None


class WorkforceCandidatesView(BaseModel):
    roles: list[str]
    agents: list[str]


def _job_role_view(role: JobRole) -> JobRoleView:
    return JobRoleView(
        role_key=role.role_key,
        name=role.name,
        description=role.description,
        status=role.status.value,
        created_by=role.created_by,
        created_at=role.created_at,
        updated_at=role.updated_at,
    )


def _digital_employee_view(employee: DigitalEmployee) -> DigitalEmployeeView:
    return DigitalEmployeeView(
        agent_key=employee.agent_key,
        name=employee.name,
        description=employee.description,
        role_key=employee.role_key,
        status=employee.status.value,
        created_by=employee.created_by,
        created_at=employee.created_at,
        updated_at=employee.updated_at,
    )


@app.get("/api/v1/workforce/roles", response_model=JobRoleListView)
def list_workforce_roles(
    role_status: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    context: UserContext = Depends(current_user),
) -> JobRoleListView:
    """岗位目录列表：仅超级管理员、严格本租户、必须分页。"""
    _require_workforce_directory_admin(context)
    items, total = workforce_directory_service.list_roles(
        context, status=_workforce_status_query(role_status), limit=limit, offset=offset
    )
    return JobRoleListView(
        items=[_job_role_view(item) for item in items], total=total, limit=limit, offset=offset
    )


@app.post("/api/v1/workforce/roles", response_model=JobRoleView, status_code=status.HTTP_201_CREATED)
def create_workforce_role(
    payload: JobRoleCreateRequest, context: UserContext = Depends(current_user)
) -> JobRoleView:
    """新建岗位：标识重复 409，标识或中文名非法 422。"""
    _require_workforce_directory_admin(context)
    try:
        role = workforce_directory_service.create_role(
            context, role_key=payload.role_key, name=payload.name, description=payload.description
        )
    except (DirectoryError, DirectoryNotFound, PolicyError) as exc:
        _raise_directory_http(exc)
    return _job_role_view(role)


@app.patch("/api/v1/workforce/roles/{role_key}", response_model=JobRoleView)
def update_workforce_role(
    role_key: str, payload: JobRoleUpdateRequest, context: UserContext = Depends(current_user)
) -> JobRoleView:
    """改中文名 / 描述 / 状态；标识不可改，岗位不存在 404。"""
    _require_workforce_directory_admin(context)
    try:
        role = workforce_directory_service.update_role(
            context,
            role_key,
            name=payload.name,
            description=payload.description,
            status=_workforce_status_query(payload.status),
        )
    except (DirectoryError, DirectoryNotFound, PolicyError) as exc:
        _raise_directory_http(exc)
    return _job_role_view(role)


@app.get("/api/v1/workforce/agents", response_model=DigitalEmployeeListView)
def list_workforce_agents(
    agent_status: str | None = Query(default=None, alias="status"),
    role_key: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    context: UserContext = Depends(current_user),
) -> DigitalEmployeeListView:
    """数字员工目录列表：可按状态与所属岗位过滤；仅超级管理员、严格本租户、必须分页。"""
    _require_workforce_directory_admin(context)
    try:
        items, total = workforce_directory_service.list_employees(
            context,
            status=_workforce_status_query(agent_status),
            role_key=role_key,
            limit=limit,
            offset=offset,
        )
    except (DirectoryError, DirectoryNotFound, PolicyError) as exc:
        _raise_directory_http(exc)
    return DigitalEmployeeListView(
        items=[_digital_employee_view(item) for item in items], total=total, limit=limit, offset=offset
    )


@app.post(
    "/api/v1/workforce/agents",
    response_model=DigitalEmployeeView,
    status_code=status.HTTP_201_CREATED,
)
def create_workforce_agent(
    payload: DigitalEmployeeCreateRequest, context: UserContext = Depends(current_user)
) -> DigitalEmployeeView:
    """新建数字员工：标识重复 409，所属岗位不存在或已停用 409。"""
    _require_workforce_directory_admin(context)
    try:
        employee = workforce_directory_service.create_employee(
            context,
            agent_key=payload.agent_key,
            name=payload.name,
            role_key=payload.role_key,
            description=payload.description,
        )
    except (DirectoryError, DirectoryNotFound, PolicyError) as exc:
        _raise_directory_http(exc)
    return _digital_employee_view(employee)


@app.patch("/api/v1/workforce/agents/{agent_key}", response_model=DigitalEmployeeView)
def update_workforce_agent(
    agent_key: str, payload: DigitalEmployeeUpdateRequest, context: UserContext = Depends(current_user)
) -> DigitalEmployeeView:
    """改中文名 / 描述 / 所属岗位 / 状态；`agent_key` 是身份不可改（传了 422）。"""
    _require_workforce_directory_admin(context)
    try:
        employee = workforce_directory_service.update_employee(
            context,
            agent_key,
            name=payload.name,
            description=payload.description,
            role_key=payload.role_key,
            status=_workforce_status_query(payload.status),
        )
    except (DirectoryError, DirectoryNotFound, PolicyError) as exc:
        _raise_directory_http(exc)
    return _digital_employee_view(employee)


@app.get("/api/v1/workforce/candidates", response_model=WorkforceCandidatesView)
def workforce_candidates(context: UserContext = Depends(current_user)) -> WorkforceCandidatesView:
    """尚未纳入目录的标识：知识绑定与任务里出现过、但目录里还没有的那些（供一键纳管）。"""
    _require_workforce_directory_admin(context)
    result = workforce_directory_service.candidates(context)
    return WorkforceCandidatesView(roles=result["roles"], agents=result["agents"])


# ------------------------------------------------------------ P2c-4 只读候选端点（**推翻契约 Y1**）


def _require_model_catalog_admin(context: UserContext) -> None:
    """模型 / 工具候选端点与员工配置面同权限：**仅 `super_admin`**（其他角色 `403`）。"""
    if context.role != "super_admin":
        raise HTTPException(status_code=403, detail="只有超级管理员可以读取模型与工具候选")


@app.get("/api/v1/workforce/model-candidates")
def workforce_model_candidates(context: UserContext = Depends(current_user)) -> dict[str, object]:
    """模型候选键只读列表（P2c-4 §2.10）：与员工配置 `model_key` 的**保存闸门同源**。

    只返回候选键（`registered_model_keys(settings)`），**不含** base_url / api_key 等任何凭据或内部地址；
    候选为空 = 本部署未注册模型键（界面如实告知「只能使用默认模型」，不摆假候选）。
    """
    _require_model_catalog_admin(context)
    keys = sorted(registered_model_keys(settings))
    return {"items": keys, "total": len(keys)}


@app.get("/api/v1/tools/catalog")
def tool_catalog(context: UserContext = Depends(current_user)) -> dict[str, object]:
    """工具目录 + 保存闸门集合（P2c-4 §2.10 · **推翻契约 Y1**）。

    - `items` = **执行工具目录**（`ToolSpecCatalog`：工具键 / 风险档 / 是否需审批 / 是否有副作用 /
      是否可逆 / 参数与参数角色）——只读元数据，**不含**参数取值、凭据或内部地址；
    - `allowlist` = 员工配置 `tool_allowlist` 的**保存闸门集合**（`WORKBENCH_PLANNER_TOOLS` 声明的键）；
      两个集合**不是同一批名字**，故如实分开返回；**后端校验不变**（不在闸门集合内的键保存仍 `422`）。
    """
    _require_model_catalog_admin(context)
    catalog = build_tool_spec_catalog()
    items = [
        {
            "tool_key": spec.key,
            "risk_level": spec.risk_level.value,
            "requires_approval": bool(spec.requires_approval),
            "has_side_effect": bool(spec.has_side_effect),
            "reversible": bool(spec.reversible),
            "params": [
                {"name": name, "role": spec.param_roles[name].value}
                for name in sorted(spec.param_roles)
            ],
        }
        for spec in catalog.specs
    ]
    allowlist = sorted(allowed_tool_names(settings))
    return {"items": items, "allowlist": allowlist, "total": len(items)}


# ------------------------------------------------------------ 对话层（P1，D7：桩回复）


def _raise_conversation_http(exc: Exception) -> NoReturn:
    """把对话领域异常映射成 HTTP 语义；子类先判，避免被基类截走。"""
    if isinstance(exc, ConversationStateConflict):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, InvalidConversation):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if isinstance(exc, ConversationNotFound):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, PolicyError):
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    raise exc


def _conversation_status_query(value: str | None) -> str | None:
    if value is None:
        return None
    if value not in ("active", "archived"):
        raise HTTPException(status_code=422, detail="状态只能是 active 或 archived")
    return value


class ConversationView(BaseModel):
    """会话视图：刻意不含 `operator_id` 与 `dsh_session_id`（账号 PII 与内部映射不外泄）。

    P2c-4 **只增** `mode`（`ask` / `plan` / `goal` / `craft`，默认 `craft`）。
    """

    conversation_id: str
    agent_key: str | None = None
    title: str
    status: str
    mode: str = "craft"
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ConversationListView(BaseModel):
    items: list[ConversationView]
    total: int
    limit: int
    offset: int


class MessageView(BaseModel):
    message_id: str
    conversation_id: str
    role: str
    content: str
    # P1 的助手消息都是确定性桩；显式标注，绝不伪装成真实模型输出
    stub: bool = False
    tool_name: str | None = None
    tool_call_id: str | None = None
    created_at: datetime | None = None
    # P2c-6（**只增**，可空）：发言账号 id；助手 / 工具 / 系统恒 `null`，
    # 存量行 `null` ⇒ 前端展示回退为「发起人」（零破坏）。
    sender_id: str | None = None


class ConversationDetailView(ConversationView):
    messages: list[MessageView]
    messages_total: int
    messages_limit: int
    messages_offset: int


class ConversationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_key: str | None = Field(default=None, max_length=64)
    title: str = Field(default="", max_length=120)


class ConversationModeRequest(BaseModel):
    """改模式请求体（P2c-4 §2.9）；取值受控枚举，未知字段 `extra=forbid` ⇒ `422`。"""

    model_config = ConfigDict(extra="forbid")
    mode: str = Field(min_length=1, max_length=16)


class MessageCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str = Field(min_length=1, max_length=8000)


class MessageCreateResponse(BaseModel):
    message_id: str
    conversation_id: str
    stub: bool
    reply: MessageView


class AgentConfigView(BaseModel):
    agent_key: str
    system_prompt: str
    model_key: str
    temperature: float
    tool_allowlist: list[str]
    memory_policy: dict[str, object]
    autonomy_level: str
    risk_threshold: str
    approval_timeout_minutes: int
    daily_budget_cents: int
    updated_at: datetime | None = None


class AgentConfigUpdateRequest(BaseModel):
    """`agent_key` 是身份、不可改；未知字段因 `extra=forbid` 直接 422。"""

    model_config = ConfigDict(extra="forbid")
    system_prompt: str | None = None
    model_key: str | None = None
    temperature: float | None = None
    tool_allowlist: list[str] | None = None
    memory_policy: dict[str, object] | None = None
    autonomy_level: str | None = None
    risk_threshold: str | None = None
    approval_timeout_minutes: int | None = None
    daily_budget_cents: int | None = None


def _conversation_view(conversation: Conversation) -> ConversationView:
    return ConversationView(
        conversation_id=conversation.conversation_id,
        agent_key=conversation.agent_key,
        title=conversation.title,
        status=conversation.status.value,
        mode=conversation.mode.value,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
    )


def _message_view(message: ConversationMessage) -> MessageView:
    return MessageView(
        message_id=message.message_id,
        conversation_id=message.conversation_id,
        role=message.role.value,
        content=message.content,
        stub=message.role == MessageRole.ASSISTANT,
        tool_name=message.tool_name,
        tool_call_id=message.tool_call_id,
        created_at=message.created_at,
        sender_id=message.sender_id,
    )


def _agent_config_view(employee: DigitalEmployee) -> AgentConfigView:
    return AgentConfigView(
        agent_key=employee.agent_key,
        system_prompt=employee.system_prompt,
        model_key=employee.model_key,
        temperature=employee.temperature,
        tool_allowlist=list(employee.tool_allowlist),
        memory_policy=dict(employee.memory_policy),
        autonomy_level=employee.autonomy_level,
        risk_threshold=employee.risk_threshold,
        approval_timeout_minutes=employee.approval_timeout_minutes,
        daily_budget_cents=employee.daily_budget_cents,
        updated_at=employee.updated_at,
    )


@app.post("/api/v1/conversations", response_model=ConversationView, status_code=status.HTTP_201_CREATED)
def create_conversation(
    payload: ConversationCreateRequest, context: UserContext = Depends(current_user)
) -> ConversationView:
    """新建会话；`agent_key` 可选（缺省用默认员工）。"""
    try:
        ensure_can_converse(context)
        conversation = conversation_service.create_conversation(
            context, agent_key=payload.agent_key, title=payload.title
        )
    except (ConversationStateConflict, InvalidConversation, ConversationNotFound, PolicyError) as exc:
        _raise_conversation_http(exc)
    return _conversation_view(conversation)


@app.get("/api/v1/conversations", response_model=ConversationListView)
def list_conversations(
    conversation_status: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    context: UserContext = Depends(current_user),
) -> ConversationListView:
    """会话列表：普通岗位只列本人在本租户发起的会话；CEO/超级管理员可列本租户全部；必须分页。"""
    try:
        ensure_can_converse(context)
        items, total = conversation_service.list_conversations(
            context, status=_conversation_status_query(conversation_status), limit=limit, offset=offset
        )
    except (ConversationStateConflict, InvalidConversation, ConversationNotFound, PolicyError) as exc:
        _raise_conversation_http(exc)
    return ConversationListView(
        items=[_conversation_view(item) for item in items], total=total, limit=limit, offset=offset
    )


@app.get("/api/v1/conversations/{conversation_id}", response_model=ConversationDetailView)
def get_conversation(
    conversation_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    context: UserContext = Depends(current_user),
) -> ConversationDetailView:
    """会话详情（含消息，消息同样分页）。跨租户与改他人会话一律 404。"""
    try:
        ensure_can_converse(context)
        conversation = conversation_service.get_conversation(context, conversation_id)
        messages, messages_total = conversation_service.list_messages(
            context, conversation_id, limit=limit, offset=offset
        )
    except (ConversationStateConflict, InvalidConversation, ConversationNotFound, PolicyError) as exc:
        _raise_conversation_http(exc)
    view = _conversation_view(conversation)
    return ConversationDetailView(
        **view.model_dump(),
        messages=[_message_view(item) for item in messages],
        messages_total=messages_total,
        messages_limit=limit,
        messages_offset=offset,
    )


@app.post(
    "/api/v1/conversations/{conversation_id}/messages",
    status_code=status.HTTP_201_CREATED,
)
def send_conversation_message(
    conversation_id: str,
    payload: MessageCreateRequest,
    response: Response,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    context: UserContext = Depends(current_user),
) -> dict[str, object]:
    """发送一条用户消息。

    缺 `Idempotency-Key`（或未启用真实执行）⇒ 既有确定性桩回复（`stub=true`），不触发真实执行；
    带键 ⇒ 触发真实工具执行 + 幂等（`201` 已执行 / `202` 待批 / 拒绝码 / 失败码，见契约「工具执行」）。
    """
    try:
        ensure_can_converse(context)
        result = conversation_execution_service.handle_message(
            context, conversation_id, content=payload.content, idempotency_key=idempotency_key
        )
    except (ConversationStateConflict, InvalidConversation, ConversationNotFound, PolicyError) as exc:
        _raise_conversation_http(exc)
    except ConversationExecutionError as exc:
        raise HTTPException(status_code=exc.http_status, detail=str(exc)) from exc
    response.status_code = result.http_status
    return result.body


@app.post(
    "/api/v1/conversations/{conversation_id}/messages:stream",
    status_code=status.HTTP_201_CREATED,
)
def send_conversation_message_stream(
    conversation_id: str,
    payload: MessageCreateRequest,
    response: Response,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    context: UserContext = Depends(current_user),
) -> dict[str, object]:
    """发送一条用户消息（**实时流路径**，P2b §2.4 / Q7 候选①）。

    请求体 / 请求头 / 响应体 / 状态码与 `POST .../messages` **逐字一致**（复用同一执行服务）；
    **唯一差异**：① 执行过程写流帧（先落库，供 `GET .../stream` 增量读取）；② 响应头多一个
    `X-Stream-Run-Id`（有运行时）；不带 `Idempotency-Key` 时仍是既有桩回复且**不写帧**。
    """
    try:
        ensure_can_converse(context)
        result = conversation_execution_service.handle_message(
            context,
            conversation_id,
            content=payload.content,
            idempotency_key=idempotency_key,
            stream=True,
        )
    except (ConversationStateConflict, InvalidConversation, ConversationNotFound, PolicyError) as exc:
        _raise_conversation_http(exc)
    except ConversationExecutionError as exc:
        raise HTTPException(status_code=exc.http_status, detail=str(exc)) from exc
    response.status_code = result.http_status
    run_id = result.body.get("run_id")
    if run_id:
        response.headers["X-Stream-Run-Id"] = str(run_id)
    return result.body


# ------------------------------------------------------------ P2b 实时流（SSE 读端点 §2.3）

# SSE 心跳注释间隔（秒）：注释行不产生事件、不干扰 `Last-Event-ID`（规格 §2.3）。
SSE_HEARTBEAT_SECONDS = 15.0
# 单次增量读的帧数上限（读端只做短轮询；超出的下一轮继续）。
SSE_FRAME_BATCH = 200


def _sse_start_cursor(last_event_id: str | None, after_seq: int | None) -> int:
    """续播起点 = **max(`Last-Event-ID`, `after_seq`)**（防降级重放导致重复投递，规格 §2.3）。

    非法值一律 `422`；起点**大于** `last_seq` 不报错（只等新帧）。
    """
    values: list[int] = []
    if last_event_id is not None:
        text = last_event_id.strip()
        if not text.isdigit():
            raise HTTPException(status_code=422, detail="Last-Event-ID 必须是非负整数")
        values.append(int(text))
    if after_seq is not None:
        if after_seq < 0:
            raise HTTPException(status_code=422, detail="after_seq 必须是非负整数")
        values.append(int(after_seq))
    return max(values) if values else 0


def _sse_chunk(
    *, seq: int, kind: str, payload: dict[str, object], is_terminal: bool, run_id: str | None = None
) -> str:
    """SSE 帧：`id: <seq>` + `event: <kind>` + `data: <json>`（规格 §2.3 冻结格式）。

    P2c-2（**只增**）：`data` 内新增 `run_id`——覆盖「连接建立时无 run、稍后新 run 出现」与多客户端场景，
    客户端据此归组并解析「当前 run」（既有 `seq` / `kind` / `payload` / `is_terminal` 语义不变）。
    """
    data = json.dumps(
        {"run_id": run_id, "seq": seq, "kind": kind, "payload": payload, "is_terminal": is_terminal},
        ensure_ascii=False,
        sort_keys=True,
    )
    return f"id: {seq}\nevent: {kind}\ndata: {data}\n\n"


def _sse_unavailable_reason(store, tenant_id: str, conversation_id: str, run_id: str, last_seq: int) -> str:
    """`unavailable` 终态的原因：优先取**已落的告知帧**（熔断），否则按悬挂兜底口径（`stalled`）。"""
    try:
        tail = store.list_frames(
            tenant_id, conversation_id, run_id, after_seq=max(0, int(last_seq) - 1), limit=1
        )
    except Exception:  # noqa: BLE001 - 探测失败按悬挂口径告知，不谎报
        return REASON_STALLED
    if tail and tail[0].kind == UNAVAILABLE_KIND:
        return str(tail[0].payload.get("reason") or REASON_STALLED)
    return REASON_STALLED


_TERMINAL_RUN_STATUSES = {"completed", "failed", "cancelled"}


def _resume_result_payload(approval_id: str, result) -> dict[str, object]:
    """决议后推进的 `tool.result` payload：与首次结果**同构**（**只增** `resumed`；白名单键）。"""
    summary = dict(getattr(result, "summary", None) or {})
    payload: dict[str, object] = {
        "step_id": approval_id,
        "tool_key": str(summary.get("tool_key") or ""),
        "status": str(summary.get("status") or "ok"),
        "summary": summary,
        "sha256": summary_digest(summary),
        "resumed": True,
    }
    payload.update(
        bounded_output_fields(
            getattr(result, "output", None), file_changes_max=get_settings().file_changes_max
        )
    )
    return payload


def _resume_stream_frames(
    context: UserContext,
    run_id: str,
    approval_id: str,
    *,
    approved: bool,
    run_status: str,
    result=None,
) -> None:
    """P2c-2 §2.8：审批决议后的推进接入**同一** `StreamWriter`（无流 ⇒ 零破坏）。

    - 只有「经 `messages:stream` 发起过」的 run 才有流状态（会话经幂等行反查；旧端点 / `mock` 路径无流）；
    - `unavailable`（熔断 / 悬挂兜底）**不复活**——该 run 已显式告知「过程流不可用」；
    - 已终态的流**先重开**再续写（同一 run 的 `seq` 继续单调）；写既有 `kind`，**不新增取值域**；
    - **流是视图**：本函数任何失败都只记日志，**不得**影响决议结果与响应体。
    """
    writer = conversation_stream_writer
    store = conversation_stream_store
    idempotency = execution_idempotency_store
    if writer is None or store is None or idempotency is None:
        return
    try:
        record = idempotency.find_by_run(context.tenant_id, run_id)
        conversation_id = getattr(record, "conversation_id", None)
        if not conversation_id:
            return
        state = store.get_state(context.tenant_id, conversation_id, run_id)
        if state is None or getattr(state, "status", "") == STATUS_UNAVAILABLE:
            return
        store.reopen_if_terminal(context.tenant_id, conversation_id, run_id)
        if approved and result is not None:
            writer.write(
                context.tenant_id,
                conversation_id,
                run_id,
                kind=RuntimeEventType.TOOL_RESULT.value,
                payload=_resume_result_payload(approval_id, result),
            )
        if run_status in _TERMINAL_RUN_STATUSES:
            kind = (
                RuntimeEventType.RUN_COMPLETED.value
                if run_status == "completed"
                else RuntimeEventType.RUN_FAILED.value
            )
            writer.write(
                context.tenant_id,
                conversation_id,
                run_id,
                kind=kind,
                payload={"resumed": True, "status": run_status},
                is_terminal=True,
            )
    except Exception as exc:  # noqa: BLE001 - 流写入失败绝不阻断决议
        logger.warning("决议后推进的流写入失败（不影响决议结果）：%s", exc)


def _sse_frame_stream(
    conversation_id: str, context: UserContext, run_id: str | None, start_seq: int
):
    """SSE 增量生成器：短轮询 PG（不引入 Redis / WebSocket），心跳保活，终态主动关流。

    - 缺省 run = `latest_run_id`（无 run ⇒ 挂起仅心跳；轮询中发现新 run 后自动开始补发）；
    - 读到 `is_terminal=True` 帧 ⇒ 关流；重连且起点已覆盖终态 ⇒ 立即关流；
    - 状态 `unavailable` 且无告知帧（悬挂兜底）⇒ 补发一帧 `stream.unavailable` 后关流；
    - 单连接超 `stream_max_connection_seconds` ⇒ 关流（客户端自动重连续播）；
    - 读失败 ⇒ 关流（**不谎报**为正常结束；客户端按既有 `Last-Event-ID` 重试）。
    """
    store = conversation_stream_store
    settings = get_settings()
    poll_seconds = max(0.05, float(settings.stream_poll_interval_ms) / 1000.0)
    max_connection = float(settings.stream_max_connection_seconds)
    started = time.monotonic()
    last = int(start_seq)
    last_heartbeat = started
    active_run = run_id
    notified_unavailable = False
    while True:
        now = time.monotonic()
        if now - started >= max_connection:
            return
        if active_run is None:
            try:
                active_run = store.latest_run_id(context.tenant_id, conversation_id)
            except Exception:  # noqa: BLE001 - 读失败关流，不谎报
                return
            if active_run is None:
                if now - last_heartbeat >= SSE_HEARTBEAT_SECONDS:
                    last_heartbeat = now
                    yield ": hb\n\n"
                time.sleep(poll_seconds)
                continue
        try:
            frames = store.list_frames(
                context.tenant_id, conversation_id, active_run,
                after_seq=last, limit=SSE_FRAME_BATCH,
            )
            state = store.get_state(context.tenant_id, conversation_id, active_run)
        except Exception:  # noqa: BLE001
            return
        if frames:
            for frame in frames:
                last = max(last, int(frame.seq))
                if frame.kind == UNAVAILABLE_KIND:
                    notified_unavailable = True
                yield _sse_chunk(
                    seq=int(frame.seq), kind=frame.kind,
                    payload=dict(frame.payload), is_terminal=bool(frame.is_terminal),
                    run_id=active_run,
                )
                last_heartbeat = time.monotonic()
                if frame.is_terminal:
                    return
            continue
        if state is not None and state.is_terminal:
            if state.status == STATUS_UNAVAILABLE and not notified_unavailable:
                # 悬挂兜底不补写帧 ⇒ 读端按状态**显式告知**后关流（熔断时已落的那帧优先）。
                yield _sse_chunk(
                    seq=int(state.last_seq) + 1, kind=UNAVAILABLE_KIND,
                    payload={
                        "reason": _sse_unavailable_reason(
                            store, context.tenant_id, conversation_id, active_run, int(state.last_seq)
                        )
                    },
                    is_terminal=True,
                    run_id=active_run,
                )
            return
        if time.monotonic() - last_heartbeat >= SSE_HEARTBEAT_SECONDS:
            last_heartbeat = time.monotonic()
            yield ": hb\n\n"
        time.sleep(poll_seconds)


@app.get("/api/v1/conversations/{conversation_id}/stream")
def stream_conversation(
    conversation_id: str,
    run_id: str | None = Query(default=None, min_length=1, max_length=128),
    after_seq: int | None = Query(default=None, ge=0),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    context: UserContext = Depends(current_user),
) -> StreamingResponse:
    """SSE 读取一次运行的流帧（P2b §2.3）：认证 + 归属 + 续播 + 心跳 + 终态关流。

    权限沿用对话端点口径：未认证 `401`；`customer_admin` `403`；跨租户 / 他人会话 / 未知 run `404`；
    非法 `run_id` / `after_seq` / `Last-Event-ID` `422`。响应 `Cache-Control: no-cache` +
    `X-Accel-Buffering: no`（反代不缓冲）。
    """
    try:
        ensure_can_converse(context)
        conversation_service.get_conversation(context, conversation_id)
    except (ConversationStateConflict, InvalidConversation, ConversationNotFound, PolicyError) as exc:
        _raise_conversation_http(exc)
    start_seq = _sse_start_cursor(last_event_id, after_seq)
    resolved_run_id = run_id
    if run_id is not None:
        try:
            state = conversation_stream_store.get_state(context.tenant_id, conversation_id, run_id)
        except Exception as exc:  # noqa: BLE001 - 读失败不泄露内部细节
            raise HTTPException(status_code=503, detail="流暂不可用") from exc
        if state is None:
            raise HTTPException(status_code=404, detail="运行不存在或不属于该会话")
    else:
        # P2c-2（只增）：响应头 `X-Stream-Run-Id` = 连接建立时解析到的**当前 run**；
        # 会话尚无 run（挂起等待）⇒ 不写该头，客户端据此判定「本次没有过程流」。
        try:
            resolved_run_id = conversation_stream_store.latest_run_id(context.tenant_id, conversation_id)
        except Exception:  # noqa: BLE001 - 解析失败只降级（流本身仍可用）
            resolved_run_id = None
    headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    if resolved_run_id:
        headers["X-Stream-Run-Id"] = str(resolved_run_id)
    return StreamingResponse(
        _sse_frame_stream(conversation_id, context, run_id, start_seq),
        media_type="text/event-stream",
        headers=headers,
    )


@app.post("/api/v1/conversations/{conversation_id}/archive", response_model=ConversationView)
def archive_conversation(
    conversation_id: str, context: UserContext = Depends(current_user)
) -> ConversationView:
    """归档会话（不删除）；改他人会话返回 404。"""
    try:
        ensure_can_converse(context)
        conversation = conversation_service.archive_conversation(context, conversation_id)
    except (ConversationStateConflict, InvalidConversation, ConversationNotFound, PolicyError) as exc:
        _raise_conversation_http(exc)
    return _conversation_view(conversation)


# ------------------------------------------------------------ P2c-4 模式 / 导出 / 物理删除


@app.post("/api/v1/conversations/{conversation_id}/mode", response_model=ConversationView)
def set_conversation_mode(
    conversation_id: str,
    payload: ConversationModeRequest,
    context: UserContext = Depends(current_user),
) -> ConversationView:
    """改**每会话模式**（P2c-4 §2.9）：仅会话本人；他人 / 跨租户 `404`；归档 `409`；非法取值 `422`。

    设为同一值 = **无副作用**（不写审计）；变更写审计 `conversation.mode.changed`（受控枚举）。
    """
    try:
        ensure_can_converse(context)
        normalize_mode(payload.mode)
        conversation = conversation_service.set_conversation_mode(context, conversation_id, payload.mode)
    except (ConversationStateConflict, InvalidConversation, ConversationNotFound, PolicyError) as exc:
        _raise_conversation_http(exc)
    return _conversation_view(conversation)


@app.get("/api/v1/conversations/exports/mine")
def export_my_conversations(
    limit: int = Query(default=500, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    context: UserContext = Depends(current_user),
) -> dict[str, object]:
    """导出**本人**全部未删除会话（含归档）与消息（P2c-4 §2.11）：分页 + **条目上限如实告知**。

    返回的是**库中实际存在的字段**（用户原始输入自 U23 起只落脱敏摘要，不是原文重放）；
    **不含**他人数据、**不含**审计明细、**不含** `operator_id` / `dsh_session_id`。
    超上限（`{会话数 + 消息数} > 50000`）⇒ `truncated=true` + `limit_reason="total_items_exceeded"`（不静默截断）。
    """
    try:
        ensure_can_converse(context)
        result = conversation_service.export_mine(context, limit=limit, offset=offset)
    except (ConversationStateConflict, InvalidConversation, ConversationNotFound, PolicyError) as exc:
        _raise_conversation_http(exc)
    return {
        "exported_at": result.exported_at,
        "limit": result.limit,
        "offset": result.offset,
        "conversations": [
            {
                **_conversation_view(conversation).model_dump(),
                "messages": [_export_message_view(message) for message in messages],
                "messages_total": len(messages),
            }
            for conversation, messages in result.conversations
        ],
        "total_conversations": result.total_conversations,
        "total_messages": result.total_messages,
        "truncated": result.truncated,
        "limit_reason": result.limit_reason,
    }


@app.post("/api/v1/conversations/{conversation_id}/delete")
def delete_conversation(
    conversation_id: str, context: UserContext = Depends(current_user)
) -> dict[str, object]:
    """**物理删除**本人会话的内容行（P2c-4 §2.11）：同步、幂等（复删 `200` + 计数全 0、不重复写审计）。

    真删：幂等行 → 帧 → 流状态 → 消息（+ 会话行软删 / 标题清空）；**保留**运行 / 待批 / 审计 / 产物登记。
    他人 / 跨租户 / 已删除会话 `404`（与「不存在」不可区分）。
    """
    try:
        ensure_can_converse(context)
        outcome = conversation_service.delete_conversation(context, conversation_id)
    except (ConversationStateConflict, InvalidConversation, ConversationNotFound, PolicyError) as exc:
        _raise_conversation_http(exc)
    return {
        "conversation_id": outcome.conversation_id,
        "deleted": outcome.deleted,
        "message_count": outcome.message_count,
        "frame_count": outcome.frame_count,
        "stream_state_count": outcome.stream_state_count,
        "idempotency_count": outcome.idempotency_count,
    }


def _export_message_view(message: ConversationMessage) -> dict[str, object]:
    """导出条目里的消息视图：与 `MessageView` 同字段，**不含** `conversation_id`（父级即会话）。"""
    return {
        "message_id": message.message_id,
        "role": message.role.value,
        "content": message.content,
        "stub": message.role == MessageRole.ASSISTANT,
        "tool_name": message.tool_name,
        "tool_call_id": message.tool_call_id,
        "created_at": message.created_at,
        # P2c-6（**只增**）：导出的也是库里实际存在的字段——发言者原样带出，便于协作会话溯源。
        "sender_id": message.sender_id,
    }


# ------------------------------------------------------------ P2c-6 会话协作：分享与多端协同


class ConversationMemberCreateRequest(BaseModel):
    """添加成员请求体（`extra=forbid`：未知字段 `422`；`permission` 缺省 `read`）。"""

    model_config = ConfigDict(extra="forbid")
    member_id: str = Field(min_length=1, max_length=128)
    permission: str | None = Field(default=None, max_length=16)


class ConversationMemberGrantView(BaseModel):
    conversation_id: str
    member_id: str
    permission: str


class ConversationMemberView(BaseModel):
    """参与者条目：`display_name` / `role` 由账号解析（账号缺失 ⇒ 回退 `member_id` / `null`，不编造）。"""

    member_id: str
    display_name: str
    role: str | None = None
    # `read` / `write`；发起人为展示值 `owner`（不入库、不可撤销）。
    permission: str
    is_owner: bool = False
    added_by: str | None = None
    created_at: datetime | None = None


class ConversationMemberListView(BaseModel):
    items: list[ConversationMemberView]
    total: int


@app.post(
    "/api/v1/conversations/{conversation_id}/members",
    response_model=ConversationMemberGrantView,
    status_code=status.HTTP_201_CREATED,
)
def add_conversation_member(
    conversation_id: str,
    payload: ConversationMemberCreateRequest,
    context: UserContext = Depends(current_user),
) -> ConversationMemberGrantView:
    """添加 / 覆盖会话成员（P2c-6 §2.16）：**仅会话本人**。

    他人 / 跨租户 `404`；归档 `409`；非法成员（未知 / 跨租户 / 未审批 / `customer_admin`）或非法权限档 `422`；
    **幂等**：权限档未变 ⇒ `201` 且不重复写审计。审计 `conversation.member.added`（受控键，不落姓名 / 手机号）。
    """
    try:
        ensure_can_converse(context)
        member = conversation_service.add_member(
            context, conversation_id, member_id=payload.member_id, permission=payload.permission
        )
    except (ConversationStateConflict, InvalidConversation, ConversationNotFound, PolicyError) as exc:
        _raise_conversation_http(exc)
    return ConversationMemberGrantView(
        conversation_id=member.conversation_id, member_id=member.member_id, permission=member.permission
    )


@app.get(
    "/api/v1/conversations/{conversation_id}/members", response_model=ConversationMemberListView
)
def list_conversation_members(
    conversation_id: str, context: UserContext = Depends(current_user)
) -> ConversationMemberListView:
    """参与者列表（P2c-6 §2.16）：**本人或成员可见**（他人 / 跨租户 `404`）。

    发起人列首位（`is_owner=true` / `permission="owner"`，不可撤销）；「最近活动时间」取会话 `updated_at`
    （成员表不建活动时间列，**不做实时在线态**）。
    """
    try:
        ensure_can_converse(context)
        items = conversation_service.list_participants(context, conversation_id)
    except (ConversationStateConflict, InvalidConversation, ConversationNotFound, PolicyError) as exc:
        _raise_conversation_http(exc)
    views = [ConversationMemberView(**item) for item in items]
    return ConversationMemberListView(items=views, total=len(views))


@app.delete("/api/v1/conversations/{conversation_id}/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_conversation_member(
    conversation_id: str, member_id: str, context: UserContext = Depends(current_user)
) -> Response:
    """撤销成员（P2c-6 §2.16）：**仅会话本人**；成功 `204`。

    **幂等**：复删 / 目标不是成员（含发起人）一律 `204`（no-op，不重复写审计）；归档会话 `409`。
    **已读内容不可撤回**（撤销只影响**新**的读取 / 发言请求 ⇒ `404`，不做「收回」语义）。
    """
    try:
        ensure_can_converse(context)
        conversation_service.remove_member(context, conversation_id, member_id)
    except (ConversationStateConflict, InvalidConversation, ConversationNotFound, PolicyError) as exc:
        _raise_conversation_http(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ------------------------------------------------------------ P3 记忆层（规格 2026-09-15-memory-layer-p3-design.md §2）


class MemoryFactView(BaseModel):
    """事实类记忆视图：不含 embedding 向量本身、不含创建者 PII。"""

    memory_id: str
    content: str
    scope: str
    owner_kind: str
    status: str
    created_at: datetime | None = None


class MemoryFactCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str = Field(min_length=1, max_length=8000)
    scope: str = Field(default="user", max_length=64)
    owner_kind: str = Field(default="user", max_length=64)
    owner_id: str | None = Field(default=None, max_length=128)
    idempotency_key: str = Field(min_length=1, max_length=200)


class MemoryFactListResponse(BaseModel):
    items: list[MemoryFactView]
    total: int
    limit: int
    offset: int


class MemoryFactSearchResponse(BaseModel):
    items: list[MemoryFactView]


class MemoryRuleView(BaseModel):
    memory_id: str
    rule_key: str
    version: int
    content: str
    scope: str
    owner_kind: str
    status: str
    created_at: datetime | None = None


class MemoryRuleCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rule_key: str = Field(min_length=1, max_length=64)
    content: str = Field(min_length=1, max_length=8000)
    scope: str = Field(default="role", max_length=64)
    owner_kind: str = Field(default="user", max_length=64)
    owner_id: str | None = Field(default=None, max_length=128)


class MemoryProfileUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(min_length=1, max_length=128)
    value: str = Field(min_length=1, max_length=4000)
    owner_kind: str = Field(default="user", max_length=64)
    owner_id: str | None = Field(default=None, max_length=128)


class MemoryProfileResponse(BaseModel):
    items: dict[str, str]


def _memory_fact_view(fact: MemoryFact) -> MemoryFactView:
    return MemoryFactView(
        memory_id=fact.memory_id,
        content=fact.content,
        scope=fact.scope.value if hasattr(fact.scope, "value") else str(fact.scope),
        owner_kind=fact.owner_kind.value if hasattr(fact.owner_kind, "value") else str(fact.owner_kind),
        status=fact.status.value if hasattr(fact.status, "value") else str(fact.status),
        created_at=fact.created_at,
    )


def _memory_rule_view(rule: MemoryRule) -> MemoryRuleView:
    return MemoryRuleView(
        memory_id=rule.memory_id,
        rule_key=rule.rule_key,
        version=rule.version,
        content=rule.content,
        scope=rule.scope.value if hasattr(rule.scope, "value") else str(rule.scope),
        owner_kind=rule.owner_kind.value if hasattr(rule.owner_kind, "value") else str(rule.owner_kind),
        status=rule.status.value if hasattr(rule.status, "value") else str(rule.status),
        created_at=rule.created_at,
    )


def _raise_memory_http(exc: Exception) -> NoReturn:
    """把记忆领域异常映射成 HTTP 语义（§3.2）；fail-closed：Embedding 失败 → 502。"""
    if isinstance(exc, EmbeddingUnavailable):
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if isinstance(exc, MemoryStateConflict):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, InvalidMemory):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if isinstance(exc, MemoryBudgetExceeded):
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    if isinstance(exc, MemoryNotFound):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, PolicyError):
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    raise exc


@app.post("/api/v1/memory/facts", response_model=MemoryFactView, status_code=status.HTTP_201_CREATED)
def create_memory_fact(
    payload: MemoryFactCreateRequest, context: UserContext = Depends(current_user)
) -> MemoryFactView:
    """书写事实类记忆（人工采纳链：归属校验 → 预算闸门 → embedding 编码 → 落库 → 审计）。

    §2.3：scope 由服务端校验为合法枚举；§2.5：embedding 服务不可达 → 502（fail-closed，不静默降级）。
    幂等键：同 (tenant, owner_kind, owner_id, idempotency_key) 重放返回既有记录，不重复落库。
    """
    try:
        fact = memory_service.create_fact(
            context,
            content=payload.content,
            scope=payload.scope,
            owner_kind=payload.owner_kind,
            owner_id=payload.owner_id,
            idempotency_key=payload.idempotency_key,
        )
    except (
        InvalidMemory,
        MemoryBudgetExceeded,
        MemoryNotFound,
        MemoryStateConflict,
        PolicyError,
        EmbeddingUnavailable,
    ) as exc:
        _raise_memory_http(exc)
    return _memory_fact_view(fact)


@app.get("/api/v1/memory/facts", response_model=MemoryFactListResponse)
def list_memory_facts(
    owner_kind: str = Query(default="user", max_length=64),
    owner_id: str | None = Query(default=None, max_length=128),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    context: UserContext = Depends(current_user),
) -> MemoryFactListResponse:
    """事实类记忆列表：本人或 CEO/超级管理员；必须分页。"""
    try:
        items, total = memory_service.list_facts(
            context,
            owner_kind=owner_kind,
            owner_id=owner_id,
            limit=limit,
            offset=offset,
        )
    except (InvalidMemory, MemoryNotFound, PolicyError) as exc:
        _raise_memory_http(exc)
    return MemoryFactListResponse(
        items=[_memory_fact_view(item) for item in items], total=total, limit=limit, offset=offset
    )


@app.post("/api/v1/memory/facts/{memory_id}/supersede", response_model=MemoryFactView)
def supersede_memory_fact(memory_id: str, context: UserContext = Depends(current_user)) -> MemoryFactView:
    """作废事实类记忆（supersede 软删链，不物理删除）；本人或 admin，他人 → 404。"""
    try:
        fact = memory_service.supersede_fact(context, memory_id)
    except (InvalidMemory, MemoryNotFound, PolicyError) as exc:
        _raise_memory_http(exc)
    return _memory_fact_view(fact)


@app.post("/api/v1/memory/search", response_model=MemoryFactSearchResponse)
def search_memory_facts(
    query: str = Query(min_length=1, max_length=8000),
    limit: int = Query(default=20, ge=1, le=200),
    context: UserContext = Depends(current_user),
) -> MemoryFactSearchResponse:
    """语义检索事实类记忆（§2.6）：scope 由服务端解析为 user 档（本人），客户端传值一律忽略。"""
    try:
        items = memory_service.search_facts(context, query=query, scope=None, limit=limit)
    except (InvalidMemory, MemoryNotFound, PolicyError, EmbeddingUnavailable) as exc:
        _raise_memory_http(exc)
    return MemoryFactSearchResponse(items=[_memory_fact_view(item) for item in items])


@app.post("/api/v1/memory/rules", response_model=MemoryRuleView, status_code=status.HTTP_201_CREATED)
def create_memory_rule(
    payload: MemoryRuleCreateRequest, context: UserContext = Depends(current_user)
) -> MemoryRuleView:
    """书写规则类记忆（§2.4 人工在环）：同一 (owner, rule_key) 已有 active → supersede 旧版并 version+1。"""
    try:
        rule = memory_service.create_rule(
            context,
            rule_key=payload.rule_key,
            content=payload.content,
            scope=payload.scope,
            owner_kind=payload.owner_kind,
            owner_id=payload.owner_id,
        )
    except (InvalidMemory, MemoryNotFound, MemoryStateConflict, PolicyError) as exc:
        _raise_memory_http(exc)
    return _memory_rule_view(rule)


@app.put("/api/v1/memory/profile", response_model=MemoryProfileResponse)
def update_memory_profile(
    payload: MemoryProfileUpdateRequest, context: UserContext = Depends(current_user)
) -> MemoryProfileResponse:
    """覆写身份类画像键（§2.4 同键覆盖，记审计）；本人或 admin。"""
    try:
        memory_service.set_profile_key(
            context,
            key=payload.key,
            value=payload.value,
            owner_kind=payload.owner_kind,
            owner_id=payload.owner_id,
        )
        profile = memory_service.get_profile(
            context,
            owner_kind=payload.owner_kind,
            owner_id=payload.owner_id,
        )
    except (InvalidMemory, MemoryNotFound, MemoryBudgetExceeded, PolicyError) as exc:
        _raise_memory_http(exc)
    return MemoryProfileResponse(items=profile)


@app.get("/api/v1/memory/profile", response_model=MemoryProfileResponse)
def read_memory_profile(
    owner_kind: str = Query(default="user", max_length=64),
    owner_id: str | None = Query(default=None, max_length=128),
    context: UserContext = Depends(current_user),
) -> MemoryProfileResponse:
    """读取身份类画像（KV，不进向量检索）；本人或 admin。"""
    try:
        profile = memory_service.get_profile(
            context, owner_kind=owner_kind, owner_id=owner_id
        )
    except (InvalidMemory, MemoryNotFound, PolicyError) as exc:
        _raise_memory_http(exc)
    return MemoryProfileResponse(items=profile)


# ------------------------------------------------------------ P4 技能层（规格 2026-09-15-skill-layer-p4-design.md §2）


class SkillView(BaseModel):
    """技能视图：不含包正文与内容指纹之外可逆推原文的字段。"""

    skill_key: str
    version: str
    name: str
    description: str
    license: str
    allowed_tools: list[str]
    status: str
    source_key: str
    owner_id: str
    reviewed_by: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class SkillSubmitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    skill_key: str = Field(min_length=1, max_length=64)
    version: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=64)
    description: str = Field(min_length=1, max_length=800)
    license: str = Field(min_length=1, max_length=32)
    allowed_tools: list[str]
    source_key: str = Field(min_length=1, max_length=64)
    content_sha256: str = Field(min_length=64, max_length=64)
    # M5 裁决（2026-09-15）：技能包正文（库内落库，体积上限服务端校验，字段内部分校验见服务层）。
    content_body: str = Field(default="")


class SkillContentResponse(BaseModel):
    """技能包正文视图（详情接口专用，避免列表响应拖大）。"""

    skill_key: str
    version: str
    content_body: str
    content_sha256: str


class SkillExperienceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str = Field(min_length=1, max_length=2000)


class SkillExperienceResponse(BaseModel):
    """技能经验沉淀结果（M3 打通；只回技能引用与幂等键，不重复大字段）。"""

    skill_key: str
    version: str
    fact_id: str
    idempotency_key: str
    tagged_content: str


class SkillListResponse(BaseModel):
    items: list[SkillView]
    total: int
    limit: int
    offset: int


class SkillBindRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    skill_key: str = Field(min_length=1, max_length=64)
    agent_key: str = Field(min_length=1, max_length=64)


class SkillExpandResponse(BaseModel):
    agent_key: str
    tools: list[str]


def _skill_view(skill: Skill) -> SkillView:
    return SkillView(
        skill_key=skill.skill_key,
        version=skill.version,
        name=skill.name,
        description=skill.description,
        license=skill.license,
        allowed_tools=list(skill.allowed_tools),
        status=skill.status.value if hasattr(skill.status, "value") else str(skill.status),
        source_key=skill.source_key,
        owner_id=skill.owner_id,
        reviewed_by=skill.reviewed_by,
        created_at=skill.created_at,
        updated_at=skill.updated_at,
    )


def _raise_skill_http(exc: Exception) -> NoReturn:
    """把技能领域异常映射成 HTTP 语义（规格 §3.2）。"""
    if isinstance(exc, SkillMemoryUnavailable):
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if isinstance(exc, SkillStateConflict):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, InvalidSkillPackage):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if isinstance(exc, SkillSourceDenied):
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if isinstance(exc, SkillNotFound):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, PolicyError):
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    raise exc


@app.post("/api/v1/skills", response_model=SkillView, status_code=status.HTTP_201_CREATED)
def submit_skill(payload: SkillSubmitRequest, context: UserContext = Depends(current_user)) -> SkillView:
    """提交技能包（申报，不生效）：来源白名单 + 许可白名单 + allowed-tools 逐键校验 + D11 类描述扫描。

    幂等：同 (tenant, skill_key, version) 重复提交返回既有记录。
    """
    try:
        skill = skills_service.submit_skill(
            context,
            skill_key=payload.skill_key,
            version=payload.version,
            name=payload.name,
            description=payload.description,
            license=payload.license,
            allowed_tools=list(payload.allowed_tools),
            source_key=payload.source_key,
            content_sha256=payload.content_sha256,
            content_body=payload.content_body,
        )
    except (
        InvalidSkillPackage,
        SkillNotFound,
        SkillStateConflict,
        SkillSourceDenied,
        PolicyError,
    ) as exc:
        _raise_skill_http(exc)
    return _skill_view(skill)


@app.get("/api/v1/skills", response_model=SkillListResponse)
def list_skills(
    skill_status: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    context: UserContext = Depends(current_user),
) -> SkillListResponse:
    """技能列表：管理员全看；普通员工只看自己提交的；必须分页。"""
    try:
        items, total = skills_service.list_skills(
            context, status=skill_status, limit=limit, offset=offset
        )
    except (InvalidSkillPackage, SkillNotFound, PolicyError) as exc:
        _raise_skill_http(exc)
    return SkillListResponse(items=[_skill_view(item) for item in items], total=total, limit=limit, offset=offset)


@app.post("/api/v1/skills/{skill_key}/versions/{version}/review")
def review_skill(
    skill_key: str,
    version: str,
    approved: bool = Query(...),
    context: UserContext = Depends(current_user),
) -> SkillView:
    """审核技能包：仅 super_admin；提交人不能审自己的提交（生成者 ≠ 评审者）。"""
    try:
        skill = skills_service.review_skill(context, skill_key, version, approved=approved)
    except (InvalidSkillPackage, SkillNotFound, SkillStateConflict, PolicyError) as exc:
        _raise_skill_http(exc)
    return _skill_view(skill)


@app.post("/api/v1/skills/{skill_key}/versions/{version}/enable", response_model=SkillView)
def enable_skill(skill_key: str, version: str, context: UserContext = Depends(current_user)) -> SkillView:
    """启用技能（独立管理动作）：approved/disabled → enabled；已启用幂等。"""
    try:
        skill = skills_service.enable_skill(context, skill_key, version)
    except (SkillNotFound, SkillStateConflict, PolicyError) as exc:
        _raise_skill_http(exc)
    return _skill_view(skill)


@app.post("/api/v1/skills/{skill_key}/versions/{version}/disable", response_model=SkillView)
def disable_skill(skill_key: str, version: str, context: UserContext = Depends(current_user)) -> SkillView:
    """停用技能：enabled → disabled；已停用幂等。"""
    try:
        skill = skills_service.disable_skill(context, skill_key, version)
    except (SkillNotFound, SkillStateConflict, PolicyError) as exc:
        _raise_skill_http(exc)
    return _skill_view(skill)


@app.post("/api/v1/skills/bindings", response_model=SkillView)
def bind_skill(payload: SkillBindRequest, context: UserContext = Depends(current_user)) -> dict[str, str]:
    """绑定技能到数字员工（管理动作）。"""
    try:
        skills_service.bind_skill(context, payload.agent_key, payload.skill_key)
    except (InvalidSkillPackage, SkillNotFound, SkillStateConflict, PolicyError) as exc:
        _raise_skill_http(exc)
    return {"skill_key": payload.skill_key, "agent_key": payload.agent_key, "status": "active"}


@app.delete("/api/v1/skills/bindings")
def unbind_skill(
    skill_key: str = Query(...),
    agent_key: str = Query(...),
    context: UserContext = Depends(current_user),
) -> dict[str, str]:
    """解绑技能（管理动作）：active → disabled。"""
    try:
        skills_service.unbind_skill(context, agent_key, skill_key)
    except (InvalidSkillPackage, SkillNotFound, SkillStateConflict, PolicyError) as exc:
        _raise_skill_http(exc)
    return {"skill_key": skill_key, "agent_key": agent_key, "status": "disabled"}


@app.get("/api/v1/skills/agents/{agent_key}/tools", response_model=SkillExpandResponse)
def agent_skill_tools(agent_key: str, context: UserContext = Depends(current_user)) -> SkillExpandResponse:
    """返回某数字员工已启用技能的 allowed-tools 与执行目录的**交集**（服务端解析，fail-closed）。"""
    try:
        tools = skills_service.expanded_tools_for_agent(context, agent_key)
    except (SkillNotFound, PolicyError) as exc:
        _raise_skill_http(exc)
    return SkillExpandResponse(agent_key=agent_key, tools=list(tools))


@app.get("/api/v1/skills/{skill_key}/versions/{version}/content", response_model=SkillContentResponse)
def get_skill_content(
    skill_key: str, version: str, context: UserContext = Depends(current_user)
) -> SkillContentResponse:
    """返回技能包正文（M5 库内落库后的读取面；仅本人/管理员可见，他人未审包按 404）。"""
    try:
        skill = skills_service.get_skill(context, skill_key, version)
    except (SkillNotFound, PolicyError) as exc:
        _raise_skill_http(exc)
    return SkillContentResponse(
        skill_key=skill.skill_key,
        version=skill.version,
        content_body=skill.content_body,
        content_sha256=skill.content_sha256,
    )


@app.post("/api/v1/skills/{skill_key}/versions/{version}/memories", response_model=SkillExperienceResponse)
def save_skill_experience(
    skill_key: str,
    version: str,
    payload: SkillExperienceRequest,
    context: UserContext = Depends(current_user),
) -> SkillExperienceResponse:
    """M3 打通：把技能使用经验沉淀为事实类记忆（技能引用可检索，幂等）。

    技能须对当前操作者可见（本人/管理员，他人未审包 404）；记忆归属操作者自己；
    相同经验文本重复提交幂等返回既有记录。记忆层未接线 → 503（fail-closed）。
    """
    try:
        result = skills_service.save_experience(
            context, skill_key, version, content=payload.content
        )
    except (
        InvalidSkillPackage,
        SkillNotFound,
        SkillStateConflict,
        SkillSourceDenied,
        SkillMemoryUnavailable,
        PolicyError,
    ) as exc:
        _raise_skill_http(exc)
    return SkillExperienceResponse(
        skill_key=skill_key,
        version=version,
        fact_id=result["fact"].memory_id,
        idempotency_key=result["idempotency_key"],
        tagged_content=result["tagged_content"],
    )


@app.get("/api/v1/workforce/agents/{agent_key}/config", response_model=AgentConfigView)
def read_workforce_agent_config(
    agent_key: str, context: UserContext = Depends(current_user)
) -> AgentConfigView:
    """读数字员工配置；仅超级管理员，跨租户按不存在处理（404）。"""
    _require_workforce_directory_admin(context)
    try:
        employee = agent_config_service.read_config(context, agent_key)
    except (DirectoryError, DirectoryNotFound, PolicyError) as exc:
        _raise_directory_http(exc)
    return _agent_config_view(employee)


@app.patch("/api/v1/workforce/agents/{agent_key}/config", response_model=AgentConfigView)
def update_workforce_agent_config(
    agent_key: str, payload: AgentConfigUpdateRequest, context: UserContext = Depends(current_user)
) -> AgentConfigView:
    """改提示词 / 模型 / 温度 / 技能白名单 / 记忆策略 / 治理字段；仅超级管理员。

    D11：提示词在写入阶段即扫描，命中「忽略/绕过审批」这类指令一律 422 并写审计。
    """
    _require_workforce_directory_admin(context)
    try:
        employee = agent_config_service.update_config(
            context, agent_key, changes=payload.model_dump(exclude_unset=True)
        )
    except (DirectoryError, DirectoryNotFound, PolicyError) as exc:
        _raise_directory_http(exc)
    return _agent_config_view(employee)


def _knowledge_access_view(binding_type: str, binding_key: str, knowledge_base_ids: set[str]) -> dict[str, object]:
    return {
        "binding_type": binding_type,
        "binding_key": binding_key,
        "knowledge_base_ids": sorted(knowledge_base_ids),
    }


@app.put("/api/v1/knowledge-access/roles/{role_key}")
def bind_role_knowledge_access(
    role_key: str,
    payload: KnowledgeAccessUpdate,
    context: UserContext = Depends(current_user),
) -> dict[str, object]:
    """写路径闸门（阶段 2）：标识必须已在目录且启用，否则 `409`；权限判定优先（`403`）。"""
    try:
        _ensure_knowledge_admin(context)
        normalized = workforce_directory_service.ensure_role_binding_available(context, role_key)
        knowledge_access_registry.bind_role(context, normalized, set(payload.knowledge_base_ids))
        ids = knowledge_access_registry.resolve(context, normalized)
    except PolicyError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except DirectoryNotManaged as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _knowledge_access_view("role", normalized, ids)


@app.get("/api/v1/knowledge-access/roles/{role_key}")
def get_role_knowledge_access(role_key: str, context: UserContext = Depends(current_user)) -> dict[str, object]:
    try:
        _ensure_knowledge_admin(context)
    except PolicyError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return _knowledge_access_view("role", role_key, knowledge_access_registry.resolve(context, role_key))


@app.put("/api/v1/knowledge-access/agents/{agent_key}")
def bind_agent_knowledge_access(
    agent_key: str,
    payload: KnowledgeAccessUpdate,
    context: UserContext = Depends(current_user),
) -> dict[str, object]:
    """写路径闸门（阶段 2）：数字员工标识必须已在目录且启用，否则 `409`；权限判定优先（`403`）。"""
    try:
        _ensure_knowledge_admin(context)
        normalized = workforce_directory_service.ensure_agent_binding_available(context, agent_key)
        knowledge_access_registry.bind_agent(context, normalized, set(payload.knowledge_base_ids))
        ids = knowledge_access_registry.resolve(context, normalized, normalized)
    except PolicyError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except DirectoryNotManaged as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _knowledge_access_view("agent", normalized, ids)


@app.get("/api/v1/knowledge-access/agents/{agent_key}")
def get_agent_knowledge_access(agent_key: str, context: UserContext = Depends(current_user)) -> dict[str, object]:
    try:
        _ensure_knowledge_admin(context)
    except PolicyError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return _knowledge_access_view("agent", agent_key, knowledge_access_registry.resolve(context, agent_key, agent_key))


# ------------------------------------------------------------ P6a 自进化·评测集（规格 2026-09-16-self-evolution-p6-design.md §2.2/§2.3）

class EvalCaseCreateRequest(BaseModel):
    """登记评测用例（缺省草稿）：期望可后续用 `POST .../expectation` 补全，发布是独立管理动作。"""

    model_config = ConfigDict(extra="forbid")

    suite_key: str = Field(min_length=1, max_length=64)
    source: str = Field(default="manual", pattern="^(run_trace|manual|regression)$")
    input_snapshot: dict
    expectation: dict | None = None


class EvalCaseExpectationRequest(BaseModel):
    """补全草稿用例的期望（未发布即未生效；已发布用例的变更走 supersede）。"""

    model_config = ConfigDict(extra="forbid")

    expectation: dict


class EvalCaseSupersedeRequest(BaseModel):
    """用新用例替代旧用例（至少一项变更；旧条目 archived + superseded_by 链到新条目）。"""

    model_config = ConfigDict(extra="forbid")

    input_snapshot: dict | None = None
    expectation: dict | None = None


class EvalCaseView(BaseModel):
    case_id: str
    suite_key: str
    source: str
    status: str
    input_snapshot: dict
    expectation: dict
    input_digest: str
    superseded_by: str | None = None
    created_by: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


class EvalCaseListResponse(BaseModel):
    items: list[EvalCaseView]
    total: int
    limit: int
    offset: int


class EvalRunView(BaseModel):
    eval_run_id: str
    subject: str
    suite_key: str
    suite_digest: str
    status: str
    case_count: int
    pass_count: int
    cost_cents: int
    created_by: str
    created_at: datetime | None = None


class EvalCaseResultView(BaseModel):
    case_id: str
    passed: bool
    detail: dict


class EvalRunDetailResponse(EvalRunView):
    results: list[EvalCaseResultView]


class EvalRunListResponse(BaseModel):
    items: list[EvalRunView]
    total: int
    limit: int
    offset: int


def _evolution_service_or_503() -> EvolutionService:
    """关闭时不装配任何评测组件：管理端点一律 503（不返回空结果，以免被读成「没有用例」）。"""
    if evolution_service is None:
        raise HTTPException(status_code=503, detail="自进化评测组件未启用")
    return evolution_service


def _eval_case_view(case: EvalCase) -> EvalCaseView:
    return EvalCaseView(
        case_id=case.case_id,
        suite_key=case.suite_key,
        source=case.source.value,
        status=case.status.value,
        input_snapshot=case.input_snapshot,
        expectation=case.expectation,
        input_digest=case.input_digest,
        superseded_by=case.superseded_by,
        created_by=case.created_by,
        created_at=case.created_at,
        updated_at=case.updated_at,
    )


def _eval_run_view(run: EvalRun) -> EvalRunView:
    return EvalRunView(
        eval_run_id=run.eval_run_id,
        subject=run.subject,
        suite_key=run.suite_key,
        suite_digest=run.suite_digest,
        status=run.status.value,
        case_count=run.case_count,
        pass_count=run.pass_count,
        cost_cents=run.cost_cents,
        created_by=run.created_by,
        created_at=run.created_at,
    )


def _raise_evolution_http(exc: Exception) -> NoReturn:
    """把评测域异常映射成 HTTP 语义（规格 §4 裁决口径）。"""
    if isinstance(exc, EvalDisabled):
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if isinstance(exc, EvalCaseNotFound):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, EvalCaseStateConflict):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, (InvalidEvalCase, EvalSuiteTooLarge, EvalSuiteEmpty, UnknownEvalSubject, EvalCostExceeded)):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if isinstance(exc, PolicyError):
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    raise exc


@app.post("/api/v1/evolution/cases", response_model=EvalCaseView, status_code=status.HTTP_201_CREATED)
def create_eval_case(payload: EvalCaseCreateRequest, context: UserContext = Depends(current_user)) -> EvalCaseView:
    """登记评测用例（仅 super_admin）：来源三选一；快照必须脱敏且不含敏感键。"""
    service = _evolution_service_or_503()
    try:
        case = service.create_case(
            context,
            suite_key=payload.suite_key,
            source=payload.source,
            input_snapshot=payload.input_snapshot,
            expectation=payload.expectation,
        )
    except (InvalidEvalCase, PolicyError) as exc:
        _raise_evolution_http(exc)
    return _eval_case_view(case)


@app.get("/api/v1/evolution/cases", response_model=EvalCaseListResponse)
def list_eval_cases(
    suite_key: str | None = Query(default=None, max_length=64),
    case_status: str | None = Query(default=None, alias="status", max_length=32),
    source: str | None = Query(default=None, max_length=32),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    context: UserContext = Depends(current_user),
) -> EvalCaseListResponse:
    """评测用例列表（仅 super_admin；必须分页）。"""
    service = _evolution_service_or_503()
    try:
        items, total = service.list_cases(
            context, suite_key=suite_key, status=case_status, source=source, limit=limit, offset=offset
        )
    except (InvalidEvalCase, PolicyError) as exc:
        _raise_evolution_http(exc)
    return EvalCaseListResponse(
        items=[_eval_case_view(item) for item in items], total=total, limit=limit, offset=offset
    )


@app.get("/api/v1/evolution/cases/{case_id}", response_model=EvalCaseView)
def get_eval_case(case_id: str, context: UserContext = Depends(current_user)) -> EvalCaseView:
    """用例详情（跨租户一律 404，不泄露存在性）。"""
    service = _evolution_service_or_503()
    try:
        case = service.get_case(context, case_id)
    except (InvalidEvalCase, EvalCaseNotFound, PolicyError) as exc:
        _raise_evolution_http(exc)
    return _eval_case_view(case)


@app.post("/api/v1/evolution/cases/{case_id}/expectation", response_model=EvalCaseView)
def set_eval_case_expectation(
    case_id: str,
    payload: EvalCaseExpectationRequest,
    context: UserContext = Depends(current_user),
) -> EvalCaseView:
    """补全草稿用例的期望（仅草稿；已发布用例的变更走 supersede）。"""
    service = _evolution_service_or_503()
    try:
        case = service.set_expectation(context, case_id, payload.expectation)
    except (InvalidEvalCase, EvalCaseNotFound, EvalCaseStateConflict, PolicyError) as exc:
        _raise_evolution_http(exc)
    return _eval_case_view(case)


@app.post("/api/v1/evolution/cases/{case_id}/publish", response_model=EvalCaseView)
def publish_eval_case(case_id: str, context: UserContext = Depends(current_user)) -> EvalCaseView:
    """发布用例：发布闸门要求期望可执行（fail-closed）；重复发布幂等。"""
    service = _evolution_service_or_503()
    try:
        case = service.publish_case(context, case_id)
    except (InvalidEvalCase, EvalCaseNotFound, EvalCaseStateConflict, PolicyError) as exc:
        _raise_evolution_http(exc)
    return _eval_case_view(case)


@app.post("/api/v1/evolution/cases/{case_id}/archive", response_model=EvalCaseView)
def archive_eval_case(case_id: str, context: UserContext = Depends(current_user)) -> EvalCaseView:
    """归档用例（软删，不物理删）；重复归档幂等。"""
    service = _evolution_service_or_503()
    try:
        case = service.archive_case(context, case_id)
    except (InvalidEvalCase, EvalCaseNotFound, EvalCaseStateConflict, PolicyError) as exc:
        _raise_evolution_http(exc)
    return _eval_case_view(case)


@app.post("/api/v1/evolution/cases/{case_id}/supersede", response_model=EvalCaseView)
def supersede_eval_case(
    case_id: str,
    payload: EvalCaseSupersedeRequest,
    context: UserContext = Depends(current_user),
) -> EvalCaseView:
    """替代用例（至少一项变更）：新条目为草稿，旧条目 archived 并链到新条目。"""
    service = _evolution_service_or_503()
    try:
        case = service.supersede_case(
            context, case_id, input_snapshot=payload.input_snapshot, expectation=payload.expectation
        )
    except (InvalidEvalCase, EvalCaseNotFound, EvalCaseStateConflict, PolicyError) as exc:
        _raise_evolution_http(exc)
    return _eval_case_view(case)


@app.get("/api/v1/evolution/eval-runs", response_model=EvalRunListResponse)
def list_eval_runs(
    suite_key: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    context: UserContext = Depends(current_user),
) -> EvalRunListResponse:
    """评测运行列表（离线运行器产出；只读，仅 super_admin）。"""
    service = _evolution_service_or_503()
    try:
        items, total = service.list_runs(context, suite_key=suite_key, limit=limit, offset=offset)
    except (InvalidEvalCase, PolicyError) as exc:
        _raise_evolution_http(exc)
    return EvalRunListResponse(
        items=[_eval_run_view(item) for item in items], total=total, limit=limit, offset=offset
    )


@app.get("/api/v1/evolution/eval-runs/{eval_run_id}", response_model=EvalRunDetailResponse)
def get_eval_run(eval_run_id: str, context: UserContext = Depends(current_user)) -> EvalRunDetailResponse:
    """评测运行详情（含逐例判定；明细只含判定与计数，不含正文）。"""
    service = _evolution_service_or_503()
    try:
        run = service.get_run(context, eval_run_id)
        results = service.list_results(context, eval_run_id)
    except (InvalidEvalCase, EvalCaseNotFound, PolicyError) as exc:
        _raise_evolution_http(exc)
    base = _eval_run_view(run)
    return EvalRunDetailResponse(
        **base.model_dump(),
        results=[
            EvalCaseResultView(case_id=item.case_id, passed=item.passed, detail=item.detail)
            for item in results
        ],
    )


# ------------------------------------------------------------ 知识治理层（规格 2026-09-15-knowledge-governance-design.md §2）


class KnowledgeDocView(BaseModel):
    """知识文档视图：不含正文（正文仍在 WeKnora 侧）。"""

    document_id: str
    title: str
    owner_id: str
    status: str
    version: str
    source_key: str
    last_reviewed_at: datetime | None = None
    review_due_at: datetime | None = None
    registered_by: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


class KnowledgeDocRegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_id: str = Field(min_length=1, max_length=128)
    title: str = Field(default="", max_length=300)
    owner_id: str = Field(default="", max_length=128)
    version: str = Field(default="1", max_length=32)
    source_key: str = Field(default="manual", max_length=32)


class KnowledgeDocListResponse(BaseModel):
    items: list[KnowledgeDocView]
    total: int
    limit: int
    offset: int


class KnowledgeMetricsResponse(BaseModel):
    published: int
    needs_review: int
    archived: int
    total: int
    freshness_ratio: float


def _knowledge_doc_view(doc: KnowledgeDoc) -> KnowledgeDocView:
    return KnowledgeDocView(
        document_id=doc.document_id,
        title=doc.title,
        owner_id=doc.owner_id,
        status=doc.status.value if hasattr(doc.status, "value") else str(doc.status),
        version=doc.version,
        source_key=doc.source_key,
        last_reviewed_at=doc.last_reviewed_at,
        review_due_at=doc.review_due_at,
        registered_by=doc.registered_by,
        created_at=doc.created_at,
        updated_at=doc.updated_at,
    )


def _raise_knowledge_gov_http(exc: Exception) -> NoReturn:
    """把知识治理领域异常映射成 HTTP 语义（规格 §3.2）。"""
    if isinstance(exc, KnowledgeDocStateConflict):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, InvalidKnowledgeDoc):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if isinstance(exc, KnowledgeDocNotFound):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, PolicyError):
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    raise exc


def _raise_knowledge_search_http(exc: Exception) -> NoReturn:
    """检索入口的上游失败映射（规格 §2.3 接线段）：超时 504、其余上游失败 502。

    **不得吞异常返回空结果**（那会把「上游坏了」读成「没查到」）。对外只给固定文案：
    上游原文（含主机名 / URL）只进日志，不回显给客户端。
    """
    if isinstance(exc, httpx.TimeoutException):
        logger.warning("知识检索上游超时：%s", exc)
        raise HTTPException(status_code=504, detail="知识检索服务超时，请稍后重试") from exc
    if isinstance(exc, PolicyError):
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if isinstance(exc, (httpx.HTTPError, RuntimeError)):
        logger.warning("知识检索上游失败：%s", exc)
        raise HTTPException(status_code=502, detail="知识检索服务暂不可用") from exc
    raise exc


@app.post("/api/v1/knowledge/documents", response_model=KnowledgeDocView, status_code=status.HTTP_201_CREATED)
def register_knowledge_doc(
    payload: KnowledgeDocRegisterRequest, context: UserContext = Depends(current_user)
) -> KnowledgeDocView:
    """登记知识文档（draft；仅 super_admin）。幂等：同 (tenant, document_id) 重复返回既有。"""
    try:
        doc = knowledge_governance_service.register_document(
            context,
            document_id=payload.document_id,
            title=payload.title,
            owner_id=payload.owner_id,
            version=payload.version,
            source_key=payload.source_key,
        )
    except (InvalidKnowledgeDoc, KnowledgeDocNotFound, KnowledgeDocStateConflict, PolicyError) as exc:
        _raise_knowledge_gov_http(exc)
    return _knowledge_doc_view(doc)


@app.get("/api/v1/knowledge/documents", response_model=KnowledgeDocListResponse)
def list_knowledge_docs(
    knowledge_status: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    context: UserContext = Depends(current_user),
) -> KnowledgeDocListResponse:
    """知识文档列表（仅 super_admin）；必须分页。"""
    try:
        items, total = knowledge_governance_service.list_documents(
            context, status=knowledge_status, limit=limit, offset=offset
        )
    except (InvalidKnowledgeDoc, KnowledgeDocNotFound, PolicyError) as exc:
        _raise_knowledge_gov_http(exc)
    return KnowledgeDocListResponse(
        items=[_knowledge_doc_view(item) for item in items], total=total, limit=limit, offset=offset
    )


@app.post("/api/v1/knowledge/documents/{document_id}/publish", response_model=KnowledgeDocView)
def publish_knowledge_doc(
    document_id: str,
    owner_id: str | None = Query(default=None, max_length=128),
    context: UserContext = Depends(current_user),
) -> KnowledgeDocView:
    """发布知识文档（发布闸门：owner 必填；draft → published）。"""
    try:
        doc = knowledge_governance_service.publish_document(
            context, document_id, owner_id=owner_id
        )
    except (InvalidKnowledgeDoc, KnowledgeDocNotFound, KnowledgeDocStateConflict, PolicyError) as exc:
        _raise_knowledge_gov_http(exc)
    return _knowledge_doc_view(doc)


@app.post("/api/v1/knowledge/documents/{document_id}/archive", response_model=KnowledgeDocView)
def archive_knowledge_doc(document_id: str, context: UserContext = Depends(current_user)) -> KnowledgeDocView:
    """归档知识文档（终态，不物理删）。"""
    try:
        doc = knowledge_governance_service.archive_document(context, document_id)
    except (InvalidKnowledgeDoc, KnowledgeDocNotFound, KnowledgeDocStateConflict, PolicyError) as exc:
        _raise_knowledge_gov_http(exc)
    return _knowledge_doc_view(doc)


@app.post("/api/v1/knowledge/documents/{document_id}/review")
def review_knowledge_doc(
    document_id: str,
    approved: bool = Query(...),
    context: UserContext = Depends(current_user),
) -> KnowledgeDocView:
    """复核知识文档（人工事件）：approved → published + 刷新复核时间；否则 → archived。"""
    try:
        doc = knowledge_governance_service.review_document(context, document_id, approved=approved)
    except (InvalidKnowledgeDoc, KnowledgeDocNotFound, KnowledgeDocStateConflict, PolicyError) as exc:
        _raise_knowledge_gov_http(exc)
    return _knowledge_doc_view(doc)


@app.post("/api/v1/knowledge/review-scan")
def scan_knowledge_review_due(context: UserContext = Depends(current_user)) -> dict[str, int]:
    """手动触发到期扫描：published 且过 review_due_at → needs_review；返回置位数（幂等）。"""
    try:
        count = knowledge_governance_service.scan_review_due(context)
    except (InvalidKnowledgeDoc, KnowledgeDocNotFound, KnowledgeDocStateConflict, PolicyError) as exc:
        _raise_knowledge_gov_http(exc)
    return {"reviewed_due": count}


@app.get("/api/v1/knowledge/metrics", response_model=KnowledgeMetricsResponse)
def knowledge_governance_metrics(context: UserContext = Depends(current_user)) -> KnowledgeMetricsResponse:
    """Freshness Index（运营指标，仅 super_admin）。"""
    try:
        metrics = knowledge_governance_service.metrics(context)
    except (InvalidKnowledgeDoc, KnowledgeDocNotFound, PolicyError) as exc:
        _raise_knowledge_gov_http(exc)
    return KnowledgeMetricsResponse(**metrics)


@app.get("/api/v1/knowledge/governance/eligible", response_model=KnowledgeDocListResponse)
def knowledge_governance_eligible(
    limit: int = Query(default=200, ge=1, le=1000),
    context: UserContext = Depends(current_user),
) -> KnowledgeDocListResponse:
    """检索谓词守卫白名单出口（§2.3）：只返回 status='published' 且未过 review_due_at 的文档。

    供未来检索组合件在请求 WeKnora 前取白名单（空则 fail-closed）；仅 super_admin 可读。
    """
    try:
        ensure_knowledge_metrics_read(context)
        docs = knowledge_governance_service.list_published_eligible(context)
    except (InvalidKnowledgeDoc, KnowledgeDocNotFound, PolicyError) as exc:
        _raise_knowledge_gov_http(exc)
    return KnowledgeDocListResponse(
        items=[_knowledge_doc_view(item) for item in docs], total=len(docs), limit=limit, offset=0
    )


# ------------------------------------------------------------ 知识检索入口（§2.3 接线）

class KnowledgeSearchRequest(BaseModel):
    """检索请求：**范围只能由服务端解析**——客户端只能选「用哪个岗位 / 哪个数字员工」，不得自带租户或知识库 id。"""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=500)
    role_key: str | None = Field(default=None, max_length=64)
    agent_key: str | None = Field(default=None, max_length=64)
    limit: int = Field(default=10, ge=1, le=50)

    @model_validator(mode="after")
    def _exactly_one_scope(self) -> "KnowledgeSearchRequest":
        if bool(self.role_key) == bool(self.agent_key):
            raise ValueError("role_key 与 agent_key 必须且只能提供一个")
        return self


class KnowledgeSearchCitationView(BaseModel):
    citation_id: str
    content: str
    source_title: str
    knowledge_id: str
    score: float | None = None


class KnowledgeSearchResponse(BaseModel):
    items: list[KnowledgeSearchCitationView]
    total: int
    limit: int
    truncated: bool
    # 空结果归因：`no_binding`（该岗位/员工没有绑定）/ `empty_whitelist`（守卫拦截，fail-closed）/
    # `no_hits`（白名单非空但无命中）；非空结果为 None。供运维区分「配置问题」与「真没查到」。
    reason: str | None = None


class _BoundRegistry:
    """把「本次请求已解析出的知识库集合」交给谓词守卫（不回放第二次解析）。

    守卫内部会调 `registry.resolve(context, role_key)`；而端点已按 `role_key` / `agent_key`
    解析过一次（`registry.resolve` 支持 `agent_key`，守卫只传 `role_key`）⇒ 这里**只回放已解析结果**，
    不重新解析、也不允许扩大（与测试 `_FakeRegistry` 同手法 ⇒ 守卫代码零改动）。
    """

    def __init__(self, knowledge_base_ids: set[str]) -> None:
        self._ids = frozenset(knowledge_base_ids)

    def resolve(self, _context: UserContext, _role_key: str) -> set[str]:
        return set(self._ids)


def _audit_blocked_search(context: UserContext, payload: KnowledgeSearchRequest, *, reason: str) -> None:
    """拦截路径落审计（§2.7 扩展码）：只记受控字段（role_key / agent_key / reason），**不记查询正文**。

    读操作例外：审计通道故障**不阻断检索**（只在日志留痕），失败也不静默——见下方 warning。
    """
    detail: dict[str, object] = {"reason": reason}
    if payload.role_key:
        detail["role_key"] = payload.role_key
    if payload.agent_key:
        detail["agent_key"] = payload.agent_key
    try:
        audit_service.record(
            AuditAction.KNOWLEDGE_SEARCH_BLOCKED,
            tenant_id=context.tenant_id,
            actor_id=context.user_id,
            target_type="knowledge_search",
            target_id=payload.role_key or payload.agent_key or "",
            detail=detail,
        )
    except Exception as exc:  # noqa: BLE001 —— 读操作不因审计通道故障而失败
        logger.warning("知识检索拦截审计写入失败：%s", exc)


@app.post("/api/v1/knowledge/search", response_model=KnowledgeSearchResponse)
def knowledge_search(
    payload: KnowledgeSearchRequest,
    context: UserContext = Depends(current_user),
) -> KnowledgeSearchResponse:
    """知识检索（治理层唯一生产入口，规格 §2.3）：谓词守卫在请求 WeKnora **前**完成文档级 pre-filter。

    口径：
    - **仅 super_admin**；范围由服务端按 `role_key` / `agent_key` 解析（客户端不得自带租户/知识库）；
    - 未配置 WeKnora 或治理开关关闭 ⇒ **503**（不提供「无守卫的检索入口」，避免造旁路）；
    - 无绑定 / 白名单空 ⇒ **不请求上游**（fail-closed）并落 `knowledge.search.blocked` 审计；
    - 上游超时 ⇒ 504、其余上游失败 ⇒ 502（`_raise_knowledge_search_http`）；
    - `limit` 只做**服务端截断**（上游 `top_k` 语义未核实，不臆造）。
    """
    try:
        _ensure_knowledge_admin(context)
    except PolicyError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if weknora_search_runtime is None or not settings.knowledge_governance_enabled:
        raise HTTPException(status_code=503, detail="知识检索服务未启用")

    role_key = payload.role_key or ""
    resolved = knowledge_access_registry.resolve(context, role_key, payload.agent_key)
    if not resolved:
        _audit_blocked_search(context, payload, reason="no_binding")
        return KnowledgeSearchResponse(
            items=[], total=0, limit=payload.limit, truncated=False, reason="no_binding"
        )

    adapter = weknora_search_runtime.adapter_for(
        tenant_id=context.tenant_id, knowledge_base_ids=resolved
    )
    guard = build_scoped_search(
        governance=knowledge_governance_service,
        registry=_BoundRegistry(resolved),
        adapter=adapter,
        enabled=True,
    )
    try:
        citations = guard(context, role_key, payload.query)
    except (httpx.HTTPError, RuntimeError, PolicyError) as exc:
        _raise_knowledge_search_http(exc)

    if not citations:
        try:
            whitelist = knowledge_governance_service.list_published_eligible(context)
        except (InvalidKnowledgeDoc, KnowledgeDocNotFound, PolicyError) as exc:
            _raise_knowledge_gov_http(exc)
        reason = "empty_whitelist" if not whitelist else "no_hits"
        if reason == "empty_whitelist":
            _audit_blocked_search(context, payload, reason=reason)
        return KnowledgeSearchResponse(
            items=[], total=0, limit=payload.limit, truncated=False, reason=reason
        )

    return KnowledgeSearchResponse(
        items=[
            KnowledgeSearchCitationView(
                citation_id=item.citation_id,
                content=item.content,
                source_title=item.source_title,
                knowledge_id=item.knowledge_id,
                score=item.score,
            )
            for item in citations[: payload.limit]
        ],
        total=len(citations),
        limit=payload.limit,
        truncated=len(citations) > payload.limit,
        reason=None,
    )


@app.get("/api/v1/knowledge-access/audits")
def list_knowledge_access_audits(
    context: UserContext = Depends(current_user),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[dict[str, object]]:
    try:
        _ensure_knowledge_admin(context)
    except PolicyError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return [
        {
            "tenant_id": audit.tenant_id,
            "binding_type": audit.binding_type,
            "binding_key": audit.binding_key,
            "old_knowledge_base_ids": audit.old_knowledge_base_ids,
            "new_knowledge_base_ids": audit.new_knowledge_base_ids,
            "actor_id": audit.actor_id,
            "occurred_at": audit.occurred_at,
        }
        for audit in knowledge_access_registry.list_audits(context, limit=limit)
    ]


class AuditRecordView(BaseModel):
    record_id: str
    action: str
    actor_id: str | None = None
    target_type: str | None = None
    target_id: str | None = None
    phone_masked: str | None = None
    detail: dict[str, object]
    occurred_at: datetime


class AuditListView(BaseModel):
    items: list[AuditRecordView]
    total: int
    limit: int
    offset: int


def _parse_audit_actions(values: list[str] | None) -> list[AuditAction] | None:
    """把查询参数里的动作码转成枚举；未知动作码直接拒绝，不做静默忽略。"""
    if not values:
        return None
    parsed: list[AuditAction] = []
    for raw in values:
        try:
            parsed.append(AuditAction(raw))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"未知的审计动作：{raw}") from exc
    return parsed


def _require_aware(value: datetime | None, *, name: str) -> datetime | None:
    """拒绝无时区时间：否则时间范围的含义随部署时区漂移。"""
    if value is None:
        return None
    if value.tzinfo is None:
        raise HTTPException(status_code=422, detail=f"{name} 必须带时区")
    return value


@app.get("/api/v1/audits", response_model=AuditListView)
def list_audits(
    action: list[str] | None = Query(default=None),
    target_type: str | None = None,
    target_id: str | None = None,
    actor_id: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    context: UserContext = Depends(current_user),
) -> AuditListView:
    """通用审计查询：仅 CEO/超级管理员，且只返回当前租户的记录（tenant_id 为空的全局记录不返回）。"""
    if context.role not in {"ceo", "super_admin"}:
        raise HTTPException(status_code=403, detail="只有 CEO 或超级管理员可以查看审计日志")
    items, total = audit_service.query(
        context.tenant_id,
        actions=_parse_audit_actions(action),
        target_type=target_type,
        target_id=target_id,
        actor_id=actor_id,
        since=_require_aware(since, name="since"),
        until=_require_aware(until, name="until"),
        limit=limit,
        offset=offset,
    )
    return AuditListView(
        items=[
            AuditRecordView(
                record_id=record.record_id,
                action=record.action.value,
                actor_id=record.actor_id,
                target_type=record.target_type,
                target_id=record.target_id,
                phone_masked=record.phone_masked,
                detail=record.detail,
                occurred_at=record.occurred_at,
            )
            for record in items
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@app.get("/api/v1/collaboration-dynamics", response_model=list[CollaborationDynamicView])
def collaboration_dynamics(
    context: UserContext = Depends(current_user),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[CollaborationDynamicView]:
    dynamics: list[CollaborationDynamicView] = []
    for event in event_bus.read_recent(limit=limit):
        if event.aggregate_type != "task":
            continue
        try:
            task = store.get(context, event.aggregate_id)
        except TaskNotFound:
            continue
        dynamics.append(
            CollaborationDynamicView(
                event_id=event.event_id,
                aggregate_id=event.aggregate_id,
                action=event.action,
                title=task.title,
                employee_key=task.employee_key,
                status=task.status,
                tenant_id=task.tenant_id,
                project_id=task.project_id,
                created_by=task.created_by,
                occurred_at=event.occurred_at,
            )
        )
    return dynamics


@app.post("/api/v1/tasks", response_model=TaskView, status_code=status.HTTP_201_CREATED)
def create_task(
    payload: TaskCreate,
    response: Response,
    context: UserContext = Depends(current_user),
) -> TaskView:
    try:
        ensure_can_create(context, payload.risk_level, payload.budget)
    except PolicyError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    # 审批判定收敛到 workforce 服务一处（段一规格 §2.2）：有纳管员工按其治理配置，
    # 否则回落「风险不低于 high 即审批」的既有口径。
    requires_approval = workforce_directory_service.task_requires_approval(
        context, agent_key=payload.employee_key, risk_level=payload.risk_level
    )

    task = Task(
        tenant_id=context.tenant_id,
        project_id=payload.project_id,
        created_by=context.user_id,
        employee_key=payload.employee_key,
        title=payload.title,
        risk_level=payload.risk_level,
        budget=payload.budget,
        idempotency_key=payload.idempotency_key,
        request_fingerprint=hashlib.sha256(
            json.dumps(payload.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        status=TaskStatus.PENDING_APPROVAL if requires_approval else TaskStatus.QUEUED,
    )
    task.audits.append(AuditEvent(action="task.created", actor_id=context.user_id, actor_role=context.role))
    try:
        stored, created = store.create(context, task)
    except IdempotencyConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not created:
        response.status_code = status.HTTP_200_OK
        return to_view(stored)
    publish_task_event(stored, "task.created", context)
    return to_view(stored)


@app.get("/api/v1/tasks/{task_id}", response_model=TaskView)
def get_task(task_id: str, context: UserContext = Depends(current_user)) -> TaskView:
    try:
        return to_view(store.get(context, task_id))
    except TaskNotFound as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc


@app.post("/api/v1/tasks/{task_id}/approve", response_model=TaskView)
def approve_task(task_id: str, context: UserContext = Depends(current_user)) -> TaskView:
    try:
        ensure_can_approve(context)
        # 发起人不得自审（与计划提案 / 运行内审批同一口径）：先取任务做归属校验，
        # 再走状态机（403 先于 409，与既有审批入口的检查顺序一致）。
        if store.get(context, task_id).created_by == context.user_id:
            raise PolicyError("发起人不能审批自己创建的任务")
        task = store.approve(context, task_id)
    except PolicyError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except TaskNotFound as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc
    except TaskStateConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    publish_task_event(task, "task.approved", context)
    # 站内通知：把结果告知任务创建人（通知失败不阻断审批，内部降级为审计）。
    inbox_service.task_approved(
        tenant_id=task.tenant_id, recipient_id=task.created_by, task_id=task.id
    )
    return to_view(task)


def _notify_run_terminal(context: UserContext, run_id: str) -> None:
    """运行进入失败/取消终态时通知任务创建人。

    接收人必须反查（运行记录不含 user_id）；任务不可见时**跳过并写审计**，不猜接收人。
    通知本身不是关键路径：写入失败由 InboxService 降级为 `inbox.write_failed` 审计。
    """
    try:
        record = run_metrics_service.store.get(context.tenant_id, run_id)
    except RunRecordNotFound:
        return
    if record.status not in {"failed", "cancelled"}:
        return
    notify_kind = (
        "run.approval_rejected"
        if record.finish_reason is FinishReason.APPROVAL_REJECTED
        else f"run.{record.status}"
    )
    try:
        task = store.get(context, record.task_id)
    except TaskNotFound:
        audit_service.record(
            AuditAction.RUN_NOTIFY_SKIPPED,
            tenant_id=record.tenant_id,
            actor_id=context.user_id,
            target_type="run",
            target_id=run_id,
            detail={"kind": notify_kind, "reason": "task_unavailable"},
        )
        return
    if record.finish_reason is FinishReason.APPROVAL_REJECTED:
        inbox_service.run_approval_rejected(
            tenant_id=record.tenant_id,
            recipient_id=task.created_by,
            run_id=run_id,
        )
        return
    inbox_service.run_decided(
        tenant_id=record.tenant_id,
        recipient_id=task.created_by,
        run_id=run_id,
        status=record.status,
    )


@app.post("/api/v1/tasks/{task_id}/runs", response_model=RuntimeRunView, status_code=status.HTTP_201_CREATED)
def start_runtime_run(task_id: str, payload: RuntimeRunCreate, context: UserContext = Depends(current_user)) -> RuntimeRunView:
    try:
        run_id, runtime_key, policy_version = runtime_service.start(context, task_id, payload.runtime_key, payload.steps, payload.mode)
    except RunAccessDenied as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc
    except (PolicyDenied, ApprovalRequired) as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=400, detail="运行时不可用") from exc
    _notify_run_terminal(context, run_id)
    return RuntimeRunView(run_id=run_id, runtime_key=runtime_key, policy_version=policy_version, status=runtime_service.snapshot(context, run_id).status)


@app.get("/api/v1/runs/{run_id}/events")
def stream_runtime_events(run_id: str, cursor: str | None = None, context: UserContext = Depends(current_user)) -> list[dict[str, object]]:
    """运行事件（**只读**）。P2c-6 裁定 ⑤：会话成员可见（`member_reader=True`，仅此读路径放松）。"""
    try:
        _key, adapter, _state = runtime_service.adapter_for_task(context, run_id, member_reader=True)
        events = adapter.stream_events(run_id, cursor)
    except RunAccessDenied as exc:
        detail = str(exc)
        raise HTTPException(status_code=404 if detail == "运行不存在" else 403, detail=detail) from exc
    return [event.to_public_dict() for event in events]


@app.get("/api/v1/runs/{run_id}/artifacts")
def list_run_artifacts(
    run_id: str, context: UserContext = Depends(current_user)
) -> dict[str, object]:
    """产物登记只读列表（P2c-3 §2.7 / 契约「产物登记与只读端点」）。

    - **归属判定与运行接口一致**（同 `/runs/{run_id}/metrics`）：本租户运行记录 + 承载任务可见性；
      跨租户 / 不可见 / 未知运行一律 `404`（不泄露存在性）；
    - **只返回元数据**（虚拟路径 / 变更类型 / 字节 / sha256 / 时间）——**不含** `tenant_id`、宿主真实路径与内容；
    - 保留期已到（`expires_at <= now`、尚未被周期任务清理）的条目**不再返回**（保留期外如实降级）。
    - P2c-6 裁定 ⑤：**会话成员可见**——承载任务不可见时用成员判定兜底（`_member_can_read_run`）。
    """
    try:
        record = run_metrics_service.store.get(context.tenant_id, run_id)
    except RunRecordNotFound as exc:
        raise HTTPException(status_code=404, detail="运行记录不存在") from exc
    try:
        store.get(context, record.task_id)
    except TaskNotFound as exc:
        if not _member_can_read_run(context, run_id):
            raise HTTPException(status_code=404, detail="运行记录不存在") from exc
    items = run_artifact_store.list_for_run(context.tenant_id, run_id)
    return {
        "run_id": run_id,
        "items": [item.to_view() for item in items],
        "total": len(items),
    }


@app.get("/api/v1/runs/{run_id}/acceptance")
def get_run_acceptance(run_id: str, context: UserContext = Depends(current_user)) -> dict[str, object]:
    """运行**结构判定**（P2c-4 §2.5「自动验收」）：三条件全满足 ⇒ `met`，否则 `unmet`（如实）。

    **纯读**：不调模型、不写库、不改运行状态。归属判定同运行接口（跨租户 / 不可见 / 未知运行 `404`）。
    三条件：① 步骤全部完成 ② 无未决审批 ③ `finish_reason` 为正常终态（`run_completed`）。
    P2c-6 裁定 ⑤：**会话成员可见**（承载任务不可见时用成员判定兜底 + `member_reader=True`）。
    """
    try:
        record = run_metrics_service.store.get(context.tenant_id, run_id)
    except RunRecordNotFound as exc:
        raise HTTPException(status_code=404, detail="运行记录不存在") from exc
    try:
        store.get(context, record.task_id)
    except TaskNotFound as exc:
        if not _member_can_read_run(context, run_id):
            raise HTTPException(status_code=404, detail="运行记录不存在") from exc
    try:
        _key, _adapter, state = runtime_service.adapter_for_task(context, run_id, member_reader=True)
    except RunAccessDenied as exc:
        raise HTTPException(status_code=404, detail="运行不存在") from exc
    result = evaluate_acceptance(
        status=record.status,
        step_count=record.step_count,
        completed_step_count=record.completed_step_count,
        finish_reason=str(record.finish_reason) if record.finish_reason else None,
        approval_statuses=tuple(state.approvals.values()),
    )
    return {
        "run_id": run_id,
        "verdict": result.verdict.value,
        "checks": {
            "steps_complete": result.steps_complete,
            "no_pending_approvals": result.no_pending_approvals,
            "finish_reason_ok": result.finish_reason_ok,
        },
        "steps": {"completed": result.completed_steps, "total": result.total_steps},
        "pending_approvals": result.pending_approvals,
        "finish_reason": result.finish_reason,
        "status": result.status,
    }


@app.get("/api/v1/runs/{run_id}/metrics", response_model=RunMetricsView)
def get_run_metrics(run_id: str, context: UserContext = Depends(current_user)) -> RunMetricsView:
    """运行概览（**只读**）。P2c-6 裁定 ⑤：会话成员可见（承载任务不可见时用成员判定兜底）。"""
    try:
        record = run_metrics_service.store.get(context.tenant_id, run_id)
    except RunRecordNotFound as exc:
        raise HTTPException(status_code=404, detail="运行记录不存在") from exc
    try:
        store.get(context, record.task_id)
    except TaskNotFound as exc:
        if not _member_can_read_run(context, run_id):
            raise HTTPException(status_code=404, detail="运行记录不存在") from exc
    return RunMetricsView(
        run_id=record.run_id,
        task_id=record.task_id,
        proposal_id=record.proposal_id,
        runtime_key=record.runtime_key,
        status=record.status,
        step_count=record.step_count,
        completed_step_count=record.completed_step_count,
        tool_calls=record.tool_calls,
        successful_tools=record.successful_tools,
        knowledge_hits=record.knowledge_hits,
        latency_ms=record.latency_ms,
        started_at=record.started_at,
        finished_at=record.finished_at,
        finish_reason=str(record.finish_reason) if record.finish_reason else None,
    )


@app.get("/api/v1/metrics/summary")
def get_run_metrics_summary(
    runtime_key: str | None = None, context: UserContext = Depends(current_user)
) -> dict[str, object]:
    if context.role not in {"ceo", "super_admin"}:
        raise HTTPException(status_code=403, detail="只有 CEO 或超级管理员可以查看运行指标")
    return run_metrics_service.summary(context.tenant_id, runtime_key=runtime_key)


@app.post("/api/v1/runs/{run_id}/pause")
def pause_runtime_run(run_id: str, payload: RuntimeAction, context: UserContext = Depends(current_user)) -> dict[str, str]:
    try:
        runtime_service.pause(context, run_id, payload.reason)
    except RunAccessDenied as exc:
        raise HTTPException(status_code=404, detail="运行不存在") from exc
    return {"run_id": run_id, "status": "paused"}


@app.post("/api/v1/runs/{run_id}/resume")
def resume_runtime_run(run_id: str, context: UserContext = Depends(current_user)) -> dict[str, str]:
    try:
        runtime_service.resume(context, run_id)
    except RunAccessDenied as exc:
        raise HTTPException(status_code=404, detail="运行不存在") from exc
    return {"run_id": run_id, "status": "running"}


@app.post("/api/v1/runs/{run_id}/cancel")
def cancel_runtime_run(run_id: str, payload: RuntimeAction, context: UserContext = Depends(current_user)) -> dict[str, str]:
    try:
        runtime_service.cancel(context, run_id, payload.reason)
    except RunAccessDenied as exc:
        raise HTTPException(status_code=404, detail="运行不存在") from exc
    _notify_run_terminal(context, run_id)
    return {"run_id": run_id, "status": "cancelled"}


@app.post("/api/v1/runs/{run_id}/approvals", status_code=status.HTTP_202_ACCEPTED)
def request_runtime_approval(run_id: str, payload: RuntimeApprovalCreate, context: UserContext = Depends(current_user)) -> dict[str, str]:
    try:
        _key, adapter, _state = runtime_service.adapter_for_task(context, run_id)
        approval_id = adapter.request_approval(run_id, payload.action)
    except RunAccessDenied as exc:
        raise HTTPException(status_code=404, detail="运行不存在") from exc
    return {"run_id": run_id, "approval_id": approval_id, "status": "pending"}


class RunApprovalDecision(BaseModel):
    """审批决议请求体。`extra="forbid"`：客户端塞 `authorized_by` 之类字段会直接 422。"""

    model_config = ConfigDict(extra="forbid")

    approved: bool


# 执行授权位的来源**由服务端判定**，请求体不能覆盖；取值必须在 `AUTHORIZATION_SOURCES` 白名单内。
RUN_APPROVAL_SOURCE = "user"


class RunApprovalView(BaseModel):
    approval_id: str
    step_id: str | None = None
    tool: str | None = None
    status: str


class RunApprovalListView(BaseModel):
    items: list[RunApprovalView]


@app.get("/api/v1/runs/{run_id}/approvals", response_model=RunApprovalListView)
def list_run_approvals(run_id: str, context: UserContext = Depends(current_user)) -> RunApprovalListView:
    """列出该运行的审批项（含已决议），供审批人查看待办与结果。

    P2c-6 裁定 ⑤：**只读列表**对会话成员可见；**决议端点不放松**（决议仍仅 CEO / 超管且不得自审）。
    """
    try:
        _key, _adapter, state = runtime_service.adapter_for_task(context, run_id, member_reader=True)
    except RunAccessDenied as exc:
        raise HTTPException(status_code=404, detail="运行不存在") from exc
    tools = {step.step_id: step.tool for step in state.plan.steps}
    return RunApprovalListView(
        items=[
            RunApprovalView(
                approval_id=approval_id,
                step_id=approval_id if approval_id in tools else None,
                tool=tools.get(approval_id),
                status=status,
            )
            for approval_id, status in state.approvals.items()
        ]
    )


@app.post("/api/v1/runs/{run_id}/approvals/{approval_id}/approval")
def decide_run_approval(
    run_id: str,
    approval_id: str,
    payload: RunApprovalDecision,
    context: UserContext = Depends(current_user),
) -> dict[str, object]:
    """决议运行内的审批项；仅 CEO/超级管理员，且发起人不能自审。"""
    # P2c-4 §2.9（推进处 fail-closed）：会话模式为 `ask` ⇒ **整体拒绝**（不落决议、不重跑）。
    # 放在最前：宁可拒绝决议，也不产生「已批准但被模式挡住」的悬挂授权位。
    try:
        conversation_execution_service.ensure_resume_allowed(context, run_id)
    except ConversationExecutionError as exc:
        raise HTTPException(status_code=exc.http_status, detail=str(exc)) from exc
    try:
        runtime_service.decide_approval(
            context, run_id, approval_id, payload.approved, source=RUN_APPROVAL_SOURCE
        )
    except RunAccessDenied as exc:
        raise HTTPException(status_code=404, detail="运行不存在") from exc
    except RunApprovalDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ApprovalNotFound as exc:
        raise HTTPException(status_code=404, detail="审批不存在") from exc
    except ApprovalAlreadyDecided as exc:
        raise HTTPException(status_code=409, detail="审批已决议") from exc
    except RunNotDecidable as exc:
        raise HTTPException(status_code=409, detail="运行已结束，无法决议") from exc
    except ExecutionNotAuthorized as exc:
        # 授权位落不下或与当前计划不一致：拒绝推进执行（fail-closed）。
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    audit_service.record(
        AuditAction.RUN_APPROVAL_DECIDED,
        tenant_id=context.tenant_id,
        actor_id=context.user_id,
        target_type="run",
        target_id=run_id,
        detail={
            "status": "approved" if payload.approved else "rejected",
            # 授权来源由服务端判定，不来自请求体（`RunApprovalDecision` 是 extra=forbid）。
            "authorized_by_source": RUN_APPROVAL_SOURCE,
        },
    )
    _notify_run_terminal(context, run_id)
    # 段二（dsh 接入段）§4.1.6-4：审批**通过**且装配了工具执行入口时，在同一请求内触发「审批后重跑」。
    # 调用位置在 `decide_approval`（【事务 A】写 027 决议 + 026 快照 + 适配器决议）**提交之后**，
    # **不在其事务内**——依据 §4.1.6-5「授权位不回滚」（重跑失败不撤销已批准的授权）与 §4.1.6-4 调用链
    # （`resume` 与【事务 A】并列，非其中一步）。`backend=mock`（`tool_execution_service is None`）时
    # 本分支不进入，端点行为与返回值与改动前完全一致（§4.1.6-2）。
    # §4.1.6-7：成功路径在既有字段之上**新增可选字段** `execution: {outcome, code?, message_id?}`；
    # **既有字段一个都不改**；响应体**不含**参数原文 / 宿主路径 / 凭据（`ToolExecutionResult` 本身即无这些）。
    execution: dict[str, object] | None = None
    resume_result = None
    if payload.approved and tool_execution_service is not None:
        try:
            resume_result = tool_execution_service.resume(
                tenant_id=context.tenant_id, run_id=run_id, approval_id=approval_id
            )
        except ToolExecutionError as exc:
            # §4.1.6-5 重跑失败语义：按受控异常携带的 HTTP 语义原样映射（409 / 422 / 403 / 502 / 504）。
            raise HTTPException(status_code=exc.http_status, detail=str(exc)) from exc
        if resume_result is not None:
            execution = {"outcome": resume_result.outcome}
            if resume_result.code is not None:
                execution["code"] = resume_result.code
            if resume_result.message_id is not None:
                execution["message_id"] = resume_result.message_id
    run_status = runtime_service.snapshot(context, run_id).status
    # P2c-2 §2.8：决议后推进接入**同一**帧写入（无流 ⇒ 零破坏；流写入失败不影响决议与响应体）。
    _resume_stream_frames(
        context,
        run_id,
        approval_id,
        approved=payload.approved,
        run_status=run_status,
        result=resume_result,
    )
    body: dict[str, object] = {
        "run_id": run_id,
        "approval_id": approval_id,
        "status": "approved" if payload.approved else "rejected",
        "run_status": run_status,
    }
    if execution is not None:
        body["execution"] = execution
    return body


class RegistrationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phone: str = Field(min_length=1, max_length=20)
    password: str = Field(min_length=10, max_length=128)
    position: str = Field(min_length=1, max_length=100)
    full_name: str = Field(min_length=1, max_length=100)
    email: str | None = Field(default=None, max_length=200)
    tenant_id: str | None = Field(default=None, max_length=64)
    bootstrap_token: str | None = Field(default=None, max_length=200)


class RegistrationApproval(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str = Field(min_length=1, max_length=40)
    tenant_id: str = Field(min_length=1, max_length=64)


class RegistrationRejection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=500)


class PendingApprovalView(BaseModel):
    kind: str
    target_id: str
    title: str
    requested_by: str | None
    created_at: datetime
    detail: dict[str, object]


class PendingApprovalsView(BaseModel):
    items: list[PendingApprovalView]
    counts: dict[str, int]


class SessionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phone: str = Field(min_length=1, max_length=20)
    password: str = Field(min_length=1, max_length=128)
    totp_code: str | None = Field(default=None, max_length=20)


class TotpConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    totp_code: str = Field(min_length=1, max_length=20)


class SsoCallback(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=4096)
    state: str = Field(min_length=1, max_length=512)


class SsoVerification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    totp_code: str = Field(min_length=1, max_length=20)


class PasswordChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    old_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=10, max_length=128)


class PasswordReset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    new_password: str = Field(min_length=10, max_length=128)


def _account_view(account) -> dict[str, object]:
    return {
        "account_id": account.account_id,
        "phone": mask_phone(account.phone),
        "position": account.position,
        "full_name": account.full_name,
        "email": account.email,
        "role": account.role,
        "tenant_id": account.tenant_id,
        "status": account.status.value,
        "requested_at": account.requested_at,
        "reviewed_at": account.reviewed_at,
    }


@app.post("/api/v1/auth/registrations", status_code=status.HTTP_201_CREATED)
def submit_registration(payload: RegistrationCreate) -> dict[str, object]:
    try:
        account = account_service.request_registration(
            RegistrationRequest(
                phone=payload.phone,
                password=payload.password,
                position=payload.position,
                full_name=payload.full_name,
                email=payload.email,
                tenant_id=payload.tenant_id,
                bootstrap_token=payload.bootstrap_token,
            )
        )
    except AccountConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except BootstrapDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except PasswordPolicyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _account_view(account)


@app.get("/api/v1/auth/registrations")
def list_registrations(
    status_filter: str = Query(default="pending", alias="status"),
    context: UserContext = Depends(current_user),
) -> list[dict[str, object]]:
    try:
        requested_status = AccountStatus(status_filter)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="不支持的账号状态") from exc
    try:
        items = account_service.list_requests(context, requested_status)
    except PolicyError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return [_account_view(item) for item in items]


@app.post("/api/v1/auth/registrations/{account_id}/approval")
def approve_registration(
    account_id: str, payload: RegistrationApproval, context: UserContext = Depends(current_user)
) -> dict[str, object]:
    try:
        account = account_service.approve(
            context, account_id, role=payload.role, tenant_id=payload.tenant_id
        )
    except PolicyError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except AccountStateConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except AccountNotFound as exc:
        raise HTTPException(status_code=404, detail="账号申请不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    # 站内通知：告知申请人已通过审批（驳回不发站内通知——被驳回账号无法登录）。
    inbox_service.registration_approved(
        tenant_id=str(account.tenant_id or ""), recipient_id=account.account_id
    )
    return _account_view(account)


@app.post("/api/v1/auth/registrations/{account_id}/rejection")
def reject_registration(
    account_id: str, payload: RegistrationRejection, context: UserContext = Depends(current_user)
) -> dict[str, object]:
    try:
        account = account_service.reject(context, account_id, reason=payload.reason)
    except PolicyError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except AccountStateConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except AccountNotFound as exc:
        raise HTTPException(status_code=404, detail="账号申请不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _account_view(account)


def _pending_approval_view(item) -> PendingApprovalView:
    return PendingApprovalView(
        kind=item.kind,
        target_id=item.target_id,
        title=item.title,
        requested_by=item.requested_by,
        created_at=item.created_at,
        detail=item.detail,
    )


@app.get("/api/v1/approvals/pending")
def list_pending_approvals(
    limit: int = Query(default=50, ge=1, le=200),
    context: UserContext = Depends(current_user),
) -> PendingApprovalsView:
    items, counts = approvals_service.pending(context, limit=limit)
    return PendingApprovalsView(
        items=[_pending_approval_view(item) for item in items],
        counts=counts,
    )


class InboxItemView(BaseModel):
    inbox_id: str
    kind: str
    title: str
    target_type: str | None = None
    target_id: str | None = None
    created_at: datetime
    read_at: datetime | None = None


class InboxListView(BaseModel):
    items: list[InboxItemView]
    unread_count: int


def _inbox_view(item: InboxItem) -> InboxItemView:
    return InboxItemView(
        inbox_id=item.inbox_id,
        kind=item.kind.value,
        title=item.title,
        target_type=item.target_type,
        target_id=item.target_id,
        created_at=item.created_at,
        read_at=item.read_at,
    )


@app.get("/api/v1/inbox", response_model=InboxListView)
def list_inbox(
    unread_only: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    context: UserContext = Depends(current_user),
) -> InboxListView:
    """列出**本人**的站内通知；`unread_count` 始终是本人未读总数（与筛选无关）。"""
    items, unread_count = inbox_service.list(context, unread_only=unread_only, limit=limit)
    return InboxListView(
        items=[_inbox_view(item) for item in items], unread_count=unread_count
    )


@app.post("/api/v1/inbox/{inbox_id}/read", response_model=InboxItemView)
def mark_inbox_read(inbox_id: str, context: UserContext = Depends(current_user)) -> InboxItemView:
    """标记单条通知已读；他人或跨租户一律 404（不泄露存在性），重复标记幂等。"""
    try:
        item = inbox_service.mark_read(context, inbox_id)
    except InboxNotFound as exc:
        raise HTTPException(status_code=404, detail="通知不存在") from exc
    return _inbox_view(item)


@app.post("/api/v1/inbox/read-all")
def mark_all_inbox_read(context: UserContext = Depends(current_user)) -> dict[str, int]:
    """把本人全部未读通知标记为已读，返回实际更新条数。"""
    return {"updated": inbox_service.mark_all_read(context)}


@app.post("/api/v1/auth/sessions")
def create_session(payload: SessionCreate) -> dict[str, object]:
    if not settings.auth_secret:
        raise HTTPException(status_code=503, detail="会话密钥未配置，请先设置 WORKBENCH_AUTH_SECRET")
    try:
        context = account_service.login(
            payload.phone, payload.password, totp_code=payload.totp_code
        )
    except LoginRateLimited as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except TotpRequired as exc:
        raise HTTPException(status_code=401, detail="需要动态验证码") from exc
    except TotpInvalid as exc:
        raise HTTPException(status_code=401, detail="动态验证码不正确") from exc
    except LoginFailed as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    full_ttl = settings.session_ttl_seconds
    if context.scope == TOTP_ENROLLMENT_SCOPE:
        ttl = min(full_ttl, settings.totp_enrollment_ttl_seconds)
    else:
        ttl = full_ttl
    token = create_access_token(context, settings.auth_secret, ttl_seconds=ttl)
    return {
        "access_token": token,
        "token_type": "Bearer",
        "expires_in": ttl,
        "tenant_id": context.tenant_id,
        "user_id": context.user_id,
        "role": context.role,
        "scope": context.scope,
    }


@app.post("/api/v1/auth/logout", status_code=204)
def logout(context: UserContext = Depends(current_user)) -> Response:
    """登出当前**令牌会话**：把该令牌的 jti 记入服务端撤销名单，立即失效。

    仅对令牌会话有效；使用开发期头部身份（X-* 头）时没有令牌可撤销，返回 401。
    """
    if not context.token_id:
        raise HTTPException(status_code=401, detail="当前会话不是令牌会话，无法登出")
    expires_at = context.expires_at or (
        datetime.now(UTC) + timedelta(seconds=settings.session_ttl_seconds)
    )
    try:
        session_revocation_store.revoke(context.token_id, expires_at=expires_at)
    except Exception as exc:  # noqa: BLE001 撤销失败必须报错，不能静默返回成功
        raise HTTPException(status_code=503, detail="会话状态暂时无法更新，请稍后重试") from exc
    return Response(status_code=204)


@app.get("/api/v1/auth/sso/authorize")
def sso_authorize() -> dict[str, str]:
    try:
        url, state = account_service.begin_sso_login()
    except SsoNotConfigured as exc:
        raise HTTPException(status_code=503, detail="SSO 未启用") from exc
    return {"authorization_url": url, "state": state}


@app.post("/api/v1/auth/sso/callback")
def sso_callback(payload: SsoCallback) -> dict[str, object]:
    if not settings.auth_secret:
        raise HTTPException(status_code=503, detail="会话密钥未配置，请先设置 WORKBENCH_AUTH_SECRET")
    try:
        account, requires_totp = account_service.complete_sso_login(
            code=payload.code, state=payload.state
        )
    except SsoNotConfigured as exc:
        raise HTTPException(status_code=503, detail="SSO 未启用") from exc
    except (SsoError, SsoStateNotFound) as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    if requires_totp:
        context = UserContext(
            tenant_id=str(account.tenant_id),
            user_id=account.account_id,
            role=str(account.role),
            scope=SSO_PENDING_SCOPE,
        )
        ttl = settings.sso_state_ttl_seconds
        token = create_access_token(context, settings.auth_secret, ttl_seconds=ttl)
        return {
            "access_token": token,
            "token_type": "Bearer",
            "expires_in": ttl,
            "scope": SSO_PENDING_SCOPE,
            "requires_totp": True,
            "tenant_id": context.tenant_id,
            "user_id": context.user_id,
            "role": context.role,
        }
    context = UserContext(
        tenant_id=str(account.tenant_id),
        user_id=account.account_id,
        role=str(account.role),
        scope=FULL_SCOPE,
    )
    ttl = settings.session_ttl_seconds
    token = create_access_token(context, settings.auth_secret, ttl_seconds=ttl)
    return {
        "access_token": token,
        "token_type": "Bearer",
        "expires_in": ttl,
        "tenant_id": context.tenant_id,
        "user_id": context.user_id,
        "role": context.role,
        "scope": context.scope,
    }


@app.post("/api/v1/auth/sso/verification")
def sso_verification(
    payload: SsoVerification, context: UserContext = Depends(current_user)
) -> dict[str, object]:
    if context.scope != SSO_PENDING_SCOPE:
        raise HTTPException(status_code=403, detail="当前会话不允许执行该操作")
    if not settings.auth_secret:
        raise HTTPException(status_code=503, detail="会话密钥未配置，请先设置 WORKBENCH_AUTH_SECRET")
    try:
        account = account_service.repository.get(context.user_id)
    except AccountNotFound as exc:
        raise HTTPException(status_code=401, detail="账号不可用") from exc
    try:
        account_service.verify_sso_totp(account, payload.totp_code)
    except TotpRequired as exc:
        raise HTTPException(status_code=401, detail="需要动态验证码") from exc
    except TotpInvalid as exc:
        raise HTTPException(status_code=401, detail="动态验证码不正确") from exc
    except LoginFailed as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    session_context = UserContext(
        tenant_id=str(account.tenant_id),
        user_id=account.account_id,
        role=str(account.role),
        scope=FULL_SCOPE,
    )
    ttl = settings.session_ttl_seconds
    token = create_access_token(session_context, settings.auth_secret, ttl_seconds=ttl)
    return {
        "access_token": token,
        "token_type": "Bearer",
        "expires_in": ttl,
        "tenant_id": session_context.tenant_id,
        "user_id": session_context.user_id,
        "role": session_context.role,
        "scope": session_context.scope,
    }


@app.post("/api/v1/auth/me/totp")
def start_totp_enrollment(context: UserContext = Depends(current_user)) -> dict[str, str]:
    secret, uri = account_service.start_totp_enrollment(context)
    return {
        "secret": secret,
        "otpauth_uri": uri,
        "digest": "SHA1",
        "digits": "6",
        "period": "30",
    }


@app.post("/api/v1/auth/me/totp/confirmation")
def confirm_totp(
    payload: TotpConfirmation, context: UserContext = Depends(current_user)
) -> dict[str, str]:
    try:
        account_service.confirm_totp_enrollment(context, payload.totp_code)
    except TotpNotEnrolled as exc:
        raise HTTPException(status_code=409, detail="请先开始绑定动态口令") from exc
    except TotpInvalid as exc:
        raise HTTPException(status_code=401, detail="动态验证码不正确") from exc
    return {"status": "confirmed"}


@app.post("/api/v1/auth/accounts/{account_id}/totp-reset")
def reset_account_totp(
    account_id: str, context: UserContext = Depends(current_user)
) -> dict[str, str]:
    try:
        account_service.reset_totp(context, account_id)
    except PolicyError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except AccountNotFound as exc:
        raise HTTPException(status_code=404, detail="账号不存在") from exc
    return {"status": "reset"}


@app.put("/api/v1/auth/me/password")
def change_own_password(payload: PasswordChange, context: UserContext = Depends(current_user)) -> dict[str, str]:
    try:
        account_service.change_password(
            context, old_password=payload.old_password, new_password=payload.new_password
        )
    except LoginFailed as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except PasswordPolicyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"status": "updated"}


@app.post("/api/v1/auth/accounts/{account_id}/password")
def reset_account_password(
    account_id: str, payload: PasswordReset, context: UserContext = Depends(current_user)
) -> dict[str, str]:
    try:
        account_service.reset_password(context, account_id, new_password=payload.new_password)
    except PolicyError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except AccountNotFound as exc:
        raise HTTPException(status_code=404, detail="账号不存在") from exc
    except PasswordPolicyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"status": "reset"}


class PlanProposalCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal: str = Field(min_length=1, max_length=2_000)
    idempotency_key: str = Field(min_length=1, max_length=200)


class PlanProposalRejection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=500)


class PlanRunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    runtime_key: str = Field(default="mock", min_length=1, max_length=80)
    mode: str = Field(default="product_manager", pattern="^(product_manager|fde)$")


def _plan_view(proposal) -> dict[str, object]:
    return {
        "proposal_id": proposal.proposal_id,
        "task_id": proposal.task_id,
        "goal": proposal.goal,
        "status": proposal.status.value,
        "steps": [
            {
                "step_id": step.step_id,
                "tool": step.tool,
                "kind": step.kind,
                "requires_approval": step.requires_approval,
            }
            for step in proposal.steps
        ],
        "generator": {
            "key": proposal.generator_key,
            "model": proposal.generator_model,
        },
        "created_by": proposal.created_by,
        "created_at": proposal.created_at,
        "reviewed_by": proposal.reviewed_by,
        "reviewed_at": proposal.reviewed_at,
        "rejection_reason": proposal.rejection_reason,
    }


@app.post("/api/v1/tasks/{task_id}/plan-proposals", status_code=status.HTTP_201_CREATED)
def create_plan_proposal(
    task_id: str, payload: PlanProposalCreate, context: UserContext = Depends(current_user)
) -> dict[str, object]:
    try:
        proposal = planner_service.propose(context, task_id, payload.goal, payload.idempotency_key)
    except TaskNotFound as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc
    except PlannerNotConfigured as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (UnknownTool, PlanGenerationError) as exc:
        raise HTTPException(status_code=422, detail="计划生成失败，请调整目标后重试") from exc
    except ModelNotAllowed as exc:
        raise HTTPException(status_code=403, detail="没有获准处理当前数据等级的模型") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _plan_view(proposal)


@app.get("/api/v1/plan-proposals/{proposal_id}")
def get_plan_proposal(proposal_id: str, context: UserContext = Depends(current_user)) -> dict[str, object]:
    try:
        proposal = planner_service.get(context, proposal_id)
    except (PlanProposalNotFound, PlannerAccessDenied) as exc:
        raise HTTPException(status_code=404, detail="计划提案不存在") from exc
    return _plan_view(proposal)


@app.post("/api/v1/plan-proposals/{proposal_id}/approval")
def approve_plan_proposal(proposal_id: str, context: UserContext = Depends(current_user)) -> dict[str, object]:
    try:
        proposal = planner_service.approve(context, proposal_id)
    except PlanProposalNotFound as exc:
        raise HTTPException(status_code=404, detail="计划提案不存在") from exc
    except PlanProposalStateConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PolicyError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    inbox_service.plan_decided(
        tenant_id=proposal.tenant_id,
        recipient_id=proposal.created_by,
        proposal_id=proposal.proposal_id,
        approved=True,
    )
    return _plan_view(proposal)


@app.post("/api/v1/plan-proposals/{proposal_id}/rejection")
def reject_plan_proposal(
    proposal_id: str, payload: PlanProposalRejection, context: UserContext = Depends(current_user)
) -> dict[str, object]:
    try:
        proposal = planner_service.reject(context, proposal_id, payload.reason)
    except PlanProposalNotFound as exc:
        raise HTTPException(status_code=404, detail="计划提案不存在") from exc
    except PlanProposalStateConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PolicyError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    # 站内通知：驳回结果告知提案发起人（通知失败不阻断审批）。
    inbox_service.plan_decided(
        tenant_id=proposal.tenant_id,
        recipient_id=proposal.created_by,
        proposal_id=proposal.proposal_id,
        approved=False,
    )
    return _plan_view(proposal)


@app.post("/api/v1/plan-proposals/{proposal_id}/runs", status_code=status.HTTP_201_CREATED)
def start_plan_run(
    proposal_id: str, payload: PlanRunCreate, context: UserContext = Depends(current_user)
) -> dict[str, object]:
    try:
        run_id, runtime_key, policy_version = planner_service.start_run(
            context, proposal_id, payload.runtime_key, payload.mode
        )
    except (PlanProposalNotFound, PlannerAccessDenied) as exc:
        raise HTTPException(status_code=404, detail="计划提案不存在") from exc
    except PlanProposalStateConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RunAccessDenied as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc
    except (PolicyDenied, ApprovalRequired) as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=400, detail="运行时不可用") from exc
    _notify_run_terminal(context, run_id)
    return {
        "run_id": run_id,
        "runtime_key": runtime_key,
        "policy_version": policy_version,
        "status": runtime_service.snapshot(context, run_id).status,
    }


class OrchestrationProposalCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str = Field(default="runtime_default", min_length=1, max_length=60)


class OrchestrationProposalRejection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=500)


def _ensure_orchestration_admin(context: UserContext) -> None:
    if context.role not in {"ceo", "super_admin"}:
        raise HTTPException(status_code=403, detail="只有 CEO 或超级管理员可以管理编排优化提案")


def _orchestration_view(proposal) -> dict[str, object]:
    return {
        "proposal_id": proposal.proposal_id,
        "kind": proposal.kind.value,
        "current_value": proposal.current_value,
        "proposed_value": proposal.proposed_value,
        "rationale": proposal.rationale,
        "metrics_snapshot": proposal.metrics_snapshot,
        "status": proposal.status.value,
        "created_by": proposal.created_by,
        "created_at": proposal.created_at,
        "reviewed_by": proposal.reviewed_by,
        "reviewed_at": proposal.reviewed_at,
        "rejection_reason": proposal.rejection_reason,
    }


@app.post("/api/v1/orchestration-proposals")
def create_orchestration_proposal(
    payload: OrchestrationProposalCreate, context: UserContext = Depends(current_user)
) -> dict[str, object]:
    _ensure_orchestration_admin(context)
    try:
        proposal, reason = orchestration_service.generate(context, kind=payload.kind)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "proposal": _orchestration_view(proposal) if proposal is not None else None,
        "reason": reason,
    }


@app.get("/api/v1/orchestration-proposals")
def list_orchestration_proposals(
    context: UserContext = Depends(current_user),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, object]:
    _ensure_orchestration_admin(context)
    return {
        "items": [
            _orchestration_view(item)
            for item in orchestration_service.list(context, limit=limit)
        ]
    }


@app.get("/api/v1/orchestration-proposals/{proposal_id}")
def get_orchestration_proposal(
    proposal_id: str, context: UserContext = Depends(current_user)
) -> dict[str, object]:
    _ensure_orchestration_admin(context)
    try:
        proposal = orchestration_service.get(context, proposal_id)
    except OrchestrationProposalNotFound as exc:
        raise HTTPException(status_code=404, detail="优化提案不存在") from exc
    return _orchestration_view(proposal)


@app.post("/api/v1/orchestration-proposals/{proposal_id}/approval")
def approve_orchestration_proposal(
    proposal_id: str, context: UserContext = Depends(current_user)
) -> dict[str, object]:
    _ensure_orchestration_admin(context)
    try:
        proposal = orchestration_service.approve(context, proposal_id)
    except OrchestrationProposalNotFound as exc:
        raise HTTPException(status_code=404, detail="优化提案不存在") from exc
    except OrchestrationProposalStateConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PolicyError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    # 站内通知：审核结果告知提案发起人（通知失败不阻断审批）。
    inbox_service.orchestration_decided(
        tenant_id=proposal.tenant_id,
        recipient_id=proposal.created_by,
        proposal_id=proposal.proposal_id,
        approved=True,
    )
    return _orchestration_view(proposal)


@app.post("/api/v1/orchestration-proposals/{proposal_id}/rejection")
def reject_orchestration_proposal(
    proposal_id: str,
    payload: OrchestrationProposalRejection,
    context: UserContext = Depends(current_user),
) -> dict[str, object]:
    _ensure_orchestration_admin(context)
    try:
        proposal = orchestration_service.reject(context, proposal_id, payload.reason)
    except OrchestrationProposalNotFound as exc:
        raise HTTPException(status_code=404, detail="优化提案不存在") from exc
    except OrchestrationProposalStateConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PolicyError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    # 站内通知：驳回结果告知提案发起人（通知失败不阻断审批）。
    inbox_service.orchestration_decided(
        tenant_id=proposal.tenant_id,
        recipient_id=proposal.created_by,
        proposal_id=proposal.proposal_id,
        approved=False,
    )
    return _orchestration_view(proposal)


# ---------------------------------------------------------------- CRM（P5a，真源 specs/2026-09-17-crm-p5a-design.md §2.12）
#
# 本层只做请求校验（extra=forbid）→ 服务调用 → 视图 / 异常映射；权限与归属在服务层统一判定。
# 敏感字段：列表 / 详情默认**掩码**（mask_record）；明文仅经 reveal 专用端点（POST + 审计留痕）；
# 数字员工侧另经进程内工具面（永不返回敏感字段，见 app/crm/tools.py）。


class CrmStrictModel(BaseModel):
    """CRM 请求基类：未知字段一律拒绝（extra=forbid；宪法白名单口径）。"""

    model_config = ConfigDict(extra="forbid")


def _raise_crm_http(exc: Exception) -> NoReturn:
    """CRM 领域异常 → HTTP 语义（§2.9）：404 不泄露存在性 / 403 角色 / 409 状态 / 422 输入 / 502 网关。"""
    if isinstance(exc, FollowupPlanError):
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if isinstance(exc, CrmStateConflict):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, InvalidCrm):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if isinstance(exc, CrmNotFound):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, PolicyError):
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    raise exc


def _crm_do(func, *args, **kwargs):
    """统一异常映射包装（服务层异常 → HTTP 语义）。"""
    try:
        return func(*args, **kwargs)
    except (FollowupPlanError, CrmStateConflict, InvalidCrm, CrmNotFound, PolicyError) as exc:
        _raise_crm_http(exc)


# ------------------------------------------------------------ 视图（掩码出口统一在此）


def _crm_account_view(account) -> dict:
    return {
        "account_id": account.account_id,
        "name": account.name,
        "industry": account.industry,
        "source": account.source,
        "status": account.status,
        "owner_id": account.owner_id,
        "custom_fields": dict(account.custom_fields or {}),
        "health_score": account.health_score,
        "health_band": account.health_band,
        "health_computed_at": account.health_computed_at,
        "created_at": account.created_at,
        "updated_at": account.updated_at,
    }


def _contact_view(contact) -> dict:
    masked = mask_record(contact)
    return {
        "contact_id": masked["contact_id"],
        "account_id": masked.get("account_id"),
        "name": masked["name"],
        "title": masked["title"],
        "phone": masked["phone"],
        "email": masked["email"],
        "is_primary": masked["is_primary"],
        "birthday": masked.get("birthday"),
        "owner_id": masked["owner_id"],
        "custom_fields": dict(masked.get("custom_fields") or {}),
        "created_at": masked["created_at"],
    }


def _lead_view(lead) -> dict:
    masked = mask_record(lead)
    return {
        "lead_id": masked["lead_id"],
        "name": masked["name"],
        "company": masked["company"],
        "phone": masked["phone"],
        "email": masked["email"],
        "source": masked["source"],
        "status": masked["status"],
        "owner_id": masked["owner_id"],
        "converted_account_id": masked.get("converted_account_id"),
        "custom_fields": dict(masked.get("custom_fields") or {}),
        "created_at": masked["created_at"],
    }


def _opportunity_view(opportunity) -> dict:
    return {
        "opportunity_id": opportunity.opportunity_id,
        "account_id": opportunity.account_id,
        "name": opportunity.name,
        "stage": opportunity.stage,
        "amount_cents": opportunity.amount_cents,
        "expected_close": opportunity.expected_close,
        "owner_id": opportunity.owner_id,
        "stage_entered_at": opportunity.stage_entered_at,
        "closed_at": opportunity.closed_at,
        "custom_fields": dict(opportunity.custom_fields or {}),
        "created_at": opportunity.created_at,
    }


def _activity_view(activity) -> dict:
    return {
        "activity_id": activity.activity_id,
        "kind": activity.kind,
        "subject": activity.subject,
        "account_id": activity.account_id,
        "contact_id": activity.contact_id,
        "opportunity_id": activity.opportunity_id,
        "owner_id": activity.owner_id,
        "status": activity.status,
        "due_at": activity.due_at,
        "occurred_at": activity.occurred_at,
        "created_by_kind": activity.created_by_kind,
    }


def _quote_view(quote) -> dict:
    return {
        "quote_id": quote.quote_id,
        "account_id": quote.account_id,
        "opportunity_id": quote.opportunity_id,
        "quote_no": quote.quote_no,
        "status": quote.status,
        "subtotal_cents": quote.subtotal_cents,
        "tax_cents": quote.tax_cents,
        "total_cents": quote.total_cents,
        "valid_until": quote.valid_until,
        "confirmed_at": quote.confirmed_at,
        "converted_contract_id": quote.converted_contract_id,
        "owner_id": quote.owner_id,
        "created_at": quote.created_at,
    }


def _quote_line_view(line) -> dict:
    return {
        "line_no": line.line_no,
        "description": line.description,
        "qty": line.qty,
        "unit_price_cents": line.unit_price_cents,
        "tax_rate_bp": line.tax_rate_bp,
        "line_subtotal_cents": line.line_subtotal_cents,
        "line_tax_cents": line.line_tax_cents,
    }


def _contract_view(contract) -> dict:
    return {
        "contract_id": contract.contract_id,
        "account_id": contract.account_id,
        "quote_id": contract.quote_id,
        "opportunity_id": contract.opportunity_id,
        "contract_no": contract.contract_no,
        "title": contract.title,
        "status": contract.status,
        "amount_cents": contract.amount_cents,
        "paid_cents": contract.paid_cents,
        "starts_on": contract.starts_on,
        "ends_on": contract.ends_on,
        "document_object_key": contract.document_object_key,
        "signed_at": contract.signed_at,
        "owner_id": contract.owner_id,
        "created_at": contract.created_at,
    }


def _insight_view(insight) -> dict:
    return {
        "insight_id": insight.insight_id,
        "account_id": insight.account_id,
        "kind": insight.kind,
        "content": dict(insight.content),
        "evidence_refs": list(insight.evidence_refs),
        "dropped_refs": list(insight.dropped_refs),
        "model_key": insight.model_key,
        "generated_by": insight.generated_by,
        "created_at": insight.created_at,
    }


def _target_view(target) -> dict:
    return {
        "target_id": target.target_id,
        "owner_id": target.owner_id,
        "period_month": target.period_month,
        "amount_target_cents": target.amount_target_cents,
        "count_target": target.count_target,
    }


def _field_def_view(definition) -> dict:
    return {
        "object_key": definition.object_key,
        "field_key": definition.field_key,
        "label": definition.label,
        "field_type": definition.field_type,
        "required": definition.required,
        "options": list(definition.options),
        "active": definition.active,
    }


# ------------------------------------------------------------ 请求模型


class CrmAccountCreateRequest(CrmStrictModel):
    name: str = Field(min_length=1, max_length=200)
    industry: str = Field(default="", max_length=200)
    owner_id: str | None = Field(default=None, max_length=64)
    custom_fields: dict | None = None


class CrmAccountUpdateRequest(CrmStrictModel):
    name: str | None = Field(default=None, max_length=200)
    industry: str | None = Field(default=None, max_length=200)
    status: str | None = Field(default=None, max_length=32)
    custom_fields: dict | None = None


class CrmContactCreateRequest(CrmStrictModel):
    name: str = Field(min_length=1, max_length=200)
    title: str = Field(default="", max_length=200)
    phone: str = Field(default="", max_length=64)
    email: str = Field(default="", max_length=254)
    is_primary: bool = False
    birthday: date | None = None
    custom_fields: dict | None = None


class CrmContactUpdateRequest(CrmStrictModel):
    name: str | None = Field(default=None, max_length=200)
    title: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=64)
    email: str | None = Field(default=None, max_length=254)
    is_primary: bool | None = None
    birthday: date | None = None
    custom_fields: dict | None = None


class CrmLeadCreateRequest(CrmStrictModel):
    name: str = Field(min_length=1, max_length=200)
    company: str = Field(default="", max_length=200)
    phone: str = Field(default="", max_length=64)
    email: str = Field(default="", max_length=254)
    source: str = Field(default="manual", max_length=64)
    custom_fields: dict | None = None


class CrmLeadConvertRequest(CrmStrictModel):
    create_opportunity: bool = False
    opportunity_name: str | None = Field(default=None, max_length=200)
    account_name: str | None = Field(default=None, max_length=200)


class CrmRevealRequest(CrmStrictModel):
    field: str = Field(min_length=1, max_length=64)


# ------------------------------------------------------------ 账户


@app.get("/api/v1/crm/accounts")
def crm_list_accounts(
    owner_id: str | None = Query(default=None, max_length=64),
    status_filter: str | None = Query(default=None, alias="status", max_length=32),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    context: UserContext = Depends(current_user),
) -> dict:
    """客户列表（employee 仅本人负责）。"""
    items, total = _crm_do(
        crm_service.list_accounts, context, owner_id=owner_id, status=status_filter, limit=limit, offset=offset
    )
    return {
        "items": [_crm_account_view(item) for item in items],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@app.post("/api/v1/crm/accounts", status_code=status.HTTP_201_CREATED)
def crm_create_account(
    payload: CrmAccountCreateRequest, context: UserContext = Depends(current_user)
) -> dict:
    """建客户（`owner_id` 缺省 = 操作者本人；非特权岗位指定他人 ⇒ 404）。"""
    account = _crm_do(
        crm_service.create_account, context, name=payload.name, industry=payload.industry,
        owner_id=payload.owner_id, custom_fields=payload.custom_fields,
    )
    return _crm_account_view(account)


@app.get("/api/v1/crm/accounts/{account_id}")
def crm_get_account(account_id: str, context: UserContext = Depends(current_user)) -> dict:
    account = _crm_do(crm_service.get_account, context, account_id)
    return _crm_account_view(account)


@app.patch("/api/v1/crm/accounts/{account_id}")
def crm_update_account(
    account_id: str, payload: CrmAccountUpdateRequest, context: UserContext = Depends(current_user)
) -> dict:
    account = _crm_do(
        crm_service.update_account, context, account_id,
        name=payload.name, industry=payload.industry, status=payload.status,
        custom_fields=payload.custom_fields,
    )
    return _crm_account_view(account)


@app.post("/api/v1/crm/accounts/{account_id}/followup-plan")
def crm_generate_followup_plan(
    account_id: str, context: UserContext = Depends(current_user)
) -> dict:
    """生成跟进计划（人工触发）：建议附**证据引用**；全部无效或网关未接 ⇒ 「依据不足」。

    网关失败 ⇒ 502（不降级、不落库）；**建议永不直接执行**。
    """
    insight = _crm_do(crm_service.generate_followup_plan, context, account_id)
    return _insight_view(insight)


@app.get("/api/v1/crm/accounts/{account_id}/insights")
def crm_list_insights(
    account_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    context: UserContext = Depends(current_user),
) -> dict:
    items, total = _crm_do(crm_service.list_insights, context, account_id, limit=limit, offset=offset)
    return {
        "items": [_insight_view(item) for item in items],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


# ------------------------------------------------------------ 联系人（敏感字段默认掩码）


@app.get("/api/v1/crm/accounts/{account_id}/contacts")
def crm_list_contacts(
    account_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    context: UserContext = Depends(current_user),
) -> dict:
    items, total = _crm_do(
        crm_service.list_contacts, context, account_id=account_id, limit=limit, offset=offset
    )
    return {
        "items": [_contact_view(item) for item in items],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@app.post("/api/v1/crm/accounts/{account_id}/contacts", status_code=status.HTTP_201_CREATED)
def crm_create_contact(
    account_id: str, payload: CrmContactCreateRequest, context: UserContext = Depends(current_user)
) -> dict:
    contact = _crm_do(
        crm_service.create_contact, context, name=payload.name, account_id=account_id,
        title=payload.title, phone=payload.phone, email=payload.email,
        is_primary=payload.is_primary, birthday=payload.birthday, custom_fields=payload.custom_fields,
    )
    return _contact_view(contact)


@app.get("/api/v1/crm/contacts/{contact_id}")
def crm_get_contact(contact_id: str, context: UserContext = Depends(current_user)) -> dict:
    contact = _crm_do(crm_service.get_contact, context, contact_id)
    return _contact_view(contact)


@app.patch("/api/v1/crm/contacts/{contact_id}")
def crm_update_contact(
    contact_id: str, payload: CrmContactUpdateRequest, context: UserContext = Depends(current_user)
) -> dict:
    contact = _crm_do(
        crm_service.update_contact, context, contact_id,
        name=payload.name, title=payload.title, phone=payload.phone, email=payload.email,
        is_primary=payload.is_primary, birthday=payload.birthday, custom_fields=payload.custom_fields,
    )
    return _contact_view(contact)


@app.post("/api/v1/crm/contacts/{contact_id}/reveal")
def crm_reveal_contact_field(
    contact_id: str, payload: CrmRevealRequest, response: Response,
    context: UserContext = Depends(current_user),
) -> dict:
    """敏感字段揭示（**专用端点**）：数据范围内 + 审计 `crm.sensitive.revealed`（不落字段值）。"""
    value = _crm_do(
        crm_service.reveal_sensitive, context, entity="contact", entity_id=contact_id, field=payload.field
    )
    response.headers["Cache-Control"] = "no-store"
    return {"contact_id": contact_id, "field": payload.field, "value": value}


# ------------------------------------------------------------ 线索


@app.get("/api/v1/crm/leads")
def crm_list_leads(
    owner_id: str | None = Query(default=None, max_length=64),
    status_filter: str | None = Query(default=None, alias="status", max_length=32),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    context: UserContext = Depends(current_user),
) -> dict:
    items, total = _crm_do(
        crm_service.list_leads, context, owner_id=owner_id, status=status_filter, limit=limit, offset=offset
    )
    return {
        "items": [_lead_view(item) for item in items],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@app.post("/api/v1/crm/leads", status_code=status.HTTP_201_CREATED)
def crm_create_lead(payload: CrmLeadCreateRequest, context: UserContext = Depends(current_user)) -> dict:
    lead = _crm_do(
        crm_service.create_lead, context, name=payload.name, company=payload.company,
        phone=payload.phone, email=payload.email, source=payload.source,
        custom_fields=payload.custom_fields,
    )
    return _lead_view(lead)


@app.post("/api/v1/crm/leads/{lead_id}/convert", status_code=status.HTTP_201_CREATED)
def crm_convert_lead(
    lead_id: str, payload: CrmLeadConvertRequest, context: UserContext = Depends(current_user)
) -> dict:
    """线索转化（单事务）：产出 Account + Contact（+ 可选 Opportunity）；重复转化 ⇒ 409。"""
    account, contact, opportunity = _crm_do(
        crm_service.convert_lead, context, lead_id,
        create_opportunity=payload.create_opportunity, opportunity_name=payload.opportunity_name,
        account_name=payload.account_name,
    )
    return {
        "account": _crm_account_view(account),
        "contact": _contact_view(contact),
        "opportunity": _opportunity_view(opportunity) if opportunity is not None else None,
    }


@app.post("/api/v1/crm/leads/{lead_id}/reveal")
def crm_reveal_lead_field(
    lead_id: str, payload: CrmRevealRequest, context: UserContext = Depends(current_user)
) -> dict:
    value = _crm_do(
        crm_service.reveal_sensitive, context, entity="lead", entity_id=lead_id, field=payload.field
    )
    return {"lead_id": lead_id, "field": payload.field, "value": value}


# ------------------------------------------------------------ 商机


class CrmOpportunityCreateRequest(CrmStrictModel):
    account_id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=200)
    amount_cents: int = Field(default=0, ge=0)
    expected_close: date | None = None
    custom_fields: dict | None = None


class CrmOpportunityStageRequest(CrmStrictModel):
    to_stage: str = Field(min_length=1, max_length=32)


class CrmActivityCreateRequest(CrmStrictModel):
    kind: str = Field(min_length=1, max_length=16)
    subject: str = Field(default="", max_length=200)
    content: str = Field(default="", max_length=8000)
    account_id: str | None = Field(default=None, max_length=64)
    contact_id: str | None = Field(default=None, max_length=64)
    opportunity_id: str | None = Field(default=None, max_length=64)
    status: str | None = Field(default=None, max_length=16)
    due_at: datetime | None = None


@app.get("/api/v1/crm/opportunities")
def crm_list_opportunities(
    owner_id: str | None = Query(default=None, max_length=64),
    account_id: str | None = Query(default=None, max_length=64),
    stage: str | None = Query(default=None, max_length=32),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    context: UserContext = Depends(current_user),
) -> dict:
    items, total = _crm_do(
        crm_service.list_opportunities, context,
        owner_id=owner_id, account_id=account_id, stage=stage, limit=limit, offset=offset,
    )
    return {
        "items": [_opportunity_view(item) for item in items],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@app.post("/api/v1/crm/opportunities", status_code=status.HTTP_201_CREATED)
def crm_create_opportunity(
    payload: CrmOpportunityCreateRequest, context: UserContext = Depends(current_user)
) -> dict:
    opportunity = _crm_do(
        crm_service.create_opportunity, context, account_id=payload.account_id, name=payload.name,
        amount_cents=payload.amount_cents, expected_close=payload.expected_close,
        custom_fields=payload.custom_fields,
    )
    return _opportunity_view(opportunity)


@app.get("/api/v1/crm/opportunities/{opportunity_id}")
def crm_get_opportunity(
    opportunity_id: str, context: UserContext = Depends(current_user)
) -> dict:
    """商机详情（含**阶段事件时间线**——转化率 / 账龄的事实源）。"""
    opportunity = _crm_do(crm_service.get_opportunity, context, opportunity_id)
    events = _crm_do(crm_service.list_stage_events, context, opportunity_id)
    return {
        "opportunity": _opportunity_view(opportunity),
        "stage_events": [
            {
                "event_id": event.event_id,
                "from_stage": event.from_stage,
                "to_stage": event.to_stage,
                "amount_cents": event.amount_cents,
                "actor_id": event.actor_id,
                "occurred_at": event.occurred_at,
            }
            for event in events
        ],
    }


@app.post("/api/v1/crm/opportunities/{opportunity_id}/stage")
def crm_change_opportunity_stage(
    opportunity_id: str, payload: CrmOpportunityStageRequest, context: UserContext = Depends(current_user)
) -> dict:
    """阶段迁移（白名单；非法迁移 / 并发先写 ⇒ 409；每次迁移 append 阶段事件）。"""
    opportunity = _crm_do(
        crm_service.change_opportunity_stage, context, opportunity_id, to_stage=payload.to_stage
    )
    return _opportunity_view(opportunity)


# ------------------------------------------------------------ 跟进活动


@app.get("/api/v1/crm/activities")
def crm_list_activities(
    account_id: str | None = Query(default=None, max_length=64),
    contact_id: str | None = Query(default=None, max_length=64),
    opportunity_id: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    context: UserContext = Depends(current_user),
) -> dict:
    items, total = _crm_do(
        crm_service.list_activities, context,
        account_id=account_id, contact_id=contact_id, opportunity_id=opportunity_id,
        limit=limit, offset=offset,
    )
    return {
        "items": [_activity_view(item) for item in items],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@app.post("/api/v1/crm/activities", status_code=status.HTTP_201_CREATED)
def crm_log_activity(
    payload: CrmActivityCreateRequest, context: UserContext = Depends(current_user)
) -> dict:
    """登记跟进活动（`task` 类默认 `planned` 且必须带 `due_at`；到期提醒幂等）。"""
    activity = _crm_do(
        crm_service.log_activity, context, kind=payload.kind, subject=payload.subject,
        content=payload.content, account_id=payload.account_id, contact_id=payload.contact_id,
        opportunity_id=payload.opportunity_id, status=payload.status, due_at=payload.due_at,
    )
    return _activity_view(activity)


# ------------------------------------------------------------ 报价（金额由服务端重算）


class CrmQuoteLineItem(CrmStrictModel):
    description: str = Field(min_length=1, max_length=2000)
    qty: Decimal
    unit_price_cents: int = Field(ge=0)
    tax_rate_bp: int = Field(default=0, ge=0, le=10000)


class CrmQuoteCreateRequest(CrmStrictModel):
    account_id: str = Field(min_length=1, max_length=64)
    lines: list[CrmQuoteLineItem] = Field(min_length=1, max_length=200)
    opportunity_id: str | None = Field(default=None, max_length=64)
    valid_until: date | None = None


class CrmQuoteLinesRequest(CrmStrictModel):
    lines: list[CrmQuoteLineItem] = Field(min_length=1, max_length=200)


class CrmContractCreateRequest(CrmStrictModel):
    account_id: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=200)
    amount_cents: int = Field(default=0, ge=0)
    opportunity_id: str | None = Field(default=None, max_length=64)
    starts_on: date | None = None
    ends_on: date | None = None
    document_object_key: str = Field(default="", max_length=512)


class CrmContractSignatureRequest(CrmStrictModel):
    signed_at: datetime
    document_object_key: str | None = Field(default=None, max_length=512)


class CrmPaymentRequest(CrmStrictModel):
    amount_cents: int = Field(gt=0)


class CrmTargetUpsertRequest(CrmStrictModel):
    owner_id: str = Field(min_length=1, max_length=64)
    period_month: date
    amount_target_cents: int = Field(default=0, ge=0)
    count_target: int = Field(default=0, ge=0)


class CrmFieldDefUpsertRequest(CrmStrictModel):
    object_key: str = Field(min_length=1, max_length=32)
    field_key: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=200)
    field_type: str = Field(min_length=1, max_length=16)
    required: bool = False
    options: list[str] | None = None


def _crm_lines_payload(lines: list[CrmQuoteLineItem]) -> list[dict]:
    return [
        {
            "description": item.description,
            "qty": str(item.qty),
            "unit_price_cents": item.unit_price_cents,
            "tax_rate_bp": item.tax_rate_bp,
        }
        for item in lines
    ]


@app.get("/api/v1/crm/quotes")
def crm_list_quotes(
    account_id: str | None = Query(default=None, max_length=64),
    status_filter: str | None = Query(default=None, alias="status", max_length=32),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    context: UserContext = Depends(current_user),
) -> dict:
    items, total = _crm_do(
        crm_service.list_quotes, context, account_id=account_id, status=status_filter,
        limit=limit, offset=offset,
    )
    return {
        "items": [_quote_view(item) for item in items],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@app.post("/api/v1/crm/quotes", status_code=status.HTTP_201_CREATED)
def crm_create_quote(payload: CrmQuoteCreateRequest, context: UserContext = Depends(current_user)) -> dict:
    """建报价（行金额 / 税额由服务端重算：Decimal + ROUND_HALF_UP，整数分）。"""
    quote = _crm_do(
        crm_service.create_quote, context, account_id=payload.account_id,
        lines=_crm_lines_payload(payload.lines), opportunity_id=payload.opportunity_id,
        valid_until=payload.valid_until,
    )
    lines = _crm_do(crm_service.store.list_quote_lines, context.tenant_id, quote.quote_id)
    return {"quote": _quote_view(quote), "lines": [_quote_line_view(line) for line in lines]}


@app.get("/api/v1/crm/quotes/{quote_id}")
def crm_get_quote(quote_id: str, context: UserContext = Depends(current_user)) -> dict:
    quote = _crm_do(crm_service.get_quote, context, quote_id)
    lines = _crm_do(crm_service.store.list_quote_lines, context.tenant_id, quote_id)
    return {"quote": _quote_view(quote), "lines": [_quote_line_view(line) for line in lines]}


@app.put("/api/v1/crm/quotes/{quote_id}/lines")
def crm_replace_quote_lines(
    quote_id: str, payload: CrmQuoteLinesRequest, context: UserContext = Depends(current_user)
) -> dict:
    """行全量替换（仅 `draft`；confirmed 冻结 ⇒ 409）。"""
    quote = _crm_do(
        crm_service.replace_quote_lines, context, quote_id, lines=_crm_lines_payload(payload.lines)
    )
    lines = _crm_do(crm_service.store.list_quote_lines, context.tenant_id, quote_id)
    return {"quote": _quote_view(quote), "lines": [_quote_line_view(line) for line in lines]}


@app.post("/api/v1/crm/quotes/{quote_id}/confirm")
def crm_confirm_quote(quote_id: str, context: UserContext = Depends(current_user)) -> dict:
    quote = _crm_do(crm_service.confirm_quote, context, quote_id)
    return _quote_view(quote)


@app.post("/api/v1/crm/quotes/{quote_id}/void")
def crm_void_quote(quote_id: str, context: UserContext = Depends(current_user)) -> dict:
    quote = _crm_do(crm_service.void_quote, context, quote_id)
    return _quote_view(quote)


@app.post("/api/v1/crm/quotes/{quote_id}/convert-to-contract", status_code=status.HTTP_201_CREATED)
def crm_convert_quote_to_contract(
    quote_id: str, context: UserContext = Depends(current_user)
) -> dict:
    """报价转合同（单事务；仅 `confirmed`；金额取报价合计）。"""
    contract = _crm_do(crm_service.convert_quote_to_contract, context, quote_id)
    return _contract_view(contract)


# ------------------------------------------------------------ 合同（签署 / 回款均人工登记）


@app.get("/api/v1/crm/contracts")
def crm_list_contracts(
    account_id: str | None = Query(default=None, max_length=64),
    status_filter: str | None = Query(default=None, alias="status", max_length=32),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    context: UserContext = Depends(current_user),
) -> dict:
    items, total = _crm_do(
        crm_service.list_contracts, context, account_id=account_id, status=status_filter,
        limit=limit, offset=offset,
    )
    return {
        "items": [_contract_view(item) for item in items],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@app.post("/api/v1/crm/contracts", status_code=status.HTTP_201_CREATED)
def crm_create_contract(
    payload: CrmContractCreateRequest, context: UserContext = Depends(current_user)
) -> dict:
    contract = _crm_do(
        crm_service.create_contract, context, account_id=payload.account_id, title=payload.title,
        amount_cents=payload.amount_cents, opportunity_id=payload.opportunity_id,
        starts_on=payload.starts_on, ends_on=payload.ends_on,
        document_object_key=payload.document_object_key,
    )
    return _contract_view(contract)


@app.get("/api/v1/crm/contracts/{contract_id}")
def crm_get_contract(contract_id: str, context: UserContext = Depends(current_user)) -> dict:
    contract = _crm_do(crm_service.get_contract, context, contract_id)
    return _contract_view(contract)


@app.post("/api/v1/crm/contracts/{contract_id}/submit-for-sign")
def crm_submit_contract_for_sign(
    contract_id: str, context: UserContext = Depends(current_user)
) -> dict:
    contract = _crm_do(crm_service.submit_contract_for_sign, context, contract_id)
    return _contract_view(contract)


@app.post("/api/v1/crm/contracts/{contract_id}/register-signature")
def crm_register_signature(
    contract_id: str, payload: CrmContractSignatureRequest, context: UserContext = Depends(current_user)
) -> dict:
    """**人工登记**签署结果（本段无 provider；系统只做台账，不承诺法律效力）。"""
    contract = _crm_do(
        crm_service.register_signature, context, contract_id,
        signed_at=payload.signed_at, document_object_key=payload.document_object_key,
    )
    return _contract_view(contract)


@app.post("/api/v1/crm/contracts/{contract_id}/register-payment")
def crm_register_payment(
    contract_id: str, payload: CrmPaymentRequest, context: UserContext = Depends(current_user)
) -> dict:
    """回款**人工登记**（原子增量；超合同金额 ⇒ 409）。"""
    contract = _crm_do(crm_service.register_payment, context, contract_id, amount_cents=payload.amount_cents)
    return _contract_view(contract)


@app.post("/api/v1/crm/contracts/{contract_id}/void")
def crm_void_contract(contract_id: str, context: UserContext = Depends(current_user)) -> dict:
    contract = _crm_do(crm_service.void_contract, context, contract_id)
    return _contract_view(contract)


# ------------------------------------------------------------ 目标 / 自定义字段 / 进度指标


@app.get("/api/v1/crm/targets")
def crm_list_targets(
    period_month: date | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    context: UserContext = Depends(current_user),
) -> dict:
    """目标列表（employee 仅自己；管理角色全量）。"""
    items, total = _crm_do(
        crm_service.list_targets, context, period_month=period_month, limit=limit, offset=offset
    )
    return {
        "items": [_target_view(item) for item in items],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@app.put("/api/v1/crm/targets")
def crm_set_target(payload: CrmTargetUpsertRequest, context: UserContext = Depends(current_user)) -> dict:
    """目标写入（UPSERT；限 `ceo` / `super_admin`，其余 ⇒ 403）。"""
    target = _crm_do(
        crm_service.set_target, context, owner_id=payload.owner_id, period_month=payload.period_month,
        amount_target_cents=payload.amount_target_cents, count_target=payload.count_target,
    )
    return _target_view(target)


@app.get("/api/v1/crm/field-defs")
def crm_list_field_defs(
    object_key: str = Query(..., min_length=1, max_length=32),
    context: UserContext = Depends(current_user),
) -> dict:
    items = _crm_do(crm_service.list_field_defs, context, object_key=object_key)
    return {"items": [_field_def_view(item) for item in items]}


@app.put("/api/v1/crm/field-defs")
def crm_upsert_field_def(
    payload: CrmFieldDefUpsertRequest, context: UserContext = Depends(current_user)
) -> dict:
    """字段定义写入（管理动作：`ceo` / `super_admin`；§1.3-9 本段不做字段管理 UI，走 API）。"""
    definition = _crm_do(
        crm_service.upsert_field_def, context, object_key=payload.object_key,
        field_key=payload.field_key, label=payload.label, field_type=payload.field_type,
        required=payload.required, options=payload.options,
    )
    return _field_def_view(definition)


@app.get("/api/v1/crm/progress/summary")
def crm_progress_summary(
    scope: str = Query(default="me", max_length=8),
    context: UserContext = Depends(current_user),
) -> dict:
    """多维度进度指标（§2.6）：分母为零一律 `null`；`scope=all` 需管理角色（否则 403）。"""
    return _crm_do(crm_service.progress_summary, context, scope=scope)
