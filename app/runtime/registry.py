from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Callable

from .contracts import AgentRuntimeAdapter
from .adapters import (
    AgentScopeAdapter,
    CodexWorkerAdapter,
    DeerFlowAdapter,
    HermesAdapter,
    HttpRuntimeTransport,
    RAGFlowAdapter,
)
from .mock import MockRuntime
from .state import RuntimeStateStore


class RuntimeNotFound(LookupError):
    pass


class RuntimeConfigError(ValueError):
    pass


@dataclass(frozen=True)
class RuntimeEndpointConfig:
    key: str
    endpoint: str
    timeout_seconds: float
    capabilities: tuple[str, ...]
    version: str
    auth_injected: bool = False
    auth_token: str = field(default="", repr=False)
    auth_header: str = "Authorization"
    auth_scheme: str = "Bearer"

    def auth_headers(self) -> dict[str, str]:
        """按配置组装认证头；无凭据即返回空表（绝不静默匿名以外地伪造）。"""
        if not self.auth_token:
            return {}
        value = f"{self.auth_scheme} {self.auth_token}" if self.auth_scheme else self.auth_token
        return {self.auth_header: value}


class RuntimeRegistry:
    def __init__(self) -> None:
        self._items: dict[str, AgentRuntimeAdapter] = {}

    def register(self, key: str, adapter: AgentRuntimeAdapter) -> None:
        self._items[key] = adapter

    def get(self, key: str) -> AgentRuntimeAdapter:
        try:
            return self._items[key]
        except KeyError as exc:
            raise RuntimeNotFound(key) from exc

    def keys(self) -> tuple[str, ...]:
        return tuple(sorted(self._items))

    def health(self) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for key in self.keys():
            adapter = self._items[key]
            try:
                raw = adapter.health()
                if not isinstance(raw, dict):
                    raise TypeError("invalid health response")
                allowed = {"runtime", "version", "capabilities", "sandbox", "reason"}
                summary: dict[str, Any] = {}
                for name in allowed:
                    value = raw.get(name)
                    if name == "capabilities":
                        if isinstance(value, (list, tuple)) and all(isinstance(item, str) for item in value):
                            summary[name] = list(value)
                    elif isinstance(value, str):
                        summary[name] = value
                summary["status"] = "unavailable" if key == "ragflow" and raw.get("status") == "unavailable" else "ok"
                result[key] = summary
            except Exception as exc:  # 外部健康检查失败也要返回可读摘要
                result[key] = {"status": "error", "reason": "Runtime 健康检查失败"}
        return result


def _validate_endpoint(key: str, value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise RuntimeConfigError(f"{key} Runtime 缺少地址")
    if not value.startswith(("http://", "https://")):
        raise RuntimeConfigError(f"{key} Runtime 地址协议必须是 HTTP 或 HTTPS")
    return value


def _validate_timeout(key: str, value: Any) -> float:
    try:
        timeout = float(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeConfigError(f"{key} Runtime 超时时间无效") from exc
    if not math.isfinite(timeout) or timeout <= 0:
        raise RuntimeConfigError(f"{key} Runtime 超时时间无效")
    return timeout


def _validate_version(key: str, value: Any) -> str:
    normalized = value.strip() if isinstance(value, str) else value
    if (
        not isinstance(normalized, str)
        or not normalized
        or normalized.lower() in {"latest", "main", "head"}
    ):
        raise RuntimeConfigError(f"{key} Runtime 需要固定版本")
    return normalized


def build_runtime_registry(
    config: dict[str, dict[str, Any]],
    *,
    transport_factory: Callable[[str, RuntimeEndpointConfig], Any] | None = None,
    state_store: RuntimeStateStore | None = None,
) -> RuntimeRegistry:
    """从受控配置构建 Runtime 注册表；默认只提供 Mock。"""
    registry = RuntimeRegistry()
    runtime_state = state_store or RuntimeStateStore()
    registry.register("mock", MockRuntime(runtime_state))
    transport_factory = transport_factory or (
        lambda _key, item: HttpRuntimeTransport(
            timeout_seconds=item.timeout_seconds, headers=item.auth_headers()
        )
    )
    constructors = {
        "deerflow": DeerFlowAdapter,
        "codex_worker": CodexWorkerAdapter,
        "hermes": HermesAdapter,
        "ragflow": RAGFlowAdapter,
        "agentscope": AgentScopeAdapter,
    }
    for key, raw in config.items():
        if key == "mock" or not raw.get("enabled", False):
            continue
        constructor = constructors.get(key)
        if constructor is None:
            raise RuntimeConfigError(f"未知 Runtime: {key}")
        endpoint = _validate_endpoint(key, raw.get("endpoint"))
        raw_capabilities = raw.get("capabilities")
        if (
            not isinstance(raw_capabilities, (list, tuple))
            or not raw_capabilities
            or any(not isinstance(item, str) or not item.strip() for item in raw_capabilities)
        ):
            raise RuntimeConfigError(f"{key} Runtime 未配置能力白名单")
        capabilities = tuple(item.strip() for item in raw_capabilities)
        timeout_seconds = _validate_timeout(key, raw.get("timeout_seconds", 30.0))
        version = _validate_version(key, raw.get("version"))
        auth_injected = bool(raw.get("auth_injected", False))
        raw_token = raw.get("auth_token")
        auth_token = raw_token if isinstance(raw_token, str) else ""
        if auth_injected and not auth_token.strip():
            raise RuntimeConfigError(f"{key} Runtime 声明已注入认证但缺少凭据")
        auth_header = raw.get("auth_header") or "Authorization"
        raw_scheme = raw.get("auth_scheme", "Bearer")
        auth_scheme = raw_scheme if isinstance(raw_scheme, str) else "Bearer"
        item = RuntimeEndpointConfig(
            key=key,
            endpoint=endpoint,
            timeout_seconds=timeout_seconds,
            capabilities=capabilities,
            version=version,
            auth_injected=auth_injected,
            auth_token=auth_token,
            auth_header=auth_header,
            auth_scheme=auth_scheme,
        )
        registry.register(key, constructor(transport_factory(key, item), endpoint))
    return registry
