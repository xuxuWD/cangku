import base64
import hashlib
import hmac
import json

import pytest
from pydantic import ValidationError

from app.auth import create_access_token, verify_access_token
from app.domain import UserContext
from app.settings import Settings

SECRET = "s" * 40


def raw_token(payload: dict[str, object], secret: str = SECRET) -> str:
    encoded = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode()
    ).rstrip(b"=")
    signature = hmac.new(secret.encode(), encoded, hashlib.sha256).digest()
    return encoded.decode() + "." + base64.urlsafe_b64encode(signature).rstrip(b"=").decode()


def test_session_token_round_trips_identity() -> None:
    token = create_access_token(UserContext("t-1", "acct-1", "employee"), SECRET, ttl_seconds=900)

    context = verify_access_token(token, SECRET)

    assert (context.tenant_id, context.user_id, context.role) == ("t-1", "acct-1", "employee")


def test_expired_token_is_rejected() -> None:
    token = create_access_token(UserContext("t-1", "acct-1", "employee"), SECRET, ttl_seconds=-1)

    with pytest.raises(ValueError, match="登录凭证无效"):
        verify_access_token(token, SECRET)


def test_token_without_expiry_is_rejected() -> None:
    token = raw_token({"tenant_id": "t-1", "user_id": "acct-1", "role": "employee"})

    with pytest.raises(ValueError, match="登录凭证无效"):
        verify_access_token(token, SECRET)


def test_tampered_token_is_rejected() -> None:
    token = create_access_token(UserContext("t-1", "acct-1", "employee"), SECRET, ttl_seconds=900)

    with pytest.raises(ValueError, match="登录凭证无效"):
        verify_access_token(token + "tampered", SECRET)
    with pytest.raises(ValueError, match="登录凭证无效"):
        verify_access_token(token, "other-secret-value")


def test_session_ttl_default_and_bounds() -> None:
    assert Settings().session_ttl_seconds == 900

    with pytest.raises(ValidationError):
        Settings(session_ttl_seconds=10)
    with pytest.raises(ValidationError):
        Settings(session_ttl_seconds=99999)


def test_bootstrap_token_defaults_to_empty() -> None:
    assert Settings().bootstrap_token == ""
