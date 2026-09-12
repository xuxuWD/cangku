from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class PreflightCheck:
    name: str
    status: str
    message: str


@dataclass(frozen=True)
class PreflightReport:
    status: str
    checks: tuple[PreflightCheck, ...]

    def to_text(self) -> str:
        lines = [f"外部 Runtime staging 预检结果：{self.status}"]
        lines.extend(f"[{check.status}] {check.name}：{check.message}" for check in self.checks)
        return "\n".join(lines)


# 与 Settings 的 AliasChoices 口径一致：裸名优先，`WORKBENCH_` 前缀次之；
# 且先出现的那个变量即使为空串也不再回退（pydantic-settings 取"先命中"的变量）。
_RUNTIME_KEYS = ("ragflow", "agentscope", "deerflow", "codex_worker", "hermes")
_RUNTIME_FIELDS = ("endpoint", "version", "capabilities", "auth_injected")


def _runtime_env_candidates() -> dict[str, tuple[str, ...]]:
    return {
        f"{key}_{field}": (
            f"{key.upper()}_{field.upper()}",
            f"WORKBENCH_{key.upper()}_{field.upper()}",
        )
        for key in _RUNTIME_KEYS
        for field in _RUNTIME_FIELDS
    }


def _first_present(candidates: tuple[str, ...]) -> str:
    for name in candidates:
        if name in os.environ:
            return os.environ[name]
    return ""


def _as_mapping(config: Mapping[str, object] | None) -> dict[str, object]:
    if config is not None:
        return dict(config)
    values: dict[str, object] = {
        "environment": os.getenv("WORKBENCH_ENV", ""),
        "staging_id": os.getenv("WORKBENCH_STAGING_ID", ""),
        "runtime_network": os.getenv("WORKBENCH_RUNTIME_NETWORK", ""),
    }
    values.update(
        {key: _first_present(candidates) for key, candidates in _runtime_env_candidates().items()}
    )
    return values


# 外部云服务（须 HTTPS，认证必填）与本地独立进程（允许 http，认证可选）口径不同：
# 后者按 `poc-runtime-config.example.yaml` 的定位，不强制 TLS，也不强制认证注入。
_EXTERNAL_RUNTIMES = (("RAGFlow", "ragflow"), ("AgentScope", "agentscope"))
_LOCAL_RUNTIMES = (("DeerFlow", "deerflow"), ("Codex Worker", "codex_worker"), ("Hermes", "hermes"))


def _fixed_version(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip()) and value.strip().lower() not in {"latest", "main", "head"}


def _https_endpoint(value: object) -> bool:
    return isinstance(value, str) and value.startswith("https://") and bool(value[8:].strip())


def _http_endpoint(value: object) -> bool:
    """本地独立进程允许 http；仍须是带主机名的 http(s) 绝对地址。"""
    if not isinstance(value, str):
        return False
    for scheme in ("https://", "http://"):
        if value.startswith(scheme):
            return bool(value[len(scheme):].strip())
    return False


def _capability_whitelist(value: object) -> bool:
    """与 build_runtime_registry 的能力白名单校验口径一致：逗号分隔、去空白后至少一项非空。"""
    return isinstance(value, str) and any(item.strip() for item in value.split(","))


# 与 Settings/pydantic 的 bool 解析口径一致：这些写法都表示"已注入"。
_TRUTHY_MARKERS = frozenset({"true", "1", "yes", "on", "t"})


def _auth_injected_marker(value: object) -> bool:
    """认证注入标记必须是合法真值；写成 `Bearer xxx` 一类非法值同样判 fail。"""
    return isinstance(value, str) and value.strip().lower() in _TRUTHY_MARKERS


def run_preflight(config: Mapping[str, object] | None = None) -> PreflightReport:
    values = _as_mapping(config)
    checks: list[PreflightCheck] = []

    environment = values.get("environment")
    checks.append(PreflightCheck("运行环境", "pass", "已设置为非 development 环境") if isinstance(environment, str) and environment.strip() and environment.strip().lower() != "development" else PreflightCheck("运行环境", "fail", "必须设置为非 development 环境"))

    staging_id = values.get("staging_id")
    checks.append(PreflightCheck("Staging 标识", "pass", "已配置独立标识") if isinstance(staging_id, str) and staging_id.strip() else PreflightCheck("Staging 标识", "fail", "必须配置独立 staging 标识"))

    for label, key in _EXTERNAL_RUNTIMES:
        endpoint = values.get(f"{key}_endpoint")
        checks.append(PreflightCheck(f"{label} 地址", "pass", "已配置 HTTPS 地址") if _https_endpoint(endpoint) else PreflightCheck(f"{label} 地址", "fail", "必须使用 HTTPS 地址"))
        version = values.get(f"{key}_version")
        checks.append(PreflightCheck(f"{label} 版本", "pass", "已配置固定版本") if _fixed_version(version) else PreflightCheck(f"{label} 版本", "fail", "必须配置固定版本"))
        capabilities = values.get(f"{key}_capabilities")
        checks.append(PreflightCheck(f"{label} 能力白名单", "pass", "已登记非空能力白名单") if _capability_whitelist(capabilities) else PreflightCheck(f"{label} 能力白名单", "fail", "能力白名单为空会导致应用启动期 fail-closed"))
        auth = values.get(f"{key}_auth_injected")
        checks.append(PreflightCheck(f"{label} 认证注入", "pass", "部署环境已声明注入") if _auth_injected_marker(auth) else PreflightCheck(f"{label} 认证注入", "fail", "必须由部署环境声明认证注入（true/1/yes/on/t）"))

    # 本地独立进程：地址允许 http，认证可选，但版本与能力白名单仍必须明确登记。
    for label, key in _LOCAL_RUNTIMES:
        endpoint = values.get(f"{key}_endpoint")
        checks.append(PreflightCheck(f"{label} 地址", "pass", "已配置本地进程地址") if _http_endpoint(endpoint) else PreflightCheck(f"{label} 地址", "fail", "必须配置 http(s) 地址"))
        version = values.get(f"{key}_version")
        checks.append(PreflightCheck(f"{label} 版本", "pass", "已配置固定版本") if _fixed_version(version) else PreflightCheck(f"{label} 版本", "fail", "必须配置固定版本"))
        capabilities = values.get(f"{key}_capabilities")
        checks.append(PreflightCheck(f"{label} 能力白名单", "pass", "已登记非空能力白名单") if _capability_whitelist(capabilities) else PreflightCheck(f"{label} 能力白名单", "fail", "能力白名单为空会导致应用启动期 fail-closed"))

    network = values.get("runtime_network")
    checks.append(PreflightCheck("网络白名单", "pass", "已配置 Runtime 网络范围") if isinstance(network, str) and network.strip() else PreflightCheck("网络白名单", "fail", "必须配置 Runtime 网络白名单"))

    status = "pass" if all(check.status == "pass" for check in checks) else "fail"
    return PreflightReport(status=status, checks=tuple(checks))


def main() -> int:
    parser = argparse.ArgumentParser(description="RAGFlow/AgentScope staging 前置预检")
    parser.add_argument("--example", action="store_true", help="使用空配置演示 fail-closed 输出")
    args = parser.parse_args()
    report = run_preflight({} if args.example else None)
    print(report.to_text())
    return 0 if report.status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
