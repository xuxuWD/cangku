"""预创建 `workbench-exec-internal` 内网桥（**顺序处置**，规格 §3.3 / §8 U20 方案 b-1）。

**为什么要单独一个脚本**（顺序陷阱）：`app/tool_execution/executor.py::_ensure_internal_network`
只在**首次执行时按需建网**；而部署侧把该网络声明为 `external: true`（边车 / 网关要挂上去）
⇒ 要求网络**预先存在**。若首个 turn 之前没人建网，边车/执行链路无网可用。

本脚本把「确保存在」提前到部署步骤，语义与 `executor._ensure_internal_network` **逐字同口径**：
    - 不存在 → 以 `driver=bridge, internal=True` 创建（**无外网出口**）；
    - 已存在但 `internal=False` → **拒绝**（fail-closed，绝不静默复用非内网桥）。

用法：
    py scripts/ensure_exec_internal_network.py [--network workbench-exec-internal]

退出码：`0` = 网络就绪；`2` = 环境 / 配置错误（无 Docker、网络非内网）。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.tool_execution.executor import INTERNAL_NETWORK_NAME  # noqa: E402


def ensure_internal_network(network_name: str) -> str:
    """确保内网桥存在且 `internal=True`；返回一句可打印的结论。"""
    try:
        import docker  # noqa: PLC0415 - 仅部署侧需要，失败即 fail-closed
    except ModuleNotFoundError as exc:
        raise SystemExit("未安装 Docker SDK（包名 docker），拒绝执行") from exc
    try:
        client = docker.from_env()
        client.ping()
    except Exception as exc:  # noqa: BLE001 - 守护进程不可用即拒绝
        raise SystemExit(f"Docker 守护进程不可用：{exc}") from exc

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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="预创建执行内网桥（顺序处置）")
    parser.add_argument("--network", default=INTERNAL_NETWORK_NAME)
    args = parser.parse_args(argv)
    print(ensure_internal_network(args.network))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
