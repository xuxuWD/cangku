from __future__ import annotations

import re

from .models import ContentDraft


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
                suffix = f" - {source.url}" if source.url else ""
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
