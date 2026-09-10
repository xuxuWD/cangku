from __future__ import annotations

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
