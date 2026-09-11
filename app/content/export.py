from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.audit.redaction import SENSITIVE_KEY_TOKENS, key_tokens

from .models import ContentDraft


def mask_url_credentials(url: str) -> str:
    """遮蔽来源链接中的凭证：userinfo、敏感查询参数，并丢弃 #fragment。

    素材链接由员工提供，可能夹带 `?access_token=...` 或 `https://user:pass@host`；
    导出产物会发给外部，因此这里按现有脱敏词元表（`SENSITIVE_KEY_TOKENS`）遮蔽，
    避免把密钥带进 Markdown。非敏感参数与路径保持原样，来源仍可追溯。
    """
    if not url:
        return url
    try:
        parts = urlsplit(url)
    except ValueError:
        return "***"
    netloc = parts.netloc
    if "@" in netloc:
        netloc = f"***@{netloc.rsplit('@', 1)[1]}"
    query = parts.query
    if query:
        query = urlencode(
            [
                (name, "***" if key_tokens(name) & SENSITIVE_KEY_TOKENS else value)
                for name, value in parse_qsl(query, keep_blank_values=True)
            ]
        )
    return urlunsplit((parts.scheme, netloc, parts.path, query, ""))


class MarkdownExporter:
    @staticmethod
    def _clean(value: str) -> str:
        return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", value).strip()

    def render(self, draft: ContentDraft) -> bytes:
        lines = [
            f"# {self._clean(draft.title)}",
            "",
            f"> {self._clean(draft.summary)}",
            "",
            "## 正文",
            "",
            self._clean(draft.body_markdown),
            "",
            "## 配图建议",
            "",
            *[f"- {self._clean(item)}" for item in draft.image_suggestions],
            "",
            "## 来源",
            "",
        ]
        if draft.citations:
            for index, source in enumerate(draft.citations, 1):
                suffix = f" - {mask_url_credentials(source.url)}" if source.url else ""
                lines.append(f"{index}. 员工提供的素材{suffix}")
        else:
            lines.append("暂无外部来源")
        lines.extend([
            "",
            "---",
            f"任务号：{self._clean(draft.task_id)}",
            f"确认时间：{draft.confirmed_at.isoformat() if draft.confirmed_at else ''}",
            "说明：该文件为内容草稿，不代表已发布。",
            "",
        ])
        return "\n".join(lines).encode("utf-8")
