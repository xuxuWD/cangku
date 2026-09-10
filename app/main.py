from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field

from .audit.logging import configure_audit_logging
from .audit.redaction import mask_phone
from .bootstrap import build_account_service, build_audit_service, build_commercial_components, build_content_generator, build_content_store, build_dead_letter_store, build_event_bus, build_knowledge_access_registry, build_login_rate_limiter, build_planner_service, build_task_repository
from .events import EventEnvelope
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
)
from .accounts.passwords import PasswordPolicyError
from .accounts.rate_limit import LoginRateLimited
from .auth import create_access_token, verify_access_token
from .settings import get_settings, validate_runtime_settings
from .runtime.policy import ApprovalRequired, PolicyDenied
from .runtime.service import RunAccessDenied, RuntimeService
from .content.models import ContentBriefInput, ContentStatus, SourceInput
from .content.service import ContentNotFound, ContentService, ExportNotAllowed, RevisionConflict
from .commercial.lifecycle import CommercialLifecycleService, LifecycleJob
from .commercial.repository import ResourceNotFound
from .commercial.tenant import Actor, CommercialPolicyError
from .planner.models import (
    PlanGenerationError,
    PlanProposalNotFound,
    PlanProposalStateConflict,
    PlannerAccessDenied,
    PlannerNotConfigured,
    UnknownTool,
)


app = FastAPI(title="公司数字员工工作台", version="0.1.0")
settings = get_settings()
validate_runtime_settings(settings)
if settings.env == "development":
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[],
        allow_origin_regex=r"https?://(localhost|127\.0\.0\.1):\d+",
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Accept", "Content-Type", "X-Tenant-Id", "X-User-Id", "X-User-Role", "Idempotency-Key"],
    )
configure_audit_logging(settings.log_level)
audit_service = build_audit_service(settings)
login_rate_limiter = build_login_rate_limiter(settings)
store = build_task_repository(settings)
event_bus = build_event_bus(settings)
dead_letter_store = build_dead_letter_store(settings, event_bus=event_bus)
knowledge_access_registry = build_knowledge_access_registry(settings)
runtime_service = RuntimeService(store)
content_service = ContentService(
    task_store=store,
    runtime_service=runtime_service,
    content_store=build_content_store(settings),
    knowledge_registry=knowledge_access_registry,
    content_generator=build_content_generator(settings),
)
commercial_repository, commercial_usage, commercial_lifecycle = build_commercial_components(settings)
planner_service, planner_store = build_planner_service(
    settings, task_store=store, runtime_service=runtime_service, audit=audit_service
)
account_service, _ = build_account_service(
    settings, audit=audit_service, login_limiter=login_rate_limiter
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


class CollaborationDynamicView(BaseModel):
    event_id: str
    aggregate_id: str
    action: str
    title: str
    employee_key: str
    status: TaskStatus
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


def current_user(
    tenant_id: str | None = Header(default=None, alias="X-Tenant-Id"),
    user_id: str | None = Header(default=None, alias="X-User-Id"),
    role: str | None = Header(default=None, alias="X-User-Role"),
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> UserContext:
    if settings.env != "development":
        if not settings.auth_secret or not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="请使用有效的登录凭证")
        try:
            return verify_access_token(authorization.removeprefix("Bearer "), settings.auth_secret)
        except ValueError as exc:
            raise HTTPException(status_code=401, detail="登录凭证无效") from exc
    if authorization and authorization.startswith("Bearer ") and settings.auth_secret:
        try:
            return verify_access_token(authorization.removeprefix("Bearer "), settings.auth_secret)
        except ValueError as exc:
            raise HTTPException(status_code=401, detail="登录凭证无效") from exc
    if not tenant_id or not user_id or not role:
        raise HTTPException(status_code=401, detail="缺少登录身份信息")
    return UserContext(tenant_id=tenant_id, user_id=user_id, role=role)


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
    return to_view(task)


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
    return RuntimeRunView(run_id=run_id, runtime_key=runtime_key, policy_version=policy_version, status="running")


@app.get("/api/v1/runs/{run_id}/events")
def stream_runtime_events(run_id: str, cursor: str | None = None, context: UserContext = Depends(current_user)) -> list[dict[str, object]]:
    try:
        _key, adapter, _state = runtime_service.adapter_for_task(context, run_id)
        events = adapter.stream_events(run_id, cursor)
    except RunAccessDenied as exc:
        detail = str(exc)
        raise HTTPException(status_code=404 if detail == "运行不存在" else 403, detail=detail) from exc
    return [event.to_public_dict() for event in events]


@app.post("/api/v1/runs/{run_id}/pause")
def pause_runtime_run(run_id: str, payload: RuntimeAction, context: UserContext = Depends(current_user)) -> dict[str, str]:
    try:
        _key, adapter, _state = runtime_service.adapter_for_task(context, run_id)
        adapter.pause_run(run_id, payload.reason)
    except RunAccessDenied as exc:
        raise HTTPException(status_code=404, detail="运行不存在") from exc
    return {"run_id": run_id, "status": "paused"}


@app.post("/api/v1/runs/{run_id}/resume")
def resume_runtime_run(run_id: str, context: UserContext = Depends(current_user)) -> dict[str, str]:
    try:
        _key, adapter, _state = runtime_service.adapter_for_task(context, run_id)
        adapter.resume_run(run_id)
    except RunAccessDenied as exc:
        raise HTTPException(status_code=404, detail="运行不存在") from exc
    return {"run_id": run_id, "status": "running"}


@app.post("/api/v1/runs/{run_id}/cancel")
def cancel_runtime_run(run_id: str, payload: RuntimeAction, context: UserContext = Depends(current_user)) -> dict[str, str]:
    try:
        _key, adapter, _state = runtime_service.adapter_for_task(context, run_id)
        adapter.cancel_run(run_id, payload.reason)
    except RunAccessDenied as exc:
        raise HTTPException(status_code=404, detail="运行不存在") from exc
    return {"run_id": run_id, "status": "cancelled"}


@app.post("/api/v1/runs/{run_id}/approvals", status_code=status.HTTP_202_ACCEPTED)
def request_runtime_approval(run_id: str, payload: RuntimeApprovalCreate, context: UserContext = Depends(current_user)) -> dict[str, str]:
    try:
        _key, adapter, _state = runtime_service.adapter_for_task(context, run_id)
        approval_id = adapter.request_approval(run_id, payload.action)
    except RunAccessDenied as exc:
        raise HTTPException(status_code=404, detail="运行不存在") from exc
    return {"run_id": run_id, "approval_id": approval_id, "status": "pending"}


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


class SessionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phone: str = Field(min_length=1, max_length=20)
    password: str = Field(min_length=1, max_length=128)


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


@app.post("/api/v1/auth/sessions")
def create_session(payload: SessionCreate) -> dict[str, object]:
    if not settings.auth_secret:
        raise HTTPException(status_code=503, detail="会话密钥未配置，请先设置 WORKBENCH_AUTH_SECRET")
    try:
        context = account_service.login(payload.phone, payload.password)
    except LoginRateLimited as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except LoginFailed as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    token = create_access_token(context, settings.auth_secret, ttl_seconds=settings.session_ttl_seconds)
    return {
        "access_token": token,
        "token_type": "Bearer",
        "expires_in": settings.session_ttl_seconds,
        "tenant_id": context.tenant_id,
        "user_id": context.user_id,
        "role": context.role,
    }


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
    return {
        "run_id": run_id,
        "runtime_key": runtime_key,
        "policy_version": policy_version,
        "status": "running",
    }
