from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Protocol

from .models import NormalizedSource


class ContentGenerationError(RuntimeError):
    """A safe, user-facing generation failure without raw provider payloads."""


class ContentGenerationUpstreamError(ContentGenerationError):
    """上游调用失败（网络 / 超时 / 鉴权 / 5xx 等）——与「输出格式不符」区分，界面文案不同。"""


class ContentGenerationFormatError(ContentGenerationError):
    """上游有响应，但内容不符合约定的结构要求。"""


@dataclass(frozen=True)
class ContentGenerationInput:
    topic: str
    sources: tuple[NormalizedSource, ...]
    knowledge_references: tuple[str, ...]
    template_version: str = "mock-content-v1"


@dataclass(frozen=True)
class GeneratedContentDraft:
    title: str
    summary: str
    body_markdown: str
    image_suggestions: tuple[str, ...]
    provider: str
    model_name: str
    template_version: str


class ContentGenerator(Protocol):
    def generate(self, value: ContentGenerationInput) -> GeneratedContentDraft: ...


class MockContentGenerator:
    provider = "mock"
    model_name = "mock-content-v1"

    def generate(self, value: ContentGenerationInput) -> GeneratedContentDraft:
        digest = hashlib.sha256(
            json.dumps(
                {
                    "topic": value.topic,
                    "sources": [item.__dict__ for item in value.sources],
                    "knowledge_references": value.knowledge_references,
                },
                ensure_ascii=False,
                sort_keys=True,
            ).encode()
        ).hexdigest()[:12]
        topic = value.topic
        body = "\n\n".join([
            f"## 为什么值得关注\n\n本篇围绕“{topic}”提炼可复用的信息，帮助读者快速理解背景与重点。",
            "## 核心内容\n\n结合已提供素材，建议从问题现状、关键判断和落地动作三个层次展开，形成清晰的阅读路径。",
            f"## 可以怎么做\n\n先确认目标，再按优先级验证小范围方案，最后用实际反馈迭代。素材指纹：`{digest}`。",
        ])
        return GeneratedContentDraft(
            title=f"{topic}：从素材到行动的实践指南",
            summary=f"围绕“{topic}”整理的公众号图文草稿，包含关键观察、实践建议与来源引用。",
            body_markdown=body,
            image_suggestions=(f"围绕“{topic}”的主视觉，突出一个明确观点",),
            provider=self.provider,
            model_name=self.model_name,
            template_version=value.template_version,
        )
