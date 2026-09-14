"""执行回调边车（规格 §3.5 P1 第 3 条 ②④ / §8 U20 方案 b-1）。

**为什么单列一个包、而不放进 `app/tool_execution/`**：边车是一个**独立进程**，
其暴露面（**只监听一个端口、只挂 `workbench-exec-internal`**）必须与工作台 app 进程
（默认网络、整套 API 面）**物理隔离**——若把回调监听器放进 app 进程，等于把工作台
整个 API 面放到执行容器可达的网络上（门禁 §B14 与评审已明确禁止）。这与
`app/model_gateway/`（另一个「跑在容器外的受控进程」）同构：**独立包 + 标准库实现**。

职责边界（口径，不得越界）：
    - **②④ 绑定强制判定** ＝ **工作台控制面**（工作台侧自持绑定 + `constant-time` 比对），
      由本边车在**服务端权威上下文**中完成（`expected` 绝不取自请求体）；
    - 边车**只做判定 + 受控转发**：判定之后经「边车 → 工作台」的**受控出向调用**交回工作台；
      **不得**在边车里改写回调用途 / 语义（不新增审计动作码、不动迁移）。
"""

from .config import ExecCallbackConfig, ExecCallbackConfigError
from .registry import ActiveExecutionRegistry
from .server import (
    CALLBACK_PATH,
    CallbackOutcome,
    ExecCallbackPlane,
    ExecCallbackServer,
    WorkbenchForwarder,
    build_plane,
    start_in_thread,
)

__all__ = [
    "ActiveExecutionRegistry",
    "CALLBACK_PATH",
    "CallbackOutcome",
    "ExecCallbackConfig",
    "ExecCallbackConfigError",
    "ExecCallbackPlane",
    "ExecCallbackServer",
    "WorkbenchForwarder",
    "build_plane",
    "start_in_thread",
]
