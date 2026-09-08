from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
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
        lines = [f"私有部署 G0 预检结果：{self.status}"]
        for check in self.checks:
            lines.append(f"[{check.status}] {check.name}：{check.message}")
        return "\n".join(lines)


def _as_mapping(config: Mapping[str, object] | None) -> dict[str, object]:
    if config is not None:
        return dict(config)

    def json_env(name: str, fallback: object) -> object:
        raw = os.getenv(name)
        if not raw:
            return fallback
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw

    migration_dir = Path(__file__).resolve().parents[1] / "migrations"
    expected = sorted(path.stem for path in migration_dir.glob("*.sql"))
    applied = [item.strip() for item in os.getenv("WORKBENCH_APPLIED_MIGRATIONS", "").split(",") if item.strip()]
    return {
        "environment": os.getenv("WORKBENCH_ENV", ""),
        "storage_backend": os.getenv("WORKBENCH_STORAGE_BACKEND", ""),
        "database_url": os.getenv("WORKBENCH_DATABASE_URL", ""),
        "auth_secret": os.getenv("WORKBENCH_AUTH_SECRET", ""),
        "backup_key": os.getenv("WORKBENCH_BACKUP_ENCRYPTION_KEY", ""),
        "applied_migrations": applied,
        "expected_migrations": expected,
        "retention_policy": json_env("WORKBENCH_RETENTION_POLICY", {}),
        "runtime_versions": json_env("WORKBENCH_RUNTIME_VERSIONS", {}),
    }


def run_preflight(config: Mapping[str, object] | None = None) -> PreflightReport:
    values = _as_mapping(config)
    checks: list[PreflightCheck] = []

    environment = values.get("environment")
    if not isinstance(environment, str) or not environment.strip() or environment.lower() == "development":
        checks.append(PreflightCheck("运行环境", "fail", "必须设置为非 development 环境"))
    else:
        checks.append(PreflightCheck("运行环境", "pass", "已设置为部署环境"))

    storage_backend = values.get("storage_backend")
    if storage_backend != "postgres":
        checks.append(PreflightCheck("存储模式", "fail", "必须使用 PostgreSQL 持久化"))
    else:
        checks.append(PreflightCheck("存储模式", "pass", "已配置 PostgreSQL 持久化"))

    database_url = values.get("database_url")
    if not isinstance(database_url, str) or not database_url.startswith(("postgresql://", "postgresql+psycopg://")):
        checks.append(PreflightCheck("数据库地址", "fail", "缺少有效的 PostgreSQL 地址"))
    else:
        checks.append(PreflightCheck("数据库地址", "pass", "已配置 PostgreSQL"))

    backup_key = values.get("backup_key")
    if not isinstance(backup_key, str) or len(backup_key) < 32:
        checks.append(PreflightCheck("备份加密密钥", "fail", "必须配置至少 32 个字符的密钥"))
    else:
        checks.append(PreflightCheck("备份加密密钥", "pass", "已配置（值不会显示）"))

    auth_secret = values.get("auth_secret")
    if not isinstance(auth_secret, str) or len(auth_secret) < 32:
        checks.append(PreflightCheck("认证密钥", "fail", "必须配置至少 32 个字符的密钥"))
    else:
        checks.append(PreflightCheck("认证密钥", "pass", "已配置（值不会显示）"))

    if isinstance(auth_secret, str) and isinstance(backup_key, str) and auth_secret and auth_secret == backup_key:
        checks.append(PreflightCheck("密钥隔离", "fail", "认证密钥和备份加密密钥必须使用不同值"))
    else:
        checks.append(PreflightCheck("密钥隔离", "pass", "认证密钥与备份密钥已分离"))

    expected = {str(item) for item in values.get("expected_migrations", []) or []}
    applied = {str(item) for item in values.get("applied_migrations", []) or []}
    if not expected:
        checks.append(PreflightCheck("迁移状态", "blocked", "未提供待核对的迁移清单"))
    elif applied != expected:
        missing = len(expected - applied)
        extra = len(applied - expected)
        checks.append(PreflightCheck("迁移状态", "blocked", f"迁移清单不一致（缺少 {missing} 项，多出 {extra} 项）"))
    else:
        checks.append(PreflightCheck("迁移状态", "pass", "迁移清单一致"))

    retention = values.get("retention_policy")
    if not isinstance(retention, Mapping) or not retention or any(
        not isinstance(value, int) or isinstance(value, bool) or value < 1 for value in retention.values()
    ):
        checks.append(PreflightCheck("保留策略", "blocked", "必须明确配置正整数天数"))
    else:
        checks.append(PreflightCheck("保留策略", "pass", "已配置"))

    runtimes = values.get("runtime_versions")
    unpinned = []
    if isinstance(runtimes, Mapping):
        unpinned = [str(key) for key, version in runtimes.items() if not isinstance(version, str) or not version.strip() or version.lower() in {"latest", "main", "head"}]
    else:
        unpinned = ["未提供"]
    if not isinstance(runtimes, Mapping) or not runtimes:
        checks.append(PreflightCheck("Runtime 版本", "blocked", "至少登记一个固定版本"))
    elif unpinned:
        checks.append(PreflightCheck("Runtime 版本", "blocked", f"存在未固定版本：{', '.join(unpinned)}"))
    else:
        checks.append(PreflightCheck("Runtime 版本", "pass", "所有 Runtime 均已固定版本"))

    if any(check.status == "fail" for check in checks):
        status = "fail"
    elif any(check.status == "blocked" for check in checks):
        status = "blocked"
    else:
        status = "pass"
    return PreflightReport(status=status, checks=tuple(checks))


def main() -> int:
    parser = argparse.ArgumentParser(description="公司工作台私有部署 G0 预检")
    parser.add_argument("--example", action="store_true", help="使用空配置演示 fail-closed 输出")
    args = parser.parse_args()
    report = run_preflight({} if args.example else None)
    print(report.to_text())
    return 0 if report.status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
