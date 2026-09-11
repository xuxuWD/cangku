from __future__ import annotations

from datetime import datetime
from typing import Sequence

from .logging import emit_audit_line
from .models import AuditAction, AuditRecord, build_record
from .store import AuditStore


class AuditService:
    """审计入口：先落库再写结构化日志，两条通道都不静默吞掉异常。"""

    def __init__(self, store: AuditStore) -> None:
        self.store = store

    def record(
        self,
        action: AuditAction,
        *,
        tenant_id: str | None = None,
        actor_id: str | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
        phone_masked: str | None = None,
        detail: dict[str, object] | None = None,
    ) -> AuditRecord:
        record = build_record(
            action,
            tenant_id=tenant_id,
            actor_id=actor_id,
            target_type=target_type,
            target_id=target_id,
            phone_masked=phone_masked,
            detail=detail,
        )
        saved = self.store.append(record)
        emit_audit_line(saved)
        return saved

    def query(
        self,
        tenant_id: str,
        *,
        actions: Sequence[AuditAction] | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
        actor_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[AuditRecord], int]:
        """只读查询：转发到仓储；租户条件由调用方从鉴权上下文提供，不允许省略。"""
        return self.store.query(
            tenant_id,
            actions=actions,
            target_type=target_type,
            target_id=target_id,
            actor_id=actor_id,
            since=since,
            until=until,
            limit=limit,
            offset=offset,
        )
