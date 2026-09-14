"""预创建执行回调所需的**两条网桥**（**顺序处置**，规格 §3.3 / §8 U20 方案 b-1 / §8 U21 裁决「候选②」）。

**为什么要单独一个脚本**（顺序陷阱）：`app/tool_execution/executor.py::_ensure_internal_network`
只在**首次执行时按需建网**；而部署侧把网络声明为 `external: true`（边车 / 网关 / 工作台要挂上去）
⇒ 要求网络**预先存在**。若首个 turn 之前没人建网，边车 / 执行链路无网可用。

**两条网（§8 U21 拓扑）**：
    - `workbench-exec-internal`（`workbench-exec-internal`）：**只有**模型网关 + 执行回调边车 +
      执行容器挂这里；**工作台 app 容器不得加入**（否则把整套 API 面暴露给执行容器）。
    - `workbench-exec-callback`（回调网）：**只有** 边车 + 工作台 app 挂这里 —— 这是
      「边车 → 工作台」的受控出向路径；**执行容器绝不可达该网**。

两条网都以 `driver=bridge, internal=True` 创建（无外网出口）。语义与
`executor._ensure_internal_network` 同口径：
    - 不存在 → 以 `driver=bridge, internal=True` 创建（**无外网出口**）；
    - 已存在但 `internal=False` → **拒绝**（fail-closed，绝不静默复用非内网桥）。

用法：
    py scripts/ensure_exec_internal_network.py [--network workbench-exec-internal]
                                               [--callback-network workbench-exec-callback]

退出码：`0` = 两条网均就绪；`2` = 环境 / 配置错误（无 Docker、网络非内网）。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.tool_execution.executor import INTERNAL_NETWORK_NAME  # noqa: E402

# 回调网：只含「工作台 + 边车」（§8 U21 裁决）。**执行容器绝不可达**。
CALLBACK_NETWORK_NAME = "workbench-exec-callback"


def _ensure_network(client, network_name: str) -> str:
    """确保某条内网桥存在且 `internal=True`；返回一句可打印的结论。"""
    for network in client.networks.list(names=[network_name]):
        if network.name == network_name:
            internal = bool((network.attrs or {}).get("Internal", False))
            if not internal:
                raise SystemExit(
                    f"网络 {network_name} 已存在但 internal=False（非内网桥），拒绝复用（fail-closed）"
                )
            return f"网络 {network_name} 已存在且 internal=True（无需改动）"
    client.networks.create(network_name, driver="bridge", internal=True)
    return f"已创建内网桥 {network_name}（driver=bridge, internal=True）"


def ensure_internal_network(network_name: str) -> str:
    """确保**执行内网桥**存在且 `internal=True`（保留旧入口，语义不变）。"""
    client = _docker_client()
    return _ensure_network(client, network_name)


def ensure_callback_network(network_name: str) -> str:
    """确保**回调网**存在且 `internal=True`（只含「工作台 + 边车」）。"""
    client = _docker_client()
    return _ensure_network(client, network_name)


def ensure_networks(
    internal_name: str = INTERNAL_NETWORK_NAME,
    callback_name: str = CALLBACK_NETWORK_NAME,
) -> list[str]:
    """一次建好两条网（同一次 Docker 连接内），返回逐条结论。"""
    client = _docker_client()
    return [_ensure_network(client, internal_name), _ensure_network(client, callback_name)]


def _docker_client():
    try:
        import docker  # noqa: PLC0415 - 仅部署侧需要，失败即 fail-closed
    except ModuleNotFoundError as exc:
        raise SystemExit("未安装 Docker SDK（包名 docker），拒绝执行") from exc
    try:
        client = docker.from_env()
        client.ping()
    except Exception as exc:  # noqa: BLE001 - 守护进程不可用即拒绝
        raise SystemExit(f"Docker 守护进程不可用：{exc}") from exc
    return client


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="预创建执行内网桥 + 回调网（顺序处置）")
    parser.add_argument("--network", default=INTERNAL_NETWORK_NAME)
    parser.add_argument("--callback-network", default=CALLBACK_NETWORK_NAME)
    args = parser.parse_args(argv)
    for line in ensure_networks(args.network, args.callback_network):
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
