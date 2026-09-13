"""短期网关令牌库（规格 §3.5 P1 第 3 条「短期令牌六条」）。

职责边界（2026-09-13 裁决，规格 §3.5 P1 第 3 条注）：
    - **数据面只判「令牌存在且未过期」**（③ 服务端为准 / ④ constant-time 比对）；
    - **不做绑定校验** —— `bound` 只是宿主经控制面写入的**审计元数据**，
      真正的绑定强制在工作台控制面（执行侧回调时反查 `(tenant, session, generation)`）；
    - ① 每 turn 新铸（由调用方在每轮 `mint`）、⑤ 终态同步吊销（`revoke`）、
      ⑥ 孤儿令牌上限（`orphan_token_limit`，超限 fail-closed 拒绝新铸）。

安全口径：令牌明文只存内存；日志/快照**只允许出现前缀**，不得回显完整令牌。
"""

from __future__ import annotations

import hmac
import secrets
import time
from dataclasses import dataclass

# 令牌熵：32 字节随机 ⇒ base64url ≈ 43 字符（与既有取证脚本观测到的 43 字符一致）。
TOKEN_BYTES = 32
TOKEN_PREFIX_LEN = 6


class OrphanTokenLimitExceeded(RuntimeError):
    """在册令牌数超 `orphan_token_limit`：**拒绝新铸**（fail-closed，不打挂网关进程）。"""


@dataclass(frozen=True)
class TokenRecord:
    """一枚在册短期令牌（**只含审计元数据，不含安全判据**）。"""

    token: str
    bound: str  # 审计元数据：宿主声明的绑定标签，**不构成安全边界**
    born_at: float
    expires_at: float

    def expires_in_ms(self, now: float) -> int:
        return max(0, int((self.expires_at - now) * 1000))

    def public_dict(self, now: float) -> dict[str, object]:
        """对外快照：**不含完整令牌**，只回前缀与剩余寿命。"""
        return {
            "id": self.token[:TOKEN_PREFIX_LEN],
            "bound": self.bound,
            "expiresInMs": self.expires_in_ms(now),
        }


class TokenStore:
    """服务端权威的短期令牌库（③：不信任容器内声明）。"""

    def __init__(self, *, orphan_token_limit: int = 64) -> None:
        if orphan_token_limit < 0:
            raise ValueError("孤儿令牌上限必须为非负整数")
        self.orphan_token_limit = orphan_token_limit
        self._tokens: dict[str, TokenRecord] = {}

    # ------------------------------------------------------------------ 控制面

    def mint(self, *, bound: str, ttl_seconds: int, now: float | None = None) -> str:
        """铸造一枚新令牌（① 每 turn 新铸）；超出孤儿上限则拒绝（⑥）。"""
        moment = time.time() if now is None else now
        self.purge_expired(now=moment)
        if self.orphan_token_limit and len(self._tokens) >= self.orphan_token_limit:
            raise OrphanTokenLimitExceeded(
                f"在册令牌 {len(self._tokens)} 达孤儿上限 {self.orphan_token_limit}，拒绝新铸"
            )
        token = secrets.token_urlsafe(TOKEN_BYTES)
        self._tokens[token] = TokenRecord(
            token=token,
            bound=bound or "unbound",
            born_at=moment,
            expires_at=moment + float(ttl_seconds),
        )
        return token

    def revoke(self, *, bound: str) -> int:
        """按绑定标签**同步吊销**（⑤）；返回被吊销的令牌数。"""
        victims = [tok for tok, rec in self._tokens.items() if rec.bound == bound]
        for tok in victims:
            del self._tokens[tok]
        return len(victims)

    # ------------------------------------------------------------------ 数据面

    def authorize(self, token: str, *, now: float | None = None) -> TokenRecord | None:
        """数据面授权：**只判「存在且未过期」**；比对走 constant-time（④）。

        不得在此做绑定校验：容器是**不可信侧**，其声明无从验证；
        网关是透明转发面，只能防误用、不能防伪造（§3.5 P1 第 3 条注）。
        """
        if not isinstance(token, str) or not token:
            return None
        moment = time.time() if now is None else now
        found: TokenRecord | None = None
        # 逐枚 constant-time 比对：避免用可变时间查找泄漏「令牌是否存在/前缀」。
        for rec in self._tokens.values():
            if hmac.compare_digest(rec.token, token):
                found = rec
        if found is None:
            return None
        if moment >= found.expires_at:
            del self._tokens[found.token]
            return None
        return found

    # ------------------------------------------------------------------ 维护

    def purge_expired(self, *, now: float | None = None) -> int:
        moment = time.time() if now is None else now
        expired = [tok for tok, rec in self._tokens.items() if moment >= rec.expires_at]
        for tok in expired:
            del self._tokens[tok]
        return len(expired)

    @property
    def live_count(self) -> int:
        return len(self._tokens)

    def snapshot(self, *, now: float | None = None) -> list[dict[str, object]]:
        moment = time.time() if now is None else now
        return [rec.public_dict(moment) for rec in self._tokens.values()]
