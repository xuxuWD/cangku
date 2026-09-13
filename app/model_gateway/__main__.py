"""网关进程入口：`python -m app.model_gateway`。

只读环境变量（值一律由部署密钥系统注入，**本进程不回显密钥**）：

    WORKBENCH_MODEL_GATEWAY_UPSTREAM_BASE_URL       上游供应商端点（只在网关侧出现）
    WORKBENCH_MODEL_GATEWAY_UPSTREAM_API_KEY        供应商密钥（只在网关侧；缺失则透传必 401）
    WORKBENCH_MODEL_GATEWAY_MINT_SECRET             控制面密钥（必填；缺失拒绝启动）
    WORKBENCH_MODEL_GATEWAY_HOST                    监听地址（默认 0.0.0.0）
    WORKBENCH_MODEL_GATEWAY_PORT                    监听端口（默认 8080）
    WORKBENCH_MODEL_GATEWAY_TOKEN_TTL_SECONDS       短期令牌有效期（默认 300）
    WORKBENCH_MODEL_GATEWAY_UPSTREAM_TIMEOUT_SECONDS 上游超时秒（默认 60）
    WORKBENCH_MODEL_GATEWAY_MAX_RETRIES             传输级重试上限（默认 0，fail-closed）
    WORKBENCH_MODEL_GATEWAY_ORPHAN_TOKEN_LIMIT      孤儿令牌上限（默认 64）
    WORKBENCH_MODEL_GATEWAY_RATE_LIMIT_PER_MINUTE   每令牌每分钟上限（默认 600，0=关闭）
"""

from __future__ import annotations

import logging
import signal
import sys

from .config import GatewayConfigError, ModelGatewayConfig
from .server import LOGGER_NAME, ModelGateway, ModelGatewayServer


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stdout,
    )
    logger = logging.getLogger(LOGGER_NAME)
    try:
        config = ModelGatewayConfig.from_env()
    except GatewayConfigError as exc:
        logger.error("网关拒绝启动：%s", exc)
        return 2
    server = ModelGatewayServer(ModelGateway(config))

    def _stop(_signum: int, _frame: object) -> None:
        logger.info("网关收到终止信号，正在退出")
        server.stop()

    for name in ("SIGTERM", "SIGINT"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), _stop)
    try:
        server.start()
    except KeyboardInterrupt:  # pragma: no cover - 交互式中断
        server.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
