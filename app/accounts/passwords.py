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

# 通用弱口令样本（按公开的常见口令统计整理，不是任何一次泄露库的拷贝）。
# 只收录长度达到 MIN_PASSWORD_LENGTH 的条目：更短的经典弱口令会被长度规则先拒绝，
# 收录进来就是永远走不到的死数据。
# 比对时把输入转小写后精确查表，因此大小写变体会被拦截；但列表是固定字符串集合，
# 对已收录口令再做追加或更冷门的 leetspeak 变形不会命中（已知限制，见 API 契约）。
COMMON_PASSWORDS = frozenset(
    {
        "password12",
        "password123",
        "password1234",
        "passw0rd123",
        "p@ssw0rd123",
        "qwerty1234",
        "qwerty12345",
        "qwertyuiop",
        "1q2w3e4r5t",
        "1qaz2wsx3edc",
        "qazwsxedc123",
        "asdfghjkl1",
        "abc1234567",
        "1234567890",
        "0987654321",
        "letmein123",
        "letmein1234",
        "welcome123",
        "welcome1234",
        "changeme123",
        "default123",
        "admin12345",
        "administrator",
        "iloveyou123",
        "monkey12345",
        "dragon12345",
        "football123",
        "baseball123",
        "sunshine123",
        "princess123",
        "superman123",
        "master12345",
        "shadow12345",
        "michael12345",
    }
)


class PasswordPolicyError(ValueError):
    """口令不满足最小安全策略。"""


def _validate(password: object) -> None:
    if not isinstance(password, str):
        raise PasswordPolicyError("口令必须是文本")
    if len(password) < MIN_PASSWORD_LENGTH or len(password) > MAX_PASSWORD_LENGTH:
        raise PasswordPolicyError(f"口令长度必须在 {MIN_PASSWORD_LENGTH} 到 {MAX_PASSWORD_LENGTH} 之间")
    if any(ord(char) < 32 or ord(char) == 127 for char in password):
        raise PasswordPolicyError("口令不能包含控制字符")
    if password.isdigit():
        raise PasswordPolicyError("口令不能是纯数字")
    if len(set(password)) == 1:
        raise PasswordPolicyError("口令不能是重复的单一字符")
    if password.lower() in COMMON_PASSWORDS:
        raise PasswordPolicyError("口令过于常见，请更换")


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
