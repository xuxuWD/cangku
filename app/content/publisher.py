from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

import httpx


class PublicationNotConfigured(ValueError):
    """未配置发布渠道时发布功能关闭（fail-closed）。"""


class PublicationFailed(RuntimeError):
    """发布或回执核对失败；调用方必须转入人工接管，绝不自动重发。"""


@dataclass(frozen=True)
class PublicationReceipt:
    receipt_id: str
    status: str
    published_at: datetime
    detail: dict | None = None


class Publisher(Protocol):
    name: str

    def publish(
        self, *, title: str, content: str, idempotency_key: str
    ) -> PublicationReceipt: ...

    def verify(self, receipt_id: str) -> str: ...


PublisherTransport = Callable[..., Any]


def _default_transport(
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    json: dict[str, str] | None,
    timeout: float,
):
    """默认传输层：真实 HTTP 调用；非 2xx 由 raise_for_status 抛出。"""
    if method == "POST":
        response = httpx.post(url, headers=headers, json=json, timeout=timeout)
    else:
        response = httpx.get(url, headers=headers, timeout=timeout)
    response.raise_for_status()
    return response


class WechatMpPublisher:
    """微信公众号发布器：一次调用一次落回执，失败即人工接管，不自动重发。"""

    def __init__(
        self,
        endpoint: str,
        account_id: str,
        access_token: str,
        *,
        timeout_seconds: float,
        transport: PublisherTransport | None = None,
        name: str = "wechat_mp",
    ) -> None:
        if not endpoint or not endpoint.strip():
            raise ValueError("发布端点不能为空")
        if not account_id or not account_id.strip():
            raise ValueError("发布账号不能为空")
        if not access_token or not access_token.strip():
            raise ValueError("发布访问令牌不能为空")
        self.endpoint = endpoint.rstrip("/")
        self.account_id = account_id
        self.access_token = access_token
        self.timeout_seconds = timeout_seconds
        self.name = name
        self._transport = transport or _default_transport

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

    def publish(
        self, *, title: str, content: str, idempotency_key: str
    ) -> PublicationReceipt:
        payload = {
            "title": title,
            "content": content,
            "idempotency_key": idempotency_key,
            "account_id": self.account_id,
        }
        url = f"{self.endpoint}/publish"
        try:
            response = self._transport(
                "POST", url, headers=self._headers(), json=payload, timeout=self.timeout_seconds
            )
        except Exception as exc:  # noqa: BLE001 - 传输层任何异常都视为发布失败
            raise PublicationFailed("发布请求失败") from exc
        status_code = getattr(response, "status_code", 200)
        if not 200 <= int(status_code) < 300:
            raise PublicationFailed("发布接口返回非 2xx 状态码")
        try:
            data = response.json()
        except Exception as exc:  # noqa: BLE001 - 响应不可解析同样判定失败
            raise PublicationFailed("发布响应无法解析") from exc
        receipt_id = str(data.get("receipt_id") or "").strip() if isinstance(data, dict) else ""
        if not receipt_id:
            raise PublicationFailed("发布响应缺少回执号")
        status = str(data.get("status") or "succeeded")
        return PublicationReceipt(
            receipt_id=receipt_id,
            status=status,
            published_at=datetime.now(UTC),
            detail=dict(data) if isinstance(data, dict) else None,
        )

    def verify(self, receipt_id: str) -> str:
        url = f"{self.endpoint}/publish/{receipt_id}"
        try:
            response = self._transport(
                "GET", url, headers=self._headers(), json=None, timeout=self.timeout_seconds
            )
        except Exception as exc:  # noqa: BLE001 - 传输层任何异常都视为核对失败
            raise PublicationFailed("回执核对请求失败") from exc
        status_code = getattr(response, "status_code", 200)
        if not 200 <= int(status_code) < 300:
            raise PublicationFailed("回执核对接口返回非 2xx 状态码")
        try:
            data = response.json()
        except Exception as exc:  # noqa: BLE001 - 响应不可解析同样判定失败
            raise PublicationFailed("回执核对响应无法解析") from exc
        status = str(data.get("status") or "").strip() if isinstance(data, dict) else ""
        if not status:
            raise PublicationFailed("回执核对响应缺少状态")
        return status
