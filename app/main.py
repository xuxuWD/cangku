from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field

from .audit.logging import configure_audit_logging
from .audit.models import AuditAction
from .audit.redaction import mask_phone
from .bootstrap import build_account_service, build_audit_service, build_commercial_components, build_content_generator, build_content_publisher, build_content_scraper, build_content_store, build_dead_letter_store, build_event_bus, build_inbox_service, build_knowledge_access_registry, build_login_rate_limiter, build_orchestration_proposal_service, build_planner_service, build_publication_service, build_run_metrics, build_runtime_service, build_session_revocation_store, build_task_repository
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
from .runtime.contracts import ApprovalAlreadyDecided, ApprovalNotFound, RunNotDecidable
from .runtime.policy import ApprovalRequired, PolicyDenied
from .runtime.records import FinishReason, RunRecordNotFound
from .runtime.service import RunAccessDenied, RunApprovalDenied
from .content.models import ContentBriefInput, ContentStatus, SourceInput
from .content.service import ContentNotFound, ContentService, ExportNotAllowed, RevisionConflict, ScrapeNotConfigured
from .content.scraper import ScrapeDenied, ScrapeFailed
from .content.publication_service import PublicationNotAllowed
from .content.publication_store import PublicationNotFound
from .content.publisher import PublicationFailed, PublicationNotConfigured
from .commercial.lifecycle import CommercialLifecycleService, LifecycleJob
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
run_metrics_service = build_run_metrics(settings)
runtime_service = build_runtime_service(settings, store=store, run_metrics=run_metrics_service)
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
commercial_repository, commercial_usage, commercial_lifecycle = build_commercial_components(settings)
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
    try:
        _ensure_knowledge_admin(context)
        knowledge_access_registry.bind_role(context, role_key, set(payload.knowledge_base_ids))
        ids = knowledge_access_registry.resolve(context, role_key)
    except PolicyError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return _knowledge_access_view("role", role_key, ids)


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
    try:
        _ensure_knowledge_admin(context)
        knowledge_access_registry.bind_agent(context, agent_key, set(payload.knowledge_base_ids))
        ids = knowledge_access_registry.resolve(context, agent_key, agent_key)
    except PolicyError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return _knowledge_access_view("agent", agent_key, ids)


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
        status=(
            TaskStatus.PENDING_APPROVAL
            if payload.risk_level == RiskLevel.HIGH
            else TaskStatus.QUEUED
        ),
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
    model_config = ConfigDict(extra="forbid")

    approved: bool


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
) -> dict[str, str]:
    """决议运行内的审批项；仅 CEO/超级管理员，且发起人不能自审。"""
    try:
        runtime_service.decide_approval(context, run_id, approval_id, payload.approved)
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
    audit_service.record(
        AuditAction.RUN_APPROVAL_DECIDED,
        tenant_id=context.tenant_id,
        actor_id=context.user_id,
        target_type="run",
        target_id=run_id,
        detail={"status": "approved" if payload.approved else "rejected"},
    )
    _notify_run_terminal(context, run_id)
    return {
        "run_id": run_id,
        "approval_id": approval_id,
        "status": "approved" if payload.approved else "rejected",
        "run_status": runtime_service.snapshot(context, run_id).status,
    }


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
