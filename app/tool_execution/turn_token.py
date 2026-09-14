"""一次 turn 的短期网关令牌**生产接线**（规格 §3.5 P1 第 3 条 ②④⑤ / §8 U24）。

口径（2026-09-14 用户裁决 **1-A**）：**一次 turn = 一次容器执行**（`ContainerExecutor.execute`）。
本模块把**既有**三块组件接成**一条生产链路**，不新造机制：

    - **mint**：`GatewayTokenClient.mint`（每 turn 新铸，绑租户 / 会话 / 代次）；
    - **自持绑定**：`TokenBindingStore.record`（②④ 判定用；与回调判定侧**共用同一实例**）；
    - **权威登记**：`ActiveExecutionRegistry.register`（②④ 的 `expected` 来源；终态 `retire`）；
    - **终态吊销**：`build_terminal_state_revoker`（⑤，与 mint **共用同一控制面客户端**）。

**②④ 的唯一约束 = 共享单例**：`TokenBindingStore` / `ActiveExecutionRegistry` 由**装配期**创建，
`build_exec_callback_guard`（判定侧读）与本控制器（写入侧写）**共用同一实例**；否则 ②④ 恒 `403`
（§8 U24 原样复现）。装配点见 `app/bootstrap.py` 与 `app/main.py`。

**绑定取值**（`bound` / `session_id` / `generation`，按既有数据模型决定）：

    - `session_id` = **任务的 `task_id`**（`ActiveExecutionRegistry` 的**会话键**；与
      `DshAdapter` 以 `context.task_id` 作会话同一口径）；
    - `generation` = **会话内当前代次 + 1**，无当前执行时为 `1`（**取自 `ActiveExecutionRegistry`
      的权威值**，不另立计数器 ⇒ 不形成第二事实源）；
    - 网关侧 `bound` 标签 = `"{tenant}:{session}:{generation}"`（与 `DshAdapter._bound_for` 同口径；
      网关上它**只作审计元数据**，绑定强制在工作台控制面）。

安全口径：容器内 env 由 `dsh.build_token_env` 生成（**唯一事实源**），只含
「网关内网地址 + 短期令牌」；**供应商密钥不进容器 / 不进日志 / 不进审计**。
令牌明文只在本进程内存与容器 env 中存在，**本模块不落任何令牌日志**。
"""

from __future__ import annotations

from threading import RLock
from typing import Callable, Mapping

from ..runtime.adapters.dsh import build_token_env
from .active_execution import ActiveExecutionRegistry
from .errors import ToolExecutionConfigError
from .gateway_token import GatewayTokenClient, build_terminal_state_revoker
from .log import get_logger
from .token_binding import TokenBinding, TokenBindingStore


def bound_label(binding: TokenBinding) -> str:
    """网关侧 `bound` 标签（**审计元数据**；与 `DshAdapter._bound_for` 同口径）。"""
    return f"{binding.tenant_id}:{binding.session_id}:{binding.generation}"


class TurnTokenController:
    """一次 turn 的令牌控制面：mint + 自持绑定 + 权威登记 + 终态吊销（②④⑤）。"""

    def __init__(
        self,
        *,
        store: TokenBindingStore,
        registry: ActiveExecutionRegistry,
        gateway_base_url: str,
        mint_secret: str,
        timeout_seconds: float = 10.0,
        vendor_api_key: str = "",
    ) -> None:
        # 写入侧与判定侧**必须**是这两个共享实例（装配期单例，见 `bootstrap` / `main`）。
        self.store = store
        self.registry = registry
        self.gateway_base_url = gateway_base_url
        self._mint_secret = mint_secret
        self._vendor_api_key = vendor_api_key
        self.timeout_seconds = float(timeout_seconds)
        self._lock = RLock()
        # run_id -> (自持绑定三元组, 网关 bound 标签)：终态吊销据此把运行映射回绑定。
        self._by_run: dict[str, tuple[TokenBinding, str]] = {}
        self._client_obj: GatewayTokenClient | None = None
        self._revoker: Callable[[str], None] | None = None

    # ------------------------------------------------------------------ 启动期

    def problems(self) -> list[str]:
        """装配期缺件清单（空 = 合格）。缺失 ⇒ 由启动期断言**拒绝启用真实执行**（记 error，不打挂进程）。"""
        problems: list[str] = []
        if not str(self.gateway_base_url or "").strip():
            problems.append("未配置模型网关地址（WORKBENCH_MODEL_GATEWAY_BASE_URL），容器内 baseURL 无落点")
        if not str(self._mint_secret or "").strip():
            problems.append("未配置网关控制面密钥（WORKBENCH_MODEL_GATEWAY_MINT_SECRET），拒绝启用真实执行")
        return problems

    @property
    def ready(self) -> bool:
        return not self.problems()

    # ------------------------------------------------------------------ turn 生命周期

    def open_turn(self, *, tenant_id: str, session_id: str, run_id: str) -> Mapping[str, str]:
        """进入一次新 turn：mint → 落自持绑定 → 登记当前执行；返回容器内 env（**不含供应商密钥**）。"""
        self._require_ready()
        if not tenant_id or not session_id or not run_id:
            raise ToolExecutionConfigError("turn 绑定标识不完整，拒绝铸造令牌")
        with self._lock:
            if run_id in self._by_run:
                # 幂等收口：同一 run 重复进入 → 先清旧（吊销旧令牌 + 摘旧登记），不留孤儿。
                self.on_terminal(run_id)
            current = self.registry.current_for(session_id)
            generation = (int(current.generation) + 1) if current is not None else 1
            binding = TokenBinding(tenant_id, session_id, generation)
            bound = bound_label(binding)
            # 令牌明文仅在内存流转；任何异常路径都不得把明文写进日志。
            token = self._client().mint(bound)
            try:
                environment = build_token_env(
                    token=token,
                    gateway_base_url=self.gateway_base_url,
                    vendor_api_key=self._vendor_api_key,
                )
            except Exception:
                self._revoke_quietly(bound)
                raise
            try:
                self.store.record(token=token, binding=binding)
                self.registry.register(binding)
            except Exception:
                # 登记失败（并发同代次 / 中途跨租户等）⇒ 回滚已落副本 + 撤销刚铸令牌（fail-closed）。
                self.store.revoke(token)
                self._revoke_quietly(bound)
                raise
            self._by_run[run_id] = (binding, bound)
        return environment

    def on_terminal(self, run_id: str) -> None:
        """终态同步：`registry.retire` + 清自持绑定 + 网关吊销。失败只告警，**不影响执行结果返回**。

        本方法即注入 `ContainerExecutor(token_revoker=…)` 的入口（签名 `Callable[[str], None]`）。
        """
        if not run_id:
            return
        with self._lock:
            item = self._by_run.pop(run_id, None)
        if item is None:
            return
        binding, bound = item
        try:
            self.registry.retire(binding.session_id)
        except Exception as exc:  # noqa: BLE001 - 摘除失败不影响结果，但必须留痕
            get_logger().error("终态登记摘除失败，需人工介入（§3.5 P1 ②④）：%s", exc)
        try:
            self.store.revoke_binding(binding)
        except Exception as exc:  # noqa: BLE001 - 同上
            get_logger().error("终态自持绑定清除失败，需人工介入（§3.5 P1 ②④）：%s", exc)
        self._revoke_quietly(bound)

    # ------------------------------------------------------------------ 内部

    def _require_ready(self) -> None:
        problems = self.problems()
        if problems:
            raise ToolExecutionConfigError("；".join(problems))

    def _client(self) -> GatewayTokenClient:
        with self._lock:
            if self._client_obj is None:
                self._client_obj = GatewayTokenClient(
                    base_url=self.gateway_base_url,
                    admin_secret=self._mint_secret,
                    timeout_seconds=self.timeout_seconds,
                )
            return self._client_obj

    def _terminal_revoke(self) -> Callable[[str], None]:
        """终态吊销器（⑤ 的既有入口 `build_terminal_state_revoker`；与 mint 共用同一客户端）。"""
        with self._lock:
            if self._revoker is None:
                self._revoker = build_terminal_state_revoker(
                    base_url=self.gateway_base_url,
                    admin_secret=self._mint_secret,
                    timeout_seconds=self.timeout_seconds,
                    client=self._client(),
                )
            return self._revoker

    def _revoke_quietly(self, bound: str) -> None:
        try:
            self._terminal_revoke()(bound)
        except Exception as exc:  # noqa: BLE001 - 吊销失败不影响既有结果，但必须留痕
            get_logger().error("终态同步吊销失败，需人工介入（§3.5 P1 ⑤）：%s", exc)
