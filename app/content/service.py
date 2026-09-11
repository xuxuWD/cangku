from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from app.audit.models import AuditAction
from app.domain import AuditEvent, IdempotencyConflict, RiskLevel, Task, TaskNotFound, UserContext
from app.knowledge_policy import KnowledgeAccessRegistry
from app.runtime.service import RuntimeService

from .export import MarkdownExporter
from .generator import ContentGenerationError, ContentGenerationInput, ContentGenerator, MockContentGenerator
from .models import ContentAudit, ContentBriefInput, ContentDraft, ContentStatus, NormalizedBrief, normalize_brief
from .scraper import ScrapeDenied, ScrapeFailed, ScrapedDocument, WebScraper
from .store import ContentRecord, ContentStore, ContentStoreConflict


class ContentNotFound(LookupError):
    pass


class RevisionConflict(ValueError):
    pass


class ExportNotAllowed(ValueError):
    pass


class ScrapeNotConfigured(ValueError):
    """未配置抓取白名单时抓取功能关闭。"""


def _url_host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""


def _fingerprint(brief: NormalizedBrief) -> str:
    value = {"topic": brief.topic, "sources": [item.__dict__ for item in brief.sources], "knowledge_references": brief.knowledge_references}
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


class ContentService:
    def __init__(
        self, task_store: Any, runtime_service: RuntimeService, content_store: ContentStore,
        knowledge_registry: KnowledgeAccessRegistry | None = None, content_generator: ContentGenerator | None = None,
        scraper: WebScraper | None = None, audit: Any | None = None,
    ) -> None:
        self.task_store = task_store
        self.runtime_service = runtime_service
        self.content_store = content_store
        self.knowledge_registry = knowledge_registry
        self.content_generator = content_generator or MockContentGenerator()
        self.scraper = scraper
        self.audit = audit

    def _record_scrape(self, actor: UserContext, domain: str, status: str) -> None:
        if self.audit is None:
            return
        self.audit.record(
            AuditAction.CONTENT_SOURCE_SCRAPED,
            tenant_id=actor.tenant_id,
            actor_id=actor.user_id,
            detail={"domain": domain, "status": status},
        )

    def scrape_source(self, actor: UserContext, url: str) -> ScrapedDocument:
        if self.scraper is None:
            raise ScrapeNotConfigured("未配置抓取白名单，抓取功能未启用")
        try:
            document = self.scraper.fetch(url)
        except ScrapeDenied:
            self._record_scrape(actor, _url_host(url), "denied")
            raise
        except ScrapeFailed:
            self._record_scrape(actor, _url_host(url), "failed")
            raise
        self._record_scrape(actor, _url_host(document.url), "fetched")
        return document

    def _record(self, actor: UserContext, task_id: str) -> ContentRecord:
        try:
            return self.content_store.get(actor.tenant_id, actor.user_id, task_id, elevated=actor.role in {"ceo", "super_admin"})
        except KeyError as exc:
            raise ContentNotFound(task_id) from exc

    def _draft(self, record: ContentRecord, run_id: str, generated) -> ContentDraft:
        return ContentDraft(
            draft_id=f"draft-{run_id}", task_id=record.task_id, run_id=run_id, tenant_id=record.tenant_id,
            title=generated.title, summary=generated.summary, body_markdown=generated.body_markdown,
            image_suggestions=list(generated.image_suggestions), citations=list(record.brief.sources),
            template_version=generated.template_version, status=ContentStatus.REVIEWING,
        )

    def _generate_draft(self, record: ContentRecord, run_id: str) -> tuple[ContentDraft, ContentAudit]:
        started = ContentAudit("content.generation.started", record.created_by)
        record.audits.append(started)
        try:
            generated = self.content_generator.generate(ContentGenerationInput(
                topic=record.brief.topic, sources=record.brief.sources,
                knowledge_references=record.brief.knowledge_references,
            ))
        except ContentGenerationError as exc:
            failed = ContentDraft(
                draft_id=f"draft-{run_id}", task_id=record.task_id, run_id=run_id, tenant_id=record.tenant_id,
                title=record.brief.topic, summary="模型生成失败，请检查配置后重新生成。", body_markdown="",
                image_suggestions=[], citations=list(record.brief.sources), template_version="generation-failed",
                status=ContentStatus.FAILED,
            )
            return failed, ContentAudit("content.generation.failed", record.created_by, detail={"reason": str(exc)[:200]})
        completed = ContentAudit(
            "content.generation.completed", record.created_by,
            detail={"provider": generated.provider, "model": generated.model_name},
        )
        return self._draft(record, run_id, generated), completed

    def create(self, *, actor: UserContext, payload: ContentBriefInput, idempotency_key: str):
        normalized = normalize_brief(payload)
        if self.knowledge_registry is not None:
            allowed = self.knowledge_registry.resolve(actor, "content-operator", "content-writer")
            if not set(normalized.knowledge_references).issubset(allowed):
                raise ContentNotFound("knowledge scope")
        fingerprint = _fingerprint(normalized)
        existing = self.content_store.find_by_idempotency(actor.tenant_id, actor.user_id, idempotency_key)
        if existing is not None:
            if existing.input_fingerprint != fingerprint:
                raise IdempotencyConflict("相同幂等键对应的内容素材不一致")
            return existing
        task = Task(
            tenant_id=actor.tenant_id, project_id=None, created_by=actor.user_id, employee_key="content-writer",
            title=normalized.topic, risk_level=RiskLevel.LOW, budget=0, idempotency_key=idempotency_key,
            request_fingerprint=fingerprint, status=__import__("app.domain", fromlist=["TaskStatus"]).TaskStatus.QUEUED,
        )
        task.audits.append(AuditEvent(action="task.created", actor_id=actor.user_id, actor_role=actor.role))
        stored, _ = self.task_store.create(actor, task)
        run_id, _, _ = self.runtime_service.start(actor, stored.id, "mock", [{"step_id": "content.generate", "kind": "read", "tool": "content.generate"}], "product_manager")
        record = ContentRecord(stored.id, actor.tenant_id, actor.user_id, idempotency_key, fingerprint, normalized, [run_id])
        record.audits.append(ContentAudit("content.created", actor.user_id))
        draft, generation_audit = self._generate_draft(record, run_id)
        record.drafts.append(draft)
        record.audits.append(generation_audit)
        self.content_store.add(record)
        return record

    def regenerate(self, *, actor: UserContext, task_id: str, idempotency_key: str) -> ContentRecord:
        record = self._record(actor, task_id)
        for audit in record.audits:
            if audit.action == "content.regeneration.created" and audit.detail.get("idempotency_key") == idempotency_key:
                return record
        run_id, _, _ = self.runtime_service.start(
            actor, record.task_id, "mock", [{"step_id": "content.generate", "kind": "read", "tool": "content.generate"}], "product_manager"
        )
        record.run_ids.append(run_id)
        record.audits.append(ContentAudit("content.regeneration.created", actor.user_id, detail={"idempotency_key": idempotency_key}))
        draft, generation_audit = self._generate_draft(record, run_id)
        record.drafts.append(draft)
        record.audits.append(generation_audit)
        self.content_store.save(record)
        return record

    def get(self, *, actor: UserContext, task_id: str) -> ContentRecord:
        return self._record(actor, task_id)

    def list(
        self,
        *,
        actor: UserContext,
        status: ContentStatus | None,
        page: int,
        page_size: int,
    ) -> dict[str, object]:
        if page < 1:
            raise ValueError("页码必须是正整数")
        if page_size < 1 or page_size > 100:
            raise ValueError("每页数量必须在 1 到 100 之间")
        allowed_statuses = {ContentStatus.REVIEWING, ContentStatus.FAILED, ContentStatus.CONFIRMED}
        if status is not None and status not in allowed_statuses:
            raise ValueError("不支持的内容任务状态")
        user_id = None if actor.role in {"ceo", "super_admin"} else actor.user_id
        summaries, total = self.content_store.list_summaries(
            actor.tenant_id,
            user_id=user_id,
            status=status,
            offset=(page - 1) * page_size,
            limit=page_size,
        )
        return {
            "items": summaries,
            "page": page,
            "page_size": page_size,
            "total": total,
            "has_next": page * page_size < total,
        }

    def runtime_side_effects(self, run_id: str) -> list[dict[str, object]]:
        return []

    def update_draft(
        self, *, actor: UserContext, task_id: str, revision: int, title: str, summary: str,
        body_markdown: str, image_suggestions: list[str],
    ) -> ContentDraft:
        record = self._record(actor, task_id)
        draft = record.draft
        if draft.revision != revision:
            raise RevisionConflict("草稿已被其他页面修改，请重新读取")
        if draft.status != ContentStatus.REVIEWING:
            raise RevisionConflict("当前草稿状态不允许编辑")
        expected_revision = draft.revision
        draft.title, draft.summary, draft.body_markdown = title.strip(), summary.strip(), body_markdown.strip()
        draft.image_suggestions = [item.strip() for item in image_suggestions if item.strip()]
        draft.revision += 1
        draft.updated_at = datetime.now(UTC)
        record.audits.append(ContentAudit("draft.updated", actor.user_id))
        try:
            self.content_store.save(record, expected_revision=expected_revision)
        except ContentStoreConflict as exc:
            raise RevisionConflict("草稿已被其他页面修改，请重新读取") from exc
        return draft

    def confirm(self, *, actor: UserContext, task_id: str, revision: int) -> ContentDraft:
        record = self._record(actor, task_id)
        draft = record.draft
        if draft.revision != revision:
            raise RevisionConflict("草稿已被其他页面修改，请重新读取")
        if draft.status != ContentStatus.REVIEWING:
            raise RevisionConflict("当前草稿状态不允许确认")
        expected_revision = draft.revision
        draft.status = ContentStatus.CONFIRMED
        draft.confirmed_by = actor.user_id
        draft.confirmed_at = datetime.now(UTC)
        draft.updated_at = draft.confirmed_at
        record.audits.append(ContentAudit("draft.confirmed", actor.user_id, draft.confirmed_at))
        try:
            self.content_store.save(record, expected_revision=expected_revision)
        except ContentStoreConflict as exc:
            raise RevisionConflict("草稿已被其他页面修改，请重新读取") from exc
        return draft

    def revoke_confirmation(self, *, actor: UserContext, task_id: str) -> ContentDraft:
        record = self._record(actor, task_id)
        draft = record.draft
        if draft.status != ContentStatus.CONFIRMED:
            raise RevisionConflict("当前草稿尚未确认")
        expected_revision = draft.revision
        draft.status = ContentStatus.REVIEWING
        draft.revision += 1
        draft.confirmed_by = None
        draft.confirmed_at = None
        draft.updated_at = datetime.now(UTC)
        record.audits.append(ContentAudit("draft.confirmation_revoked", actor.user_id))
        try:
            self.content_store.save(record, expected_revision=expected_revision)
        except ContentStoreConflict as exc:
            raise RevisionConflict("草稿已被其他页面修改，请重新读取") from exc
        return draft

    def export_markdown(self, *, actor: UserContext, task_id: str) -> bytes:
        record = self._record(actor, task_id)
        if record.draft.status != ContentStatus.CONFIRMED:
            raise ExportNotAllowed("内容确认后才能导出")
        record.audits.append(ContentAudit("draft.exported", actor.user_id))
        try:
            self.content_store.save(record, expected_revision=record.draft.revision)
        except ContentStoreConflict as exc:
            raise RevisionConflict("草稿已被其他页面修改，请重新读取") from exc
        return MarkdownExporter().render(record.draft)
