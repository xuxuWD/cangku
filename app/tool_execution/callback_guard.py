"""工作台侧「执行回调接收」的 ②④ 判定与限流（规格 §3.5 P1 第 3 条 / §8 U21 裁决「候选②」）。

**为什么判定落在这里、而不在边车**（2026-09-14 用户裁决「候选②：边车纯转发 + 判定回工作台」）：
    边车是**独立进程**，此前它自行持有 `TokenBindingStore` /「当前执行」登记表来判定 ⇒ 与
    「签发令牌的工作台进程」是**两个进程**，权威状态不共享（§8 U21 的缺口）。候选② 的处置是
    让边车**退化为无状态纯转发**（容器 → 边车 → 工作台），把 ②④ 判定**回到工作台的权威状态处**：
      - `expected` **从工作台权威状态重建**（`ActiveExecutionRegistry` 的「会话当前代次」），
        **绝不取自请求体**；
      - 与令牌自持绑定（`TokenBindingStore`，mint 时落）做 `constant-time` 比对；
      - 不匹配 / 跨租户 / 旧代次 / 未知令牌 → `403`（**不泄露存在性**，文案固定）并记审计
        （复用既有动作码 `tool.blocked`，**不新增动作码**）。

**边界**：本模块是**工作台进程内**的组件；边车**不得**导入 / 复刻这里的任何判定逻辑
（`tests/test_exec_callback.py` 有静态断言守住这一点）。
"""

from __future__ import annotations

import hmac
import time
from threading import RLock
from typing import Callable

from .active_execution import ActiveExecutionRegistry
from .token_binding import ControlPlaneBindingVerifier, TokenBinding, TokenBindingStore

# 必不匹配的占位绑定：会话无活动执行时，用它把请求引到 `verify` 的统一拒绝路径
# （恒定时间比对 + 审计），避免绕开审计。`generation=0` 与「从 1 开始」的合法代次天然不撞。
_NO_ACTIVE_EXECUTION = "__no_active_execution__"


def shared_secret_matches(configured: str, provided: str | None) -> bool:
    """恒时比对「边车 → 工作台」的预共享密钥（对称）。**缺失即拒**（fail-closed）。"""
    if not configured or not provided:
        return False
    return hmac.compare_digest(str(configured), str(provided))


class WorkbenchCallbackGuard:
    """工作台侧 ②④ 判定：从权威状态重建 `expected` 并恒时比对。"""

    def __init__(
        self,
        *,
        store: TokenBindingStore,
        registry: ActiveExecutionRegistry,
        audit=None,
    ) -> None:
        self.store = store
        self.registry = registry
        self.verifier = ControlPlaneBindingVerifier(store=store, audit=audit)

    def authorize(
        self,
        *,
        token: str,
        session_id: str = "",
        run_id: str | None = None,
        tool_key: str | None = None,
    ) -> TokenBinding:
        """校验通过返回绑定；否则抛 `BindingDenied`（`403`，不泄露存在性）并记审计。

        `session_id` 只是到 `ActiveExecutionRegistry` 的**查找键**；被比对的三元组一律取自
        权威登记表（`expected`），**不读请求体里的任何绑定声明**。
        """
        expected = self.registry.current_for(session_id)
        if expected is None:
            expected = TokenBinding(_NO_ACTIVE_EXECUTION, session_id or _NO_ACTIVE_EXECUTION, 0)
        return self.verifier.verify(
            token=token,
            expected=expected,
            run_id=run_id,
            tool_key=tool_key,
        )


class CallbackRateLimiter:
    """令牌桶限流（默认 `100` rps）。

    口径取舍（§8 U21 裁决「限流 = 100 rps，超限 429」）：以**均衡速率 100 rps** 实现，
    容量（突发）取 `100`（≈ 1 秒的额度）——即允许短时突发 100 个请求、长期均值 100 rps。
    本限流是**进程内**的；多副本部署下是「每副本 100 rps」而非全局 100 rps（**未验证项**）。
    """

    def __init__(
        self,
        *,
        rate_per_second: float = 100.0,
        capacity: float | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if rate_per_second <= 0:
            raise ValueError("限流速率必须为正")
        self.rate_per_second = float(rate_per_second)
        self.capacity = float(capacity if capacity is not None else rate_per_second)
        self._tokens = self.capacity
        self._updated = clock()
        self._clock = clock
        self._lock = RLock()

    def allow(self) -> bool:
        """消耗一个令牌；有则放行，无则 `False`（调用方回 `429`）。"""
        with self._lock:
            now = self._clock()
            elapsed = max(0.0, now - self._updated)
            self._tokens = min(self.capacity, self._tokens + elapsed * self.rate_per_second)
            self._updated = now
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return True
            return False
