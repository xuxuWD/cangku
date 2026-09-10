from __future__ import annotations

import re

SENSITIVE_KEY_TOKENS = frozenset(
    {
        "password",
        "passwd",
        "pwd",
        "token",
        "secret",
        "key",
        "cookie",
        "authorization",
        "credential",
        "session",
        "bearer",
    }
)
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def key_tokens(key: object) -> set[str]:
    """把键名归一切词：camelCase 边界拆开、- 与 _ 视为分隔，再小写比对词元。"""
    text = _CAMEL_BOUNDARY.sub("_", str(key))
    return {part for part in text.lower().replace("-", "_").split("_") if part}


def has_sensitive_key(value: object) -> bool:
    """递归检查是否出现敏感键名；按词元比对，避免误伤 keyword 之类。"""
    if isinstance(value, dict):
        for key, item in value.items():
            if key_tokens(key) & SENSITIVE_KEY_TOKENS or has_sensitive_key(item):
                return True
        return False
    if isinstance(value, list):
        return any(has_sensitive_key(item) for item in value)
    return False


def mask_phone(phone: str) -> str:
    """手机号脱敏；非 11 位一律全量遮蔽，避免短号泄露。"""
    if len(phone) < 11:
        return "*" * len(phone)
    return f"{phone[:3]}{'*' * (len(phone) - 7)}{phone[-4:]}"
