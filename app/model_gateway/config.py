"""模型网关进程配置（规格 §3.5 P1 / §4 的「路径① 网关六项」）。

网关是**独立进程、跑在容器外**，故配置从**进程环境变量**读取（不依赖 `app.settings` /
pydantic —— 网关镜像里除标准库外**不装任何依赖**，以缩小可信计算基）。

环境变量名与 §4 的 `WORKBENCH_MODEL_GATEWAY_*` 同一套；额外两项（控制面密钥 / 孤儿令牌上限）
为 §3.5 P1 第 3 条落地所必需，`值一律由部署密钥系统注入`。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping
from urllib.parse import urlparse

ENV_PREFIX = "WORKBENCH_MODEL_GATEWAY_"

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8080
DEFAULT_TOKEN_TTL_SECONDS = 300
DEFAULT_UPSTREAM_TIMEOUT_SECONDS = 60.0
DEFAULT_MAX_RETRIES = 0
DEFAULT_ORPHAN_TOKEN_LIMIT = 64
DEFAULT_RATE_LIMIT_PER_MINUTE = 600


class GatewayConfigError(ValueError):
    """网关装配期配置错误（fail-closed）：拒绝启动并告警。"""


def _text(env: Mapping[str, str], name: str, default: str = "") -> str:
    value = env.get(ENV_PREFIX + name, default)
    return value.strip() if isinstance(value, str) else default


def _number(env: Mapping[str, str], name: str, default, cast):
    raw = env.get(ENV_PREFIX + name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return cast(str(raw).strip())
    except (TypeError, ValueError) as exc:
        raise GatewayConfigError(f"{ENV_PREFIX}{name} 取值非法") from exc


@dataclass(frozen=True)
class ModelGatewayConfig:
    """网关运行参数（不可变；值来源见 `from_env`）。"""

    upstream_base_url: str
    upstream_api_key: str
    mint_secret: str
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    token_ttl_seconds: int = DEFAULT_TOKEN_TTL_SECONDS
    upstream_timeout_seconds: float = DEFAULT_UPSTREAM_TIMEOUT_SECONDS
    max_retries: int = DEFAULT_MAX_RETRIES
    orphan_token_limit: int = DEFAULT_ORPHAN_TOKEN_LIMIT
    rate_limit_per_minute: int = DEFAULT_RATE_LIMIT_PER_MINUTE

    def __post_init__(self) -> None:
        parsed = urlparse(self.upstream_base_url or "")
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise GatewayConfigError(
                "未配置合法的上游供应商端点（WORKBENCH_MODEL_GATEWAY_UPSTREAM_BASE_URL），拒绝启动网关"
            )
        if not self.mint_secret:
            raise GatewayConfigError(
                "未配置网关控制面密钥（WORKBENCH_MODEL_GATEWAY_MINT_SECRET），拒绝启动网关"
            )
        if self.token_ttl_seconds < 1:
            raise GatewayConfigError("令牌有效期必须为正整数")
        if self.upstream_timeout_seconds <= 0:
            raise GatewayConfigError("上游超时必须为正数")
        if self.max_retries < 0:
            raise GatewayConfigError("重试上限必须为非负整数")
        if self.orphan_token_limit < 0:
            raise GatewayConfigError("孤儿令牌上限必须为非负整数")

    @property
    def has_upstream_key(self) -> bool:
        """只暴露「密钥是否存在」这一布尔，**不回显密钥本身**（启动行据此打印）。"""
        return bool(self.upstream_api_key)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "ModelGatewayConfig":
        source = os.environ if env is None else env
        return cls(
            upstream_base_url=_text(source, "UPSTREAM_BASE_URL"),
            upstream_api_key=_text(source, "UPSTREAM_API_KEY"),
            mint_secret=_text(source, "MINT_SECRET"),
            host=_text(source, "HOST", DEFAULT_HOST) or DEFAULT_HOST,
            port=_number(source, "PORT", DEFAULT_PORT, int),
            token_ttl_seconds=_number(source, "TOKEN_TTL_SECONDS", DEFAULT_TOKEN_TTL_SECONDS, int),
            upstream_timeout_seconds=_number(
                source, "UPSTREAM_TIMEOUT_SECONDS", DEFAULT_UPSTREAM_TIMEOUT_SECONDS, float
            ),
            max_retries=_number(source, "MAX_RETRIES", DEFAULT_MAX_RETRIES, int),
            orphan_token_limit=_number(
                source, "ORPHAN_TOKEN_LIMIT", DEFAULT_ORPHAN_TOKEN_LIMIT, int
            ),
            rate_limit_per_minute=_number(
                source, "RATE_LIMIT_PER_MINUTE", DEFAULT_RATE_LIMIT_PER_MINUTE, int
            ),
        )
