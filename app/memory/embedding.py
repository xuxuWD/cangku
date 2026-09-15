"""Embedding 适配器：对接本地 Qwen3-Embedding-0.6B HTTP 服务（§2.5）。

独立进程 HTTP 边界，端口/地址走 `WORKBENCH_EMBEDDING_BASE_URL` 配置（外置，不进代码）。
复用 `runtime/adapters/common.py` 的 `HttpRuntimeTransport` 传输模式（httpx + TransportError 语义）。
embedding 失败**默认拒绝写入**（fail-closed，不静默降级为「无向量」入库，§2.5）：
任何调用失败抛 `EmbeddingUnavailable`（接口层 → 502/503）。
"""

from __future__ import annotations

import hashlib
from typing import Any

import httpx

from .models import EMBEDDING_DIMENSIONS


class EmbeddingUnavailable(LookupError):
    """Embedding 服务不可用 / 返回异常。502 语义；禁止把失败伪装成成功。"""


class EmbeddingAdapter:
    """通过约定的 HTTP 边界调用独立 embedding 服务（Qwen3-Embedding-0.6B 或同协议实现）。"""

    def __init__(
        self,
        base_url: str,
        timeout_seconds: float = 10.0,
        max_tokens: int = 8192,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.max_tokens = max_tokens
        self.client = client or httpx.Client(timeout=timeout_seconds)

    def embed(self, text: str) -> list[float]:
        """把文本编码为 1024 维向量。

        模型名由服务端解析（请求体不携带模型参数），不暴露给上层。
        fail-closed：非 2xx、JSON 解析失败、网络错误、维度不符 —— 一律抛 `EmbeddingUnavailable`。
        """
        try:
            response = self.client.post(
                f"{self.base_url}/v1/embeddings",
                json={"model": "", "input": [text]},
            )
            response.raise_for_status()
            payload = response.json()
            data = payload["data"][0]["embedding"]
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
            raise EmbeddingUnavailable(f"Embedding 服务调用失败: {exc}") from exc
        if not isinstance(data, list) or not all(isinstance(item, (int, float)) for item in data):
            raise EmbeddingUnavailable("Embedding 服务返回的向量格式无效")
        vector = [float(item) for item in data]
        if len(vector) != EMBEDDING_DIMENSIONS:
            raise EmbeddingUnavailable(
                f"Embedding 服务返回维度 {len(vector)}，期望 {EMBEDDING_DIMENSIONS}（fail-closed，拒绝写入）"
            )
        return vector

    def health(self) -> dict[str, Any]:
        """健康检查；非 2xx / 解析失败抛 `EmbeddingUnavailable`。"""
        try:
            response = self.client.get(f"{self.base_url}/health")
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise EmbeddingUnavailable(f"Embedding 健康检查失败: {exc}") from exc
        return {"status": "ok"}


class FakeEmbeddingAdapter:
    """测试 / 开发期用：确定性伪向量（长度 1024，由文本哈希填充）。

    确定性很重要：同一文本永远得到同一向量（供内存检索 / 幂等断言用）。
    """

    def __init__(self, dimensions: int = EMBEDDING_DIMENSIONS) -> None:
        self.dimensions = dimensions

    def embed(self, text: str) -> list[float]:
        """由 sha256(text) 派生确定性向量，值 ∈ [0,1)。"""
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        vector: list[float] = []
        while len(vector) < self.dimensions:
            vector.extend(byte / 256.0 for byte in digest)
            digest = hashlib.sha256(digest).digest()
        return vector[: self.dimensions]

    def health(self) -> dict[str, Any]:
        return {"status": "ok"}