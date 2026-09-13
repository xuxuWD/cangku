"""模型网关的上游转发（规格 §3.5 P1 第 4 条）。

职责：**凭据注入 + 转发**（不改写模型语义）；**超时与重试上限显式配置**，
重试归口在本进程（容器内不重试 —— §F9.4 实测 `dsh-llm-retry` 会自行重试 5 次，
若两侧都重试会放大；故本转发器只按 `max_retries` 做**传输级**重试）。

只做传输级重试：连接失败 / 读超时才重试；**收到响应后绝不重试**（避免重复计费）。
"""

from __future__ import annotations

import http.client
import socket
import ssl
from dataclasses import dataclass, field
from typing import Mapping
from urllib.parse import urlparse


class UpstreamTransportError(RuntimeError):
    """上游传输失败（连接/读失败，且已达重试上限）。"""


class UpstreamTimeout(UpstreamTransportError):
    """上游超时（达重试上限后仍超时）。"""


@dataclass
class UpstreamResponse:
    """一次已建立的上游响应（调用方负责流式读取后 `close`）。"""

    status: int
    headers: list[tuple[str, str]]
    response: http.client.HTTPResponse
    connection: http.client.HTTPConnection
    attempts: int

    def read(self, size: int) -> bytes:
        return self.response.read(size)

    def close(self) -> None:
        try:
            self.response.close()
        finally:
            self.connection.close()

    def header(self, name: str) -> str | None:
        lowered = name.lower()
        for key, value in self.headers:
            if key.lower() == lowered:
                return value
        return None


def _normalize_base(base_url: str) -> tuple[str, str, int, str]:
    parsed = urlparse(base_url)
    scheme = parsed.scheme
    host = parsed.hostname or ""
    port = parsed.port or (443 if scheme == "https" else 80)
    base_path = (parsed.path or "").rstrip("/")
    return scheme, host, port, base_path


@dataclass
class UpstreamForwarder:
    """把容器内的 OpenAI 兼容请求透明转发到供应商上游。"""

    base_url: str
    api_key: str
    timeout_seconds: float = 60.0
    max_retries: int = 0
    _scheme: str = field(init=False, default="https")
    _host: str = field(init=False, default="")
    _port: int = field(init=False, default=443)
    _base_path: str = field(init=False, default="")

    def __post_init__(self) -> None:
        scheme, host, port, base_path = _normalize_base(self.base_url)
        self._scheme = scheme or "https"
        self._host = host
        self._port = port
        self._base_path = base_path

    def _connect(self) -> http.client.HTTPConnection:
        if self._scheme == "https":
            return http.client.HTTPSConnection(
                self._host, self._port, timeout=self.timeout_seconds, context=ssl.create_default_context()
            )
        return http.client.HTTPConnection(self._host, self._port, timeout=self.timeout_seconds)

    def request(
        self,
        method: str,
        path: str,
        headers: Mapping[str, str],
        body: bytes,
    ) -> UpstreamResponse:
        """转发一次请求；传输级失败按 `max_retries` 重试后仍失败则抛出。"""
        target = f"{self._base_path}{path}" or path
        # 凭据注入是网关的**唯一权威**：先剔除容器侧带来的任何鉴权头，再写入供应商密钥。
        out_headers = {
            key: value for key, value in headers.items() if key.lower() != "authorization"
        }
        out_headers["authorization"] = f"Bearer {self.api_key}"
        out_headers["host"] = self._host if self._port in (80, 443) else f"{self._host}:{self._port}"
        out_headers["content-length"] = str(len(body))
        attempts = 0
        last_error: Exception | None = None
        while attempts <= self.max_retries:
            attempts += 1
            connection = self._connect()
            try:
                connection.request(method, target, body=body, headers=out_headers)
                response = connection.getresponse()
            except (socket.timeout, TimeoutError) as exc:
                last_error = UpstreamTimeout(str(exc))
                connection.close()
                continue
            except (OSError, http.client.HTTPException) as exc:
                last_error = UpstreamTransportError(str(exc))
                connection.close()
                continue
            return UpstreamResponse(
                status=response.status,
                headers=response.getheaders(),
                response=response,
                connection=connection,
                attempts=attempts,
            )
        raise last_error if last_error is not None else UpstreamTransportError("上游请求失败")
