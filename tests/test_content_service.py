from app.content.models import ContentBriefInput, ContentStatus, SourceInput, normalize_brief


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
