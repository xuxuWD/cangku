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
        "database_url": os.getenv("WORKBENCH_DATABASE_URL", ""),
        "backup_key": os.getenv("WORKBENCH_BACKUP_ENCRYPTION_KEY", ""),
        "applied_migrations": applied,
        "expected_migrations": expected,
        "retention_policy": json_env("WORKBENCH_RETENTION_POLICY", {}),
        "runtime_versions": json_env("WORKBENCH_RUNTIME_VERSIONS", {}),
    }


def run_preflight(config: Mapping[str, object] | None = None) -> PreflightReport:
    values = _as_mapping(config)
    checks: list[PreflightCheck] = []

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
