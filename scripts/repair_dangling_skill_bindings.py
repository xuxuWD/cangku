"""技能绑定「违规行」盘点与修复（第 11 轮专项，契约 `docs/contracts/skill-binding-gate-plan.md` §4）。

**用途**：第 11 轮给 `bind` 补了两条域内闸门（技能必须**存在**且**已启用**）——但闸门**只影响后续请求**，
历史上（第 9 轮真机取证）写入的**悬空绑定 / 未启用技能绑定**仍留在库里，会让绑定台账失真。
本脚本把这批行**盘点出来**，并在显式确认后把它们置为 `disabled`。

**安全约定（逐条）**：
1. **默认干跑**（dry-run）：只打印，不写任何数据；必须显式 `--apply` 才写；
2. **只改状态、绝不删除**：只执行 `UPDATE … SET status='disabled' … AND status='active'`（已 `disabled` 的行不动）；
3. **必须指定租户**（`--tenant`）：不做"全库一把改"；
4. **DSN 从环境变量取**（`WORKBENCH_DATABASE_URL`），**脚本内不出现任何连接串 / 凭据**；
5. 退出码：`0` = 无待修（或已应用）；`1` = 干跑发现待修行（需人工确认后 `--apply`）；`2` = 用法 / 连接错误。

**不做**：修「员工键不在数字员工目录」这一类（第 ③ 条闸门**本轮暂缓**，见专项方案 §7）——该类别只在报告里列出。

用法::

    # 只盘点（安全，默认）
    python scripts/repair_dangling_skill_bindings.py --tenant <tenant_id>

    # 确认后执行修复
    python scripts/repair_dangling_skill_bindings.py --tenant <tenant_id> --apply
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass

# 违规原因（受控枚举）
REASON_SKILL_MISSING = "skill_missing"
REASON_SKILL_NOT_ENABLED = "skill_not_enabled"

REASON_LABEL = {
    REASON_SKILL_MISSING: "技能包不存在（悬空绑定）",
    REASON_SKILL_NOT_ENABLED: "技能包没有任何已启用版本",
}


@dataclass(frozen=True)
class BindingRow:
    """待盘点的一行绑定（只取判定需要的字段）。"""

    agent_key: str
    skill_key: str
    status: str


def violation_reason(row: BindingRow, skill_statuses: dict[str, set[str]]) -> str | None:
    """该绑定行是否违反绑定闸门；返回原因或 `None`（合规）。

    - `skill_key` 在本租户**没有任何版本** ⇒ `skill_missing`；
    - 有版本但**没有 `enabled` 版本** ⇒ `skill_not_enabled`；
    - 其余 ⇒ 合规。

    刻意**不判**"员工键是否在目录"（第 ③ 条闸门暂缓，见模块 docstring）。
    """
    statuses = skill_statuses.get(row.skill_key)
    if not statuses:
        return REASON_SKILL_MISSING
    if "enabled" not in statuses:
        return REASON_SKILL_NOT_ENABLED
    return None


def find_violations(
    rows: list[BindingRow], skill_statuses: dict[str, set[str]]
) -> tuple[list[BindingRow], list[BindingRow]]:
    """返回 `(待修行, 仅报告行)`。

    - 待修 = **`active` 且违规**（这些才真正生效，需要收口）；
    - 仅报告 = 违规但已 `disabled`（历史行，不生效，不动它）。
    """
    pending: list[BindingRow] = []
    report_only: list[BindingRow] = []
    for row in rows:
        if violation_reason(row, skill_statuses) is None:
            continue
        (pending if row.status == "active" else report_only).append(row)
    return pending, report_only


# ------------------------------------------------------------ 数据库层（薄，仅两条只读 + 一条写）


def _connect(dsn: str):
    from psycopg import connect  # 延迟导入：单元测试只测纯函数，不需要驱动

    return connect(dsn, autocommit=False)


def load_rows(connection, tenant_id: str) -> list[BindingRow]:
    """盘点 SQL（只读）：本租户全部绑定行。"""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT agent_key, skill_key, status FROM workbench_skill_bindings WHERE tenant_id = %s",
            (tenant_id,),
        )
        return [BindingRow(agent_key=str(a), skill_key=str(s), status=str(st)) for a, s, st in cursor.fetchall()]


def load_skill_statuses(connection, tenant_id: str) -> dict[str, set[str]]:
    """技能侧状态表（只读）：`skill_key -> {该 key 全部版本的状态}`。"""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT skill_key, status FROM workbench_skills WHERE tenant_id = %s",
            (tenant_id,),
        )
        grouped: dict[str, set[str]] = {}
        for skill_key, status in cursor.fetchall():
            grouped.setdefault(str(skill_key), set()).add(str(status))
        return grouped


def disable_rows(connection, tenant_id: str, rows: list[BindingRow]) -> int:
    """把待修行置为 `disabled`（**只改状态**；`RETURNING` 计数用于核对）。"""
    changed = 0
    for row in rows:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE workbench_skill_bindings
                SET status = 'disabled'
                WHERE tenant_id = %s AND agent_key = %s AND skill_key = %s AND status = 'active'
                RETURNING agent_key
                """,
                (tenant_id, row.agent_key, row.skill_key),
            )
            changed += len(cursor.fetchall())
    return changed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="技能绑定违规行盘点与修复（默认干跑；只改状态、不删除）")
    parser.add_argument("--tenant", required=True, help="租户标识（必填：不做全库一把改）")
    parser.add_argument("--apply", action="store_true", help="确认执行修复（缺省只盘点）")
    parser.add_argument("--dsn-env", default="WORKBENCH_DATABASE_URL", help="读取 DSN 的环境变量名")
    args = parser.parse_args(argv)

    dsn = os.environ.get(args.dsn_env)
    if not dsn:
        print(f"[错误] 环境变量 {args.dsn_env} 未设置（脚本内不内置任何连接串/凭据）", file=sys.stderr)
        return 2

    try:
        connection = _connect(dsn)
    except Exception as exc:  # noqa: BLE001 连接失败如实报错，不吞
        print(f"[错误] 数据库连接失败：{exc}", file=sys.stderr)
        return 2

    try:
        rows = load_rows(connection, args.tenant)
        skill_statuses = load_skill_statuses(connection, args.tenant)
        pending, report_only = find_violations(rows, skill_statuses)

        print(f"租户 {args.tenant}：绑定行 {len(rows)} 条；技能键 {len(skill_statuses)} 个")
        for row in pending:
            reason = violation_reason(row, skill_statuses)
            print(f"  [待修] {row.agent_key} ↔ {row.skill_key}（生效中）：{REASON_LABEL[reason]}")
        for row in report_only:
            reason = violation_reason(row, skill_statuses)
            print(f"  [仅报告-不生效] {row.agent_key} ↔ {row.skill_key}（已解除）：{REASON_LABEL[reason]}")

        if not pending:
            print("没有需要修复的行（干跑与实跑都不会改动任何数据）。")
            return 0

        if not args.apply:
            print(f"干跑结束：发现 {len(pending)} 条待修行。确认无误后加 --apply 执行（只改状态、不删除）。")
            return 1

        changed = disable_rows(connection, args.tenant, pending)
        connection.commit()
        print(f"已把 {changed} 条绑定置为已解除（期望 {len(pending)} 条）。")
        return 0
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())