"""待批动作 / 逐项授权项仓储 `workbench_tool_actions`（迁移 027，规格 §4.1.1）。

双实现范式照 `app/runtime/records.py`：Protocol + InMemory（测试）+ Postgres（生产）。
写入即校验迁移 027 的两条结构性约束：
    - `body_ciphertext` 与 `body_expires_at` **同有同无**（`body_check`）；
    - `reason_code` 只能是 9 值受控枚举（§3.4 与 §4.1.1 同一集合）。
"""

from __future__ import annotations

import json
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from threading import RLock
from typing import Protocol

from ..domain import RiskLevel

# §4.1.6-8：审批超时置 `expired` 时的**受控常量**（不得来自请求体）。
EXPIRY_DECIDED_BY = "system:approval-timeout"
EXPIRY_DECISION_SOURCE = "timeout"


class ReasonCode(StrEnum):
    """受控枚举码（9 值）；自由文本一律不得落库 / 落审计。"""

    PATH_DENIED = "path_denied"
    BLACKLISTED = "blacklisted"
    PARAM_INVALID = "param_invalid"
    NOT_AUTHORIZED = "not_authorized"
    NOT_IN_CATALOG = "not_in_catalog"
    TIMEOUT = "timeout"
    RUNTIME_ERROR = "runtime_error"
    APPROVAL_DENIED = "approval_denied"
    APPROVAL_EXPIRED = "approval_expired"


class ToolActionStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class ToolActionNotFound(LookupError):
    """工具动作不存在或不属于当前租户。"""


@dataclass(frozen=True)
class ToolAction:
    """`workbench_tool_actions` 一行（字段与迁移 027 一一对应）。"""

    tenant_id: str
    action_id: str
    run_id: str
    task_id: str
    step_id: str
    tool_key: str
    args_digest: str
    args_json: dict
    plan_digest: str
    risk_level: RiskLevel
    requires_approval: bool
    status: ToolActionStatus
    requested_by: str
    requested_at: datetime
    approval_id: str | None = None
    body_ciphertext: bytes | None = None
    body_expires_at: datetime | None = None
    decided_by: str | None = None
    decided_at: datetime | None = None
    decision_source: str | None = None
    reason_code: ReasonCode | None = None


def _validate(action: ToolAction) -> None:
    if (action.body_ciphertext is None) != (action.body_expires_at is None):
        raise ValueError("body_ciphertext 与 body_expires_at 必须同有同无（迁移 027 body_check）")
    if action.reason_code is not None:
        try:
            ReasonCode(action.reason_code)
        except ValueError as exc:
            raise ValueError("reason_code 不在 9 值受控枚举内") from exc
    pending = action.status is ToolActionStatus.PENDING
    decided = action.decided_by is not None or action.decided_at is not None
    if pending and decided:
        raise ValueError("pending 行不得带决议列（迁移 027 decision_check）")
    if not pending and (action.decided_by is None or action.decided_at is None):
        raise ValueError("非 pending 行必须同时带 decided_by 与 decided_at（迁移 027 decision_check）")


def expire_row(action: ToolAction) -> ToolAction:
    """把一行 `pending` 待批动作按 §4.1.6-8 置为 `expired`（同事务三件事的**单一口径**）。

    ① `status='expired'`；② `decided_by` / `decided_at=到期时刻` / `decision_source` 取受控常量；
    ③ 清空 `body_ciphertext` 与 `body_expires_at`。**不得只清密文不改状态**——否则该行仍为
    `pending`，一旦被批准将无正文可还原（§4.1.6-8 末句）。
    """
    return replace(
        action,
        status=ToolActionStatus.EXPIRED,
        decided_by=EXPIRY_DECIDED_BY,
        decided_at=action.body_expires_at,
        decision_source=EXPIRY_DECISION_SOURCE,
        body_ciphertext=None,
        body_expires_at=None,
    )


def is_due(action: ToolAction, *, now: datetime) -> bool:
    """该行是否「已到期」：仅 `pending` 且带到期时刻且 `body_expires_at <= now`（未到期绝不动）。"""
    return (
        action.status is ToolActionStatus.PENDING
        and action.body_expires_at is not None
        and action.body_expires_at <= now
    )


class ToolActionStore(Protocol):
    def upsert(self, action: ToolAction) -> ToolAction: ...
    def get(self, tenant_id: str, action_id: str) -> ToolAction: ...
    def list_for_run(self, tenant_id: str, run_id: str) -> list[ToolAction]: ...
    def find_approved(
        self, *, tenant_id: str, run_id: str, approval_id: str
    ) -> ToolAction | None: ...
    def expire_pending_bodies(self, *, now: datetime) -> list[ToolAction]: ...


class InMemoryToolActionStore:
    """开发 / 测试用内存仓储；同 (tenant_id, action_id) 覆盖写。"""

    def __init__(self) -> None:
        self._items: dict[tuple[str, str], ToolAction] = {}
        self._lock = RLock()

    def upsert(self, action: ToolAction) -> ToolAction:
        _validate(action)
        with self._lock:
            self._items[(action.tenant_id, action.action_id)] = action
            return action

    def get(self, tenant_id: str, action_id: str) -> ToolAction:
        with self._lock:
            item = self._items.get((tenant_id, action_id))
        if item is None:
            raise ToolActionNotFound(action_id)
        return item

    def list_for_run(self, tenant_id: str, run_id: str) -> list[ToolAction]:
        with self._lock:
            return [
                item
                for item in self._items.values()
                if item.tenant_id == tenant_id and item.run_id == run_id
            ]

    def find_approved(
        self, *, tenant_id: str, run_id: str, approval_id: str
    ) -> ToolAction | None:
        with self._lock:
            for item in self._items.values():
                if (
                    item.tenant_id == tenant_id
                    and item.run_id == run_id
                    and item.approval_id == approval_id
                    and item.status is ToolActionStatus.APPROVED
                ):
                    return item
        return None

    def expire_pending_bodies(self, *, now: datetime) -> list[ToolAction]:
        """到期（`body_expires_at <= now`）的 `pending` 行 → `expired` + 清空密文两列；返回被清理行。

        返回被清理的行本身（已置 `expired`），供调用方按既有动作码留审计证据（§4.1.7-6）。
        幂等：非 `pending`（已判决 / 已过期）与未到期行一律不动；重复调用第二次返回空列表。
        跨租户全量清扫（这是系统级后台任务，不属任何单一租户请求），**只动到期行**。
        """
        expired: list[ToolAction] = []
        with self._lock:
            for key, item in list(self._items.items()):
                if not is_due(item, now=now):
                    continue
                updated = expire_row(item)
                _validate(updated)
                self._items[key] = updated
                expired.append(updated)
        return expired


class PostgresToolActionStore:
    """`workbench_tool_actions` 持久化；主键 (tenant_id, action_id) 冲突时覆盖更新。"""

    _COLUMNS = (
        "tenant_id, action_id, approval_id, run_id, task_id, step_id, tool_key, "
        "args_digest, args_json, body_ciphertext, body_expires_at, plan_digest, "
        "risk_level, requires_approval, status, requested_by, requested_at, "
        "decided_by, decided_at, decision_source, reason_code"
    )
    _PLACEHOLDERS = (
        "%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, "
        "%s, %s, %s, %s, %s, %s, %s, %s, %s"
    )

    def __init__(self, connection_or_pool) -> None:
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
    def _hydrate(row: tuple) -> ToolAction:
        raw_args = row[8]
        if isinstance(raw_args, str):
            raw_args = json.loads(raw_args)
        ciphertext = row[9]
        return ToolAction(
            tenant_id=str(row[0]),
            action_id=str(row[1]),
            approval_id=row[2],
            run_id=str(row[3]),
            task_id=str(row[4]),
            step_id=str(row[5]),
            tool_key=str(row[6]),
            args_digest=str(row[7]),
            args_json=dict(raw_args or {}),
            body_ciphertext=bytes(ciphertext) if ciphertext is not None else None,
            body_expires_at=row[10],
            plan_digest=str(row[11]),
            risk_level=RiskLevel(str(row[12])),
            requires_approval=bool(row[13]),
            status=ToolActionStatus(str(row[14])),
            requested_by=str(row[15]),
            requested_at=row[16],
            decided_by=row[17],
            decided_at=row[18],
            decision_source=row[19],
            reason_code=ReasonCode(str(row[20])) if row[20] else None,
        )

    @staticmethod
    def _params(action: ToolAction) -> tuple:
        return (
            action.tenant_id,
            action.action_id,
            action.approval_id,
            action.run_id,
            action.task_id,
            action.step_id,
            action.tool_key,
            action.args_digest,
            json.dumps(action.args_json, ensure_ascii=False),
            action.body_ciphertext,
            action.body_expires_at,
            action.plan_digest,
            action.risk_level.value,
            action.requires_approval,
            action.status.value,
            action.requested_by,
            action.requested_at,
            action.decided_by,
            action.decided_at,
            action.decision_source,
            action.reason_code.value if action.reason_code else None,
        )

    def upsert(self, action: ToolAction) -> ToolAction:
        _validate(action)
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""
                        INSERT INTO workbench_tool_actions ({self._COLUMNS})
                        VALUES ({self._PLACEHOLDERS})
                        ON CONFLICT (tenant_id, action_id) DO UPDATE SET
                            approval_id = EXCLUDED.approval_id,
                            run_id = EXCLUDED.run_id,
                            task_id = EXCLUDED.task_id,
                            step_id = EXCLUDED.step_id,
                            tool_key = EXCLUDED.tool_key,
                            args_digest = EXCLUDED.args_digest,
                            args_json = EXCLUDED.args_json,
                            body_ciphertext = EXCLUDED.body_ciphertext,
                            body_expires_at = EXCLUDED.body_expires_at,
                            plan_digest = EXCLUDED.plan_digest,
                            risk_level = EXCLUDED.risk_level,
                            requires_approval = EXCLUDED.requires_approval,
                            status = EXCLUDED.status,
                            requested_by = EXCLUDED.requested_by,
                            requested_at = EXCLUDED.requested_at,
                            decided_by = EXCLUDED.decided_by,
                            decided_at = EXCLUDED.decided_at,
                            decision_source = EXCLUDED.decision_source,
                            reason_code = EXCLUDED.reason_code
                        RETURNING {self._COLUMNS}
                        """,
                        self._params(action),
                    )
                    row = cursor.fetchone()
        if row is None:
            raise ToolActionNotFound(action.action_id)
        return self._hydrate(row)

    def get(self, tenant_id: str, action_id: str) -> ToolAction:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT {self._COLUMNS} FROM workbench_tool_actions
                    WHERE tenant_id = %s AND action_id = %s
                    """,
                    (tenant_id, action_id),
                )
                row = cursor.fetchone()
        if row is None:
            raise ToolActionNotFound(action_id)
        return self._hydrate(row)

    def list_for_run(self, tenant_id: str, run_id: str) -> list[ToolAction]:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT {self._COLUMNS} FROM workbench_tool_actions
                    WHERE tenant_id = %s AND run_id = %s ORDER BY requested_at
                    """,
                    (tenant_id, run_id),
                )
                rows = cursor.fetchall()
        return [self._hydrate(row) for row in rows]

    def find_approved(
        self, *, tenant_id: str, run_id: str, approval_id: str
    ) -> ToolAction | None:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT {self._COLUMNS} FROM workbench_tool_actions
                    WHERE tenant_id = %s AND run_id = %s AND approval_id = %s
                      AND status = 'approved'
                    """,
                    (tenant_id, run_id, approval_id),
                )
                row = cursor.fetchone()
        return self._hydrate(row) if row is not None else None

    def expire_pending_bodies(self, *, now: datetime) -> list[ToolAction]:
        """到期行 → `expired` + 清空密文两列（单条 UPDATE，**一个事务**，§4.1.6-8）。

        `RETURNING` 回传被清理的行本身，供调用方按既有动作码留审计证据（§4.1.7-6）。
        只命中 `status='pending' AND body_expires_at <= now`：
        * **未到期的绝不动**（`body_expires_at > now` 不在集合内）；
        * 非 `pending` 行（含已 `approved`）不动——并发决议与清扫互不覆盖（首写先落者胜，
          另一方的 `WHERE status='pending'` 不再命中）；
        * **幂等**：重复执行第二次无命中、返回空列表，不误删、不报错。
        `decided_at` 取 **本行的到期时刻**（`body_expires_at`），不取 `now`（§4.1.6-8②）。
        """
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""
                        UPDATE workbench_tool_actions
                        SET status = %s,
                            decided_by = %s,
                            decided_at = body_expires_at,
                            decision_source = %s,
                            body_ciphertext = NULL,
                            body_expires_at = NULL
                        WHERE status = %s
                          AND body_expires_at IS NOT NULL
                          AND body_expires_at <= %s
                        RETURNING {self._COLUMNS}
                        """,
                        (
                            ToolActionStatus.EXPIRED.value,
                            EXPIRY_DECIDED_BY,
                            EXPIRY_DECISION_SOURCE,
                            ToolActionStatus.PENDING.value,
                            now,
                        ),
                    )
                    rows = cursor.fetchall()
        return [self._hydrate(row) for row in rows]
