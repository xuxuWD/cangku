"""前端审计动作标签与后端 AuditAction 的一致性守护。

背景：管理台审计页的 `AUDIT_ACTION_LABELS` 必须覆盖后端 `AuditAction` 的全部取值。
标签缺失会让界面回落成动作码；多出的键通常是拼错的动作码，会让筛选请求被后端 422 拒绝。
本测试从 TypeScript 标签表中抽取键，与 `app.audit.models.AuditAction` 的取值集合比对，两者必须完全一致。
"""

from __future__ import annotations

import re
from pathlib import Path

from app.audit.models import AuditAction

ROOT = Path(__file__).resolve().parents[1]
TYPES = ROOT / "admin-web" / "src" / "features" / "auditLog" / "types.ts"
LABELS_BODY = re.compile(
    r"export const AUDIT_ACTION_LABELS\s*:\s*Record<\s*string\s*,\s*string\s*>\s*=\s*\{(?P<body>.*?)\n\}",
    re.DOTALL,
)
LABEL_KEY = re.compile(r"['\"](?P<key>[^'\"]+)['\"]\s*:")


def frontend_actions() -> set[str]:
    match = LABELS_BODY.search(TYPES.read_text(encoding="utf-8"))
    assert match is not None, f"{TYPES} 中未找到 AUDIT_ACTION_LABELS 标签表"
    return {item.group("key") for item in LABEL_KEY.finditer(match.group("body"))}


def test_frontend_audit_labels_match_backend() -> None:
    backend = {item.value for item in AuditAction}
    labels = frontend_actions()
    missing = sorted(backend - labels)
    extra = sorted(labels - backend)
    # 判定依据：缺标签会让界面回落成动作码；多余键多为拼错的动作码，会让筛选请求被 422 拒绝。
    assert labels == backend, f"auditLog/types.ts 的 AUDIT_ACTION_LABELS 与后端不一致：缺少 {missing}；多余 {extra}"
