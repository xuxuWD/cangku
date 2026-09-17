import json

import pytest

from app.planner.generator import MockPlanGenerator, OpenAICompatiblePlanGenerator
from app.planner.models import (
    PlanGenerationError,
    PlannerNotConfigured,
    Tool,
    ToolCatalog,
    normalize_steps,
)


def catalog() -> ToolCatalog:
    return ToolCatalog(
        (
            Tool(name="knowledge.search", kind="read"),
            Tool(name="content.publish", kind="publish"),
        )
    )


def test_mock_generator_is_deterministic_and_uses_read_tools_only() -> None:
    generator = MockPlanGenerator()

    first = generator.generate("整理本周公众号选题", catalog=catalog(), max_steps=5)
    second = generator.generate("整理本周公众号选题", catalog=catalog(), max_steps=5)

    assert first == second
    assert [step["tool"] for step in first] == ["knowledge.search"]
    assert generator.key == "mock"
    assert generator.model_name is None


def test_mock_generator_requires_configured_catalog() -> None:
    generator = MockPlanGenerator()

    with pytest.raises(PlannerNotConfigured):
        generator.generate("任意目标", catalog=ToolCatalog(), max_steps=5)


def test_mock_generator_respects_max_steps() -> None:
    wide = ToolCatalog(tuple(Tool(name=f"read.tool{i}", kind="read") for i in range(5)))

    steps = MockPlanGenerator().generate("目标", catalog=wide, max_steps=2)

    assert len(steps) == 2


def test_openai_generator_parses_steps_from_model_response() -> None:
    captured: dict[str, object] = {}

    def transport(url, headers, payload, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["payload"] = payload
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "steps": [
                                    {"step_id": "s1", "tool": "knowledge.search", "args": {"query": "选题"}},
                                    {"step_id": "s2", "tool": "content.publish"},
                                ]
                            }
                        )
                    }
                }
            ]
        }

    generator = OpenAICompatiblePlanGenerator(
        base_url="https://model.example/v1",
        model_name="planner-small",
        api_key="secret-key",
        timeout_seconds=5,
        transport=transport,
    )

    steps = generator.generate("整理选题并发布", catalog=catalog(), max_steps=5)

    assert [step["tool"] for step in steps] == ["knowledge.search", "content.publish"]
    assert captured["url"] == "https://model.example/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer secret-key"
    assert generator.key == "openai_compatible"
    assert generator.model_name == "planner-small"


def _url_for_base_url(base_url: str) -> str:
    captured: dict[str, object] = {}

    def transport(url, headers, payload, timeout):
        captured["url"] = url
        return {"choices": [{"message": {"content": json.dumps({"steps": []})}}]}

    generator = OpenAICompatiblePlanGenerator(
        base_url=base_url,
        model_name="planner-small",
        api_key="secret-key",
        timeout_seconds=5,
        transport=transport,
    )
    generator.generate("目标", catalog=catalog(), max_steps=5)
    return str(captured["url"])


def test_openai_generator_appends_v1_when_base_url_omits_it() -> None:
    """与内容模型同一套语义：地址不带 /v1 时由客户端补齐，不会打到 /chat/completions。"""
    assert _url_for_base_url("https://model.example") == "https://model.example/v1/chat/completions"


def test_openai_generator_does_not_duplicate_v1_suffix() -> None:
    assert _url_for_base_url("https://model.example/v1/") == "https://model.example/v1/chat/completions"


def test_openai_generator_does_not_dictate_kind_or_approval() -> None:
    def transport(url, headers, payload, timeout):
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "steps": [
                                    {
                                        "step_id": "s1",
                                        "tool": "content.publish",
                                        "kind": "read",
                                        "requires_approval": False,
                                    }
                                ]
                            }
                        )
                    }
                }
            ]
        }

    generator = OpenAICompatiblePlanGenerator(
        base_url="https://model.example/v1",
        model_name="planner-small",
        api_key="secret-key",
        timeout_seconds=5,
        transport=transport,
    )

    steps = generator.generate("发布", catalog=catalog(), max_steps=5)

    assert "kind" not in steps[0]
    assert "requires_approval" not in steps[0]


def test_openai_generator_raises_on_bad_payloads() -> None:
    def make(payload):
        def transport(url, headers, _payload, timeout):
            return payload

        return OpenAICompatiblePlanGenerator(
            base_url="https://model.example/v1",
            model_name="planner-small",
            api_key="secret-key",
            timeout_seconds=5,
            transport=transport,
        )

    with pytest.raises(PlanGenerationError, match="模型响应"):
        make({"choices": []}).generate("目标", catalog=catalog(), max_steps=5)

    with pytest.raises(PlanGenerationError, match="JSON"):
        make({"choices": [{"message": {"content": "not-json"}}]}).generate(
            "目标", catalog=catalog(), max_steps=5
        )

    with pytest.raises(PlanGenerationError, match="步骤列表"):
        make({"choices": [{"message": {"content": json.dumps({"steps": "text"})}}]}).generate(
            "目标", catalog=catalog(), max_steps=5
        )


def test_openai_generator_raises_on_transport_failure() -> None:
    def transport(url, headers, payload, timeout):
        raise RuntimeError("connection reset")

    generator = OpenAICompatiblePlanGenerator(
        base_url="https://model.example/v1",
        model_name="planner-small",
        api_key="secret-key",
        timeout_seconds=5,
        transport=transport,
    )

    with pytest.raises(PlanGenerationError, match="模型调用失败"):
        generator.generate("目标", catalog=catalog(), max_steps=5)


def test_openai_generator_reports_missing_configuration() -> None:
    with pytest.raises(ValueError, match="地址、模型名和 API Key"):
        OpenAICompatiblePlanGenerator(
            base_url="", model_name="", api_key="", timeout_seconds=5, transport=lambda *a: {}
        )


def test_openai_generator_strips_unknown_keys_from_steps() -> None:
    def transport(url, headers, payload, timeout):
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "steps": [
                                    {
                                        "step_id": "s1",
                                        "tool": "content.publish",
                                        "kind": "read",
                                        "requires_approval": False,
                                        "next": "s2",
                                        "danger": "rm -rf /",
                                    }
                                ]
                            }
                        )
                    }
                }
            ]
        }

    generator = OpenAICompatiblePlanGenerator(
        base_url="https://model.example/v1",
        model_name="planner-small",
        api_key="secret-key",
        timeout_seconds=5,
        transport=transport,
    )

    steps = generator.generate("目标", catalog=catalog(), max_steps=5)

    assert set(steps[0]) == {"step_id", "tool"}
    assert "danger" not in steps[0]
    assert "next" not in steps[0]


def test_openai_generator_truncates_steps_beyond_max_steps() -> None:
    def transport(url, headers, payload, timeout):
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "steps": [
                                    {"step_id": f"s{i}", "tool": "knowledge.search"} for i in range(6)
                                ]
                            }
                        )
                    }
                }
            ]
        }

    generator = OpenAICompatiblePlanGenerator(
        base_url="https://model.example/v1",
        model_name="planner-small",
        api_key="secret-key",
        timeout_seconds=5,
        transport=transport,
    )

    steps = generator.generate("目标", catalog=catalog(), max_steps=2)

    assert len(steps) == 2


def test_openai_generator_error_message_hides_endpoint_and_credentials() -> None:
    def transport(url, headers, payload, timeout):
        raise RuntimeError(
            "HTTPError for https://internal.model.corp/v1/chat/completions "
            "with headers {'Authorization': 'Bearer secret-key'}"
        )

    generator = OpenAICompatiblePlanGenerator(
        base_url="https://model.example/v1",
        model_name="planner-small",
        api_key="secret-key",
        timeout_seconds=5,
        transport=transport,
    )

    with pytest.raises(PlanGenerationError) as excinfo:
        generator.generate("目标", catalog=catalog(), max_steps=5)

    message = str(excinfo.value)
    assert "internal.model.corp" not in message
    assert "secret-key" not in message
    assert "Bearer" not in message
    assert message == "模型调用失败"


def _generator_with_steps(steps):
    def transport(url, headers, payload, timeout):
        return {
            "choices": [
                {"message": {"content": json.dumps({"steps": steps}, ensure_ascii=False)}}
            ]
        }

    return OpenAICompatiblePlanGenerator(
        base_url="https://model.example/v1",
        model_name="planner-small",
        api_key="secret-key",
        timeout_seconds=5,
        transport=transport,
    )


def test_openai_generator_drops_non_object_step_items_instead_of_failing_whole_plan() -> None:
    """缺陷回归（2026-09-18）：真实模型偶尔在 steps 里混入非对象元素（说明性字符串、数字等）。
    旧实现 `if not isinstance(item, dict): raise` ⇒ **整份计划被拒**，与内容生成的缺陷同源。
    改为**逐条丢弃**，与 CRM `sanitize_output` 的既有范式一致。"""
    generator = _generator_with_steps([
        {"step_id": "s1", "tool": "knowledge.search"},
        "这是一段说明文字，不是步骤对象",
        123,
        None,
        {"step_id": "s2", "tool": "content.publish"},
    ])

    steps = generator.generate("整理选题并发布", catalog=catalog(), max_steps=5)

    assert [step["step_id"] for step in steps] == ["s1", "s2"]


def test_openai_generator_drops_all_invalid_steps_and_downstream_rejects_empty_plan() -> None:
    """逐条丢弃不得退化成"静默产出空计划"：全部非法时生成器返回空列表，
    由下游 `normalize_steps` 明确拒绝（不重复在生成器里设防）。"""
    generator = _generator_with_steps(["说明文字", 123, None])

    assert generator.generate("目标", catalog=catalog(), max_steps=5) == []

    with pytest.raises(PlanGenerationError, match="至少一个步骤"):
        normalize_steps([], catalog(), max_steps=5)
