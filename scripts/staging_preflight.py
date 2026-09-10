"""Staging 前置预检：聚合基础设施隔离、商业化 G0 与外部 Runtime 元数据。

脚本只读取部署环境中的非敏感元数据和密钥是否存在，不读取或打印密钥值，
也不发起任何网络请求。它用于判断隔离 staging 环境是否已具备执行跨租户测试、
并发压测、沙箱验证和真实外部服务联调的前置条件，本身不构成真实验收证据。
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
from urllib.parse import urlsplit

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.commercial_g0_preflight import _as_mapping as _commercial_mapping
from scripts.commercial_g0_preflight import run_preflight as _run_commercial
from scripts.runtime_staging_preflight import _as_mapping as _runtime_mapping
from scripts.runtime_staging_preflight import run_preflight as _run_runtime


_LOCAL_HOSTS = {"", "localhost", "127.0.0.1", "::1", "0.0.0.0"}


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
        lines = [f"Staging 前置预检结果：{self.status}"]
        lines.extend(f"[{check.status}] {check.name}：{check.message}" for check in self.checks)
        return "\n".join(lines)


def _host(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        return ""
    try:
        parsed = urlsplit(value.strip())
    except ValueError:
        return ""
    return (parsed.hostname or "").lower()


def _independent_host(value: object) -> bool:
    host = _host(value)
    return bool(host) and host not in _LOCAL_HOSTS


def _as_mapping(config: Mapping[str, object] | None = None) -> dict[str, object]:
    """复用两个既有预检的环境解析，再补充 staging 基础设施隔离元数据。"""
    if config is not None:
        return dict(config)
    values = _commercial_mapping(None)
    values.update(_runtime_mapping(None))
    values.update(
        {
            "redis_url": os.getenv("WORKBENCH_REDIS_URL", ""),
            "object_storage_url": os.getenv("WORKBENCH_OBJECT_STORAGE_URL", ""),
            "staging_tenant_id": os.getenv("WORKBENCH_STAGING_TENANT_ID", ""),
            "object_namespace": os.getenv("WORKBENCH_OBJECT_NAMESPACE", ""),
            "ragflow_test_account_ready": os.getenv("RAGFLOW_TEST_ACCOUNT_READY", ""),
            "agentscope_test_account_ready": os.getenv("AGENTSCOPE_TEST_ACCOUNT_READY", ""),
        }
    )
    return values


def _marker_ready(value: object) -> bool:
    return isinstance(value, str) and value.strip().lower() == "true"


def _infrastructure_checks(values: Mapping[str, object]) -> list[PreflightCheck]:
    checks: list[PreflightCheck] = []

    for label, key in (
        ("PostgreSQL 独立主机", "database_url"),
        ("Redis 独立主机", "redis_url"),
        ("对象存储独立主机", "object_storage_url"),
    ):
        raw = values.get(key)
        if not isinstance(raw, str) or not raw.strip():
            checks.append(PreflightCheck(label, "fail", "必须配置 staging 服务地址"))
        elif not _independent_host(raw):
            checks.append(PreflightCheck(label, "fail", "必须使用独立主机地址，不能回落本地默认"))
        else:
            checks.append(PreflightCheck(label, "pass", "已配置独立主机"))

    for label, key, hint in (
        ("Staging 租户隔离", "staging_tenant_id", "必须登记独立 staging 租户"),
        ("对象存储命名空间", "object_namespace", "必须登记独立对象存储命名空间"),
    ):
        raw = values.get(key)
        if isinstance(raw, str) and raw.strip():
            checks.append(PreflightCheck(label, "pass", "已配置独立标识"))
        else:
            checks.append(PreflightCheck(label, "fail", hint))

    for label, key in (
        ("RAGFlow 测试账号", "ragflow_test_account_ready"),
        ("AgentScope 测试账号", "agentscope_test_account_ready"),
    ):
        if _marker_ready(values.get(key)):
            checks.append(PreflightCheck(label, "pass", "部署已声明测试账号就绪"))
        else:
            checks.append(PreflightCheck(label, "fail", "必须提供隔离测试账号并声明就绪"))

    return checks


def run_preflight(config: Mapping[str, object] | None = None) -> PreflightReport:
    values = _as_mapping(config)
    checks = _infrastructure_checks(values)

    for prefix, report in (
        ("商业化", _run_commercial(values)),
        ("外部 Runtime", _run_runtime(values)),
    ):
        checks.extend(
            PreflightCheck(f"{prefix}：{check.name}", check.status, check.message)
            for check in report.checks
        )

    if any(check.status == "fail" for check in checks):
        status = "fail"
    elif any(check.status == "blocked" for check in checks):
        status = "blocked"
    else:
        status = "pass"
    return PreflightReport(status=status, checks=tuple(checks))


def main() -> int:
    parser = argparse.ArgumentParser(description="公司工作台 staging 前置预检")
    parser.add_argument("--example", action="store_true", help="使用空配置演示 fail-closed 输出")
    args = parser.parse_args()
    report = run_preflight({} if args.example else None)
    print(report.to_text())
    return 0 if report.status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
