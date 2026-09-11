from __future__ import annotations

from typing import Any

from app.audit.models import AuditAction
from app.domain import UserContext

from .models import ContentStatus
from .publisher import PublicationFailed, PublicationNotConfigured, Publisher
from .publication_store import PublicationRecord, PublicationNotFound, PublicationStore
from .service import ContentNotFound
from .store import ContentRecord


class PublicationNotAllowed(ValueError):
    """内容未确认时不允许发布。"""


class PublicationService:
    """内容发布编排：先确认、再幂等、失败即人工接管且绝不自动重发。"""

    def __init__(
        self,
        content_store: Any,
        publication_store: PublicationStore,
        *,
        publisher: Publisher | None,
        audit: Any,
        inbox: Any = None,
    ) -> None:
        self.content_store = content_store
        self.publication_store = publication_store
        self.publisher = publisher
        self.audit = audit
        # 站内通知（收件箱）：失败转人工接管时告知内容负责人；None 表示不接入。
        self.inbox = inbox

    def _record(self, actor: UserContext, task_id: str) -> ContentRecord:
        try:
            return self.content_store.get(
                actor.tenant_id,
                actor.user_id,
                task_id,
                elevated=actor.role in {"ceo", "super_admin"},
            )
        except KeyError as exc:
            raise ContentNotFound(task_id) from exc

    def _write_audit(
        self, action: AuditAction, actor: UserContext, detail: dict[str, object]
    ) -> None:
        if self.audit is None:
            return
        self.audit.record(
            action,
            tenant_id=actor.tenant_id,
            actor_id=actor.user_id,
            detail=detail,
        )

    def publish(self, actor: UserContext, task_id: str) -> PublicationRecord:
        record = self._record(actor, task_id)
        draft = record.draft
        if draft.status is not ContentStatus.CONFIRMED:
            raise PublicationNotAllowed("内容未确认，不能发布")

        idempotency_key = f"{task_id}:{draft.revision}"
        existing = self.publication_store.find_by_idempotency(actor.tenant_id, idempotency_key)
        if existing is not None:
            return existing

        if self.publisher is None:
            raise PublicationNotConfigured("未配置发布渠道，发布功能未启用")

        stored = self.publication_store.add(
            PublicationRecord(
                tenant_id=actor.tenant_id,
                task_id=task_id,
                revision=draft.revision,
                target=self.publisher.name,
                idempotency_key=idempotency_key,
                created_by=actor.user_id,
            )
        )
        # 并发下同一幂等键已有结果（成功或已接管）时直接返回，绝不重发。
        if stored.status != "pending":
            return stored

        target = self.publisher.name
        self._write_audit(
            AuditAction.CONTENT_PUBLICATION_REQUESTED, actor, {"target": target}
        )
        try:
            receipt = self.publisher.publish(
                title=draft.title,
                content=draft.body_markdown,
                idempotency_key=idempotency_key,
            )
        except PublicationFailed as exc:
            self.publication_store.mark_result(
                stored.publication_id,
                status="manual_takeover",
                error=str(exc)[:500],
            )
            self._write_audit(
                AuditAction.CONTENT_PUBLICATION_MANUAL_TAKEOVER,
                actor,
                {"target": target, "status": "manual_takeover"},
            )
            # 告知内容负责人需要人工接管；通知失败不阻断（InboxService 内部降级为审计）。
            if self.inbox is not None:
                self.inbox.publication_manual_takeover(
                    tenant_id=actor.tenant_id,
                    recipient_id=record.created_by,
                    task_id=task_id,
                )
            raise
        succeeded = self.publication_store.mark_result(
            stored.publication_id, status="succeeded", receipt_id=receipt.receipt_id
        )
        self._write_audit(
            AuditAction.CONTENT_PUBLICATION_SUCCEEDED,
            actor,
            {"target": target, "receipt_id": receipt.receipt_id},
        )
        return succeeded

    def verify(self, actor: UserContext, publication_id: str) -> PublicationRecord:
        publication = self.publication_store.get(actor.tenant_id, publication_id)
        # 可见性口径与内容记录一致：非 ceo/super_admin 仅本人。
        self._record(actor, publication.task_id)
        if self.publisher is None:
            raise PublicationNotConfigured("未配置发布渠道，发布功能未启用")
        if not publication.receipt_id:
            raise PublicationFailed("该发布没有回执，无法核对")
        verified_status = self.publisher.verify(publication.receipt_id)
        updated = self.publication_store.mark_verified(
            publication.publication_id, status=verified_status
        )
        self._write_audit(
            AuditAction.CONTENT_PUBLICATION_VERIFIED,
            actor,
            {"target": self.publisher.name, "status": verified_status},
        )
        return updated

    def list(self, actor: UserContext, task_id: str) -> list[PublicationRecord]:
        self._record(actor, task_id)
        return self.publication_store.list_for_task(actor.tenant_id, task_id)
