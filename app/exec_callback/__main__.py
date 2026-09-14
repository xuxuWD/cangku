"""边车进程入口：`python -m app.exec_callback`（规格 §3.5 P1 第 3 条 ②④ / §8 U20 方案 b-1）。

**只读环境变量**（值一律由部署配置注入；本进程**不回显任何密钥 / 令牌**）：

    WORKBENCH_EXEC_CALLBACK_FORWARD_URL        边车 → 工作台的受控出向调用目标（**必填**；缺失拒绝启动）
    WORKBENCH_EXEC_CALLBACK_LISTEN_HOST        边车唯一监听地址（默认 0.0.0.0）
    WORKBENCH_EXEC_CALLBACK_LISTEN_PORT        边车唯一监听端口（默认 8081）
    WORKBENCH_EXEC_CALLBACK_FORWARD_TIMEOUT_SECONDS  转发超时秒（默认 10）

⚠️ **网络成员事实**（隔离的真正依据）：本进程对外可达性由「只挂 `workbench-exec-internal`」
限定；**不得**把它双宿到工作台默认网络，也**不得**把工作台 app 容器接入该网络。
⚠️ **未接线残留**：本入口只起「一个端口 + 一个端点」的判定 / 转发面；**权威绑定与
当前执行登记**须由工作台控制面经受控通道注入（本次未实现跨进程同步 ⇒ 见交付报告「未验证项」）。
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
