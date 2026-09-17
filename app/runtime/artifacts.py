"""P2c-3 产物登记（`workbench_run_artifacts`，迁移 `037`）：**运行级元数据** + 保留期清理。

性质（契约「产物登记与只读端点」）：
    - 登记的是**元数据**（虚拟路径 / 变更类型 / 字节 / sha256 / 时间），**不是文件副本、不含内容**；
    - **不进审计、不进消息表**；写入**唯一入口** = 工具执行链路（`fs.write/overwrite/delete` 产生变更时）；
    - **登记失败不影响执行结果**（与帧回传同为「视图」；调用方 catch 后只记日志）；
    - 保留期 `WORKBENCH_RUN_ARTIFACT_RETENTION_DAYS`（默认 30 天）：登记时置 `expires_at`；
      清理逐租户删除 `expires_at < cutoff` 的行，**只清本表**（帧 / 消息 / 审计 / 运行记录不受影响）。

跨租户拒写（§既有手法）：PG 侧走**复合外键** `(tenant_id, run_id) → workbench_run_records`（父表唯一约束
由迁移 `027` 补齐）——租户不匹配时父行不存在 ⇒ 直接拒写，无需应用层判定。
"""

from __future__ import annotations

from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Iterable, Protocol
from uuid import uuid4

from ..tool_execution.file_ops import CHANGE_KINDS
from ..tool_execution.log import get_logger

DEFAULT_RETENTION_DAYS = 30


class FileChangeLike(Protocol):
    """登记入参的**结构协议**（避免 runtime 依赖 tool_execution 的具体类型）。"""

    virtual_path: str
    change_kind: str
    bytes: int
    sha256: str


@dataclass(frozen=True)
class RunArtifact:
    """一行产物登记（**只读投影**；不含内容、调用方不得外泄 `tenant_id`）。"""

    tenant_id: str
    run_id: str
    artifact_id: str
    virtual_path: str
    change_kind: str
    bytes: int
    sha256: str
    created_at: datetime
    expires_at: datetime | None = None

    def to_view(self) -> dict[str, object]:
        """对外视图：**不含** `tenant_id`、宿主路径与内容。"""
        return {
            "artifact_id": self.artifact_id,
            "virtual_path": self.virtual_path,
            "change_kind": self.change_kind,
            "bytes": int(self.bytes),
            "sha256": self.sha256,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
        }


def _now() -> datetime:
    return datetime.now(UTC)


def _validate(changes: Iterable[FileChangeLike]) -> list[FileChangeLike]:
    """逐条校验（fail-closed）：**任一条不合法即整批不登记**（不写半批、不伪造）。"""
    items = list(changes)
    for change in items:
        virtual_path = getattr(change, "virtual_path", None)
        change_kind = getattr(change, "change_kind", None)
        size = getattr(change, "bytes", None)
        sha256 = getattr(change, "sha256", None)
        if not isinstance(virtual_path, str) or not virtual_path or not virtual_path.startswith("/"):
            raise ValueError("产物登记的虚拟路径非法")
        if change_kind not in CHANGE_KINDS:
            raise ValueError("产物登记的变更类型非法")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise ValueError("产物登记的字节数非法")
        if not isinstance(sha256, str) or not sha256.startswith("sha256:"):
            raise ValueError("产物登记的摘要非法")
    return items


class InMemoryRunArtifactStore:
    """内存实现（仅 development；口径与 PG 实现一致）。"""

    def __init__(
        self,
        *,
        retention_days: int = DEFAULT_RETENTION_DAYS,
        id_factory=None,
    ) -> None:
        self.retention_days = int(retention_days)
        self._new_id = id_factory or (lambda: uuid4().hex)
        self._rows: list[RunArtifact] = []

    def register(
        self,
        tenant_id: str,
        run_id: str,
        changes: Iterable[FileChangeLike],
        *,
        now: datetime | None = None,
    ) -> int:
        items = _validate(changes)
        if not items:
            return 0
        reference = now or _now()
        expires_at = reference + timedelta(days=self.retention_days)
        for change in items:
            self._rows.append(
                RunArtifact(
                    tenant_id=tenant_id,
                    run_id=run_id,
                    artifact_id=self._new_id(),
                    virtual_path=str(change.virtual_path),
                    change_kind=str(change.change_kind),
                    bytes=int(change.bytes),
                    sha256=str(change.sha256),
                    created_at=reference,
                    expires_at=expires_at,
                )
            )
        return len(items)

    def list_for_run(
        self, tenant_id: str, run_id: str, *, now: datetime | None = None
    ) -> list[RunArtifact]:
        reference = now or _now()
        return [
            row
            for row in self._rows
            if row.tenant_id == tenant_id
            and row.run_id == run_id
            and (row.expires_at is None or row.expires_at > reference)
        ]

    def purge_expired(self, *, cutoff: datetime) -> int:
        kept = [
            row
            for row in self._rows
            if row.expires_at is None or row.expires_at >= cutoff
        ]
        removed = len(self._rows) - len(kept)
        self._rows = kept
        return removed


class PostgresRunArtifactStore:
    """PG 实现（迁移 037）；跨租户写由**复合外键**拒绝（`(tenant_id, run_id)` 父行必须存在）。"""

    def __init__(self, connection_or_pool: Any, *, retention_days: int = DEFAULT_RETENTION_DAYS) -> None:
        self.connection = connection_or_pool
        self.retention_days = int(retention_days)

    @contextmanager
    def _connection(self):
        if hasattr(self.connection, "connection") and callable(self.connection.connection):
            with self.connection.connection() as connection:
                yield connection
        else:
            with nullcontext(self.connection) as connection:
                yield connection

    def _rows(
        self,
        tenant_id: str,
        run_id: str,
        changes: Iterable[FileChangeLike],
        *,
        now: datetime | None,
    ) -> list[tuple]:
        items = _validate(changes)
        if not items:
            return []
        reference = now or _now()
        expires_at = reference + timedelta(days=self.retention_days)
        return [
            (
                tenant_id,
                run_id,
                uuid4().hex,
                str(change.virtual_path),
                str(change.change_kind),
                int(change.bytes),
                str(change.sha256),
                reference,
                expires_at,
            )
            for change in items
        ]

    def register(
        self,
        tenant_id: str,
        run_id: str,
        changes: Iterable[FileChangeLike],
        *,
        now: datetime | None = None,
    ) -> int:
        rows = self._rows(tenant_id, run_id, changes, now=now)
        if not rows:
            return 0
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.executemany(
                        """
                        INSERT INTO workbench_run_artifacts
                            (tenant_id, run_id, artifact_id, virtual_path, change_kind,
                             bytes, sha256, created_at, expires_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT DO NOTHING
                        """,
                        rows,
                    )
        return len(rows)

    def list_for_run(
        self, tenant_id: str, run_id: str, *, now: datetime | None = None
    ) -> list[RunArtifact]:
        reference = now or _now()
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT tenant_id, run_id, artifact_id, virtual_path, change_kind,
                           bytes, sha256, created_at, expires_at
                    FROM workbench_run_artifacts
                    WHERE tenant_id = %s AND run_id = %s
                      AND (expires_at IS NULL OR expires_at > %s)
                    ORDER BY created_at, artifact_id
                    """,
                    (tenant_id, run_id, reference),
                )
                rows = cursor.fetchall()
        return [
            RunArtifact(
                tenant_id=str(row[0]),
                run_id=str(row[1]),
                artifact_id=str(row[2]),
                virtual_path=str(row[3]),
                change_kind=str(row[4]),
                bytes=int(row[5]),
                sha256=str(row[6]),
                created_at=row[7],
                expires_at=row[8],
            )
            for row in rows
        ]

    def purge_expired(self, *, cutoff: datetime) -> int:
        """**逐租户**删除到期行（带 `tenant_id`）；返回删除行数。"""
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT DISTINCT tenant_id FROM workbench_run_artifacts
                        WHERE expires_at IS NOT NULL AND expires_at < %s
                        """,
                        (cutoff,),
                    )
                    tenant_ids = [str(row[0]) for row in cursor.fetchall()]
                    removed = 0
                    for tenant_id in tenant_ids:
                        cursor.execute(
                            """
                            DELETE FROM workbench_run_artifacts
                            WHERE tenant_id = %s AND expires_at IS NOT NULL AND expires_at < %s
                            """,
                            (tenant_id, cutoff),
                        )
                        removed += int(cursor.rowcount or 0)
                    return removed


def register_run_artifacts(
    store: Any | None,
    *,
    tenant_id: str,
    run_id: str,
    changes: Iterable[FileChangeLike],
    now: datetime | None = None,
) -> int:
    """**best-effort** 登记（未装配 `store` ⇒ 0）：失败只记日志，**不影响执行结果**。"""
    if store is None:
        return 0
    try:
        return int(store.register(tenant_id, run_id, changes, now=now))
    except Exception as exc:  # noqa: BLE001 - 登记是视图：失败不得阻断或改变执行结果
        get_logger().error("产物登记失败（不影响执行结果）：%s", exc)
        return 0