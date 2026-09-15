"""dsh 适配器（规格 §3.5 / §3.6）：**剖面锁死 + 启动期断言 + 容器内只注入短期网关令牌**。

口径（2026-09-13 裁决路径①「自建模型网关」）：
    - 容器内 `baseURL` 指向**网关内网地址**（`DEEPSEEK_BASE_URL`）；
    - 容器内 `apiKeyEnv`（`DEEPSEEK_API_KEY`）放**我们签发的短期网关令牌**，
      **绝不**放供应商密钥（供应商密钥只在容器外的 `app.model_gateway`）。

剖面锁死（§3.5「剖面必须锁死」表，逐条：`DSH_PERMISSION_MODE=read-only`、禁用清单、
`restrict` 非空工具面、遥测开关）。**断言失败 = 拒绝启用真实执行并告警（记 `error`），
不拒绝整个服务进程启动**（§3.6 口径）——因此构造函数**不抛进程级异常**。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable
from uuid import uuid4

from ..contracts import AgentPlan, AgentRuntimeAdapter, RuntimeContext, RuntimeEvent

# --------------------------------------------------------------------- 剖面锁死常量

# 总闸：实测 `danger-full-access` 会同时关掉沙箱与审批（§F7.2），必须显式 read-only。
PROFILE_PERMISSION_MODE = "read-only"
# 遥测：上游自带开关（§F8.1④）；本场景无可观测外发，但保留为兜底。
TELEMETRY_DISABLED = "1"

ENV_PERMISSION_MODE = "DSH_PERMISSION_MODE"
ENV_TELEMETRY_DISABLED = "DSH_TELEMETRY_DISABLED"
ENV_BASE_URL = "DEEPSEEK_BASE_URL"
ENV_API_KEY = "DEEPSEEK_API_KEY"

# 供应商密钥「不得进入容器」的禁止字段名（env / argv / 容器 spec 三面同口径）。
FORBIDDEN_IN_CONTAINER_ENV_NAMES = frozenset(
    {"DEEPSEEK_API_KEY_SUPPLIER", "MODEL_GATEWAY_UPSTREAM_API_KEY", "OPENAI_API_KEY_SUPPLIER"}
)

# 容器内 env 的**白名单**（§3.3 凭据行 / §8 **U28** 残留 **G2**，2026-09-15）：我方经
# `-e` / `environment` 注入容器的变量**只允许**下列两项 —— `baseURL`（网关内网地址）与
# `apiKeyEnv`（短期网关令牌）。白名单是**闸门**：执行侧（`app/tool_execution/executor.py` 的
# `ContainerSpec`）在**装配期逐键校验**，白名单外一律 fail-closed，**不依赖上游自觉**。
# 逐项口径（值来源 / 最长 TTL / 绑定语义）见规格 §3.3 凭据行。
# **本集合必须等于 `build_token_env` 的产出键集合**（防两处事实源漂移）：
#   `tests/test_container_executor.py::test_env_whitelist_accepts_the_token_env_and_matches_its_source`
ALLOWED_IN_CONTAINER_ENV_NAMES = frozenset({ENV_BASE_URL, ENV_API_KEY})


def build_token_env(
    *, token: str, gateway_base_url: str, vendor_api_key: str = ""
) -> dict[str, str]:
    """容器内**短期令牌**环境（**唯一事实源**：常量 + 禁止名单都在本函数里收口）。

    只放两项：`baseURL` → **网关内网地址**；`apiKeyEnv` → **短期网关令牌**（非供应商密钥）。
    任何**供应商密钥**都不进容器 —— 若令牌本身就是供应商密钥，直接拒绝；禁止字段名一律剔除。
    产出键集合必须**恰好等于** `ALLOWED_IN_CONTAINER_ENV_NAMES`（G2 白名单，执行侧据此逐键校验）。

    > 落点说明（为什么抽在这里、而不在 `tool_execution`）：常量（`ENV_BASE_URL` / `ENV_API_KEY`）
    > 与禁止名单（`FORBIDDEN_IN_CONTAINER_ENV_NAMES`）的**定义处就是本模块**；把构造函数与它们
    > 放在同一模块，才能保证「注入内容」与「禁令名单」**不形成第二事实源**。容器执行侧
    > （`app/tool_execution/turn_token.py`）**只调用本函数**，不复制常量。
    """
    if not isinstance(token, str) or not token.strip():
        raise DshProfileLockError("容器内短期令牌不得为空")
    if not isinstance(gateway_base_url, str) or not gateway_base_url.strip():
        raise DshProfileLockError("容器内 baseURL 无落点（未配置模型网关地址）")
    env = {ENV_BASE_URL: gateway_base_url, ENV_API_KEY: token}
    if vendor_api_key and vendor_api_key in env.values():
        raise DshProfileLockError("供应商密钥不得进入容器环境")
    for name in FORBIDDEN_IN_CONTAINER_ENV_NAMES:
        env.pop(name, None)
    # G2 白名单自检：本函数是**唯一事实源**，一旦将来新增键而忘了同步白名单，此处即 fail-closed
    # （否则执行侧会在装配期以"白名单外变量"为由拒绝，报错点离成因更远）。
    beyond_whitelist = sorted(set(env) - ALLOWED_IN_CONTAINER_ENV_NAMES)
    if beyond_whitelist:
        raise DshProfileLockError(
            "容器 env 超出白名单（G2，§3.3 凭据行）：" + "、".join(beyond_whitelist)
        )
    return env


@dataclass(frozen=True)
class DisabledPlugin:
    """一条禁用项：`plugin_id` 是 `--patch` 里按 id 打的；`package` 是上游包名（用于取证/断言）。"""

    plugin_id: str
    package: str


# §3.5 禁用清单（逐条对齐：tool-bash / tool-pwsh / subprocess-local / web_* / skill /
# subagent* / workflow / ralph / 遥测插件）。
DISABLED_PLUGINS: tuple[DisabledPlugin, ...] = (
    DisabledPlugin("tool-bash", "@deepseek-ai/dsh-tool-bash"),
    DisabledPlugin("tool-pwsh", "@deepseek-ai/dsh-tool-pwsh"),
    DisabledPlugin("subprocess-local", "@deepseek-ai/dsh-subprocess-local"),
    DisabledPlugin("web", "@deepseek-ai/dsh-web"),
    DisabledPlugin("web-search-deepseek", "@deepseek-ai/dsh-web-search-deepseek"),
    DisabledPlugin("web-fetch-http", "@deepseek-ai/dsh-web-fetch-http"),
    DisabledPlugin("tool-web", "@deepseek-ai/dsh-tool-web"),
    DisabledPlugin("skill", "@deepseek-ai/dsh-skill"),
    DisabledPlugin("subagent", "@deepseek-ai/dsh-subagent"),
    DisabledPlugin("subagent-fork", "@deepseek-ai/dsh-subagent-fork"),
    DisabledPlugin("workflow", "@deepseek-ai/dsh-workflow"),
    DisabledPlugin("ralph", "@deepseek-ai/dsh-ralph"),
    DisabledPlugin("session-telemetry-otel", "@deepseek-ai/dsh-session-telemetry-otel"),
)
REQUIRED_DISABLED_IDS = frozenset(item.plugin_id for item in DISABLED_PLUGINS)
REQUIRED_DISABLED_PACKAGES = frozenset(item.package for item in DISABLED_PLUGINS)

# `restrict` 收窄到**本模式允许的最小工具面**（只读检视类）；空集 = fail-closed。
RESTRICT_TOOLS: tuple[str, ...] = ("read", "read_image", "glob", "grep", "todo_write")


@dataclass(frozen=True)
class DshProfileLock:
    """剖面锁死的**唯一事实源**（禁用清单 / 工具面 / 总闸 / 遥测，均不得做成"可配置关闭"）。"""

    permission_mode: str = PROFILE_PERMISSION_MODE
    disabled_plugins: tuple[DisabledPlugin, ...] = DISABLED_PLUGINS
    restrict_tools: tuple[str, ...] = RESTRICT_TOOLS
    telemetry_disabled: bool = True

    # -------------------------------------------------------------- 断言

    def problems(self) -> list[str]:
        """返回剖面问题清单（空 = 合格）；**不得为过测试放宽**。"""
        problems: list[str] = []
        if self.permission_mode != PROFILE_PERMISSION_MODE:
            problems.append(
                f"{ENV_PERMISSION_MODE} 必须为 {PROFILE_PERMISSION_MODE}（实测 {self.permission_mode}）"
            )
        disabled_ids = {item.plugin_id for item in self.disabled_plugins}
        missing = sorted(REQUIRED_DISABLED_IDS - disabled_ids)
        if missing:
            problems.append("禁用清单缺少：" + "、".join(missing))
        if not self.restrict_tools:
            problems.append("restrict 工具面为空（fail-closed：拒绝启用真实执行）")
        if not self.telemetry_disabled:
            problems.append(f"{ENV_TELEMETRY_DISABLED} 必须打开（遥测兜底开关）")
        return problems

    @property
    def disabled_ids(self) -> tuple[str, ...]:
        return tuple(item.plugin_id for item in self.disabled_plugins)

    @property
    def disabled_packages(self) -> tuple[str, ...]:
        return tuple(item.package for item in self.disabled_plugins)

    # -------------------------------------------------------------- 产出物

    def patch_yaml(self) -> str:
        """`--patch` 覆盖层内容（按插件 id 打 `disabled: true`；§F11 实测手段）。"""
        lines = ["# 段二剖面锁死：按 id 整族禁用（规格 §3.5）"]
        for item in self.disabled_plugins:
            lines.append(f"- id: {item.plugin_id}")
            lines.append("  disabled: true")
        return "\n".join(lines) + "\n"

    def env(self) -> dict[str, str]:
        """剖面相关环境变量（**不含任何凭据**；凭据由 `build_turn_env` 单独注入）。"""
        return {
            ENV_PERMISSION_MODE: self.permission_mode,
            ENV_TELEMETRY_DISABLED: TELEMETRY_DISABLED if self.telemetry_disabled else "0",
        }


def assert_profile_locked(profile: DshProfileLock) -> bool:
    """启动期断言：合格返回 `True`；不合格**记 `error` 并返回 `False`**（不抛、不打挂进程）。"""
    problems = profile.problems()
    if not problems:
        return True
    from ...tool_execution.log import get_logger

    logger = get_logger()
    for problem in problems:
        logger.error("段二 dsh 真实执行未启用：%s", problem)
    return False


# --------------------------------------------------------------------- 适配器配置


class DshProfileLockError(RuntimeError):
    """剖面断言未通过：拒绝启用真实执行（fail-closed，不打挂进程）。"""


@dataclass(frozen=True)
class DshAdapterConfig:
    """适配器装配参数（来自 §4 的外置配置；**供应商密钥不在此注入容器**）。"""

    gateway_base_url: str
    exec_image_digest: str
    dsh_version: str = ""
    token_ttl_seconds: int = 300
    exec_timeout_seconds: int = 180
    provider: str = "deepseek-official"
    model: str = "deepseek-flash"
    workspace_mount: str = "/workspace"
    dsh_home_mount: str = "/dshhome"
    # 仅用于**拒绝性断言 / 取证**：确认供应商密钥不在任何容器面。**绝不注入容器**。
    vendor_api_key: str = field(default="", repr=False)

    @classmethod
    def from_settings(cls, settings) -> "DshAdapterConfig":
        return cls(
            gateway_base_url=settings.model_gateway_base_url,
            exec_image_digest=settings.exec_image_digest,
            dsh_version=settings.dsh_version,
            token_ttl_seconds=settings.model_gateway_token_ttl_seconds,
            exec_timeout_seconds=settings.exec_timeout_seconds,
            vendor_api_key=settings.model_gateway_upstream_api_key,
        )


@dataclass(frozen=True)
class DshTurnSpec:
    """一次 dsh turn 的容器装配（**审计可读，不含供应商密钥**）。"""

    bound: str
    env: dict[str, str]
    gateway_base_url: str
    model: str
    provider: str


# --------------------------------------------------------------------- 适配器


class DshAdapter(AgentRuntimeAdapter):
    """dsh 运行时适配器：剖面锁死 + 每 turn 新铸短期令牌 + 终态吊销。

    `turn_runner` 为**容器内 dsh turn 的驱动**（由装配处注入）；未装配时 `start_run` fail-closed。
    """

    def __init__(
        self,
        config: DshAdapterConfig,
        *,
        token_client: Any | None = None,
        turn_runner: Callable[[DshTurnSpec], Any] | None = None,
        profile: DshProfileLock | None = None,
    ) -> None:
        self.config = config
        self.profile = profile or DshProfileLock()
        self.token_client = token_client
        self.turn_runner = turn_runner
        self._runs: dict[str, dict[str, Any]] = {}
        self._generation = 0
        self.real_execution_enabled = self._assert_ready()

    # -------------------------------------------------------------- 装配断言

    def _assert_ready(self) -> bool:
        problems = list(self.profile.problems())
        if not self.config.gateway_base_url:
            problems.append("未配置模型网关地址，容器内 baseURL 无落点")
        if not self.config.exec_image_digest:
            problems.append("未配置执行镜像 digest")
        elif "@sha256:" not in self.config.exec_image_digest:
            problems.append("执行镜像必须按 digest 钉死（repo@sha256:…），禁止浮动 tag")
        if not problems:
            return True
        from ...tool_execution.log import get_logger

        logger = get_logger()
        for problem in problems:
            logger.error("段二 dsh 真实执行未启用：%s", problem)
        return False

    @property
    def profile_env(self) -> dict[str, str]:
        """剖面环境变量（总闸 + 遥测），**不含凭据**。"""
        return self.profile.env()

    def build_turn_env(self, *, token: str) -> dict[str, str]:
        """组装容器内环境变量：baseURL → 网关；API Key → **短期令牌**（非供应商密钥）。

        令牌面的常量 / 禁止名单 / 供应商密钥拒绝性自检**全部复用模块级 `build_token_env`**
        （唯一事实源，不在本方法内复写）。
        """
        env = dict(self.profile_env)
        env.update(
            build_token_env(
                token=token,
                gateway_base_url=self.config.gateway_base_url,
                vendor_api_key=self.config.vendor_api_key,
            )
        )
        env["DSH_HOME"] = self.config.dsh_home_mount
        env["DSH_MODEL"] = self.config.model
        env["DSH_PROVIDER"] = self.config.provider
        return env

    def _bound_for(self, context: RuntimeContext, session: str, generation: int) -> str:
        """绑定标签 `tenant:session:generation`（**审计元数据**；强制校验在工作台控制面）。"""
        return f"{context.tenant_id}:{session}:{generation}"

    # -------------------------------------------------------------- 契约实现

    def start_run(self, context: RuntimeContext, plan: AgentPlan) -> str:
        if not self.real_execution_enabled:
            raise DshProfileLockError("dsh 真实执行未启用：剖面断言未通过（§3.6）")
        if self.token_client is None:
            raise DshProfileLockError("未装配网关令牌控制面客户端，拒绝启用真实执行")
        if self.turn_runner is None:
            raise DshProfileLockError("未装配 dsh turn 驱动，拒绝启用真实执行")
        self._generation += 1
        session = context.task_id
        bound = self._bound_for(context, session, self._generation)
        token = self.token_client.mint(bound)
        run_id = f"dsh-{uuid4().hex[:12]}"
        spec = DshTurnSpec(
            bound=bound,
            env=self.build_turn_env(token=token),
            gateway_base_url=self.config.gateway_base_url,
            model=self.config.model,
            provider=self.config.provider,
        )
        self._runs[run_id] = {"spec": spec, "bound": bound, "context": context}
        self.turn_runner(spec)
        return run_id

    def stream_events(self, run_id: str, cursor: str | None = None) -> list[RuntimeEvent]:
        self._require(run_id)
        return []

    def pause_run(self, run_id: str, reason: str) -> None:
        self._require(run_id)

    def resume_run(self, run_id: str) -> None:
        self._require(run_id)

    def cancel_run(self, run_id: str, reason: str) -> None:
        record = self._require(run_id)
        self._revoke(record["bound"])

    def request_approval(self, run_id: str, action: dict[str, Any]) -> str:
        self._require(run_id)
        return f"approval-{uuid4().hex[:8]}"

    def decide_approval(self, run_id: str, approval_id: str, approved: bool) -> None:
        self._require(run_id)

    def get_checkpoint(self, run_id: str) -> dict[str, Any] | None:
        return {"status": "dsh"} if run_id in self._runs else None

    def replay_run(self, run_id: str, from_step: str | None = None) -> str:
        self._require(run_id)
        return run_id

    def get_usage(self, run_id: str) -> dict[str, Any]:
        self._require(run_id)
        return {"runtime": "dsh", "metering": "model_gateway"}

    def health(self) -> dict[str, Any]:
        return {
            "runtime": "dsh",
            "version": self.config.dsh_version or "unspecified",
            "sandbox": self.profile.permission_mode,
            "status": "ok" if self.real_execution_enabled else "unavailable",
            "capabilities": list(self.profile.restrict_tools),
        }

    # -------------------------------------------------------------- 内部

    def _require(self, run_id: str) -> dict[str, Any]:
        record = self._runs.get(run_id)
        if record is None:
            raise DshProfileLockError(f"未知运行：{run_id}")
        return record

    def _revoke(self, bound: str) -> None:
        """终态同步吊销（⑤）：失败只告警，不影响既有结果返回。"""
        if self.token_client is None:
            return
        try:
            self.token_client.revoke(bound)
        except Exception as exc:  # noqa: BLE001 - 吊销失败不影响既有结果
            from ...tool_execution.log import get_logger

            get_logger().error("dsh 终态同步吊销失败，需人工介入（§3.5 P1 ⑤）：%s", exc)

    def terminal_revoke(self, run_id: str) -> None:
        """turn 到终态时由驱动调用（供 `ContainerExecutor.token_revoker` 复用同一入口）。"""
        self._revoke(self._require(run_id)["bound"])


def build_dsh_adapter(
    config: DshAdapterConfig,
    *,
    token_client: Any | None = None,
    turn_runner: Callable[[DshTurnSpec], Any] | None = None,
) -> DshAdapter:
    return DshAdapter(config, token_client=token_client, turn_runner=turn_runner)
