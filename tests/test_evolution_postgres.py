"""`PostgresEvalStore` 的**真库**回归（P6a 评测集，迁移 033）。

口径（沿用 `tests/test_skills_postgres.py` 先例）：
  - DSN 从环境变量 **`WORKBENCH_TEST_DATABASE_URL`** 读；**未设置即整体 skip**。
  - 目标库必须是**已完成全部迁移（含 033）**的库；本文件**不建表、不迁移**。
  - 只操作 `TENANT` 这一个租户的数据，每个用例前后自清。

重点验证（规格 §3 + 反假）：
  1. 用例 JSONB（快照 / 期望）与指纹真库可写读；状态机流转持久化。
  2. supersede 软链（旧条目 archived + superseded_by 指向新条目）真库持久化。
  3. 运行与逐例结果落库（计数 / 指纹 / 明细）。
  4. **复合外键**：跨租户引用在 DB 层直接失败（结果表指向他租户运行）。
"""

from __future__ import annotations

import os

import pytest

from app.domain import UserContext
from app.evolution.regression import regression_case_specs
from app.evolution.service import EvolutionService
from app.evolution.store import PostgresEvalStore

DSN = os.environ.get("WORKBENCH_TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not DSN,
    reason="未设置 WORKBENCH_TEST_DATABASE_URL，跳过真库集成测试（见本文件 docstring 的局限声明）",
)

TENANT = "test-evolution-pg"
ADMIN = "acct-pg-evo-admin"


@pytest.fixture()
def service():
    psycopg = pytest.importorskip("psycopg")
    connection = psycopg.connect(DSN, autocommit=True)
    _purge(connection)
    svc = EvolutionService(PostgresEvalStore(connection))
    yield svc, connection
    _purge(connection)
    connection.close()


def _purge(connection) -> None:
    with connection.cursor() as cursor:
        # 结果表对运行 / 用例有复合外键 ⇒ 必须按依赖顺序清理。
        cursor.execute("DELETE FROM workbench_eval_case_results WHERE tenant_id = %s", (TENANT,))
        cursor.execute("DELETE FROM workbench_eval_runs WHERE tenant_id = %s", (TENANT,))
        cursor.execute("DELETE FROM workbench_eval_cases WHERE tenant_id = %s", (TENANT,))


def _admin() -> UserContext:
    return UserContext(TENANT, ADMIN, "super_admin")


def _snapshot(prompt: str = "帮我总结本周销售数据") -> dict:
    return {"prompt": prompt, "logs": []}


def _expectation(expect: str = "pass") -> dict:
    return {"probe": "runtime-safety-probe", "expect": expect}


# ------------------------------------------------------------ 用例持久化与状态机

def test_case_persists_with_jsonb_and_digest(service) -> None:
    svc, connection = service
    case = svc.create_case(
        _admin(),
        suite_key="runtime-safety",
        input_snapshot=_snapshot(),
        expectation=_expectation(expect="blocked"),
    )

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT suite_key, source, status, input_snapshot, expectation, input_digest, created_by
            FROM workbench_eval_cases WHERE tenant_id = %s AND case_id = %s
            """,
            (TENANT, case.case_id),
        )
        row = cursor.fetchone()
    assert row is not None
    assert row[0] == "runtime-safety"
    assert row[1] == "manual"
    assert row[2] == "draft"
    assert row[3]["prompt"] == "帮我总结本周销售数据"  # JSONB 读回
    assert row[4] == {"probe": "runtime-safety-probe", "expect": "blocked"}
    assert row[5] == case.input_digest and len(row[5]) == 64
    assert row[6] == ADMIN


def test_state_machine_and_supersede_persist(service) -> None:
    svc, connection = service
    old = svc.create_case(
        _admin(), suite_key="runtime-safety", input_snapshot=_snapshot(), expectation=_expectation()
    )
    svc.publish_case(_admin(), old.case_id)
    svc.archive_case(_admin(), old.case_id)
    assert svc.get_case(_admin(), old.case_id).status.value == "archived"

    # 重新登记一条开放用例，再走 supersede（软链）。
    source = svc.create_case(
        _admin(), suite_key="runtime-safety", input_snapshot=_snapshot("另一条"), expectation=_expectation()
    )
    svc.publish_case(_admin(), source.case_id)
    new = svc.supersede_case(_admin(), source.case_id, expectation=_expectation("blocked"))

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT status, superseded_by FROM workbench_eval_cases WHERE tenant_id = %s AND case_id = %s",
            (TENANT, source.case_id),
        )
        row = cursor.fetchone()
        cursor.execute(
            "SELECT status, superseded_by FROM workbench_eval_cases WHERE tenant_id = %s AND case_id = %s",
            (TENANT, new.case_id),
        )
        new_row = cursor.fetchone()
    assert row == ("archived", new.case_id)          # 旧条目软删并链到新条目
    assert new_row == ("draft", None)                # 新条目为草稿，未继承替代链


# ------------------------------------------------------------ 运行与结果

def test_run_and_results_persist(service) -> None:
    svc, connection = service
    svc.import_cases(_admin(), regression_case_specs())
    run = svc.run_eval(_admin(), subject_name="runtime-safety-probe", suite_key="runtime-safety")

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT subject, suite_key, suite_digest, status, case_count, pass_count, cost_cents
            FROM workbench_eval_runs WHERE tenant_id = %s AND eval_run_id = %s
            """,
            (TENANT, run.eval_run_id),
        )
        run_row = cursor.fetchone()
        cursor.execute(
            "SELECT COUNT(*) FROM workbench_eval_case_results WHERE tenant_id = %s AND eval_run_id = %s",
            (TENANT, run.eval_run_id),
        )
        result_count = cursor.fetchone()[0]
    assert run_row is not None
    assert run_row[0] == "runtime-safety-probe" and run_row[1] == "runtime-safety"
    assert run_row[2] == run.suite_digest and run_row[3] == "completed"
    assert (run_row[4], run_row[5], run_row[6]) == (4, 4, 0)
    assert int(result_count) == 4

    results = svc.list_results(_admin(), run.eval_run_id)
    assert len(results) == 4
    assert all(item.passed for item in results)


def test_cross_tenant_reference_fails_at_database_layer(service) -> None:
    """复合外键兜底：结果行引用**他租户**的运行 ⇒ DB 层直接 ForeignKeyViolation。"""
    svc, connection = service
    svc.import_cases(_admin(), regression_case_specs())
    run = svc.run_eval(_admin(), subject_name="runtime-safety-probe", suite_key="runtime-safety")
    case_id = svc.list_cases(_admin(), suite_key="runtime-safety", status="published")[0][0].case_id

    psycopg = pytest.importorskip("psycopg")
    with connection.cursor() as cursor:
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            cursor.execute(
                """
                INSERT INTO workbench_eval_case_results (tenant_id, eval_run_id, case_id, passed)
                VALUES (%s, %s, %s, %s)
                """,
                ("other-tenant", run.eval_run_id, case_id, True),
            )