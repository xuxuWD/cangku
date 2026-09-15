"""知识治理仓储：内存实现 + PostgreSQL 实现。

权限在**服务层**强制（复用 `models` 的 `ensure_can_manage`）；仓储层对所有查询严格带
`tenant_id`，不依赖任何调用方传入的租户条件（沿用记忆层 / 技能层 store 骨架）。

其中 `list_published_eligible` 是「检索谓词守卫」的核心落点（§2.3 pre-filter 白名单）：
只返回 `status='published'` 且未过期（`review_due_at IS NULL OR review_due_at > now`）的文档，
供检索组合件 `scoped_search` 使用；`list_needs_review` 返回到期扫描候选（§2.2 事件触发）。
状态机迁移的合法性由 service 层在 `transition_allowed` 判定后再落库；仓储层用 WHERE 守卫
做最后防线（`mark_review_due` 仅 published 且已到期才更新）。
"""

from __future__ import annotations

from contextlib import contextmanager, nullcontext
from dataclasses import replace
from datetime import datetime
from threading import RLock
from typing import Protocol

from ..domain import UserContext
from .models import (
    KnowledgeDoc,
    KnowledgeDocNotFound,
    KnowledgeDocStateConflict,
    KnowledgeDocStatus,
)

MAX_LIMIT = 200


def _clamp(limit: int) -> int:
    return max(1, min(int(limit), MAX_LIMIT))


class KnowledgeGovStore(Protocol):
    """知识文档治理读写；所有查询严格限定本租户。"""

    def register_document(self, context, *, doc):
        ...

    def get_document(self, context, document_id):
        ...

    def list_documents(self, context, *, status=None, limit=50, offset=0):
        ...

    def update_status(
        self, context, document_id, *, new_status, owner_id=None, last_reviewed_at=None, review_due_at=None
    ):
        ...

    def list_published_eligible(self, context, *, now):
        ...

    def list_needs_review(self, context, *, now):
        ...

    def mark_review_due(self, context, document_id, *, now):
        ...

    def list_all_for_tenant(self, tenant_id, *, since=None):
        ...

    def delete_all_for_tenant(self, tenant_id):
        ...


def _do_sort(rows: list[KnowledgeDoc]) -> list[KnowledgeDoc]:
    return sorted(rows, key=lambda d: (_dt_or_min(d.updated_at), d.document_id), reverse=True)


def _dt_or_min(value):
    return value or datetime.min


class InMemoryKnowledgeGovStore:
    """开发期内存实现（`memory` 存储模式，仅限 development）。"""

    def __init__(self) -> None:
        self._docs: dict[tuple[str, str], KnowledgeDoc] = {}
        self._lock = RLock()

    def register_document(self, context, *, doc: KnowledgeDoc) -> KnowledgeDoc:
        with self._lock:
            key = (context.tenant_id, doc.document_id)
            existing = self._docs.get(key)
            if existing is not None:
                return existing  # 幂等：同 (tenant, document_id) 返回既有。
            self._docs[key] = doc
            return doc

    def get_document(self, context, document_id: str) -> KnowledgeDoc:
        with self._lock:
            doc = self._docs.get((context.tenant_id, str(document_id)))
        if doc is None:
            raise KnowledgeDocNotFound(str(document_id))
        return doc

    def list_documents(self, context, *, status=None, limit=50, offset=0):
        wanted = KnowledgeDocStatus(status) if status is not None else None
        with self._lock:
            matched = [
                doc
                for (tid, _k), doc in self._docs.items()
                if tid == context.tenant_id and (wanted is None or doc.status is wanted)
            ]
        matched = _do_sort(matched)
        return matched[offset : offset + _clamp(limit)], len(matched)

    def update_status(
        self,
        context,
        document_id: str,
        *,
        new_status: KnowledgeDocStatus,
        owner_id: str | None = None,
        last_reviewed_at=None,
        review_due_at=None,
    ) -> KnowledgeDoc:
        with self._lock:
            key = (context.tenant_id, str(document_id))
            existing = self._docs.get(key)
            if existing is None:
                raise KnowledgeDocNotFound(str(document_id))
            updated = replace(
                existing,
                status=new_status,
                owner_id=existing.owner_id if owner_id is None else owner_id,
                last_reviewed_at=(
                    existing.last_reviewed_at if last_reviewed_at is None else last_reviewed_at
                ),
                review_due_at=existing.review_due_at if review_due_at is None else review_due_at,
                updated_at=datetime.now(),
            )
            self._docs[key] = updated
            return updated

    def list_published_eligible(self, context, *, now) -> list[KnowledgeDoc]:
        """检索谓词守卫白名单（§2.3 pre-filter）：published 且未过期。"""
        with self._lock:
            out = [
                doc
                for (tid, _k), doc in self._docs.items()
                if tid == context.tenant_id
                and doc.status is KnowledgeDocStatus.PUBLISHED
                and (doc.review_due_at is None or doc.review_due_at > now)
            ]
        return out

    def list_needs_review(self, context, *, now) -> list[KnowledgeDoc]:
        """到期扫描候选（§2.2 事件触发）：published 且已到期。"""
        with self._lock:
            out = [
                doc
                for (tid, _k), doc in self._docs.items()
                if tid == context.tenant_id
                and doc.status is KnowledgeDocStatus.PUBLISHED
                and doc.review_due_at is not None
                and doc.review_due_at <= now
            ]
        return out

    def mark_review_due(self, context, document_id: str, *, now) -> KnowledgeDoc:
        """published 且已到期 → needs_review；不满足返回 None（由 service 判幂等 / 冲突）。"""
        with self._lock:
            key = (context.tenant_id, str(document_id))
            existing = self._docs.get(key)
            if existing is None:
                raise KnowledgeDocNotFound(str(document_id))
            if existing.status is not KnowledgeDocStatus.PUBLISHED:
                return None
            if existing.review_due_at is None or existing.review_due_at > now:
                return None
            updated = replace(existing, status=KnowledgeDocStatus.NEEDS_REVIEW, updated_at=datetime.now())
            self._docs[key] = updated
            return updated

    # ------------------------------------------------------------ 生命周期（仅 service 层判角色）

    def list_all_for_tenant(self, tenant_id, *, since=None) -> list[KnowledgeDoc]:
        with self._lock:
            return [
                doc
                for (tid, _k), doc in self._docs.items()
                if tid == tenant_id and (since is None or (doc.created_at and doc.created_at >= since))
            ]

    def delete_all_for_tenant(self, tenant_id) -> int:
        with self._lock:
            keys = [key for key in list(self._docs.keys()) if key[0] == tenant_id]
            for key in keys:
                del self._docs[key]
            return len(keys)


class PostgresKnowledgeGovStore:
    """知识文档治理持久化（表 `workbench_knowledge_documents`，迁移 032）。"""

    _DOC_COLUMNS = (
        "tenant_id, document_id, title, owner_id, status, version, source_key, "
        "last_reviewed_at, review_due_at, registered_by, created_at, updated_at"
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

    @classmethod
    def _hydrate_doc(cls, row: tuple) -> KnowledgeDoc:
        # `_DOC_COLUMNS` 下标：0 tenant_id,1 document_id,2 title,3 owner_id,4 status,
        # 5 version,6 source_key,7 last_reviewed_at,8 review_due_at,9 registered_by,
        # 10 created_at,11 updated_at。
        return KnowledgeDoc(
            tenant_id=str(row[0]),
            document_id=str(row[1]),
            title=str(row[2]),
            owner_id=str(row[3]),
            status=KnowledgeDocStatus(str(row[4])),
            version=str(row[5]),
            source_key=str(row[6]),
            last_reviewed_at=row[7],
            review_due_at=row[8],
            registered_by=str(row[9]),
            created_at=row[10],
            updated_at=row[11],
        )

    # ------------------------------------------------------------ 文档

    def register_document(self, context, *, doc: KnowledgeDoc) -> KnowledgeDoc:
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""
                        SELECT {self._DOC_COLUMNS} FROM workbench_knowledge_documents
                        WHERE tenant_id = %s AND document_id = %s
                        """,
                        (context.tenant_id, doc.document_id),
                    )
                    existing = cursor.fetchone()
                    if existing is not None:
                        return self._hydrate_doc(existing)  # 幂等：返回既有记录。
                    cursor.execute(
                        f"""
                        INSERT INTO workbench_knowledge_documents
                            (tenant_id, document_id, title, owner_id, status, version,
                             source_key, registered_by)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING {self._DOC_COLUMNS}
                        """,
                        (
                            doc.tenant_id,
                            doc.document_id,
                            doc.title,
                            doc.owner_id,
                            doc.status.value,
                            doc.version,
                            doc.source_key,
                            doc.registered_by,
                        ),
                    )
                    row = cursor.fetchone()
        if row is None:
            raise KnowledgeDocStateConflict("文档登记失败")
        return self._hydrate_doc(row)

    def get_document(self, context, document_id: str) -> KnowledgeDoc:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT {self._DOC_COLUMNS} FROM workbench_knowledge_documents
                    WHERE tenant_id = %s AND document_id = %s
                    """,
                    (context.tenant_id, str(document_id)),
                )
                row = cursor.fetchone()
        if row is None:
            raise KnowledgeDocNotFound(str(document_id))
        return self._hydrate_doc(row)

    def list_documents(self, context, *, status=None, limit=50, offset=0):
        clauses = ["tenant_id = %s"]
        params: list[object] = [context.tenant_id]
        if status is not None:
            clauses.append("status = %s")
            params.append(KnowledgeDocStatus(status).value)
        where = " AND ".join(clauses)
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT {self._DOC_COLUMNS} FROM workbench_knowledge_documents
                    WHERE {where} ORDER BY updated_at DESC, document_id ASC LIMIT %s OFFSET %s
                    """,
                    (*params, _clamp(limit), offset),
                )
                rows = cursor.fetchall()
                cursor.execute(f"SELECT COUNT(*) FROM workbench_knowledge_documents WHERE {where}", tuple(params))
                count_row = cursor.fetchone()
        return [self._hydrate_doc(row) for row in rows], int(count_row[0]) if count_row is not None else 0

    def update_status(
        self,
        context,
        document_id: str,
        *,
        new_status: KnowledgeDocStatus,
        owner_id: str | None = None,
        last_reviewed_at=None,
        review_due_at=None,
    ) -> KnowledgeDoc:
        sets = ["status = %s"]
        params: list[object] = [new_status.value]
        if owner_id is not None:
            sets.append("owner_id = %s")
            params.append(owner_id)
        if last_reviewed_at is not None:
            sets.append("last_reviewed_at = %s")
            params.append(last_reviewed_at)
        if review_due_at is not None:
            sets.append("review_due_at = %s")
            params.append(review_due_at)
        sets.append("updated_at = now()")
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    # 参数顺序：各 SET 占位（status + 可选项），随后 WHERE 的 tenant / document_id。
                    cursor.execute(
                        f"""
                        UPDATE workbench_knowledge_documents
                        SET {", ".join(sets)}
                        WHERE tenant_id = %s AND document_id = %s
                        RETURNING {self._DOC_COLUMNS}
                        """,
                        (*params, context.tenant_id, str(document_id)),
                    )
                    row = cursor.fetchone()
        if row is None:
            raise KnowledgeDocNotFound(str(document_id))
        return self._hydrate_doc(row)

    def list_published_eligible(self, context, *, now) -> list[KnowledgeDoc]:
        """检索谓词守卫白名单（§2.3 pre-filter）：published 且未过期。"""
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT {self._DOC_COLUMNS} FROM workbench_knowledge_documents
                    WHERE tenant_id = %s AND status = %s
                      AND (review_due_at IS NULL OR review_due_at > %s)
                    """,
                    (context.tenant_id, KnowledgeDocStatus.PUBLISHED.value, now),
                )
                rows = cursor.fetchall()
        return [self._hydrate_doc(row) for row in rows]

    def list_needs_review(self, context, *, now) -> list[KnowledgeDoc]:
        """到期扫描候选（§2.2 事件触发）：published 且已到期。"""
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT {self._DOC_COLUMNS} FROM workbench_knowledge_documents
                    WHERE tenant_id = %s AND status = %s
                      AND review_due_at IS NOT NULL AND review_due_at <= %s
                    """,
                    (context.tenant_id, KnowledgeDocStatus.PUBLISHED.value, now),
                )
                rows = cursor.fetchall()
        return [self._hydrate_doc(row) for row in rows]

    def mark_review_due(self, context, document_id: str, *, now) -> KnowledgeDoc:
        """published 且已到期 → needs_review；不满足返回 None（service 判幂等 / 冲突）。"""
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""
                        UPDATE workbench_knowledge_documents
                        SET status = %s, updated_at = now()
                        WHERE tenant_id = %s AND document_id = %s AND status = %s
                          AND review_due_at IS NOT NULL AND review_due_at <= %s
                        RETURNING {self._DOC_COLUMNS}
                        """,
                        (
                            KnowledgeDocStatus.NEEDS_REVIEW.value,
                            context.tenant_id,
                            str(document_id),
                            KnowledgeDocStatus.PUBLISHED.value,
                            now,
                        ),
                    )
                    row = cursor.fetchone()
        return None if row is None else self._hydrate_doc(row)

    # ------------------------------------------------------------ 生命周期（仅 service 层判角色）

    def list_all_for_tenant(self, tenant_id, *, since=None) -> list[KnowledgeDoc]:
        clauses = ["tenant_id = %s"]
        params: list[object] = [tenant_id]
        if since is not None:
            clauses.append("created_at >= %s")
            params.append(since)
        where = " AND ".join(clauses)
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(f"SELECT {self._DOC_COLUMNS} FROM workbench_knowledge_documents WHERE {where}", tuple(params))
                rows = cursor.fetchall()
        return [self._hydrate_doc(row) for row in rows]

    def delete_all_for_tenant(self, tenant_id) -> int:
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute("DELETE FROM workbench_knowledge_documents WHERE tenant_id = %s", (tenant_id,))
                    deleted = cursor.rowcount
        return int(deleted)


# re-export 供 import 使用
__all__ = [
    "KnowledgeGovStore",
    "InMemoryKnowledgeGovStore",
    "PostgresKnowledgeGovStore",
    "MAX_LIMIT",
]