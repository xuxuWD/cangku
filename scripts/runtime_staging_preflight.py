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


def _as_mapping(config: Mapping[str, object] | None) -> dict[str, object]:
    if config is not None:
        return dict(config)
    names = {
        "environment": "WORKBENCH_ENV",
        "staging_id": "WORKBENCH_STAGING_ID",
        "ragflow_endpoint": "RAGFLOW_ENDPOINT",
        "ragflow_version": "RAGFLOW_VERSION",
        "ragflow_capabilities": "RAGFLOW_CAPABILITIES",
        "ragflow_auth_injected": "RAGFLOW_AUTH_INJECTED",
        "agentscope_endpoint": "AGENTSCOPE_ENDPOINT",
        "agentscope_version": "AGENTSCOPE_VERSION",
        "agentscope_capabilities": "AGENTSCOPE_CAPABILITIES",
        "agentscope_auth_injected": "AGENTSCOPE_AUTH_INJECTED",
        "runtime_network": "WORKBENCH_RUNTIME_NETWORK",
    }
    return {key: os.getenv(env_name, "") for key, env_name in names.items()}


def _fixed_version(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip()) and value.strip().lower() not in {"latest", "main", "head"}


def _https_endpoint(value: object) -> bool:
    return isinstance(value, str) and value.startswith("https://") and bool(value[8:].strip())


def _capability_whitelist(value: object) -> bool:
    """与 build_runtime_registry 的能力白名单校验口径一致：逗号分隔、去空白后至少一项非空。"""
    return isinstance(value, str) and any(item.strip() for item in value.split(","))


def run_preflight(config: Mapping[str, object] | None = None) -> PreflightReport:
    values = _as_mapping(config)
    checks: list[PreflightCheck] = []

    environment = values.get("environment")
    checks.append(PreflightCheck("运行环境", "pass", "已设置为非 development 环境") if isinstance(environment, str) and environment.strip() and environment.strip().lower() != "development" else PreflightCheck("运行环境", "fail", "必须设置为非 development 环境"))

    staging_id = values.get("staging_id")
    checks.append(PreflightCheck("Staging 标识", "pass", "已配置独立标识") if isinstance(staging_id, str) and staging_id.strip() else PreflightCheck("Staging 标识", "fail", "必须配置独立 staging 标识"))

    for label, key in (("RAGFlow", "ragflow"), ("AgentScope", "agentscope")):
        endpoint = values.get(f"{key}_endpoint")
        checks.append(PreflightCheck(f"{label} 地址", "pass", "已配置 HTTPS 地址") if _https_endpoint(endpoint) else PreflightCheck(f"{label} 地址", "fail", "必须使用 HTTPS 地址"))
        version = values.get(f"{key}_version")
        checks.append(PreflightCheck(f"{label} 版本", "pass", "已配置固定版本") if _fixed_version(version) else PreflightCheck(f"{label} 版本", "fail", "必须配置固定版本"))
        capabilities = values.get(f"{key}_capabilities")
        checks.append(PreflightCheck(f"{label} 能力白名单", "pass", "已登记非空能力白名单") if _capability_whitelist(capabilities) else PreflightCheck(f"{label} 能力白名单", "fail", "能力白名单为空会导致应用启动期 fail-closed"))
        auth = values.get(f"{key}_auth_injected")
        checks.append(PreflightCheck(f"{label} 认证注入", "pass", "部署环境已声明注入") if auth == "true" else PreflightCheck(f"{label} 认证注入", "fail", "必须由部署环境注入认证"))

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
