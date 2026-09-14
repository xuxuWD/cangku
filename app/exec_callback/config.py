"""执行回调边车进程配置（规格 §3.5 P1 第 3 条 ②④ / §8 U20 方案 b-1）。

边车是**独立进程**：**只监听一个端口**、**只挂 `workbench-exec-internal`**（门禁 §B14 判据 E）。
配置从**进程环境变量**读取（不依赖 `app.settings` / pydantic —— 边车镜像里除标准库外
**不装任何依赖**，以缩小可信计算基），变量名与 `app/settings.py` 的
`WORKBENCH_EXEC_CALLBACK_*` **完全一致**（三处台账：`app/settings.py` /
`.env.staging.example` / `tests/test_env_templates.py` 的 `STAGE2_SETTINGS_FIELDS`）。

**不得把回调地址 / 凭据烤进镜像**：本模块只读环境变量，**无任何内置地址或密钥**；
`FORWARD_URL` 留空即**拒绝启动**（fail-closed）。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping
from urllib.parse import urlparse

ENV_PREFIX = "WORKBENCH_EXEC_CALLBACK_"

DEFAULT_LISTEN_HOST = "0.0.0.0"
DEFAULT_LISTEN_PORT = 8081
DEFAULT_FORWARD_TIMEOUT_SECONDS = 10.0


class ExecCallbackConfigError(ValueError):
    """边车装配期配置错误（fail-closed）：拒绝启动并告警。"""


def _text(env: Mapping[str, str], name: str, default: str = "") -> str:
    value = env.get(ENV_PREFIX + name, default)
    return value.strip() if isinstance(value, str) else default


def _number(env: Mapping[str, str], name: str, default, cast):
    raw = env.get(ENV_PREFIX + name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return cast(str(raw).strip())
    except (TypeError, ValueError) as exc:
        raise ExecCallbackConfigError(f"{ENV_PREFIX}{name} 取值非法") from exc


@dataclass(frozen=True)
class ExecCallbackConfig:
    """边车运行参数（不可变；值来源见 `from_env`）。

    - `forward_url` ＝ **边车 → 工作台**的受控出向调用目标（工作台侧回调接收端点）；
      留空 / 非法 ⇒ 拒绝启动（不得把回调地址烤进镜像，只能外置注入）。
    - `listen_host` / `listen_port` ＝ 边车**唯一**监听面；对外可达性由「边车只挂
      `workbench-exec-internal`」这一网络成员事实限定（不允许双宿到工作台默认网络）。
    """

    forward_url: str
    listen_host: str = DEFAULT_LISTEN_HOST
    listen_port: int = DEFAULT_LISTEN_PORT
    forward_timeout_seconds: float = DEFAULT_FORWARD_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        parsed = urlparse(self.forward_url or "")
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ExecCallbackConfigError(
                "未配置合法的工作台转发地址（WORKBENCH_EXEC_CALLBACK_FORWARD_URL），拒绝启动边车"
            )
        if not (1 <= int(self.listen_port) <= 65535):
            raise ExecCallbackConfigError("边车监听端口必须在 1..65535 之间")
        if self.forward_timeout_seconds <= 0:
            raise ExecCallbackConfigError("边车转发超时必须为正数")

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "ExecCallbackConfig":
        source = os.environ if env is None else env
        return cls(
            forward_url=_text(source, "FORWARD_URL"),
            listen_host=_text(source, "LISTEN_HOST", DEFAULT_LISTEN_HOST) or DEFAULT_LISTEN_HOST,
            listen_port=_number(source, "LISTEN_PORT", DEFAULT_LISTEN_PORT, int),
            forward_timeout_seconds=_number(
                source, "FORWARD_TIMEOUT_SECONDS", DEFAULT_FORWARD_TIMEOUT_SECONDS, float
            ),
        )
