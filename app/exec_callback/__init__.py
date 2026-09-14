"""执行回调边车（规格 §3.5 P1 第 3 条 ②④ / §8 U20 方案 b-1 / §8 U21 裁决路线）。

**为什么单列一个包、而不放进 `app/tool_execution/`**：边车是一个**独立进程**，
其暴露面（**只监听一个端口、双宿 `workbench-exec-internal` + 回调网**）必须与工作台 app 进程
（默认网络 + 回调网、整套 API 面）**物理隔离**——若把回调监听器放进 app 进程，等于把工作台
整个 API 面放到执行容器可达的网络上（门禁 §B14 与评审已明确禁止）。这与
`app/model_gateway/`（另一个「跑在容器外的受控进程」）同构：**独立包 + 标准库实现**。

职责边界（口径，不得越界）：
    - **边车 = 无状态纯转发**（2026-09-14 返工，§8 U21 裁决「候选②」）：收到回调后**原样转发**
      到工作台接收端点，随行附带**预共享密钥**；**不做任何判定** —— 不持有 `TokenBindingStore` /
      「当前执行」登记表，不比对令牌 / 绑定（判定所需的权威状态都在工作台进程内）。
    - **②④ 绑定强制判定 = 工作台**（`app/tool_execution/callback_guard.py`）：`expected` 从
      **工作台权威状态**重建（**绝不取自请求体**），与令牌自持绑定做 `constant-time` 比对；
      不匹配 / 跨租户 / 旧代次 / 未知令牌 → `403`（不泄露存在性）+ 记审计（复用既有动作码）。
"""

from .config import ExecCallbackConfig, ExecCallbackConfigError
from .server import (
    CALLBACK_PATH,
    SHARED_SECRET_HEADER,
    CallbackOutcome,
    ExecCallbackPlane,
    ExecCallbackServer,
    WorkbenchForwarder,
    build_plane,
    start_in_thread,
)

__all__ = [
    "CALLBACK_PATH",
    "SHARED_SECRET_HEADER",
    "CallbackOutcome",
    "ExecCallbackConfig",
    "ExecCallbackConfigError",
    "ExecCallbackPlane",
    "ExecCallbackServer",
    "WorkbenchForwarder",
    "build_plane",
    "start_in_thread",
]
