from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field

from .bootstrap import build_dead_letter_store, build_event_bus, build_knowledge_access_registry, build_task_repository
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
from .auth import verify_access_token
from .settings import get_settings, validate_runtime_settings
from .runtime.policy import ApprovalRequired, PolicyDenied
from .runtime.service import RunAccessDenied, RuntimeService
from .commercial.lifecycle import CommercialLifecycleService, LifecycleJob
from .commercial.repository import InMemoryCommercialRepository, ResourceNotFound
from .commercial.tenant import Actor, CommercialPolicyError
from .commercial.usage import InMemoryUsageLedger


app = FastAPI(title="公司数字员工工作台", version="0.1.0")
settings = get_settings()
validate_runtime_settings(settings)
store = build_task_repository(settings)
event_bus = build_event_bus(settings)
dead_letter_store = build_dead_letter_store(settings, event_bus=event_bus)
knowledge_access_registry = build_knowledge_access_registry(settings)
runtime_service = RuntimeService(store)
commercial_repository = InMemoryCommercialRepository()
commercial_usage = InMemoryUsageLedger()
commercial_lifecycle = CommercialLifecycleService(commercial_repository)


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
