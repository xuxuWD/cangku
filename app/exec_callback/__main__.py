"""边车进程入口：`python -m app.exec_callback`（规格 §3.5 P1 第 3 条 ②④ / §8 U21 裁决路线）。

**只读环境变量**（值一律由部署配置注入；本进程**不回显任何密钥 / 令牌**）：

    WORKBENCH_EXEC_CALLBACK_FORWARD_URL             边车 → 工作台的受控出向调用目标（**必填**；缺失拒绝启动）
    WORKBENCH_EXEC_CALLBACK_SHARED_SECRET           「边车 → 工作台」预共享密钥（**必填**；缺失拒绝启动）
    WORKBENCH_EXEC_CALLBACK_LISTEN_HOST             边车唯一监听地址（默认 0.0.0.0）
    WORKBENCH_EXEC_CALLBACK_LISTEN_PORT             边车唯一监听端口（默认 8081）
    WORKBENCH_EXEC_CALLBACK_FORWARD_TIMEOUT_SECONDS 转发超时秒（默认 10）

⚠️ **网络成员事实**（隔离的真正依据）：本进程**双宿** `workbench-exec-internal` + 回调网；
**不得**加入工作台默认网络，**不得**把工作台 app 容器接入 `workbench-exec-internal`。
⚠️ 边车**无状态纯转发**：不持有判定所需的权威状态（令牌自持绑定 / 当前执行登记表），
②④ 判定在工作台接收端点（`app/tool_execution/callback_guard.py`）。
"""

from __future__ import annotations

import logging
import signal
import sys

from .config import ExecCallbackConfig, ExecCallbackConfigError
from .server import LOGGER_NAME, ExecCallbackServer, build_plane


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stdout,
    )
    logger = logging.getLogger(LOGGER_NAME)
    try:
        config = ExecCallbackConfig.from_env()
    except ExecCallbackConfigError as exc:
        logger.error("边车拒绝启动：%s", exc)
        return 2
    plane = build_plane(
        forward_url=config.forward_url,
        shared_secret=config.shared_secret,
        forward_timeout_seconds=config.forward_timeout_seconds,
    )
    server = ExecCallbackServer(plane, host=config.listen_host, port=config.listen_port)

    def _stop(_signum: int, _frame: object) -> None:
        logger.info("边车收到终止信号，正在退出")
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
