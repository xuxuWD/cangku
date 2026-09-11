from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from .domain import UserContext

FULL_SCOPE = "full"
TOTP_ENROLLMENT_SCOPE = "totp_enrollment"
SSO_PENDING_SCOPE = "sso_pending"


def create_access_token(context: UserContext, secret: str, *, ttl_seconds: int) -> str:
    """签发带过期时间的会话令牌；TTL 由调用方传入，本模块不读取配置。"""
    if not secret:
        raise ValueError("认证密钥不能为空")
    issued_at = datetime.now(UTC)
    payload = json.dumps(
        {
            "tenant_id": context.tenant_id,
            "user_id": context.user_id,
            "role": context.role,
            "scope": context.scope,
            "iat": int(issued_at.timestamp()),
            "exp": int((issued_at + timedelta(seconds=ttl_seconds)).timestamp()),
            "jti": uuid4().hex,
        },
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
        expires_at = data["exp"]
        if not isinstance(expires_at, int) or isinstance(expires_at, bool):
            raise ValueError("缺少过期时间")
        if datetime.now(UTC).timestamp() >= expires_at:
            raise ValueError("登录凭证已过期")
        raw_scope = data.get("scope")
        scope = raw_scope if isinstance(raw_scope, str) else FULL_SCOPE
        return UserContext(
            tenant_id=str(data["tenant_id"]),
            user_id=str(data["user_id"]),
            role=str(data["role"]),
            scope=scope,
        )
    except (KeyError, ValueError, TypeError, binascii.Error, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("登录凭证无效") from exc
