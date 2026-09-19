"""保留策略**清理原语**（B-4 选项 C，2026-09-19）：运行域 / 任务域 / 提案域的按龄物理删除。

依据：`docs/superpowers/specs/2026-09-19-retention-executor-design.md`（实施计划）+ 用户裁决
「B-4 = 选项 C」；对外口径见 `docs/api-contract.md`「保留策略执行口径」。

**为什么把三域的删除集中在一个适配器里**（而不是让各业务模块各删自己那张表）：

- 运行域跨 **7 张表**，其中 5 张子表持 `(tenant_id, run_id)` 复合外键且**无 `ON DELETE CASCADE`**
  （027 工具动作 / 执行幂等、037 产物登记、040 验收决议；042 沉淀链接有 CASCADE 但仍显式删，
  保持顺序统一）⇒ 必须**先子后父**，且要在**同一事务**里完成：否则故障时会出现
  「子表已删、父表还在」（或反之）的中间态被外部观察到；
- 任务域的删除带**防孤儿谓词**（`workbench_run_records.task_id` 无外键），与运行域删除**同轮同事务**
  才能保证「本轮删掉的运行不会让任务判定读到过期快照」；
- 让 `PostgresRunRecordStore` 等既有仓储去删别的模块的表，会把跨模块 SQL 塞进各业务模块 ——
  删除原语归生命周期域持有（计划 §3.4），业务仓储的公开契约保持不变。

**内存模式不装配本通道**（服务层 fail-closed）：内存 `TaskStore` 的 `Task` **没有创建时间字段**
⇒ 无法判定任务年龄；**不做**「把全部任务当过期」这类危险近似（那会变成「一调用就清空」）。
worker 本身要求 PostgreSQL（`configure_runtime` 拒绝非 PG），生产恒为真库实现。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol

# 每面每轮的删除上限（有界：单事务/单轮不无限大，剩余留待下一轮）。量级与既有清理器同口径。
RETENTION_PURGE_LIMIT = 5000

# 「全龄」截止时刻：租户删除（B2+B3）用它与按龄清理**共用同一套删除 SQL**（不过滤年龄 ⇒ 全清）。
# 取 Python 的 `datetime.max`（9999-12-31，在 `TIMESTAMPTZ` 取值域内）⇒ `started_at < cutoff` /
# `created_at < cutoff` 恒真，且调用方不必为「不过滤」另写一套语句。
ALL_AGES_CUTOFF = datetime.max.replace(tzinfo=UTC)

# 运行域子表 → **删除顺序**（先子后父，顺序即本元组次序）；返回计数用的键名与之对应。
RUN_DOMAIN_CHILD_TABLES: tuple[tuple[str, str], ...] = (
    ("workbench_run_artifacts", "run_artifacts"),
    ("workbench_run_acceptance_decisions", "run_acceptance_decisions"),
    ("workbench_run_promotions", "run_promotions"),
    ("workbench_tool_actions", "tool_actions"),
    ("workbench_execution_idempotency", "execution_idempotency"),
    ("workbench_runtime_states", "runtime_states"),
)

# 提案域（按 `created_at` 龄删；`proposal_id` 为主键，用作有界子查询的排序/去重键）。
# ⚠️ `workbench_plan_versions` **不在此列**：它是商业化套餐版本目录（006），不是运行期数据 ——
# 计划文档初稿把它误归入「提案域」，实施期勘误（见计划文档 §3.2 与契约）。
PROPOSAL_TABLES: tuple[tuple[str, str], ...] = (
    ("workbench_plan_proposals", "plan_proposals"),
    ("workbench_orchestration_proposals", "orchestration_proposals"),
)


class RetentionPurgeStore(Protocol):
    def purge_expired_for_tenant(
        self, tenant_id: str, *, cutoff: datetime, limit: int = RETENTION_PURGE_LIMIT
    ) -> dict[str, int]: ...


class PostgresRetentionPurgeStore:
    """真库清理原语：**每租户一轮、同一事务**完成「选过期运行 → 先子后父 → 提案域 → 任务域」。

    返回逐表计数（`runs` = `workbench_run_records` 行数；其余键见上两张表常量）。
    ⚠️ **不触碰**：`workbench_runtime_events`（属 `events` 面，全局 30 天清理器负责）、
    流帧/流状态（属实时流保留期）、任何**审计表**（审计不可删除）。
    """

    def __init__(self, connection_or_pool) -> None:
        self.connection = connection_or_pool

    def _connection(self):
        from contextlib import nullcontext
        if hasattr(self.connection, "connection") and callable(self.connection.connection):
            return self.connection.connection()
        return nullcontext(self.connection)

    def purge_expired_for_tenant(
        self, tenant_id: str, *, cutoff: datetime, limit: int = RETENTION_PURGE_LIMIT
    ) -> dict[str, int]:
        counts: dict[str, int] = {
            "runs": 0,
            **{key: 0 for _table, key in RUN_DOMAIN_CHILD_TABLES},
            "tasks": 0,
            **{key: 0 for _table, key in PROPOSAL_TABLES},
        }
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    # ① 过期运行：先选出**确定的有界集合**（顺序确定，避免每次清到不同的行）。
                    cursor.execute(
                        """
                        SELECT run_id FROM workbench_run_records
                        WHERE tenant_id = %s AND started_at < %s
                        ORDER BY started_at, run_id
                        LIMIT %s
                        """,
                        (tenant_id, cutoff, limit),
                    )
                    run_ids = [str(row[0]) for row in cursor.fetchall()]
                    if run_ids:
                        # ② 先子后父（顺序即 RUN_DOMAIN_CHILD_TABLES 次序；漏一张子表 ⇒ 外键直接拒绝删父行）。
                        for table, key in RUN_DOMAIN_CHILD_TABLES:
                            cursor.execute(
                                f"DELETE FROM {table} WHERE tenant_id = %s AND run_id = ANY(%s)",
                                (tenant_id, run_ids),
                            )
                            counts[key] = int(cursor.rowcount)
                        cursor.execute(
                            "DELETE FROM workbench_run_records WHERE tenant_id = %s AND run_id = ANY(%s)",
                            (tenant_id, run_ids),
                        )
                        counts["runs"] = int(cursor.rowcount)
                    # ③ 提案域：按龄有界删除（避免任务被删后留下孤儿提案）。
                    for table, key in PROPOSAL_TABLES:
                        cursor.execute(
                            f"""
                            DELETE FROM {table}
                            WHERE tenant_id = %s AND proposal_id IN (
                                SELECT proposal_id FROM {table}
                                WHERE tenant_id = %s AND created_at < %s
                                ORDER BY created_at, proposal_id
                                LIMIT %s
                            )
                            """,
                            (tenant_id, tenant_id, cutoff, limit),
                        )
                        counts[key] = int(cursor.rowcount)
                    # ④ 任务域：**仅当该任务的运行（若有）全部已过期时才删** —— 直接删任务会留下
                    #    悬挂运行（`workbench_run_records.task_id` 无外键，真源未要求级联）。
                    cursor.execute(
                        """
                        DELETE FROM workbench_tasks
                        WHERE tenant_id = %s AND id IN (
                            SELECT t.id FROM workbench_tasks t
                            WHERE t.tenant_id = %s AND t.created_at < %s
                              AND NOT EXISTS (
                                  SELECT 1 FROM workbench_run_records r
                                  WHERE r.tenant_id = t.tenant_id AND r.task_id = t.id
                                    AND r.started_at >= %s
                              )
                            ORDER BY t.created_at, t.id
                            LIMIT %s
                        )
                        """,
                        (tenant_id, tenant_id, cutoff, cutoff, limit),
                    )
                    counts["tasks"] = int(cursor.rowcount)
        return counts

    def purge_all_for_tenant(self, tenant_id: str, *, limit: int = RETENTION_PURGE_LIMIT) -> dict[str, int]:
        """**租户删除（B2+B3）**：把本租户的任务域 / 提案域 / 运行域**整层**清空（不分年龄）。

        与 `purge_expired_for_tenant`（保留策略执行器，按龄）**共用同一套删除 SQL 与顺序**，
        差异只有两处：

        ① 截止时刻取 `ALL_AGES_CUTOFF`（等价「不过滤年龄」）⇒ 该租户的全部任务 / 提案 / 运行都命中；
        ② **额外清 `workbench_runtime_events`** —— 按龄清理**不碰**它（属 `events` 面，由全局 30 天清理器
           负责），但租户删除是「整租户销毁」⇒ 运行事件作为租户数据一并清。

        **分批循环**直到一轮无任何删除为止（每轮 ≤ `limit` 行/面，避免单事务过大）；每轮内部仍是
        「先子后父 + 任务防孤儿谓词」的**同一事务**。终止性：每轮要么删除 ≥1 行、要么全零返回 ⇒ 必然收敛。
        """
        totals = {
            "runs": 0,
            **{key: 0 for _table, key in RUN_DOMAIN_CHILD_TABLES},
            "tasks": 0,
            **{key: 0 for _table, key in PROPOSAL_TABLES},
            "runtime_events": 0,
        }
        while True:
            batch = self.purge_expired_for_tenant(tenant_id, cutoff=ALL_AGES_CUTOFF, limit=limit)
            for key, value in batch.items():
                totals[key] = totals.get(key, 0) + value
            if not any(batch.values()):
                break
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        "DELETE FROM workbench_runtime_events WHERE tenant_id = %s",
                        (tenant_id,),
                    )
                    totals["runtime_events"] = int(cursor.rowcount)
        return totals

    def delete_all_for_tenant(self, tenant_id: str) -> int:
        """`TenantPurgeStore` 口径别名（供租户删除的清场面循环调用）：= `purge_all_for_tenant`。

        返回删除行数**合计**（含运行事件）；逐表计数由 `purge_all_for_tenant` 提供（取证用）。
        """
        return sum(self.purge_all_for_tenant(tenant_id).values())