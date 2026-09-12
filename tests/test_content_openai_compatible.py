import json

import pytest

from app.content.generator import ContentGenerationError, ContentGenerationInput
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
