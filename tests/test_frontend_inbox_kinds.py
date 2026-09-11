"""前端收件箱 kind 与后端 InboxKind 的一致性守护。

背景：管理台与手机伴侣端的 `features/inbox/types.ts` 曾缺少后端已有的
`run.cancelled`、`run.approval_rejected` 两个 kind，仅靠 `?? '通知'` 兜底掩盖了漂移。
本测试从两端 TypeScript 的 `InboxKind` 联合类型中抽取字符串字面量，与
`app.inbox.InboxKind` 的取值集合比对，三者必须完全一致（不许多也不许少）。
"""

from __future__ import annotations

import re
from pathlib import Path

from app.inbox import InboxKind

ROOT = Path(__file__).resolve().parents[1]
FRONTENDS = {
    "admin-web": ROOT / "admin-web" / "src" / "features" / "inbox" / "types.ts",
    "companion-pwa": ROOT / "companion-pwa" / "src" / "features" / "inbox" / "types.ts",
}
UNION_BODY = re.compile(r"export type InboxKind\s*=\s*(?P<body>(?:\s*\|[^\n]+)+)")
LITERAL = re.compile(r"'([^']+)'")


def frontend_kinds(path: Path) -> set[str]:
    match = UNION_BODY.search(path.read_text(encoding="utf-8"))
    assert match is not None, f"{path} 中未找到 InboxKind 联合类型"
    return set(LITERAL.findall(match.group("body")))


def test_frontend_inbox_kinds_match_backend() -> None:
    backend = {item.value for item in InboxKind}
    for name, path in FRONTENDS.items():
        kinds = frontend_kinds(path)
        missing = sorted(backend - kinds)
        extra = sorted(kinds - backend)
        # 判定依据：契约枚举不一致会导致前端无法展示新 kind，或渲染出后端不存在的类型。
        assert kinds == backend, f"{name} 的 InboxKind 与后端不一致：缺少 {missing}；多余 {extra}"
