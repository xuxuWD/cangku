from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime


class TokenInvalid(ValueError):
    pass


@dataclass(frozen=True)
class ShortLivedGrant:
    token: str

    @classmethod
    def issue(cls, secret: str, run_id: str, task_id: str, device_id: str, actions: tuple[str, ...], expires_at: datetime) -> ShortLivedGrant:
        payload = {"run_id": run_id, "task_id": task_id, "device_id": device_id, "actions": list(actions), "expires_at": expires_at.isoformat()}
        encoded = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()).decode().rstrip("=")
        signature = hmac.new(secret.encode(), encoded.encode(), hashlib.sha256).hexdigest()
        return cls(f"{encoded}.{signature}")

    @classmethod
    def verify(cls, secret: str, token: str, run_id: str, task_id: str, device_id: str, action: str) -> bool:
        try:
            encoded, signature = token.split(".", 1)
            expected = hmac.new(secret.encode(), encoded.encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(signature, expected):
                raise TokenInvalid("授权签名无效")
            padding = "=" * (-len(encoded) % 4)
            payload = json.loads(base64.urlsafe_b64decode(encoded + padding))
            expires_at = datetime.fromisoformat(payload["expires_at"])
            if datetime.now(expires_at.tzinfo) >= expires_at:
                raise TokenInvalid("授权已过期")
            if payload.get("run_id") != run_id or payload.get("task_id") != task_id or payload.get("device_id") != device_id:
                raise TokenInvalid("授权绑定不匹配")
            if action not in payload.get("actions", []):
                raise TokenInvalid("动作不在授权范围内")
            return True
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            if isinstance(exc, TokenInvalid):
                raise
            raise TokenInvalid("授权令牌无效") from exc
