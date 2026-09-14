"""**工作台**权威的「当前执行」登记表（规格 §3.5 P1 第 3 条：②④ 的 `expected` 来源）。

口径（2026-09-13 用户裁决，定死）：
    - `generation`（代次）＝ **会话内 turn 序号**：**单调递增整数、从 1 开始、每铸一次令牌 +1**；
    - ②④ 的 `expected` **一律从服务端权威上下文重建**，**绝不取自请求体**——本登记表就是
      这份「服务端权威上下文」：由**工作台控制面**在每次进入新 turn 时登记，回调到达时按
      会话读取「当前执行」的绑定 `(tenant_id, session_id, generation)` 作为 `expected`。

**这不是第二事实源**：令牌的真伪 / 自持绑定仍以 `TokenBindingStore`（mint 时落）为准；
本表只回答「该会话**当前**是第几代」，用于把**旧代次 / 跨租户**的令牌判掉。

**落点（2026-09-14 返工，§8 U21 裁决「候选②」）**：本表归**工作台控制面**所有——
边车已退化为**无状态纯转发**（不再持有本表），②④ 判定一并回到工作台接收端点
（`app/tool_execution/callback_guard.py`）。⇒ 原「跨进程同步」缺口**由架构消解**：
登记方与判定方都在工作台进程内，无需把状态同步进边车。

跨进程 / 多副本说明（如实登记，属未验证项）：生产部署若工作台多副本，「登记」与
「判定」可能落在**不同副本**上，则本表仍是**进程内**对象、副本间不共享 ⇒ 未验证。
"""

from __future__ import annotations

from threading import RLock

from .token_binding import TokenBinding

FIRST_GENERATION = 1


class ActiveExecutionRegistry:
    """`session_id -> 当前执行绑定`（服务端权威；代次单调递增、从 1 开始）。"""

    def __init__(self) -> None:
        self._by_session: dict[str, TokenBinding] = {}
        self._lock = RLock()

    def register(self, binding: TokenBinding) -> None:
        """登记一次「进入新 turn」（每铸一次令牌调用一次）。违反口径即 `ValueError`（fail-closed）。

        - 首次登记：`generation` 必须为 `1`（从 1 开始）；
        - 再次登记：`generation` 必须**严格大于**当前值（单调递增）；租户不得中途变更。
        """
        generation = int(binding.generation)
        with self._lock:
            current = self._by_session.get(binding.session_id)
            if current is None:
                if generation != FIRST_GENERATION:
                    raise ValueError("会话首个代次必须为 1")
            else:
                if binding.tenant_id != current.tenant_id:
                    raise ValueError("会话不得中途跨租户")
                if generation <= current.generation:
                    raise ValueError("代次必须单调递增")
            self._by_session[binding.session_id] = TokenBinding(
                binding.tenant_id, binding.session_id, generation
            )

    def current_for(self, session_id: str) -> TokenBinding | None:
        """读取该会话**当前执行**的权威绑定；无活动执行返回 `None`。"""
        if not session_id:
            return None
        with self._lock:
            return self._by_session.get(session_id)

    def retire(self, session_id: str) -> bool:
        """会话结束 / 终态：摘除登记（返回是否命中）。"""
        with self._lock:
            return self._by_session.pop(session_id, None) is not None
