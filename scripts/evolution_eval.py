"""P6a 自进化·评测集运维命令（规格 2026-09-16-self-evolution-p6-design.md V1/V2）。

子命令
    import-regression  导入内置**回归锁定基线**（套件 runtime-safety，固定 case_id，幂等；默认 dry-run）
    run                离线执行一个套件的已发布用例（受评对象 v1 = runtime-safety-probe；写运行与逐例结果）
    collect            只读采集「被拦截」的运行轨迹（审计 tool.blocked / knowledge.search.blocked）
                       → **草稿**用例（期望待专家补全后才能发布；默认 dry-run）

安全
    - **fail-closed**：`WORKBENCH_EVOLUTION_ENABLED=false`（默认）时**拒绝执行**（退出码 1）；
    - 写操作默认 dry-run（`import-regression` / `collect`），加 `--apply` 才写库；`run` 本身就是执行动作，
      会写评测运行与逐例结果（这是它的产物）；
    - 仅 **PostgreSQL** 后端；迁移由 API 进程负责（本脚本 **不跑迁移**，与 N1 导入脚本同口径）；
    - 操作者必须是 super_admin：`--actor-id` 写入审计（actor），不打印任何用例内容或凭据。

退出码：成功（含 dry-run）→ 0；配置 / 运行失败 → 1；参数错误 → 2（argparse 默认）。

用法
    py scripts/evolution_eval.py import-regression --tenant-id t-1 --actor-id admin-1
    py scripts/evolution_eval.py import-regression --tenant-id t-1 --actor-id admin-1 --apply
    py scripts/evolution_eval.py run --tenant-id t-1 --actor-id admin-1 --suite runtime-safety --repeats 3
    py scripts/evolution_eval.py collect --tenant-id t-1 --actor-id admin-1 --limit 50 --apply
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.evolution.collector import collect_blocked_case_specs
from app.evolution.models import EvalError
from app.evolution.regression import regression_case_specs
from app.domain import PolicyError, UserContext


def _target_hint() -> str:
    """目标库提示：只暴露主机与库名（不含凭据）。"""
    from app.settings import get_settings
    from urllib.parse import urlsplit

    settings = get_settings()
    parsed = urlsplit(settings.database_url.replace("postgresql+psycopg://", "postgresql://", 1))
    database = parsed.path.lstrip("/") or "(未配置库名)"
    return f"{parsed.hostname or '(未配置主机)'}:{parsed.port or 5432}/{database}"


def _build_service(*, with_audit: bool = True):
    """装配评测服务（**仅 postgres**；显式传 store ⇒ 复用连接且**不跑迁移**——迁移由 API 进程负责）。"""
    from app.bootstrap import build_audit_service, build_evolution_service
    from app.evolution.store import PostgresEvalStore
    from app.settings import get_settings

    settings = get_settings()
    if not settings.evolution_enabled:
        raise ValueError(
            "自进化评测组件未启用（WORKBENCH_EVOLUTION_ENABLED=false）——拒绝执行（fail-closed）"
        )
    if settings.storage_backend != "postgres":
        raise ValueError("评测集运维命令必须使用 PostgreSQL 后端（内存后端不承接评测运行）")
    from psycopg_pool import ConnectionPool

    database_url = settings.database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    pool = ConnectionPool(database_url, min_size=1, max_size=2, open=True)
    audit = build_audit_service(settings, connection=pool, migrate=False) if with_audit else None
    service = build_evolution_service(settings, store=PostgresEvalStore(pool), audit=audit)
    if service is None:  # pragma: no cover —— 开关已在上方拦截，此处仅为类型收窄
        raise ValueError("自评测组件未装配")
    return service, pool


def _admin_context(args: argparse.Namespace) -> UserContext:
    return UserContext(args.tenant_id, args.actor_id, "super_admin")


def _cmd_import_regression(args: argparse.Namespace) -> int:
    service, _pool = _build_service()
    context = _admin_context(args)
    specs = regression_case_specs()
    if not args.apply:
        print(f"[dry-run] 将导入回归基线 {len(specs)} 条（套件 runtime-safety；已存在则跳过）")
        for spec in specs:
            print(f"  - {spec.case_id}（期望 {spec.expectation['expect']}）")
        return 0
    created, skipped = service.import_cases(context, specs, publish=True)
    print(f"回归基线导入完成：新建 {len(created)} 条 / 跳过（已存在）{len(skipped)} 条（已发布）")
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    service, _pool = _build_service()
    context = _admin_context(args)
    run = service.run_eval(
        context, subject_name=args.subject, suite_key=args.suite, repeats=args.repeats
    )
    print(
        f"评测完成：run={run.eval_run_id} subject={run.subject} suite={run.suite_key} "
        f"用例 {run.case_count} 通过 {run.pass_count} 费用 {run.cost_cents} 分 状态={run.status.value}"
    )
    print(f"  用例集指纹 suite_digest={run.suite_digest}")
    return 0


def _cmd_collect(args: argparse.Namespace) -> int:
    from app.bootstrap import build_audit_service
    from app.settings import get_settings

    settings = get_settings()
    if not settings.evolution_enabled:
        raise ValueError(
            "自进化评测组件未启用（WORKBENCH_EVOLUTION_ENABLED=false）——拒绝执行（fail-closed）"
        )
    # 采集是**只读**：用独立审计仓储读取，不装配写路径。
    from psycopg_pool import ConnectionPool

    database_url = settings.database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    pool = ConnectionPool(database_url, min_size=1, max_size=2, open=True)
    audit = build_audit_service(settings, connection=pool, migrate=False)
    specs = collect_blocked_case_specs(audit, args.tenant_id, limit=args.limit)
    if not specs:
        print("未采集到可用的拦截记录（tool.blocked / knowledge.search.blocked）")
        return 0
    if not args.apply:
        print(f"[dry-run] 将采集 {len(specs)} 条**草稿**用例（期望待专家补全后才能发布）")
        for spec in specs:
            print(f"  - 套件 {spec.suite_key}（来源 {spec.source.value}）")
        return 0
    service, _pool = _build_service()
    created, skipped = service.import_cases(_admin_context(args), specs, publish=False)
    print(f"采集落库：新建草稿 {len(created)} 条 / 跳过（已存在）{len(skipped)} 条")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="P6a 评测集运维命令（默认 dry-run；--apply 才写库）")
    sub = parser.add_subparsers(dest="command", required=True)

    def _common(target: argparse.ArgumentParser) -> None:
        target.add_argument("--tenant-id", required=True, help="目标租户")
        target.add_argument("--actor-id", required=True, help="操作人账号 id（写入审计 actor；必须是 super_admin）")

    imp = sub.add_parser("import-regression", help="导入内置回归锁定基线（幂等）")
    _common(imp)
    imp.add_argument("--apply", action="store_true", help="真正写库（缺省 dry-run）")
    imp.set_defaults(handler=_cmd_import_regression)

    run = sub.add_parser("run", help="离线执行一个套件（写评测运行与逐例结果）")
    _common(run)
    run.add_argument("--subject", required=True, help="受评对象（v1：runtime-safety-probe）")
    run.add_argument("--suite", required=True, help="套件键（如 runtime-safety）")
    run.add_argument("--repeats", type=int, default=1, help="重复次数（1–10；不稳定用例以最差一次计入）")
    run.set_defaults(handler=_cmd_run)

    collect = sub.add_parser("collect", help="只读采集拦截轨迹 → 草稿用例（幂等）")
    _common(collect)
    collect.add_argument("--limit", type=int, default=50, help="每类动作用于采集的审计条数上限")
    collect.add_argument("--apply", action="store_true", help="真正写库（缺省 dry-run）")
    collect.set_defaults(handler=_cmd_collect)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    print(f"目标库：{_target_hint()}")
    try:
        return int(args.handler(args))
    except (ValueError, PolicyError, EvalError) as exc:
        print(f"执行失败：{exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())