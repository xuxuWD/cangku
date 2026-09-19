"""S2 沉淀入口（`workbench_run_promotions`，迁移 `042`）：**运行 → 任务**的沉淀链接。

性质（契约「运行沉淀（S2 · 存成任务）」）：

    - **链接语义**：本表只记「哪个运行沉淀成了哪个任务」；任务本身落既有任务仓储，
      与运行记录**级联**（运行记录被删只解除链接，任务不随之消失）；
    - **一个运行只能沉淀一次**：主键 `(tenant_id, run_id)` —— 先占位（`claim`）再建任务，
      占不到即读回既有行返回；建任务失败则 `release` 归还占位（不留悬挂链接）；
    - **标题快照只落本表**：不进审计明细（审计只记 `task_id`）。

跨租户拒写（既有手法）：PG 侧走**复合外键** `(tenant_id, run_id) → workbench_run_records`
（父表唯一约束由迁移 `027` 补齐）——租户不匹配时父行不存在 ⇒ 直接拒写，无需应用层判定。
"""

from __future__ import annotations

from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

MAX_PROMOTION_TITLE_LENGTH = 120


class RunPromotionError(ValueError):
    """入参不合法（服务端 fail-closed：宁可不沉淀，也不写半条 / 写错语义）。"""


def validate_promotion_title(title: str | None) -> str:
    """校验并归一任务标题（去首尾空白）；不合法即抛错，不猜测、不补默认标题。"""
    text = (title or "").strip()
    if not text:
        raise RunPromotionError("请填写任务标题")
    if len(text) > MAX_PROMOTION_TITLE_LENGTH:
        raise RunPromotionError(f"任务标题不超过 {MAX_PROMOTION_TITLE_LENGTH} 字")
    return text


@dataclass(frozen=True)
class RunPromotion:
    """一行沉淀链接（`tenant_id` 不得外泄给客户端）。"""

    tenant_id: str
    run_id: str
    task_id: str
    title: str
    promoted_by: str
    created_at: datetime

    def to_view(self) -> dict[str, object]:
        """对外视图：**不含** `tenant_id`。"""
        return {
            "task_id": self.task_id,
            "title": self.title,
            "promoted_by": self.promoted_by,
            "promoted_at": self.created_at,
        }


class RunPromotionStore(Protocol):
    """占位 / 读回 / 归还（内存实现与 PG 实现口径一致）。"""

    def claim(self, promotion: RunPromotion) -> tuple[RunPromotion, bool]: ...

    def find_for_run(self, tenant_id: str, run_id: str) -> RunPromotion | None: ...

    def release(self, tenant_id: str, run_id: str) -> bool: ...


class InMemoryRunPromotionStore:
    """内存实现（仅 development；口径与 PG 实现一致，含「一个运行只沉淀一次」）。"""

    def __init__(self) -> None:
        self._rows: dict[tuple[str, str], RunPromotion] = {}

    def claim(self, promotion: RunPromotion) -> tuple[RunPromotion, bool]:
        key = (promotion.tenant_id, promotion.run_id)
        existing = self._rows.get(key)
        if existing is not None:
            # 已被占：拿回**第一次**那行（不覆盖、不建第二条任务）。
            return existing, False
        self._rows[key] = promotion
        return promotion, True

    def find_for_run(self, tenant_id: str, run_id: str) -> RunPromotion | None:
        return self._rows.get((tenant_id, run_id))

    def release(self, tenant_id: str, run_id: str) -> bool:
        return self._rows.pop((tenant_id, run_id), None) is not None


class PostgresRunPromotionStore:
    """PG 实现（迁移 042）；跨租户写由**复合外键**拒绝（`(tenant_id, run_id)` 父行必须存在）。"""

    _COLUMNS = "tenant_id, run_id, task_id, title, promoted_by, created_at"

    def __init__(self, connection_or_pool: Any) -> None:
        self.connection = connection_or_pool

    @contextmanager
    def _connection(self):
        if hasattr(self.connection, "connection") and callable(self.connection.connection):
            with self.connection.connection() as connection:
                yield connection
        else:
            with nullcontext(self.connection) as connection:
                yield connection

    @staticmethod
    def _hydrate(row: tuple) -> RunPromotion:
        return RunPromotion(
            tenant_id=str(row[0]),
            run_id=str(row[1]),
            task_id=str(row[2]),
            title=str(row[3]),
            promoted_by=str(row[4]),
            created_at=row[5],
        )

    def claim(self, promotion: RunPromotion) -> tuple[RunPromotion, bool]:
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    # 占位：主键冲突 ⇒ 不写，随后读回既有行（与内存实现同语义）。
                    cursor.execute(
                        f"""
                        INSERT INTO workbench_run_promotions ({self._COLUMNS})
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (tenant_id, run_id) DO NOTHING
                        RETURNING {self._COLUMNS}
                        """,
                        (
                            promotion.tenant_id,
                            promotion.run_id,
                            promotion.task_id,
                            promotion.title,
                            promotion.promoted_by,
                            promotion.created_at,
                        ),
                    )
                    inserted = cursor.fetchone()
                    if inserted is not None:
                        return self._hydrate(inserted), True
                    cursor.execute(
                        f"""
                        SELECT {self._COLUMNS} FROM workbench_run_promotions
                        WHERE tenant_id = %s AND run_id = %s
                        """,
                        (promotion.tenant_id, promotion.run_id),
                    )
                    existing = cursor.fetchone()
        if existing is None:  # pragma: no cover - 冲突但读不回：状态不一致时如实报错，不伪造
            raise RunPromotionError("沉淀占位冲突但读回失败")
        return self._hydrate(existing), False

    def find_for_run(self, tenant_id: str, run_id: str) -> RunPromotion | None:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT {self._COLUMNS} FROM workbench_run_promotions
                    WHERE tenant_id = %s AND run_id = %s
                    """,
                    (tenant_id, run_id),
                )
                row = cursor.fetchone()
        return self._hydrate(row) if row is not None else None

    def release(self, tenant_id: str, run_id: str) -> bool:
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        "DELETE FROM workbench_run_promotions WHERE tenant_id = %s AND run_id = %s",
                        (tenant_id, run_id),
                    )
                    return bool(cursor.rowcount)