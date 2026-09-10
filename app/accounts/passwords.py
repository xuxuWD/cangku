from __future__ import annotations

import base64
import hashlib
import hmac
import os

MIN_PASSWORD_LENGTH = 10
MAX_PASSWORD_LENGTH = 128
_SCRYPT_N = 16384
_SCRYPT_R = 8
_SCRYPT_P = 1
_SALT_BYTES = 16
_DERIVED_BYTES = 32


class PasswordPolicyError(ValueError):
    """口令不满足最小安全策略。"""


def _validate(password: object) -> None:
    if not isinstance(password, str):
        raise PasswordPolicyError("口令必须是文本")
    if len(password) < MIN_PASSWORD_LENGTH or len(password) > MAX_PASSWORD_LENGTH:
        raise PasswordPolicyError(f"口令长度必须在 {MIN_PASSWORD_LENGTH} 到 {MAX_PASSWORD_LENGTH} 之间")
    if any(ord(char) < 32 or ord(char) == 127 for char in password):
        raise PasswordPolicyError("口令不能包含控制字符")


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def hash_password(password: str) -> str:
    """使用 scrypt 加随机盐哈希口令，输出自描述字符串。"""
    _validate(password)
    salt = os.urandom(_SALT_BYTES)
    derived = hashlib.scrypt(
        password.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=_DERIVED_BYTES
    )
    return "$".join(
        ["scrypt", str(_SCRYPT_N), str(_SCRYPT_R), str(_SCRYPT_P), _b64encode(salt), _b64encode(derived)]
    )


def verify_password(password: str, encoded: str) -> bool:
    """恒定时间校验口令；参数被篡改或解析失败一律返回 False，不抛异常。

    本函数不做长度策略校验，由调用方在注册/改密时负责。
    """
    try:
        scheme, n, r, p, salt_b64, hash_b64 = encoded.split("$")
        if scheme != "scrypt":
            return False
        if (int(n), int(r), int(p)) != (_SCRYPT_N, _SCRYPT_R, _SCRYPT_P):
            return False
        salt = _b64decode(salt_b64)
        expected = _b64decode(hash_b64)
        derived = hashlib.scrypt(
            password.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=len(expected)
        )
        return hmac.compare_digest(derived, expected)
    except (AttributeError, TypeError, ValueError):
        return False
