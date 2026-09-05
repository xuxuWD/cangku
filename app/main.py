from __future__ import annotations

import hashlib
import json

from fastapi import Depends, FastAPI, Header, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field

from .domain import (
    AuditEvent,
    IdempotencyConflict,
    PolicyError,
    RiskLevel,
    Task,
    TaskNotFound,
    TaskStatus,
    TaskStateConflict,
    TaskStore,
    UserContext,
    ensure_can_approve,
    ensure_can_create,
)
from .auth import verify_access_token
from .settings import get_settings, validate_runtime_settings


app = FastAPI(title="公司数字员工工作台", version="0.1.0")
store = TaskStore()
settings = get_settings()
validate_runtime_settings(settings)


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
    return to_view(task)
