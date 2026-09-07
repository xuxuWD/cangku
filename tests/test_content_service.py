from datetime import UTC, datetime, timedelta

import pytest

from app.content.models import ContentBriefInput, ContentStatus, SourceInput, normalize_brief


def employee(tenant: str, user: str):
    from app.domain import UserContext

    return UserContext(tenant_id=tenant, user_id=user, role="employee")


def brief(topic: str) -> ContentBriefInput:
    return ContentBriefInput(topic=topic, sources=[SourceInput(url="https://example.com/a", excerpt="参考摘录")], knowledge_references=[])


def make_content_service():
    from app.content.service import ContentService
    from app.content.store import ContentStore
    from app.domain import TaskStore
    from app.runtime.service import RuntimeService

    task_store = TaskStore()
    return ContentService(task_store, RuntimeService(task_store), ContentStore())


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
