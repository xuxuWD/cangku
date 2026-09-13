"""模型网关（段二交付项 F / 规格 §3.5 P1「路径① 自建模型网关」）。

**独立进程、跑在容器外**：供应商密钥只在网关；执行容器内只注入**短期网关令牌**。
本包只依赖 Python 标准库（网关镜像不装第三方依赖，缩小可信计算基）。
"""

from .config import GatewayConfigError, ModelGatewayConfig
from .server import (
    FixedWindowRateLimiter,
    Metering,
    ModelGateway,
    ModelGatewayServer,
    start_in_thread,
)
from .tokens import OrphanTokenLimitExceeded, TokenRecord, TokenStore
from .upstream import UpstreamForwarder, UpstreamResponse, UpstreamTimeout, UpstreamTransportError

__all__ = [
    "GatewayConfigError",
    "ModelGatewayConfig",
    "FixedWindowRateLimiter",
    "Metering",
    "ModelGateway",
    "ModelGatewayServer",
    "start_in_thread",
    "OrphanTokenLimitExceeded",
    "TokenRecord",
    "TokenStore",
    "UpstreamForwarder",
    "UpstreamResponse",
    "UpstreamTimeout",
    "UpstreamTransportError",
]
