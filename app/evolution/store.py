"""评测集仓储：内存（开发/测试）与 PostgreSQL（生产）双实现。

口径见 `docs/superpowers/specs/2026-09-16-self-evolution-p6-design.md` §2.7（迁移 `033`）。
租户隔离：全部方法以 `(tenant_id, ...)` 为主键前缀；跨租户一律按「未找到」处理。
"""

from __future__ import annotations

import json
from contextlib import contextmanager, nullcontext
from threading import RLock
from typing import Protocol, Sequence

from ..domain import UserContext
from .models import (
    EvalCase,
    EvalCaseNotFound,
    EvalCaseResult,
    EvalCaseSource,
    EvalCaseStatus,
    EvalRun,
    EvalRunStatus,
)

_DEFAULT_LIMIT = 50
_MAX_LIMIT = 200


def _clamp(limit: int) -> int:
    return max(1, min(int(limit), _MAX_LIMIT))


class EvalStore(Protocol):
    def create_case(self, context: UserContext, case: EvalCase) -> tuple[EvalCase, bool]: ...
    def get_case(self, context: UserContext, case_id: str) -> EvalCase: ...
    def list_cases(self, context: UserContext, *, suite_key: str | None = None, status=None, source=None, limit: int = _DEFAULT_LIMIT, offset: int = 0) -> tuple[list[EvalCase], int]: ...
    def find_case_by_digest(self, context: UserContext, *, suite_key: str, input_digest: str) -> EvalCase | None: ...
    def set_case_status(self, context: UserContext, case_id: str, *, new_status: EvalCaseStatus, allowed_if: Sequence[EvalCaseStatus], superseded_by: str | None = None) -> EvalCase | None: ...
    def set_case_expectation(self, context: UserContext, case_id: str, *, expectation: dict, allowed_if: Sequence[EvalCaseStatus]) -> EvalCase | None: ...
    def create_run(self, context: UserContext, run: EvalRun) -> EvalRun: ...
    def record_result(self, context: UserContext, result: EvalCaseResult) -> EvalCaseResult: ...
    def get_run(self, context: UserContext, eval_run_id: str) -> EvalRun: ...
    def list_runs(self, context: UserContext, *, suite_key: str | None = None, limit: int = _DEFAULT_LIMIT, offset: int = 0) -> tuple[list[EvalRun], int]: ...
    def list_results(self, context: UserContext, eval_run_id: str) -> list[EvalCaseResult]: ...


class InMemoryEvalStore:
    """开发期内存仓储；语义与 PG 实现一致（幂等 create、条件状态迁移、跨租户 404）。"""

    def __init__(self) -> None:
        self._cases: dict[tuple[str, str], EvalCase] = {}
        self._runs: dict[tuple[str, str], EvalRun] = {}
        self._results: dict[tuple[str, str], list[EvalCaseResult]] = {}
        self._lock = RLock()

    def create_case(self, context: UserContext, case: EvalCase) -> tuple[EvalCase, bool]:
        key = (context.tenant_id, case.case_id)
        with self._lock:
            if key in self._cases:
                return self._cases[key], False
            self._cases[key] = case
            return case, True

    def get_case(self, context: UserContext, case_id: str) -> EvalCase:
        with self._lock:
            case = self._cases.get((context.tenant_id, case_id))
        if case is None:
            raise EvalCaseNotFound(case_id)
        return case

    def list_cases(self, context: UserContext, *, suite_key=None, status=None, source=None, limit=_DEFAULT_LIMIT, offset=0):
        wanted_status = EvalCaseStatus(status) if status is not None else None
        wanted_source = EvalCaseSource(source) if source is not None else None
        with self._lock:
            matched = [
                case
                for (tenant_id, _case_id), case in self._cases.items()
                if tenant_id == context.tenant_id
                and (suite_key is None or case.suite_key == suite_key)
                and (wanted_status is None or case.status is wanted_status)
                and (wanted_source is None or case.source is wanted_source)
            ]
        matched.sort(key=lambda item: (item.created_at, item.case_id), reverse=True)
        return matched[offset : offset + _clamp(limit)], len(matched)

    def find_case_by_digest(self, context: UserContext, *, suite_key: str, input_digest: str) -> EvalCase | None:
        with self._lock:
            for (tenant_id, _case_id), case in self._cases.items():
                if (
                    tenant_id == context.tenant_id
                    and case.suite_key == suite_key
                    and case.input_digest == input_digest
                ):
                    return case
        return None

    def _mutate(self, context: UserContext, case_id: str, mutate) -> EvalCase | None:
        with self._lock:
            key = (context.tenant_id, case_id)
            case = self._cases.get(key)
            if case is None:
                return None
            updated = mutate(case)
            if updated is None:
                return None
            self._cases[key] = updated
            return updated

    def set_case_status(self, context, case_id, *, new_status, allowed_if, superseded_by=None):
        from dataclasses import replace

        def mutate(case: EvalCase) -> EvalCase | None:
            if case.status not in tuple(allowed_if):
                return None
            return replace(
                case,
                status=new_status,
                superseded_by=superseded_by or case.superseded_by,
            )

        return self._mutate(context, case_id, mutate)

    def set_case_expectation(self, context, case_id, *, expectation, allowed_if):
        from dataclasses import replace

        def mutate(case: EvalCase) -> EvalCase | None:
            if case.status not in tuple(allowed_if):
                return None
            return replace(case, expectation=expectation)

        return self._mutate(context, case_id, mutate)

    def create_run(self, context: UserContext, run: EvalRun) -> EvalRun:
        with self._lock:
            self._runs[(context.tenant_id, run.eval_run_id)] = run
            self._results.setdefault((context.tenant_id, run.eval_run_id), [])
        return run

    def record_result(self, context: UserContext, result: EvalCaseResult) -> EvalCaseResult:
        with self._lock:
            self._results.setdefault((context.tenant_id, result.eval_run_id), []).append(result)
        return result

    def get_run(self, context: UserContext, eval_run_id: str) -> EvalRun:
        with self._lock:
            run = self._runs.get((context.tenant_id, eval_run_id))
        if run is None:
            raise EvalCaseNotFound(eval_run_id)
        return run

    def list_runs(self, context: UserContext, *, suite_key=None, limit=_DEFAULT_LIMIT, offset=0):
        with self._lock:
            matched = [
                run
                for (tenant_id, _run_id), run in self._runs.items()
                if tenant_id == context.tenant_id and (suite_key is None or run.suite_key == suite_key)
            ]
        matched.sort(key=lambda item: (item.created_at, item.eval_run_id), reverse=True)
        return matched[offset : offset + _clamp(limit)], len(matched)

    def list_results(self, context: UserContext, eval_run_id: str) -> list[EvalCaseResult]:
        with self._lock:
            items = list(self._results.get((context.tenant_id, eval_run_id), []))
        items.sort(key=lambda item: item.case_id)
        return items


class PostgresEvalStore:
    """评测集持久化（迁移 `033`）；写入在事务内完成，失败向上抛出。

    复合外键 `(tenant_id, eval_run_id)` / `(tenant_id, case_id)` ⇒ 跨租户引用在 DB 层直接失败。
    """

    _CASE_COLUMNS = "tenant_id, case_id, suite_key, source, status, input_snapshot, input_digest, expectation, superseded_by, created_by, created_at, updated_at"
    _RUN_COLUMNS = "tenant_id, eval_run_id, subject, suite_key, suite_digest, status, case_count, pass_count, cost_cents, created_by, created_at"
    _RESULT_COLUMNS = "tenant_id, eval_run_id, case_id, passed, detail, created_at"

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
    def _json(value) -> dict:
        if isinstance(value, str):
            return dict(json.loads(value))
        return dict(value or {})

    @classmethod
    def _hydrate_case(cls, row: tuple) -> EvalCase:
        return EvalCase(
            tenant_id=str(row[0]),
            case_id=str(row[1]),
            suite_key=str(row[2]),
            source=EvalCaseSource(str(row[3])),
            status=EvalCaseStatus(str(row[4])),
            input_snapshot=cls._json(row[5]),
            input_digest=str(row[6]),
            expectation=cls._json(row[7]),
            superseded_by=None if row[8] is None else str(row[8]),
            created_by=str(row[9]),
            created_at=row[10],
            updated_at=row[11],
        )

    @classmethod
    def _hydrate_run(cls, row: tuple) -> EvalRun:
        return EvalRun(
            tenant_id=str(row[0]),
            eval_run_id=str(row[1]),
            subject=str(row[2]),
            suite_key=str(row[3]),
            suite_digest=str(row[4]),
            status=EvalRunStatus(str(row[5])),
            case_count=int(row[6]),
            pass_count=int(row[7]),
            cost_cents=int(row[8]),
            created_by=str(row[9]),
            created_at=row[10],
        )

    @classmethod
    def _hydrate_result(cls, row: tuple) -> EvalCaseResult:
        return EvalCaseResult(
            tenant_id=str(row[0]),
            eval_run_id=str(row[1]),
            case_id=str(row[2]),
            passed=bool(row[3]),
            detail=cls._json(row[4]),
            created_at=row[5],
        )

    # ------------------------------------------------------------ 用例

    def create_case(self, context: UserContext, case: EvalCase) -> tuple[EvalCase, bool]:
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""
                        INSERT INTO workbench_eval_cases
                            (tenant_id, case_id, suite_key, source, status, input_snapshot,
                             input_digest, expectation, superseded_by, created_by)
                        VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s::jsonb, %s, %s)
                        ON CONFLICT (tenant_id, case_id) DO NOTHING
                        RETURNING {self._CASE_COLUMNS}
                        """,
                        (
                            context.tenant_id,
                            case.case_id,
                            case.suite_key,
                            case.source.value,
                            case.status.value,
                            json.dumps(case.input_snapshot, ensure_ascii=False),
                            case.input_digest,
                            json.dumps(case.expectation, ensure_ascii=False),
                            case.superseded_by,
                            case.created_by,
                        ),
                    )
                    row = cursor.fetchone()
                    if row is not None:
                        return self._hydrate_case(row), True
                    cursor.execute(
                        f"SELECT {self._CASE_COLUMNS} FROM workbench_eval_cases WHERE tenant_id = %s AND case_id = %s",
                        (context.tenant_id, case.case_id),
                    )
                    existing = cursor.fetchone()
        if existing is None:
            raise EvalCaseNotFound(case.case_id)
        return self._hydrate_case(existing), False

    def get_case(self, context: UserContext, case_id: str) -> EvalCase:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT {self._CASE_COLUMNS} FROM workbench_eval_cases WHERE tenant_id = %s AND case_id = %s",
                    (context.tenant_id, case_id),
                )
                row = cursor.fetchone()
        if row is None:
            raise EvalCaseNotFound(case_id)
        return self._hydrate_case(row)

    def list_cases(self, context: UserContext, *, suite_key=None, status=None, source=None, limit=_DEFAULT_LIMIT, offset=0):
        clauses = ["tenant_id = %s"]
        params: list[object] = [context.tenant_id]
        if suite_key is not None:
            clauses.append("suite_key = %s")
            params.append(suite_key)
        if status is not None:
            clauses.append("status = %s")
            params.append(EvalCaseStatus(status).value)
        if source is not None:
            clauses.append("source = %s")
            params.append(EvalCaseSource(source).value)
        where = " AND ".join(clauses)
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT {self._CASE_COLUMNS} FROM workbench_eval_cases
                    WHERE {where} ORDER BY created_at DESC, case_id ASC LIMIT %s OFFSET %s
                    """,
                    (*params, _clamp(limit), offset),
                )
                rows = cursor.fetchall()
                cursor.execute(f"SELECT COUNT(*) FROM workbench_eval_cases WHERE {where}", tuple(params))
                count_row = cursor.fetchone()
        return [self._hydrate_case(row) for row in rows], int(count_row[0]) if count_row is not None else 0

    def find_case_by_digest(self, context: UserContext, *, suite_key: str, input_digest: str) -> EvalCase | None:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT {self._CASE_COLUMNS} FROM workbench_eval_cases
                    WHERE tenant_id = %s AND suite_key = %s AND input_digest = %s
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    (context.tenant_id, suite_key, input_digest),
                )
                row = cursor.fetchone()
        return None if row is None else self._hydrate_case(row)

    def set_case_status(self, context, case_id, *, new_status, allowed_if, superseded_by=None):
        placeholders = ", ".join(["%s"] * len(tuple(allowed_if)))
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""
                        UPDATE workbench_eval_cases
                        SET status = %s, superseded_by = COALESCE(%s, superseded_by), updated_at = now()
                        WHERE tenant_id = %s AND case_id = %s AND status IN ({placeholders})
                        RETURNING {self._CASE_COLUMNS}
                        """,
                        (
                            new_status.value,
                            superseded_by,
                            context.tenant_id,
                            case_id,
                            *[item.value for item in tuple(allowed_if)],
                        ),
                    )
                    row = cursor.fetchone()
        return None if row is None else self._hydrate_case(row)

    def set_case_expectation(self, context, case_id, *, expectation, allowed_if):
        placeholders = ", ".join(["%s"] * len(tuple(allowed_if)))
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""
                        UPDATE workbench_eval_cases
                        SET expectation = %s::jsonb, updated_at = now()
                        WHERE tenant_id = %s AND case_id = %s AND status IN ({placeholders})
                        RETURNING {self._CASE_COLUMNS}
                        """,
                        (
                            json.dumps(expectation, ensure_ascii=False),
                            context.tenant_id,
                            case_id,
                            *[item.value for item in tuple(allowed_if)],
                        ),
                    )
                    row = cursor.fetchone()
        return None if row is None else self._hydrate_case(row)

    # ------------------------------------------------------------ 运行与结果

    def create_run(self, context: UserContext, run: EvalRun) -> EvalRun:
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""
                        INSERT INTO workbench_eval_runs
                            (tenant_id, eval_run_id, subject, suite_key, suite_digest, status,
                             case_count, pass_count, cost_cents, created_by)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING {self._RUN_COLUMNS}
                        """,
                        (
                            context.tenant_id,
                            run.eval_run_id,
                            run.subject,
                            run.suite_key,
                            run.suite_digest,
                            run.status.value,
                            run.case_count,
                            run.pass_count,
                            run.cost_cents,
                            run.created_by,
                        ),
                    )
                    row = cursor.fetchone()
        if row is None:
            raise EvalCaseNotFound(run.eval_run_id)
        return self._hydrate_run(row)

    def record_result(self, context: UserContext, result: EvalCaseResult) -> EvalCaseResult:
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""
                        INSERT INTO workbench_eval_case_results
                            (tenant_id, eval_run_id, case_id, passed, detail)
                        VALUES (%s, %s, %s, %s, %s::jsonb)
                        RETURNING {self._RESULT_COLUMNS}
                        """,
                        (
                            context.tenant_id,
                            result.eval_run_id,
                            result.case_id,
                            result.passed,
                            json.dumps(result.detail, ensure_ascii=False),
                        ),
                    )
                    row = cursor.fetchone()
        if row is None:
            raise EvalCaseNotFound(result.eval_run_id)
        return self._hydrate_result(row)

    def get_run(self, context: UserContext, eval_run_id: str) -> EvalRun:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT {self._RUN_COLUMNS} FROM workbench_eval_runs WHERE tenant_id = %s AND eval_run_id = %s",
                    (context.tenant_id, eval_run_id),
                )
                row = cursor.fetchone()
        if row is None:
            raise EvalCaseNotFound(eval_run_id)
        return self._hydrate_run(row)

    def list_runs(self, context: UserContext, *, suite_key=None, limit=_DEFAULT_LIMIT, offset=0):
        clauses = ["tenant_id = %s"]
        params: list[object] = [context.tenant_id]
        if suite_key is not None:
            clauses.append("suite_key = %s")
            params.append(suite_key)
        where = " AND ".join(clauses)
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT {self._RUN_COLUMNS} FROM workbench_eval_runs
                    WHERE {where} ORDER BY created_at DESC, eval_run_id ASC LIMIT %s OFFSET %s
                    """,
                    (*params, _clamp(limit), offset),
                )
                rows = cursor.fetchall()
                cursor.execute(f"SELECT COUNT(*) FROM workbench_eval_runs WHERE {where}", tuple(params))
                count_row = cursor.fetchone()
        return [self._hydrate_run(row) for row in rows], int(count_row[0]) if count_row is not None else 0

    def list_results(self, context: UserContext, eval_run_id: str) -> list[EvalCaseResult]:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT {self._RESULT_COLUMNS} FROM workbench_eval_case_results
                    WHERE tenant_id = %s AND eval_run_id = %s ORDER BY case_id ASC
                    """,
                    (context.tenant_id, eval_run_id),
                )
                rows = cursor.fetchall()
        return [self._hydrate_result(row) for row in rows]