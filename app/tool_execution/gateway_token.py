"""模型网关短期令牌的**终态同步吊销**（规格 §3.5 P1 第 3 条 ⑤ / §8 U17）。

本期范围（用户已确认）：**只做「原型闭环 + 生产落点登记」**
    - 让 `_dsh-gateway-verify\\gw\\gw.js` 的 `/__revoke` **真的被调用**（在 turn 终态后触发）；
    - **生产实现**落在 §F 的模型网关（`WORKBENCH_MODEL_GATEWAY_*`），**不在本期范围**。

安全口径：
    - 控制面（`/__mint` / `/__revoke`）需 `X-Mint-Secret`；**密钥不得进容器**、**不得进日志**；
    - 网关数据面只判「令牌存在且未过期」；**绑定校验在工作台控制面**（§3.5 P1 第 3 条注）。
"""

from __future__ import annotations

import urllib.error
import urllib.parse
import urllib.request

from .errors import ToolExecutionConfigError


class GatewayControlError(RuntimeError):
    """网关控制面调用失败（吊销 / 铸造）。"""


class GatewayTokenClient:
    """模型网关控制面客户端：**每 turn 新铸** + **终态同步吊销**（⑤）。"""

    def __init__(self, *, base_url: str, admin_secret: str, timeout_seconds: float = 10.0) -> None:
        if not isinstance(base_url, str) or not base_url.strip():
            raise ToolExecutionConfigError("未配置模型网关地址，拒绝启用令牌控制面")
        if not isinstance(admin_secret, str) or not admin_secret.strip():
            raise ToolExecutionConfigError("未配置网关控制面密钥，拒绝启用令牌控制面")
        self.base_url = base_url.rstrip("/")
        self._admin_secret = admin_secret
        self.timeout_seconds = float(timeout_seconds)

    # ------------------------------------------------------------------ 控制面

    def mint(self, bound: str) -> str:
        """铸造一枚**绑死本次执行**的短期令牌（返回令牌明文，仅内存持有）。"""
        body = self._call(f"/__mint?bound={urllib.parse.quote(bound)}")
        token = body.strip()
        if not token:
            raise GatewayControlError("网关未返回令牌")
        return token

    def revoke(self, bound: str) -> int:
        """按绑定标签**同步吊销**该次执行的令牌；返回被吊销的令牌数。"""
        body = self._call(f"/__revoke?bound={urllib.parse.quote(bound)}")
        text = body.strip()
        if text.startswith("revoked "):
            text = text[len("revoked ") :]
        try:
            return int(text)
        except ValueError as exc:
            raise GatewayControlError("网关吊销返回值不是计数") from exc

    # ------------------------------------------------------------------ 内部

    def _call(self, path: str) -> str:
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            method="GET",
            headers={"X-Mint-Secret": self._admin_secret},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                if response.status != 200:
                    raise GatewayControlError(f"网关控制面返回 {response.status}")
                return response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:  # 401/403 等
            raise GatewayControlError(f"网关控制面拒绝：HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise GatewayControlError(f"网关控制面不可达：{exc.reason}") from exc


def build_terminal_state_revoker(
    *, base_url: str, admin_secret: str, timeout_seconds: float = 10.0
):
    """构造「turn 终态触发吊销」的可调用对象（注入 `ContainerExecutor(token_revoker=…)`）。"""
    client = GatewayTokenClient(
        base_url=base_url, admin_secret=admin_secret, timeout_seconds=timeout_seconds
    )

    def revoke(bound: str) -> None:
        client.revoke(bound)

    return revoke
