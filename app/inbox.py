"""站内通知（收件箱）。

职责
    把「等待结果的人需要知道的结果」落成可查询的收件箱条目（审批结果、需人工接管的失败）。
    只承载「发生了什么 + 去哪看」：**不存事件正文、detail、手机号或客户原文**，
    文案由服务端按固定模板生成（见 `_TITLES`）。

接收人约定
    接收人一律是**等待结果的人**（发起人/申请人），不是审批人——审批人走既有
    「待我审批」聚合接口（`app/approvals.py`）。`UserContext.user_id` 即账号 ID
    （`AccountService.login` 以 `account_id` 作为 user_id），因此写入与查询天然对齐。

存储与保留期
    - 内存实现（开发）与 PostgreSQL 实现（表 `workbench_inbox_items`，迁移 019）。
    - 默认保留 90 天（``WORKBENCH_INBOX_RETENTION_DAYS`` 可覆盖）；过期条目在写入/读取时
      **惰性清理**（仿 `app/sessions.py`），不引入定时任务。

失败策略
    通知**不是关键路径**：写入失败不阻断业务，但必须写一条审计 ``inbox.write_failed``
    （可观测的降级，不静默吞掉）。

非目标（如实登记）
    - Web Push / 短信 / 邮件；经 Outbox 异步投递（该链路未在真实环境跑通）。
    - **运行失败通知暂不实现**：运行终态当前从未落盘（只有启动快照被记录），
      待运行链路补齐终态采集后再做（见 `docs/delivery-readiness-checklist.md` E 节）。
"""

from __future__ import annotations

from contextlib import contextmanager, nullcontext
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from threading import RLock
from typing import Protocol
from uuid import uuid4

from .audit.models import AuditAction

DEFAULT_RETENTION_DAYS = 90
_MAX_LIMIT = 200


class InboxKind(StrEnum):
    """通知类型；与客户端展示、文案模板一一对应。"""

    TASK_APPROVED = "task.approved"
    PLAN_APPROVED = "plan.approved"
    PLAN_REJECTED = "plan.rejected"
    ORCHESTRATION_APPROVED = "orchestration.approved"
    ORCHESTRATION_REJECTED = "orchestration.rejected"
    PUBLICATION_MANUAL_TAKEOVER = "publication.manual_takeover"
    RUN_FAILED = "run.failed"
    RUN_CANCELLED = "run.cancelled"
    RUN_APPROVAL_REJECTED = "run.approval_rejected"
    ACCOUNT_REGISTRATION_APPROVED = "account.registration.approved"
    # P5a CRM（crm-p5a-design §2.11）：活动到期提醒与续约窗口提醒（文案固定、不含客户名 / 金额）。
    CRM_ACTIVITY_DUE = "crm.activity.due"
    CRM_RENEWAL_WINDOW = "crm.renewal.window"


# 固定文案：不含用户输入、手机号或客户原文，避免把敏感内容复制进收件箱。
_TITLES: dict[InboxKind, str] = {
    InboxKind.TASK_APPROVED: "你提交的任务已通过审批",
    InboxKind.PLAN_APPROVED: "你的计划提案已通过审核",
    InboxKind.PLAN_REJECTED: "你的计划提案已被驳回",
    InboxKind.ORCHESTRATION_APPROVED: "你的编排优化提案已通过审核",
    InboxKind.ORCHESTRATION_REJECTED: "你的编排优化提案已被驳回",
    InboxKind.PUBLICATION_MANUAL_TAKEOVER: "内容发布失败，需人工接管",
    InboxKind.RUN_FAILED: "你的任务运行失败，请查看运行详情",
    InboxKind.RUN_CANCELLED: "你的任务运行已取消",
    InboxKind.RUN_APPROVAL_REJECTED: "你的任务运行被审批驳回",
    InboxKind.ACCOUNT_REGISTRATION_APPROVED: "你的账号申请已通过审批",
    InboxKind.CRM_ACTIVITY_DUE: "你有 CRM 跟进任务已到期或即将到期",
    InboxKind.CRM_RENEWAL_WINDOW: "有合同进入续约窗口，请安排跟进",
}


class InboxNotFound(LookupError):
    """通知不存在，或不属于当前调用者（接口层统一按 404 处理，不泄露存在性）。"""


@dataclass(frozen=True)
class InboxItem:
    tenant_id: str
    recipient_id: str
    kind: InboxKind
    title: str
    target_type: str | None = None
    target_id: str | None = None
    # S1 第三款（迁移 041）：**可空**的上文标识——能反查出来就带，界面据此直达「该会话的该条卡」；
    # 反查不到即 `None` ⇒ 界面回落按 `target_type/target_id` 的既有落点（存量行零破坏）。
    target_conversation_id: str | None = None
    target_approval_id: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    read_at: datetime | None = None
    inbox_id: str = field(default_factory=lambda: f"inbox-{uuid4().hex[:12]}")


class InboxStore(Protocol):
    def add(self, item: InboxItem) -> InboxItem: ...
    def list_for_recipient(
        self, tenant_id: str, recipient_id: str, *, unread_only: bool, limit: int
    ) -> list[InboxItem]: ...
    def count_unread(self, tenant_id: str, recipient_id: str) -> int: ...
    def mark_read(self, tenant_id: str, recipient_id: str, inbox_id: str) -> InboxItem: ...
    def mark_all_read(self, tenant_id: str, recipient_id: str) -> int: ...


class InMemoryInboxStore:
    """开发期内存实现；过期条目在读写时惰性清理。"""

    def __init__(self, *, retention_days: int = DEFAULT_RETENTION_DAYS) -> None:
        self._items: dict[str, InboxItem] = {}
        self._lock = RLock()
        self._retention = timedelta(days=retention_days)

    def add(self, item: InboxItem) -> InboxItem:
        with self._lock:
            self._purge()
            self._items[item.inbox_id] = item
            return item

    def list_for_recipient(
        self, tenant_id: str, recipient_id: str, *, unread_only: bool, limit: int
    ) -> list[InboxItem]:
        with self._lock:
            self._purge()
            matched = [
                entry
                for entry in self._items.values()
                if entry.tenant_id == tenant_id
                and entry.recipient_id == recipient_id
                and (not unread_only or entry.read_at is None)
            ]
        matched.sort(key=lambda entry: entry.created_at, reverse=True)
        return matched[:limit]

    def count_unread(self, tenant_id: str, recipient_id: str) -> int:
        with self._lock:
            self._purge()
            return sum(
                1
                for entry in self._items.values()
                if entry.tenant_id == tenant_id
                and entry.recipient_id == recipient_id
                and entry.read_at is None
            )

    def mark_read(self, tenant_id: str, recipient_id: str, inbox_id: str) -> InboxItem:
        with self._lock:
            self._purge()
            entry = self._items.get(inbox_id)
            if entry is None or entry.tenant_id != tenant_id or entry.recipient_id != recipient_id:
                raise InboxNotFound("通知不存在")
            if entry.read_at is not None:
                return entry
            marked = replace(entry, read_at=datetime.now(UTC))
            self._items[inbox_id] = marked
            return marked

    def mark_all_read(self, tenant_id: str, recipient_id: str) -> int:
        with self._lock:
            self._purge()
            now = datetime.now(UTC)
            updated = 0
            for inbox_id, entry in list(self._items.items()):
                if (
                    entry.tenant_id == tenant_id
                    and entry.recipient_id == recipient_id
                    and entry.read_at is None
                ):
                    self._items[inbox_id] = replace(entry, read_at=now)
                    updated += 1
            return updated

    def _purge(self) -> None:
        cutoff = datetime.now(UTC) - self._retention
        for inbox_id in [
            key for key, entry in self._items.items() if entry.created_at < cutoff
        ]:
            self._items.pop(inbox_id, None)


class PostgresInboxStore:
    """收件箱持久化；写入时顺带清理过期条目。"""

    _COLUMNS = (
        "inbox_id, tenant_id, recipient_id, kind, title, target_type, target_id, "
        "target_conversation_id, target_approval_id, created_at, read_at"
    )

    def __init__(self, connection_or_pool, *, retention_days: int = DEFAULT_RETENTION_DAYS) -> None:
        self.connection = connection_or_pool
        self._retention = timedelta(days=retention_days)

    @contextmanager
    def _connection(self):
        if hasattr(self.connection, "connection") and callable(self.connection.connection):
            with self.connection.connection() as connection:
                yield connection
        else:
            with nullcontext(self.connection) as connection:
                yield connection

    @staticmethod
    def _hydrate(row: tuple) -> InboxItem:
        return InboxItem(
            inbox_id=str(row[0]),
            tenant_id=str(row[1]),
            recipient_id=str(row[2]),
            kind=InboxKind(str(row[3])),
            title=str(row[4]),
            target_type=row[5],
            target_id=row[6],
            target_conversation_id=row[7],
            target_approval_id=row[8],
            created_at=row[9],
            read_at=row[10],
        )

    def add(self, item: InboxItem) -> InboxItem:
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""
                        INSERT INTO workbench_inbox_items ({self._COLUMNS})
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING {self._COLUMNS}
                        """,
                        (
                            item.inbox_id,
                            item.tenant_id,
                            item.recipient_id,
                            item.kind.value,
                            item.title,
                            item.target_type,
                            item.target_id,
                            item.target_conversation_id,
                            item.target_approval_id,
                            item.created_at,
                            item.read_at,
                        ),
                    )
                    row = cursor.fetchone()
                    cursor.execute(
                        "DELETE FROM workbench_inbox_items WHERE created_at < %s",
                        (datetime.now(UTC) - self._retention,),
                    )
        if row is None:
            raise InboxNotFound("通知写入失败")
        return self._hydrate(row)

    def list_for_recipient(
        self, tenant_id: str, recipient_id: str, *, unread_only: bool, limit: int
    ) -> list[InboxItem]:
        clause = "AND read_at IS NULL" if unread_only else ""
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT {self._COLUMNS} FROM workbench_inbox_items
                    WHERE tenant_id = %s AND recipient_id = %s {clause}
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (tenant_id, recipient_id, limit),
                )
                rows = cursor.fetchall()
        return [self._hydrate(row) for row in rows]

    def count_unread(self, tenant_id: str, recipient_id: str) -> int:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT COUNT(*) FROM workbench_inbox_items
                    WHERE tenant_id = %s AND recipient_id = %s AND read_at IS NULL
                    """,
                    (tenant_id, recipient_id),
                )
                row = cursor.fetchone()
        return int(row[0]) if row is not None else 0

    def mark_read(self, tenant_id: str, recipient_id: str, inbox_id: str) -> InboxItem:
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""
                        UPDATE workbench_inbox_items
                        SET read_at = COALESCE(read_at, now())
                        WHERE inbox_id = %s AND tenant_id = %s AND recipient_id = %s
                        RETURNING {self._COLUMNS}
                        """,
                        (inbox_id, tenant_id, recipient_id),
                    )
                    row = cursor.fetchone()
        if row is None:
            raise InboxNotFound("通知不存在")
        return self._hydrate(row)

    def mark_all_read(self, tenant_id: str, recipient_id: str) -> int:
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE workbench_inbox_items
                        SET read_at = now()
                        WHERE tenant_id = %s AND recipient_id = %s AND read_at IS NULL
                        """,
                        (tenant_id, recipient_id),
                    )
                    return int(cursor.rowcount or 0)


class InboxService:
    """收件箱的写入与读取入口。"""

    def __init__(self, store: InboxStore, *, audit=None) -> None:
        self.store = store
        self.audit = audit

    # ------------------------------------------------------------ 写入（事件钩子）

    def notify(
        self,
        *,
        tenant_id: str,
        recipient_id: str,
        kind: InboxKind,
        target_type: str | None = None,
        target_id: str | None = None,
        target_conversation_id: str | None = None,
        target_approval_id: str | None = None,
    ) -> None:
        """写入一条通知；租户或接收人为空则跳过，写入失败只写审计、不阻断业务。

        `target_conversation_id` / `target_approval_id`（S1 第三款）为**可空**上文：
        由调用方从服务端权威链路反查得到（运行 → 幂等行 → 会话），**反查不到就留空**。
        """
        if not tenant_id or not recipient_id:
            return
        item = InboxItem(
            tenant_id=tenant_id,
            recipient_id=recipient_id,
            kind=kind,
            title=_TITLES[kind],
            target_type=target_type,
            target_id=target_id,
            target_conversation_id=target_conversation_id,
            target_approval_id=target_approval_id,
        )
        try:
            self.store.add(item)
        except Exception:  # noqa: BLE001 通知不是关键路径：降级为审计，不向上抛
            if self.audit is not None:
                self.audit.record(
                    AuditAction.INBOX_WRITE_FAILED,
                    tenant_id=tenant_id,
                    target_type=target_type,
                    target_id=target_id,
                    detail={"kind": str(kind)},
                )

    def task_approved(self, *, tenant_id: str, recipient_id: str, task_id: str) -> None:
        self.notify(
            tenant_id=tenant_id,
            recipient_id=recipient_id,
            kind=InboxKind.TASK_APPROVED,
            target_type="task",
            target_id=task_id,
        )

    def plan_decided(
        self, *, tenant_id: str, recipient_id: str, proposal_id: str, approved: bool
    ) -> None:
        self.notify(
            tenant_id=tenant_id,
            recipient_id=recipient_id,
            kind=InboxKind.PLAN_APPROVED if approved else InboxKind.PLAN_REJECTED,
            target_type="plan_proposal",
            target_id=proposal_id,
        )

    def orchestration_decided(
        self, *, tenant_id: str, recipient_id: str, proposal_id: str, approved: bool
    ) -> None:
        self.notify(
            tenant_id=tenant_id,
            recipient_id=recipient_id,
            kind=(
                InboxKind.ORCHESTRATION_APPROVED
                if approved
                else InboxKind.ORCHESTRATION_REJECTED
            ),
            target_type="orchestration_proposal",
            target_id=proposal_id,
        )

    def publication_manual_takeover(
        self, *, tenant_id: str, recipient_id: str, task_id: str
    ) -> None:
        self.notify(
            tenant_id=tenant_id,
            recipient_id=recipient_id,
            kind=InboxKind.PUBLICATION_MANUAL_TAKEOVER,
            target_type="publication",
            target_id=task_id,
        )

    def registration_approved(self, *, tenant_id: str, recipient_id: str) -> None:
        self.notify(
            tenant_id=tenant_id,
            recipient_id=recipient_id,
            kind=InboxKind.ACCOUNT_REGISTRATION_APPROVED,
        )

    def run_decided(
        self,
        *,
        tenant_id: str,
        recipient_id: str,
        run_id: str,
        status: str,
        conversation_id: str | None = None,
    ) -> None:
        """运行进入失败/取消终态：通知等待结果的人。非终态不通知。

        S1 第三款：会话触发的运行带上 `conversation_id` ⇒ 界面可直达该会话（反查不到则留空）。
        """
        if status == "failed":
            kind = InboxKind.RUN_FAILED
        elif status == "cancelled":
            kind = InboxKind.RUN_CANCELLED
        else:
            return
        self.notify(
            tenant_id=tenant_id,
            recipient_id=recipient_id,
            kind=kind,
            target_type="run",
            target_id=run_id,
            target_conversation_id=conversation_id,
        )

    def run_approval_rejected(
        self,
        *,
        tenant_id: str,
        recipient_id: str,
        run_id: str,
        conversation_id: str | None = None,
        approval_id: str | None = None,
    ) -> None:
        """运行内审批被驳回：告知提交人（与普通运行失败区分开）。

        S1 第三款：带上会话与**该条审批**的标识 ⇒ 界面可直达「该会话的该条卡」（缺则留空，回落运行详情）。
        """
        self.notify(
            tenant_id=tenant_id,
            recipient_id=recipient_id,
            kind=InboxKind.RUN_APPROVAL_REJECTED,
            target_type="run",
            target_id=run_id,
            target_conversation_id=conversation_id,
            target_approval_id=approval_id,
        )

    # ------------------------------------------------------------ 读取

    def list(self, actor, *, unread_only: bool = False, limit: int = 50) -> tuple[list[InboxItem], int]:
        """返回 (本人通知列表, 未读数)；未读数始终是本人未读总数，与筛选无关。"""
        items = self.store.list_for_recipient(
            actor.tenant_id, actor.user_id, unread_only=unread_only, limit=limit
        )
        return items, self.store.count_unread(actor.tenant_id, actor.user_id)

    def mark_read(self, actor, inbox_id: str) -> InboxItem:
        return self.store.mark_read(actor.tenant_id, actor.user_id, inbox_id)

    def mark_all_read(self, actor) -> int:
        return self.store.mark_all_read(actor.tenant_id, actor.user_id)
