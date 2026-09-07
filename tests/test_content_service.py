from datetime import UTC, datetime, timedelta

import pytest

from app.content.models import ContentBriefInput, ContentStatus, SourceInput, normalize_brief


def employee(tenant: str, user: str):
    from app.domain import UserContext

    return UserContext(tenant_id=tenant, user_id=user, role="employee")


def admin(tenant: str, user: str = "admin"):
    from app.domain import UserContext

    return UserContext(tenant_id=tenant, user_id=user, role="super_admin")


def brief(topic: str) -> ContentBriefInput:
    return ContentBriefInput(topic=topic, sources=[SourceInput(url="https://example.com/a", excerpt="参考摘录")], knowledge_references=[])


def make_content_service(content_store=None, content_generator=None):
    from app.content.service import ContentService
    from app.content.store import ContentStore
    from app.domain import TaskStore
    from app.runtime.service import RuntimeService

    task_store = TaskStore()
    return ContentService(
        task_store, RuntimeService(task_store), content_store or ContentStore(), content_generator=content_generator,
    )


def test_normalize_brief_requires_topic_and_one_material():
    import pytest

    with pytest.raises(ValueError, match="主题不能为空"):
        normalize_brief(ContentBriefInput(topic="", sources=[], knowledge_references=[]))
    with pytest.raises(ValueError, match="至少提供一种素材"):
        normalize_brief(ContentBriefInput(topic="本周选题", sources=[], knowledge_references=[]))


def test_normalize_brief_rejects_non_http_url_and_sorts_sources():
    import pytest

    with pytest.raises(ValueError, match="来源链接必须使用 http 或 https"):
        normalize_brief(ContentBriefInput(
            topic="选题", sources=[SourceInput(url="javascript:alert(1)", excerpt="摘录")], knowledge_references=[]
        ))
    normalized = normalize_brief(ContentBriefInput(
        topic="  选题  ",
        sources=[SourceInput(url="https://b.example", excerpt="B"), SourceInput(url="https://a.example", excerpt="A")],
        knowledge_references=["kb-2", "kb-1", "kb-1"],
    ))
    assert normalized.topic == "选题"
    assert [item.url for item in normalized.sources] == ["https://a.example", "https://b.example"]
    assert normalized.knowledge_references == ("kb-1", "kb-2")


def test_status_values_are_stable():
    assert [item.value for item in ContentStatus] == ["generating", "reviewing", "confirmed", "failed"]


def test_content_service_creates_deterministic_draft_without_side_effects():
    service = make_content_service()
    first = service.create(actor=employee("tenant-a", "u1"), payload=brief("选题"), idempotency_key="k1")
    second = service.create(actor=employee("tenant-a", "u1"), payload=brief("选题"), idempotency_key="k1")
    assert first.task_id == second.task_id
    assert first.draft.body_markdown == second.draft.body_markdown
    assert first.draft.template_version == "mock-content-v1"
    assert service.runtime_side_effects(first.run_id) == []


def test_same_idempotency_key_with_different_input_conflicts_and_other_user_is_hidden():
    from app.domain import IdempotencyConflict
    from app.content.service import ContentNotFound

    service = make_content_service()
    created = service.create(actor=employee("tenant-a", "u1"), payload=brief("选题"), idempotency_key="k1")
    with pytest.raises(IdempotencyConflict):
        service.create(actor=employee("tenant-a", "u1"), payload=brief("另一个选题"), idempotency_key="k1")
    with pytest.raises(ContentNotFound):
        service.get(actor=employee("tenant-a", "u2"), task_id=created.task_id)
    with pytest.raises(ContentNotFound):
        service.get(actor=employee("tenant-b", "u1"), task_id=created.task_id)


def test_draft_edit_uses_optimistic_revision_and_only_confirmed_draft_exports():
    from app.content.service import ExportNotAllowed, RevisionConflict

    service = make_content_service()
    item = service.create(actor=employee("tenant-a", "u1"), payload=brief("选题"), idempotency_key="k1")
    with pytest.raises(ExportNotAllowed):
        service.export_markdown(actor=employee("tenant-a", "u1"), task_id=item.task_id)
    updated = service.update_draft(
        actor=employee("tenant-a", "u1"), task_id=item.task_id, revision=1,
        title="新标题", summary="摘要", body_markdown="正文", image_suggestions=["配图"],
    )
    with pytest.raises(RevisionConflict):
        service.update_draft(
            actor=employee("tenant-a", "u1"), task_id=item.task_id, revision=1,
            title="旧版本", summary="摘要", body_markdown="正文", image_suggestions=[],
        )
    service.confirm(actor=employee("tenant-a", "u1"), task_id=item.task_id, revision=updated.revision)
    markdown = service.export_markdown(actor=employee("tenant-a", "u1"), task_id=item.task_id).decode("utf-8")
    assert "# 新标题" in markdown
    assert "tenant-a" not in markdown
    assert "token" not in markdown.lower()


def test_sqlite_content_service_mutations_survive_store_reopen(tmp_path):
    from app.content.sqlite_store import SQLiteContentStore

    path = tmp_path / "content.sqlite3"
    store = SQLiteContentStore(path)
    service = make_content_service(content_store=store)
    created = service.create(actor=employee("tenant-a", "user-a"), payload=brief("持久化"), idempotency_key="key-1")
    updated = service.update_draft(
        actor=employee("tenant-a", "user-a"), task_id=created.task_id, revision=1,
        title="已编辑", summary="摘要", body_markdown="正文", image_suggestions=["配图"],
    )
    service.confirm(actor=employee("tenant-a", "user-a"), task_id=created.task_id, revision=updated.revision)
    service.export_markdown(actor=employee("tenant-a", "user-a"), task_id=created.task_id)
    store.close()

    reopened = SQLiteContentStore(path)
    restored = reopened.get("tenant-a", "user-a", created.task_id)
    assert restored.draft.status == ContentStatus.CONFIRMED
    assert restored.draft.title == "已编辑"
    assert [audit.action for audit in restored.audits] == [
        "content.created", "content.generation.started", "content.generation.completed",
        "draft.updated", "draft.confirmed", "draft.exported",
    ]
    reopened.close()


class FailingGenerator:
    def __init__(self, message):
        self.message = message

    def generate(self, value):
        from app.content.generator import ContentGenerationError

        raise ContentGenerationError(self.message)


class SequenceGenerator:
    def __init__(self, titles):
        self.titles = iter(titles)

    def generate(self, value):
        from app.content.generator import GeneratedContentDraft

        title = next(self.titles)
        return GeneratedContentDraft(
            title=title, summary="摘要", body_markdown="正文", image_suggestions=(),
            provider="test", model_name="test-model", template_version=value.template_version,
        )


def test_generation_failure_is_audited_and_not_exportable():
    from app.content.service import ExportNotAllowed

    service = make_content_service(content_generator=FailingGenerator("模型不可用"))
    created = service.create(actor=employee("tenant-a", "u1"), payload=brief("失败用例"), idempotency_key="k1")
    assert created.draft.status == ContentStatus.FAILED
    assert created.audits[-1].action == "content.generation.failed"
    assert "模型不可用" in created.audits[-1].detail["reason"]
    with pytest.raises(ExportNotAllowed):
        service.export_markdown(actor=employee("tenant-a", "u1"), task_id=created.task_id)


def test_regenerate_reuses_task_and_creates_new_run_and_draft():
    generator = SequenceGenerator(["first", "second"])
    service = make_content_service(content_generator=generator)
    created = service.create(actor=employee("tenant-a", "u1"), payload=brief("重试"), idempotency_key="k1")
    original_run_id = created.run_id
    regenerated = service.regenerate(actor=employee("tenant-a", "u1"), task_id=created.task_id, idempotency_key="regen-1")
    assert regenerated.task_id == created.task_id
    assert regenerated.run_id != original_run_id
    assert regenerated.draft.title == "second"
    assert len(regenerated.drafts) == 2


def test_content_service_lists_scoped_paginated_summaries_without_drafts():
    service = make_content_service()
    owner = service.create(actor=employee("tenant-history", "owner"), payload=brief("我的任务"), idempotency_key="owner-key")
    service.create(actor=employee("tenant-history", "other"), payload=brief("同租户任务"), idempotency_key="other-key")
    service.create(actor=employee("tenant-other", "owner"), payload=brief("其他租户任务"), idempotency_key="tenant-key")
    service.confirm(actor=employee("tenant-history", "owner"), task_id=owner.task_id, revision=1)

    own_page = service.list(actor=employee("tenant-history", "owner"), status=ContentStatus.CONFIRMED, page=1, page_size=20)
    assert own_page["total"] == 1
    assert own_page["items"][0].task_id == owner.task_id
    assert own_page["items"][0].status is ContentStatus.CONFIRMED
    assert not hasattr(own_page["items"][0], "draft")

    admin_page = service.list(actor=admin("tenant-history"), status=None, page=1, page_size=1)
    assert admin_page["total"] == 2
    assert len(admin_page["items"]) == 1
    assert admin_page["has_next"] is True

    from app.domain import UserContext

    ceo_page = service.list(
        actor=UserContext(tenant_id="tenant-history", user_id="ceo", role="ceo"),
        status=None,
        page=1,
        page_size=20,
    )
    assert ceo_page["total"] == 2

    other_tenant_page = service.list(actor=admin("tenant-other"), status=None, page=1, page_size=20)
    assert other_tenant_page["total"] == 1
