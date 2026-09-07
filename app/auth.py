from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json

from .domain import UserContext


def create_access_token(context: UserContext, secret: str) -> str:
    if not secret:
        raise ValueError("认证密钥不能为空")
    payload = json.dumps(
        {"tenant_id": context.tenant_id, "user_id": context.user_id, "role": context.role},
        separators=(",", ":"),
    ).encode()
    encoded = base64.urlsafe_b64encode(payload).rstrip(b"=")
    signature = hmac.new(secret.encode(), encoded, hashlib.sha256).digest()
    return encoded.decode() + "." + base64.urlsafe_b64encode(signature).rstrip(b"=").decode()


def verify_access_token(token: str, secret: str) -> UserContext:
    try:
        encoded, supplied_signature = token.split(".", 1)
        expected = hmac.new(secret.encode(), encoded.encode(), hashlib.sha256).digest()
        actual = base64.urlsafe_b64decode(supplied_signature + "=" * (-len(supplied_signature) % 4))
        if not hmac.compare_digest(expected, actual):
            raise ValueError("签名无效")
        payload = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        data = json.loads(payload)
        return UserContext(
            tenant_id=str(data["tenant_id"]),
            user_id=str(data["user_id"]),
            role=str(data["role"]),
        )
    except (KeyError, ValueError, TypeError, binascii.Error, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("登录凭证无效") from exc
