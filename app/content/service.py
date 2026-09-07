from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from app.domain import AuditEvent, IdempotencyConflict, RiskLevel, Task, TaskNotFound, UserContext
from app.knowledge_policy import KnowledgeAccessRegistry
from app.runtime.service import RuntimeService

from .models import ContentAudit, ContentBriefInput, ContentDraft, ContentStatus, NormalizedBrief, normalize_brief
from .store import ContentRecord, ContentStore


class ContentNotFound(LookupError):
    pass


def _fingerprint(brief: NormalizedBrief) -> str:
    value = {"topic": brief.topic, "sources": [item.__dict__ for item in brief.sources], "knowledge_references": brief.knowledge_references}
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


class ContentService:
    def __init__(self, task_store: Any, runtime_service: RuntimeService, content_store: ContentStore, knowledge_registry: KnowledgeAccessRegistry | None = None) -> None:
        self.task_store = task_store
        self.runtime_service = runtime_service
        self.content_store = content_store
        self.knowledge_registry = knowledge_registry

    def _record(self, actor: UserContext, task_id: str) -> ContentRecord:
        try:
            return self.content_store.get(actor.tenant_id, actor.user_id, task_id, elevated=actor.role in {"ceo", "super_admin"})
        except KeyError as exc:
            raise ContentNotFound(task_id) from exc

    def _draft(self, record: ContentRecord, run_id: str) -> ContentDraft:
        digest = _fingerprint(record.brief)[:12]
        topic = record.brief.topic
        citations = list(record.brief.sources)
        title = f"{topic}：从素材到行动的实践指南"
        summary = f"围绕“{topic}”整理的公众号图文草稿，包含关键观察、实践建议与来源引用。"
        body = "\n\n".join([
            f"## 为什么值得关注\n\n本篇围绕“{topic}”提炼可复用的信息，帮助读者快速理解背景与重点。",
            f"## 核心内容\n\n结合已提供素材，建议从问题现状、关键判断和落地动作三个层次展开，形成清晰的阅读路径。",
            f"## 可以怎么做\n\n先确认目标，再按优先级验证小范围方案，最后用实际反馈迭代。素材指纹：`{digest}`。",
        ])
        return ContentDraft(
            draft_id=f"draft-{run_id}", task_id=record.task_id, run_id=run_id, tenant_id=record.tenant_id,
            title=title, summary=summary, body_markdown=body,
            image_suggestions=[f"围绕“{topic}”的主视觉，突出一个明确观点"], citations=citations,
            template_version="mock-content-v1", status=ContentStatus.REVIEWING,
        )

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
        record.drafts.append(self._draft(record, run_id))
        record.audits.append(ContentAudit("content.created", actor.user_id))
        self.content_store.add(record)
        return record

    def get(self, *, actor: UserContext, task_id: str) -> ContentRecord:
        return self._record(actor, task_id)

    def runtime_side_effects(self, run_id: str) -> list[dict[str, object]]:
        return []

