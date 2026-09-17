import json

import pytest

from app.content.generator import (
    ContentGenerationError,
    ContentGenerationFormatError,
    ContentGenerationInput,
    ContentGenerationUpstreamError,
)
from app.content.models import NormalizedSource
from app.content.openai_compatible import OpenAICompatibleContentGenerator


class TimeoutError(Exception):
    pass


class HttpResponseError(Exception):
    def __init__(self, status_code):
        self.status_code = status_code


def sample_input():
    return ContentGenerationInput(
        topic="模型选题", sources=(NormalizedSource("https://example.com", "业务摘录"),),
        knowledge_references=("kb-content",),
    )


def fake_success_response():
    return {
        "status_code": 200,
        "json": {
            "choices": [{"message": {"content": json.dumps({
                "title": "模型标题", "summary": "模型摘要", "body_markdown": "模型正文",
                "image_suggestions": ["模型配图"],
            }, ensure_ascii=False)} }],
            "usage": {"total_tokens": 42},
        },
    }


class FakeHttpTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def request(self, method, url, **kwargs):
        self.requests.append({"method": method, "url": url, **kwargs})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        if isinstance(response, HttpResponseError):
            raise response
        return response


def make_generator(transport, max_retries=0):
    return OpenAICompatibleContentGenerator(
        base_url="https://model.internal/v1", model_name="company-text", api_key="secret",
        timeout_seconds=3, max_retries=max_retries, client=transport, sleep=lambda _: None,
    )


def test_openai_compatible_generator_posts_structured_request_without_leaking_context():
    transport = FakeHttpTransport([fake_success_response()])
    result = make_generator(transport).generate(sample_input())
    request = transport.requests[0]
    assert request["url"] == "https://model.internal/v1/chat/completions"
    assert request["headers"]["Authorization"] == "Bearer secret"
    assert request["json"]["model"] == "company-text"
    assert "tenant_id" not in json.dumps(request["json"])
    assert result.title == "模型标题"
    assert result.provider == "openai_compatible"


def test_openai_compatible_generator_appends_v1_when_base_url_omits_it():
    """地址不带 /v1 时由客户端补齐；带 /v1 时不重复拼接（与规划模型同一套语义）。"""
    transport = FakeHttpTransport([fake_success_response()])
    generator = OpenAICompatibleContentGenerator(
        base_url="https://model.internal", model_name="company-text", api_key="secret",
        timeout_seconds=3, max_retries=0, client=transport, sleep=lambda _: None,
    )

    generator.generate(sample_input())

    assert transport.requests[0]["url"] == "https://model.internal/v1/chat/completions"


def test_openai_compatible_generator_retries_timeout_and_does_not_retry_4xx():
    retry_transport = FakeHttpTransport([TimeoutError(), TimeoutError(), fake_success_response()])
    assert make_generator(retry_transport, max_retries=2).generate(sample_input()).title == "模型标题"
    assert len(retry_transport.requests) == 3

    bad_request_transport = FakeHttpTransport([HttpResponseError(401)])
    with pytest.raises(ContentGenerationError, match="模型请求失败"):
        make_generator(bad_request_transport, max_retries=2).generate(sample_input())
    assert len(bad_request_transport.requests) == 1


def test_openai_compatible_generator_rejects_invalid_structured_output():
    invalid = fake_success_response()
    invalid["json"]["choices"][0]["message"]["content"] = "不是 JSON"
    with pytest.raises(ContentGenerationError, match="模型输出格式无效"):
        make_generator(FakeHttpTransport([invalid])).generate(sample_input())


def _response_with_image_suggestions(value):
    response = fake_success_response()
    response["json"]["choices"][0]["message"]["content"] = json.dumps({
        "title": "模型标题", "summary": "模型摘要", "body_markdown": "模型正文",
        "image_suggestions": value,
    }, ensure_ascii=False)
    return response


def test_openai_compatible_generator_accepts_object_image_suggestions():
    """缺陷回归（2026-09-18）：真实模型会把 image_suggestions 返回成对象数组
    （position/description），旧实现按 list[str] 硬校验 ⇒ 整份输出判定无效 ⇒ 任务随机失败。
    现要求归一化成字符串，而不是拒绝整份输出。"""
    transport = FakeHttpTransport([_response_with_image_suggestions([
        {"position": "文章开头", "description": "一张对比图"},
        {"position": "第二部分", "description": "三个并列色块"},
    ])])

    result = make_generator(transport).generate(sample_input())

    assert result.image_suggestions == ("文章开头：一张对比图", "第二部分：三个并列色块")


def test_openai_compatible_generator_normalizes_partial_object_image_suggestions():
    """对象只有 description（无 position）时直接取描述；元素为其他类型时跳过该条。"""
    transport = FakeHttpTransport([_response_with_image_suggestions([
        {"description": "只有描述"},
        {"position": "第三部分", "description": ""},
        123,
        "直接给的字符串",
    ])])

    result = make_generator(transport).generate(sample_input())

    assert result.image_suggestions == ("只有描述", "直接给的字符串")


def test_openai_compatible_generator_keeps_string_image_suggestions_unchanged():
    """既有行为不得退化：字符串数组原样保留。"""
    transport = FakeHttpTransport([_response_with_image_suggestions(["模型配图", "第二张"])])

    result = make_generator(transport).generate(sample_input())

    assert result.image_suggestions == ("模型配图", "第二张")


def test_openai_compatible_generator_separates_upstream_and_format_errors():
    """上游请求失败与输出格式不符必须可区分（界面文案不同），且都仍是 ContentGenerationError。"""
    assert issubclass(ContentGenerationUpstreamError, ContentGenerationError)
    assert issubclass(ContentGenerationFormatError, ContentGenerationError)

    upstream = FakeHttpTransport([HttpResponseError(401)])
    with pytest.raises(ContentGenerationUpstreamError, match="模型请求失败"):
        make_generator(upstream, max_retries=1).generate(sample_input())
    assert len(upstream.requests) == 1

    with pytest.raises(ContentGenerationFormatError, match="模型输出格式无效"):
        make_generator(FakeHttpTransport([_response_with_image_suggestions({"非": "数组"})])).generate(sample_input())


def test_openai_compatible_generator_prompt_declares_field_types():
    """提示词必须声明字段类型，降低模型产出异构结构的概率（与解析层容错互为两层）。"""
    transport = FakeHttpTransport([fake_success_response()])

    make_generator(transport).generate(sample_input())

    system = transport.requests[0]["json"]["messages"][0]["content"]
    assert "image_suggestions" in system
    assert "字符串数组" in system


def test_openai_compatible_generator_requests_json_object_response_format():
    """与规划模型 / CRM 跟进模型对齐：三者都是「只返回 JSON 对象」的契约，
    都应显式声明 `response_format`（本项目既有做法，内容生成此前缺失）。"""
    transport = FakeHttpTransport([fake_success_response()])

    make_generator(transport).generate(sample_input())

    assert transport.requests[0]["json"]["response_format"] == {"type": "json_object"}
