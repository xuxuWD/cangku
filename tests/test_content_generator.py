from app.content.generator import ContentGenerationInput, MockContentGenerator
from app.content.models import NormalizedSource


def test_mock_generator_returns_structured_draft_from_normalized_brief():
    result = MockContentGenerator().generate(
        ContentGenerationInput(
            topic="团队协作",
            sources=(NormalizedSource("", "素材摘录"),),
            knowledge_references=(),
            template_version="mock-content-v1",
        )
    )
    assert result.title.startswith("团队协作")
    assert result.summary
    assert result.body_markdown
    assert result.image_suggestions
    assert result.provider == "mock"

