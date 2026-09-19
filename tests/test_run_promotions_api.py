"""S2 沉淀入口：**确认完成后把这次运行存成一个可再跑的任务**（`workbench_run_promotions`，迁移 `042`）。

口径（真源）：`docs/superpowers/specs/2026-09-18-workbench-closed-loop-design.md` §3 接缝 S2
「确认后出现「**存成任务 / 设为自动化**」（B5 的轻量入口，完整画布见 C3）」；契约
`docs/api-contract.md`「运行沉淀（S2 · 存成任务）」。

关键断言（每条都对应可检查的纪律）：
  * **只对已确认的终态运行开放**：未确认 / 未结束一律 `409`（不排队、不猜）；
  * **权限与验收决议同一判定**：承载任务创建人 / CEO / 超管；他人 / 跨租户 / 未知运行一律 `404`；
  * **一个运行只能沉淀一次**：重复提交返回既有任务（`created: false`），**不重复建任务、不重复写审计**；
  * **任务走既有创建路径**：同一治理闸门（`ensure_can_create`）与同一幂等语义，不另写一套；
  * **标题正文不进审计**：审计只记 `task_id`；
  * **沉淀是链接**：任务才是产物（运行记录被删只解除链接）。
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app import main
from app.domain import RiskLevel, Task, TaskStatus, TaskStore, UserContext
from app.main import app
from app.runtime.acceptance_decisions import AcceptanceDecision, InMemoryAcceptanceDecisionStore
from app.runtime.promotions import (
    MAX_PROMOTION_TITLE_LENGTH,
    InMemoryRunPromotionStore,
    RunPromotion,
    RunPromotionError,
    validate_promotion_title,
)
from app.runtime.records import InMemoryRunRecordStore
from app.runtime.run_metrics import RunMetricsService
from app.runtime.service import RuntimeService
from app.tool_execution.store import InMemoryToolActionStore

client = TestClient(app)
TENANT = "t-promote"
OTHER_TENANT = "t-promote-other"
EMPLOYEE = "u-1"
OTHER_USER = "u-2"
CEO = "ceo-1"

READ_STEPS = [{"step_id": "step-1", "kind": "read", "tool": "fs.read"}]
PENDING_STEPS = [{"step_id": "step-1", "kind": "write", "tool": "fs.read", "requires_approval": True}]


class _AuditSpy:
    """审计探针：记录每次写的动作与明细（用于断言「只写一次」「不含标题正文」）。"""

    def __init__(self) -> None:
        self.records: list[tuple[str, dict]] = []

    def record(self, action, *, tenant_id, actor_id, target_type, target_id, detail=None, **kwargs):  # noqa: ANN001, ANN003
        self.records.append((str(action), dict(detail or {})))
        return None


@pytest.fixture()
def wired(monkeypatch):
    tasks = TaskStore()
    runs = InMemoryRunRecordStore()
    metrics = RunMetricsService(runs)
    runtime = RuntimeService(tasks, run_metrics=metrics, tool_actions=InMemoryToolActionStore())
    decisions = InMemoryAcceptanceDecisionStore()
    promotions = InMemoryRunPromotionStore()
    audit = _AuditSpy()
    monkeypatch.setattr(main, "store", tasks)
    monkeypatch.setattr(main, "run_metrics_service", metrics)
    monkeypatch.setattr(main, "runtime_service", runtime)
    monkeypatch.setattr(main, "run_acceptance_decision_store", decisions)
    monkeypatch.setattr(main, "run_promotion_store", promotions)
    monkeypatch.setattr(main, "audit_service", audit)
    return {"tasks": tasks, "runs": runs, "runtime": runtime, "decisions": decisions, "promotions": promotions, "audit": audit}


def headers(user_id: str = EMPLOYEE, role: str = "employee", tenant: str = TENANT) -> dict[str, str]:
    return {"X-Tenant-Id": tenant, "X-User-Id": user_id, "X-User-Role": role}


def _task(*, tenant: str = TENANT, user_id: str = EMPLOYEE, title: str = "整理本周选题") -> Task:
    task = Task(
        tenant_id=tenant,
        project_id="proj-1",
        created_by=user_id,
        employee_key="content-writer",
        title=title,
        risk_level=RiskLevel.LOW,
        budget=5,
        idempotency_key=f"promote-src-{tenant}-{user_id}",
        request_fingerprint="fp",
        status=TaskStatus.QUEUED,
    )
    stored, _created = main.store.create(UserContext(tenant, user_id, "employee"), task)
    return stored


def _run(*, terminal: bool = True, tenant: str = TENANT, user_id: str = EMPLOYEE) -> str:
    task = _task(tenant=tenant, user_id=user_id)
    run_id, _key, _policy = main.runtime_service.start(
        UserContext(tenant, user_id, "employee"), task.id, "mock", READ_STEPS if terminal else PENDING_STEPS, "fde"
    )
    return run_id


def _confirm(run_id: str, *, tenant: str = TENANT, user_id: str = EMPLOYEE, key: str = "dec-1") -> None:
    """记一条「确认完成」决议（真源：只有确认完成后才允许沉淀）。"""
    main.run_acceptance_decision_store.record(
        AcceptanceDecision(
            tenant_id=tenant,
            run_id=run_id,
            decision_id="",
            decision="confirmed",
            reason="",
            idempotency_key=key,
            decided_by=user_id,
            decided_by_role="employee",
            structural_verdict="met",
            created_at=datetime.now(UTC),
        )
    )


def _promote(run_id: str, *, title: str = "把选题整理做成每周任务", headers_override: dict | None = None):
    return client.post(
        f"/api/v1/runs/{run_id}/acceptance/tasks",
        headers=headers_override or headers(),
        json={"title": title},
    )


# ---------------------------------------------------------------- 纯函数与仓储


def test_validate_promotion_title_trims_and_rejects_empty_or_too_long() -> None:
    with pytest.raises(RunPromotionError):
        validate_promotion_title("   ")
    with pytest.raises(RunPromotionError):
        validate_promotion_title("x" * (MAX_PROMOTION_TITLE_LENGTH + 1))
    assert validate_promotion_title("  存成每周任务  ") == "存成每周任务"


def test_inmemory_store_claims_once_and_releases() -> None:
    store = InMemoryRunPromotionStore()
    row = RunPromotion(
        tenant_id=TENANT, run_id="run-1", task_id="task-1", title="每周任务",
        promoted_by=EMPLOYEE, created_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
    )
    first, claimed_first = store.claim(row)
    second, claimed_second = store.claim(
        RunPromotion(
            tenant_id=TENANT, run_id="run-1", task_id="task-2", title="另一个标题",
            promoted_by=OTHER_USER, created_at=row.created_at,
        )
    )
    # 判定依据：一个运行只能沉淀一次——第二次 claim 拿回**第一次**那行，不覆盖。
    assert claimed_first is True and claimed_second is False
    assert second.task_id == "task-1" and first.task_id == "task-1"
    assert store.find_for_run(TENANT, "run-1").task_id == "task-1"
    assert store.find_for_run(OTHER_TENANT, "run-1") is None  # 跨租户不可见

    assert store.release(TENANT, "run-1") is True
    assert store.find_for_run(TENANT, "run-1") is None
    assert store.release(TENANT, "run-1") is False  # 幂等：重复释放无副作用


# ---------------------------------------------------------------- 端点：前置闸门


def test_promotion_requires_a_confirmed_decision(wired) -> None:
    run_id = _run()

    response = _promote(run_id)

    assert response.status_code == 409
    assert "先确认完成" in response.json()["detail"]
    assert wired["promotions"].find_for_run(TENANT, run_id) is None, "被拒时不得留下沉淀记录"


def test_promotion_rejected_after_a_rejected_decision(wired) -> None:
    run_id = _run()
    main.run_acceptance_decision_store.record(
        AcceptanceDecision(
            tenant_id=TENANT, run_id=run_id, decision_id="", decision="rejected", reason="不符合要求",
            idempotency_key="dec-rej", decided_by=EMPLOYEE, decided_by_role="employee",
            structural_verdict="unmet", created_at=datetime.now(UTC),
        )
    )

    assert _promote(run_id).status_code == 409


def test_promotion_requires_a_terminal_run(wired) -> None:
    run_id = _run(terminal=False)
    _confirm(run_id)

    response = _promote(run_id)

    assert response.status_code == 409
    assert "尚未结束" in response.json()["detail"]


def test_promotion_hides_other_users_runs_and_tenants(wired) -> None:
    run_id = _run()
    _confirm(run_id)

    assert _promote(run_id, headers_override=headers(OTHER_USER)).status_code == 404
    assert _promote(run_id, headers_override=headers(EMPLOYEE, tenant=OTHER_TENANT)).status_code == 404
    assert _promote("run-does-not-exist").status_code == 404
    assert client.post(
        f"/api/v1/runs/{run_id}/acceptance/tasks", json={"title": "x"}
    ).status_code == 401


def test_promotion_validates_the_request_body(wired) -> None:
    run_id = _run()
    _confirm(run_id)

    assert _promote(run_id, title="   ").status_code == 422
    assert _promote(run_id, title="x" * (MAX_PROMOTION_TITLE_LENGTH + 1)).status_code == 422
    # extra=forbid：客户端指定 task_id / 员工标识一类的字段直接 422（服务端自取，不接受注入）。
    injected = client.post(
        f"/api/v1/runs/{run_id}/acceptance/tasks",
        headers=headers(),
        json={"title": "x", "task_id": "task-evil"},
    )
    assert injected.status_code == 422


# ---------------------------------------------------------------- 端点：正常路径与幂等


def test_promotion_creates_a_task_from_the_source_run(wired) -> None:
    run_id = _run()
    _confirm(run_id)

    response = _promote(run_id)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["run_id"] == run_id and body["created"] is True and body["task_id"]
    # 任务走既有创建路径：参数复刻来源承载任务（员工 / 风险档 / 预算 / 项目），标题取用户输入。
    assert body["task"]["title"] == "把选题整理做成每周任务"
    assert body["task"]["employee_key"] == "content-writer"
    assert body["task"]["risk_level"] == "low"
    assert body["task"]["project_id"] == "proj-1"
    assert body["task"]["created_by"] == EMPLOYEE
    # 真的落库：用同一身份走既有读接口能取回这条任务。
    fetched = client.get(f"/api/v1/tasks/{body['task_id']}", headers=headers())
    assert fetched.status_code == 200 and fetched.json()["title"] == body["task"]["title"]
    # 沉淀关系已登记（界面据此显示「已存成任务」）。
    assert wired["promotions"].find_for_run(TENANT, run_id).task_id == body["task_id"]


def test_promotion_is_idempotent_and_does_not_duplicate_tasks_or_audit(wired) -> None:
    run_id = _run()
    _confirm(run_id)
    before = len(wired["tasks"]._tasks)  # noqa: SLF001 - 断言「不重复建任务」需看仓储规模

    first = _promote(run_id)
    replay = _promote(run_id, title="换个标题也不行")

    assert first.status_code == 201 and replay.status_code == 200
    assert replay.json()["task_id"] == first.json()["task_id"]
    assert replay.json()["created"] is False
    assert len(wired["tasks"]._tasks) == before + 1, "重复提交不得再建第二条任务"
    actions = [action for action, _detail in wired["audit"].records]
    assert actions.count("run.promoted_to_task") == 1, "重复提交不得重复写审计"


def test_promotion_audit_carries_only_the_task_id(wired) -> None:
    run_id = _run()
    _confirm(run_id)

    _promote(run_id, title="含敏感说明的标题")

    detail = [d for action, d in wired["audit"].records if action == "run.promoted_to_task"][0]
    assert detail == {"task_id": wired["promotions"].find_for_run(TENANT, run_id).task_id}
    assert "含敏感说明的标题" not in str(wired["audit"].records), "标题正文不得进审计"


def test_decisions_endpoint_exposes_the_promotion_state(wired) -> None:
    run_id = _run()
    _confirm(run_id)

    before = client.get(f"/api/v1/runs/{run_id}/acceptance/decisions", headers=headers()).json()
    promoted = _promote(run_id).json()
    after = client.get(f"/api/v1/runs/{run_id}/acceptance/decisions", headers=headers()).json()

    assert before["promotion"] is None
    assert after["promotion"]["task_id"] == promoted["task_id"]
    assert after["promotion"]["title"] == "把选题整理做成每周任务"
    assert "tenant_id" not in after["promotion"], "租户标识不外泄"


# ---------------------------------------------------------------- 真库（pg16）


PG_DSN = os.environ.get("WORKBENCH_TEST_DATABASE_URL", "")
PG_TENANT = "test-promote-pg"
PG_RUN = "run-promote-pg"
PG_TASK = "task-promote-pg"


def test_postgres_promotion_store_claims_once_and_rejects_cross_tenant() -> None:
    if not PG_DSN:
        pytest.skip("未设置 WORKBENCH_TEST_DATABASE_URL，跳过真库集成测试")
    psycopg = pytest.importorskip("psycopg")
    from pathlib import Path

    from app.migrations import apply_migrations
    from app.runtime.promotions import PostgresRunPromotionStore

    connection = psycopg.connect(PG_DSN, autocommit=True)
    apply_migrations(connection, Path(__file__).resolve().parents[1] / "migrations")
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO workbench_run_records (run_id, tenant_id, task_id, runtime_key, status) "
            "VALUES (%s, %s, %s, 'mock', 'completed') ON CONFLICT (run_id) DO NOTHING",
            (PG_RUN, PG_TENANT, PG_TASK),
        )
    store = PostgresRunPromotionStore(connection)
    try:
        row = RunPromotion(
            tenant_id=PG_TENANT, run_id=PG_RUN, task_id="task-promote-1", title="每周任务",
            promoted_by="u-1", created_at=datetime.now(UTC),
        )
        stored, created = store.claim(row)
        again, created_again = store.claim(
            RunPromotion(
                tenant_id=PG_TENANT, run_id=PG_RUN, task_id="task-promote-2", title="抢同一个运行",
                promoted_by="u-2", created_at=row.created_at,
            )
        )
        assert created is True and created_again is False
        assert again.task_id == stored.task_id == "task-promote-1"
        assert store.find_for_run(PG_TENANT, PG_RUN).title == "每周任务"

        # 跨租户：复合外键 `(tenant_id, run_id)` 的父行不存在 ⇒ 直接拒写（不是应用层判断）。
        with pytest.raises(Exception):
            store.claim(
                RunPromotion(
                    tenant_id="test-promote-pg-other", run_id=PG_RUN, task_id="task-x", title="跨租户",
                    promoted_by="u-1", created_at=row.created_at,
                )
            )

        assert store.release(PG_TENANT, PG_RUN) is True
        assert store.find_for_run(PG_TENANT, PG_RUN) is None
    finally:
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM workbench_run_promotions WHERE tenant_id = %s", (PG_TENANT,))
            cursor.execute("DELETE FROM workbench_run_records WHERE tenant_id = %s", (PG_TENANT,))
        connection.close()