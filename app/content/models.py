from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from urllib.parse import urlparse


class ContentStatus(StrEnum):
    GENERATING = "generating"
    REVIEWING = "reviewing"
    CONFIRMED = "confirmed"
    FAILED = "failed"


@dataclass(frozen=True)
class SourceInput:
    url: str = ""
    excerpt: str = ""


@dataclass(frozen=True)
class ContentBriefInput:
    topic: str
    sources: list[SourceInput]
    knowledge_references: list[str]


@dataclass(frozen=True)
class NormalizedSource:
    url: str
    excerpt: str


@dataclass(frozen=True)
class NormalizedBrief:
    topic: str
    sources: tuple[NormalizedSource, ...]
    knowledge_references: tuple[str, ...]


@dataclass
class ContentDraft:
    draft_id: str
    task_id: str
    run_id: str
    tenant_id: str
    title: str
    summary: str
    body_markdown: str
    image_suggestions: list[str]
    citations: list[NormalizedSource]
    template_version: str
    revision: int = 1
    status: ContentStatus = ContentStatus.GENERATING
    confirmed_by: str | None = None
    confirmed_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class ContentAudit:
    action: str
    actor_id: str
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    detail: dict[str, str] = field(default_factory=dict)


def normalize_brief(value: ContentBriefInput) -> NormalizedBrief:
    topic = value.topic.strip()
    if not topic:
        raise ValueError("主题不能为空")
    if len(topic) > 200:
        raise ValueError("主题不能超过 200 个字符")
    if len(value.sources) > 20:
        raise ValueError("最多添加 20 条来源材料")

    sources: list[NormalizedSource] = []
    for source in value.sources:
        url = source.url.strip()
        excerpt = source.excerpt.strip()
        if url:
            scheme = urlparse(url).scheme.lower()
            if scheme not in {"http", "https"}:
                raise ValueError("来源链接必须使用 http 或 https")
        if not excerpt:
            raise ValueError("每条来源材料都需要正文摘录")
        if len(excerpt) > 20_000:
            raise ValueError("正文摘录不能超过 20000 个字符")
        sources.append(NormalizedSource(url=url, excerpt=excerpt))

    references = tuple(sorted({item.strip() for item in value.knowledge_references if item.strip()}))
    if not sources and not references:
        raise ValueError("至少提供一种素材")
    return NormalizedBrief(
        topic=topic,
        sources=tuple(sorted(sources, key=lambda item: (item.url, item.excerpt))),
        knowledge_references=references,
    )
