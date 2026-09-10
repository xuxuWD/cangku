"""TOTP 动态口令（RFC 4226 / RFC 6238），仅使用标准库。

设计要点：
- 6 位码、30 秒步长、校验窗口 ±1 步。
- `verify_code` 返回命中的步号（而非布尔值），供调用方做重放防护。
- 校验使用恒定时间比较。
- 不抛异常：任何非法输入一律返回 `None`，由调用方决定如何处理。
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import os
import struct
from datetime import datetime
from urllib.parse import quote, urlencode

SECRET_BYTES = 20
DIGITS = 6
STEP_SECONDS = 30
VERIFY_WINDOW_STEPS = 1
DEFAULT_ISSUER = "公司数字员工工作台"


def generate_secret() -> str:
    """生成 20 字节随机种子并做 base32 编码（去掉补位符）。"""
    return base64.b32encode(os.urandom(SECRET_BYTES)).decode().rstrip("=")


def _decode_secret(secret: object) -> bytes | None:
    if not isinstance(secret, str):
        return None
    compact = secret.strip().upper()
    if not compact:
        return None
    padded = compact + "=" * (-len(compact) % 8)
    try:
        return base64.b32decode(padded, casefold=True)
    except (binascii.Error, ValueError):
        return None


def normalize_code(value: object) -> str | None:
    """规范化验证码：去除空白后必须是恰好 DIGITS 位数字，否则返回 None。"""
    if not isinstance(value, str):
        return None
    compact = "".join(value.split())
    if len(compact) != DIGITS or not compact.isdigit():
        return None
    return compact


def hotp(secret: str, counter: int) -> str:
    """按 RFC 4226 计算一次性口令（动态截断）。"""
    key = _decode_secret(secret)
    if key is None:
        raise ValueError("无效的动态口令种子")
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    truncated = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(truncated % (10**DIGITS)).zfill(DIGITS)


def current_step(at: datetime) -> int:
    return int(at.timestamp()) // STEP_SECONDS


def verify_code(secret: str, code: object, *, at: datetime) -> int | None:
    """校验验证码，命中返回步号，未命中返回 None。"""
    normalized = normalize_code(code)
    if normalized is None or _decode_secret(secret) is None:
        return None
    step = current_step(at)
    for candidate in (step - VERIFY_WINDOW_STEPS, step, step + VERIFY_WINDOW_STEPS):
        if candidate < 0:
            continue
        if hmac.compare_digest(hotp(secret, candidate), normalized):
            return candidate
    return None


def provisioning_uri(secret: str, *, account_name: str, issuer: str = DEFAULT_ISSUER) -> str:
    """生成 otpauth URI，供验证器 App 扫码或手工录入。

    `account_name` 必须是脱敏标识（调用方传 `mask_phone` 的结果），不得放明文手机号。
    `*` 是 RFC 3986 允许的 sub-delim，保留不转义以便验证器展示。
    """
    label = quote(f"{issuer}:{account_name}", safe="*")
    query = urlencode(
        {
            "secret": secret,
            "issuer": issuer,
            "algorithm": "SHA1",
            "digits": DIGITS,
            "period": STEP_SECONDS,
        }
    )
    return f"otpauth://totp/{label}?{query}"
