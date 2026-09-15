from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import NoReturn

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field

from .audit.logging import configure_audit_logging
from .audit.models import AuditAction
from .audit.redaction import mask_phone
from .bootstrap import build_account_service, build_agent_config_service, build_audit_service, build_commercial_components, build_content_generator, build_content_publisher, build_content_scraper, build_content_store, build_conversation_execution_service, build_conversation_service, build_conversation_store, build_dead_letter_store, build_event_bus, build_exec_callback_guard, build_execution_idempotency_store, build_inbox_service, build_knowledge_access_registry, build_login_rate_limiter, build_memory_service, build_orchestration_proposal_service, build_planner_service, build_publication_service, build_run_metrics, build_runtime_service, build_runtime_state_store, build_session_revocation_store, build_skills_service, build_task_repository, build_tool_action_store, build_tool_execution, build_workforce_directory_store
from .events import EventEnvelope
from .inbox import InboxItem, InboxNotFound
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
from .runtime.contracts import ApprovalAlreadyDecided, ApprovalNotFound, RunNotDecidable
from .tool_execution.errors import ToolExecutionError
from .tool_execution.active_execution import ActiveExecutionRegistry
from .tool_execution.callback_guard import CallbackRateLimiter, shared_secret_matches
from .tool_execution.token_binding import BindingDenied, TokenBindingStore
from .tool_execution.cleanup import build_body_cleanup_task, build_orphan_cleanup_task
from .runtime.policy import ApprovalRequired, PolicyDenied
from .runtime.records import FinishReason, RunRecordNotFound
from .runtime.service import RunAccessDenied, RunApprovalDenied
from .content.models import ContentBriefInput, ContentStatus, SourceInput
from .content.service import ContentNotFound, ContentService, ExportNotAllowed, RevisionConflict, ScrapeNotConfigured
from .content.scraper import ScrapeDenied, ScrapeFailed
from .content.publication_service import PublicationNotAllowed
from .content.publication_store import PublicationNotFound
from .content.publisher import PublicationFailed, PublicationNotConfigured
from .commercial.lifecycle import CommercialLifecycleService, DeletionNotPending, LifecycleJob
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
    SkillNotFound,
    SkillSourceDenied,
    SkillStateConflict,
)
from .skills.service import SkillService
from .conversation import (
    Conversation,
    ConversationMessage,
    ConversationNotFound,
    ConversationStateConflict,
    ConversationStatus,
    InvalidConversation,
    MessageRole,
    ensure_can_converse,
)
from .conversation.execution import ConversationExecutionError


app = FastAPI(title="公司数字员工工作台", version="0.1.0")
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
workforce_directory_store = build_workforce_directory_store(settings)
workforce_directory_service = WorkforceDirectoryService(
    workforce_directory_store,
    audit=audit_service,
    knowledge_registry=knowledge_access_registry,
    task_store=store,
)
conversation_store = build_conversation_store(settings)
conversation_service = build_conversation_service(
    settings, store=conversation_store, audit=audit_service
)
# P3 记忆层（规格 docs/superpowers/specs/2026-09-15-memory-layer-p3-design.md §2.5/§2.8）：
# 嵌入式服务开发环境缺 default 时由装配层回退到 FakeEmbeddingAdapter（仅验证链路）。
memory_service = build_memory_service(settings, audit=audit_service)
# P4 技能层（规格 docs/superpowers/specs/2026-09-15-skill-layer-p4-design.md §2.3/§2.4）：
# 来源白名单为空 = 技能层关闭（可登记、不可启用，fail-closed）；allowed-tools 与执行目录取交集。
skills_service = build_skills_service(settings, audit=audit_service)
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
runtime_service = build_runtime_service(
    settings,
    store=store,
    run_metrics=run_metrics_service,
    state_store=runtime_state_store,
    tool_actions=tool_action_store,
    usage_ledger=commercial_usage,
)
# ②④ 的权威状态（§3.5 P1 第 3 条 / §8 U24）：**装配期单例**，`build_tool_execution`
# （mint 侧写：`TokenBindingStore.record` + `ActiveExecutionRegistry.register`）与
# `build_exec_callback_guard`（判定侧读）**必须共用同一实例**，否则 ②④ 恒 `403`。
exec_authority_store = TokenBindingStore()
exec_authority_registry = ActiveExecutionRegistry()
# 段二（dsh 接入段）：backend=mock 时为 None；backend=dsh 且缺件时记 error 但不退进程（§4.1.6-2/-3）。
tool_execution_service = build_tool_execution(
    settings,
    run_metrics=run_metrics_service,
    audit=audit_service,
    runtime_service=runtime_service,
    tool_actions=tool_action_store,
    token_store=exec_authority_store,
    token_registry=exec_authority_registry,
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
# 段二-4 对话入口路由（§3.7 Y2 / §3.2 第四条）：幂等行落 027 的 `workbench_execution_idempotency`。
execution_idempotency_store = build_execution_idempotency_store(settings)
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
account_service, _ = build_account_service(
    settings, audit=audit_service, login_limiter=login_rate_limiter
)
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
    """会话视图：刻意不含 `operator_id` 与 `dsh_session_id`（账号 PII 与内部映射不外泄）。"""

    conversation_id: str
    agent_key: str | None = None
    title: str
    status: str
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


class ConversationDetailView(ConversationView):
    messages: list[MessageView]
    messages_total: int
    messages_limit: int
    messages_offset: int


class ConversationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_key: str | None = Field(default=None, max_length=64)
    title: str = Field(default="", max_length=120)


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
    try:
        _key, adapter, _state = runtime_service.adapter_for_task(context, run_id)
        events = adapter.stream_events(run_id, cursor)
    except RunAccessDenied as exc:
        detail = str(exc)
        raise HTTPException(status_code=404 if detail == "运行不存在" else 403, detail=detail) from exc
    return [event.to_public_dict() for event in events]


@app.get("/api/v1/runs/{run_id}/metrics", response_model=RunMetricsView)
def get_run_metrics(run_id: str, context: UserContext = Depends(current_user)) -> RunMetricsView:
    try:
        record = run_metrics_service.store.get(context.tenant_id, run_id)
    except RunRecordNotFound as exc:
        raise HTTPException(status_code=404, detail="运行记录不存在") from exc
    try:
        store.get(context, record.task_id)
    except TaskNotFound as exc:
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
    """列出该运行的审批项（含已决议），供审批人查看待办与结果。"""
    try:
        _key, _adapter, state = runtime_service.adapter_for_task(context, run_id)
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
    if payload.approved and tool_execution_service is not None:
        try:
            result = tool_execution_service.resume(
                tenant_id=context.tenant_id, run_id=run_id, approval_id=approval_id
            )
        except ToolExecutionError as exc:
            # §4.1.6-5 重跑失败语义：按受控异常携带的 HTTP 语义原样映射（409 / 422 / 403 / 502 / 504）。
            raise HTTPException(status_code=exc.http_status, detail=str(exc)) from exc
        if result is not None:
            execution = {"outcome": result.outcome}
            if result.code is not None:
                execution["code"] = result.code
            if result.message_id is not None:
                execution["message_id"] = result.message_id
    body: dict[str, object] = {
        "run_id": run_id,
        "approval_id": approval_id,
        "status": "approved" if payload.approved else "rejected",
        "run_status": runtime_service.snapshot(context, run_id).status,
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
