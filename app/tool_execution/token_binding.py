"""短期网关令牌的**控制面绑定强制与恒时比对**（规格 §3.5 P1 第 3 条 ②④）。

口径（2026-09-13 用户裁决，定死）：
    - **校验点 ＝ 工作台控制面**：执行侧**回调工作台**（导出产物 / 请求授权）时，由工作台
      按令牌**反查工作台侧自持绑定** `(tenant_id, session_id, generation)` 并与**当前执行**比对；
    - **服务端为准**：只读工作台自持记录，**不读容器声明**（容器侧伪造绑定声明无效果）；
    - **constant-time 比对**（本模块以「调用 `hmac.compare_digest` 原语」为判据，不以计时为判据）；
    - 不匹配 / 跨租户 / 旧代次 → **拒绝**（`403`，不泄露存在性）并记审计；
    - **网关数据面不做绑定校验**（见 `gateway_token.py` 头部口径与本模块文档）。

`generation`（代次）＝ **会话内 turn 序号**（单调递增整数，从 1 开始；每铸一次令牌 +1）。
绑定由**我们（工作台）签发令牌时**在本地落一份副本；失效 / 吊销时两处副本须同步清
（网关侧 tokens Map 与工作台侧本副本）。

⚠️ 本模块**当前无调用方**：规格所述的两个回调场景（导出产物 / 请求授权）尚未存在
（`artifact.export` 是自建工具、不经容器）。用户裁决「本期做」故先交付**组件与判据**
（§5 用例 35），**在接入真实回调端点之前不得声称「②④ 已强制」**。
"""

from __future__ import annotations

import hmac
from dataclasses import dataclass
from threading import RLock

# 恒时比对的分隔符：把三元组拼成单一规范串后**一次** `compare_digest`，避免逐字段短路比较。
_CANONICAL_SEP = "\x1f"


class BindingDenied(RuntimeError):
    """回调绑定校验失败：接口层按 `403` 处理，**不泄露存在性**（文案固定、不区分原因）。"""

    http_status = 403

    def __init__(self, message: str = "回调绑定校验失败") -> None:
        super().__init__(message)


@dataclass(frozen=True)
class TokenBinding:
    """工作台侧自持的令牌绑定三元组。"""

    tenant_id: str
    session_id: str
    generation: int

    def canonical(self) -> str:
        """规范串：用于恒时比对；三元组任一不同即整串不同。"""
        return _CANONICAL_SEP.join(
            (str(self.tenant_id), str(self.session_id), str(int(self.generation)))
        )


def constant_time_equal(left: TokenBinding, right: TokenBinding) -> bool:
    """恒时比较两个绑定（**一次** `hmac.compare_digest` 原语，不做逐字段短路）。"""
    return hmac.compare_digest(left.canonical(), right.canonical())


class TokenBindingStore:
    """工作台侧自持绑定：`token -> TokenBinding`（签发时落，吊销时清）。"""

    def __init__(self) -> None:
        self._by_token: dict[str, TokenBinding] = {}
        self._lock = RLock()

    def record(self, *, token: str, binding: TokenBinding) -> None:
        if not token:
            raise ValueError("令牌不得为空")
        with self._lock:
            self._by_token[token] = binding

    def lookup(self, token: str) -> TokenBinding | None:
        with self._lock:
            return self._by_token.get(token)

    def revoke(self, token: str) -> bool:
        """同步吊销：清工作台侧副本（调用方须同时清网关侧副本）。返回是否命中。"""
        with self._lock:
            return self._by_token.pop(token, None) is not None

    def revoke_binding(self, binding: TokenBinding) -> int:
        """按绑定三元组吊销（清可能存在的多个令牌副本）；返回被清数量。"""
        with self._lock:
            matched = [token for token, item in self._by_token.items() if item == binding]
            for token in matched:
                del self._by_token[token]
            return len(matched)


class ControlPlaneBindingVerifier:
    """控制面绑定校验器（规格 §3.5 P1 第 3 条 ②④）。

    判据（§5 用例 35）：
        ① 令牌与当前执行不匹配 → 拒（`403`，不泄露存在性）并记审计；
        ② 跨租户 → 拒；③ 旧代次 → 拒；④ 完全匹配 → 放行；
        ⑤ 容器侧伪造绑定声明（`claimed_binding`）**无效果**——服务端只以自己的权威记录为准；
        ⑥ 网关数据面不做绑定（本校验器不属于网关数据面）。
    """

    def __init__(self, *, store: TokenBindingStore, audit=None) -> None:
        self.store = store
        self.audit = audit

    def verify(
        self,
        *,
        token: str,
        expected: TokenBinding,
        actor_id: str | None = None,
        run_id: str | None = None,
        tool_key: str | None = None,
        claimed_binding: TokenBinding | None = None,
    ) -> TokenBinding:
        """按令牌反查工作台自持绑定并与 `expected`（当前执行）恒时比对。

        `claimed_binding` 是**执行侧（容器）声明的绑定**，**刻意忽略**——保留该入参只为
        显式表达「不读容器声明」，使「容器伪造声明无效果」可被用例断言。
        """
        del claimed_binding  # 显式忽略：服务端不读容器声明（⑤）
        binding = self.store.lookup(token)
        if binding is None or not constant_time_equal(binding, expected):
            self._deny(
                tenant_id=expected.tenant_id,
                actor_id=actor_id,
                run_id=run_id,
                tool_key=tool_key,
            )
        return binding

    # ------------------------------------------------------------------ 内部

    def _deny(
        self,
        *,
        tenant_id: str,
        actor_id: str | None,
        run_id: str | None,
        tool_key: str | None,
    ) -> None:
        """记审计后拒绝。复用既有动作码 `tool.blocked`（**不新增审计动作码**）；文案固定不泄露存在性。"""
        if self.audit is not None:
            from ..audit.models import AuditAction

            self.audit.record(
                AuditAction.TOOL_BLOCKED,
                tenant_id=tenant_id,
                actor_id=actor_id,
                target_type="tool_action",
                target_id=run_id,
                detail={
                    "status": "blocked",
                    "reason": "not_authorized",
                    "run_id": run_id,
                    "tool_key": tool_key,
                    "risk_level": "high",
                },
            )
        raise BindingDenied()
