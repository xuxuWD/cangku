from __future__ import annotations

import re
from typing import TYPE_CHECKING, Callable, Protocol

import httpx

if TYPE_CHECKING:
    from .dead_letters import DeadLetter


class NotificationChannel(Protocol):
    name: str

    def send(self, payload: dict[str, object]) -> None: ...


Transport = Callable[..., object]
"""可注入的 HTTP 传输层，签名与 `httpx.post` 一致：`(url, *, json, timeout)`。"""


class WebhookNotificationChannel:
    """把脱敏载荷以 JSON POST 到配置的 Webhook 地址。"""

    def __init__(
        self,
        url: str,
        *,
        timeout_seconds: float = 5.0,
        transport: Transport | None = None,
        name: str = "webhook",
    ) -> None:
        if not url:
            raise ValueError("死信通知 Webhook 地址不能为空")
        self.url = url
        self.timeout_seconds = timeout_seconds
        self.name = name
        self._transport = transport

    def send(self, payload: dict[str, object]) -> None:
        self._http_post(self.url, payload, self.timeout_seconds, self._transport)

    @staticmethod
    def _http_post(
        url: str,
        payload: dict[str, object],
        timeout_seconds: float,
        transport: Transport | None = None,
    ) -> None:
        if transport is not None:
            response = transport(url, json=payload, timeout=timeout_seconds)
        else:
            response = httpx.post(url, json=payload, timeout=timeout_seconds)
        response.raise_for_status()


_CREDENTIAL_IN_URL = re.compile(r"://[^/@\s]+@")


class DeadLetterNotifier:
    """组装不含事件 payload、含凭证清理的死信通知载荷，并交给渠道发送。"""

    def __init__(self, channel: NotificationChannel) -> None:
        self.channel = channel

    @property
    def channel_name(self) -> str:
        return self.channel.name

    def notify(self, dead_letter: DeadLetter) -> None:
        self.channel.send(self._payload(dead_letter))

    @staticmethod
    def _payload(dead_letter: DeadLetter) -> dict[str, object]:
        event = dead_letter.event
        return {
            "kind": "dead_letter",
            "event_id": event.event_id,
            "tenant_id": event.tenant_id,
            "action": event.action,
            "aggregate_type": event.aggregate_type,
            "aggregate_id": event.aggregate_id,
            "attempts": dead_letter.attempts,
            "error": _redact_error(dead_letter.error),
            "occurred_at": event.occurred_at.isoformat(),
        }


def _redact_error(error: str) -> str:
    """清理 userinfo 凭证后截断到 200 字符；绝不回传事件 payload。"""
    return _CREDENTIAL_IN_URL.sub("://***@", error)[:200]
