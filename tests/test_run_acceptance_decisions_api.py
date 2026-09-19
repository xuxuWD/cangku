"""S2 运行**人工验收决议**：`POST/GET /api/v1/runs/{run_id}/acceptance/decisions`。

口径（真源）：`docs/api-contract.md`「运行验收决议（S2 · 人工验收 · 2026-09-18）」；
接缝出处 `docs/superpowers/specs/2026-09-18-workbench-closed-loop-design.md` §3（S2，M3 范围）。

关键断言（每条都对应可检查的纪律）：
  * **只记录不改状态**：决议前后运行记录与运行状态逐字段不变、**不调模型**（探针一调用即失败）；
  * **权限独立判定**：任务创建人 / CEO / 超管可决议；他人 / 跨租户 / 未知运行一律 `404`；
  * **仅终态可决议**：运行中 ⇒ `409`（不排队等待）；
  * **打回必须写原因**：缺原因 ⇒ `422`；原因只进决议表，**审计明细不含正文**；
  * **幂等**：同键重放返回既有决议（`created: false`）且**不重复写审计**；不同键追加新行（append-only）；
  * **读侧**：最新在前、`latest` 为最新一条；响应不含 `tenant_id` / `idempotency_key`。
"""

from __future__ import annotations

import json
import os

import pytest
from fastapi.testclient import TestClient

from app import main
from app.audit.models import AuditAction
from app.domain import RiskLevel, Task, TaskStatus, TaskStore, UserContext
from app.main import app
from app.runtime.acceptance_decisions import (
    AcceptanceDecision,
    AcceptanceDecisionError,
    InMemoryAcceptanceDecisionStore,
    validate_decision,
)
from app.runtime.records import InMemoryRunRecordStore, RunRecord
from app.runtime.run_metrics import RunMetricsService
from app.runtime.service import RuntimeService
from app.tool_execution.store import InMemoryToolActionStore

client = TestClient(app)
TENANT = "t-acceptance"
OTHER_TENANT = "t-acceptance-other"
EMPLOYEE = "u-1"


class _ModelProbe:
    """「一调用即失败」的模型探针：验收决议若改接 LLM / 生成器，本探针必被触发 ⇒ 用例变红。"""

    def __init__(self) -> None:
        self.calls = 0
        self.generator = self
        self.model_gateway = self

    def generate(self, *args, **kwargs):  # noqa: ANN002, ANN003 - 探针只需失败
        self.calls += 1
        raise AssertionError("验收决议不得调用模型")

    def choose(self, *args, **kwargs):  # noqa: ANN002, ANN003
        self.calls += 1
        raise AssertionError("验收决议不得调用模型")


class _AuditSpy:
    """审计探针：记录每次写的动作与明细（用于断言「不重复写审计」与「不含理由正文」）。"""

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
    probe = _ModelProbe()
    audit = _AuditSpy()
    monkeypatch.setattr(main, "store", tasks)
    monkeypatch.setattr(main, "run_metrics_service", metrics)
    monkeypatch.setattr(main, "runtime_service", runtime)
    monkeypatch.setattr(main, "run_acceptance_decision_store", decisions)
    monkeypatch.setattr(main, "audit_service", audit)
    monkeypatch.setattr(main, "planner_service", probe, raising=False)
    return {"tasks": tasks, "runs": runs, "runtime": runtime, "decisions": decisions, "probe": probe, "audit": audit}


def headers(user_id: str = EMPLOYEE, role: str = "employee", tenant: str = TENANT) -> dict[str, str]:
    return {"X-Tenant-Id": tenant, "X-User-Id": user_id, "X-User-Role": role}


def _task(tenant: str = TENANT, user_id: str = EMPLOYEE) -> Task:
    task = Task(
        tenant_id=tenant,
        project_id=None,
        created_by=user_id,
        employee_key="content-writer",
        title="验收决议用例",
        risk_level=RiskLevel.LOW,
        budget=0,
        idempotency_key=f"acceptance-{tenant}-{user_id}",
        request_fingerprint="fp",
        status=TaskStatus.QUEUED,
    )
    stored, _created = main.store.create(UserContext(tenant, user_id, "employee"), task)
    return stored


def _start_run(wired, *, approval: bool = False, tenant: str = TENANT, user_id: str = EMPLOYEE) -> str:
    task = _task(tenant, user_id)
    steps = [
        {
            "step_id": "step-1",
            "kind": "write" if approval else "read",
            "tool": "fs.read",
            "requires_approval": approval,
        }
    ]
    run_id, _key, _policy = main.runtime_service.start(
        UserContext(tenant, user_id, "employee"), task.id, "mock", steps, "fde"
    )
    return run_id


def _body(**patch) -> dict:
    body = {"decision": "confirmed", "reason": "", "idempotency_key": "k-1"}
    body.update(patch)
    return body


# ---------------------------------------------------------------- 纯函数：入参校验


def test_validate_decision_requires_reason_for_rejection() -> None:
    with pytest.raises(AcceptanceDecisionError):
        validate_decision(
            decision="rejected", reason="   ", idempotency_key="k", structural_verdict="met"
        )
    with pytest.raises(AcceptanceDecisionError):
        validate_decision(
            decision="confirmed", reason="x", idempotency_key="", structural_verdict="met"
        )
    with pytest.raises(AcceptanceDecisionError):
        validate_decision(
            decision="maybe", reason="", idempotency_key="k", structural_verdict="met"
        )
    with pytest.raises(AcceptanceDecisionError):
        validate_decision(
            decision="confirmed", reason="", idempotency_key="k", structural_verdict="unknown"
        )
    decision, reason = validate_decision(
        decision="rejected", reason="  结果不对  ", idempotency_key="k", structural_verdict="unmet"
    )
    assert (decision, reason) == ("rejected", "结果不对")


def test_inmemory_store_is_idempotent_and_keeps_history() -> None:
    counter = {"n": 0}

    def _next_id() -> str:
        counter["n"] += 1
        return f"d-{counter['n']}"

    store = InMemoryAcceptanceDecisionStore(id_factory=_next_id)
    first, created_first = store.record(
        _decision_row(decision="rejected", reason="差一步", idempotency_key="k-1")
    )
    replay, created_replay = store.record(
        _decision_row(decision="confirmed", reason="", idempotency_key="k-1")
    )
    assert created_first is True and created_replay is False
    assert replay.decision_id == first.decision_id and replay.decision == "rejected"
    store.record(_decision_row(decision="confirmed", reason="", idempotency_key="k-2"))
    items = store.list_for_run(TENANT, "run-1")
    assert [item.idempotency_key for item in items] == ["k-2", "k-1"]  # 最新在前


def _decision_row(*, decision: str, reason: str, idempotency_key: str):
    from datetime import UTC, datetime

    from app.runtime.acceptance_decisions import AcceptanceDecision

    return AcceptanceDecision(
        tenant_id=TENANT,
        run_id="run-1",
        decision_id="",
        decision=decision,
        reason=reason,
        idempotency_key=idempotency_key,
        decided_by=EMPLOYEE,
        decided_by_role="employee",
        structural_verdict="met",
        created_at=datetime.now(UTC),
    )


# ---------------------------------------------------------------- 端点：写侧


def test_confirm_records_decision_and_does_not_touch_run(wired) -> None:
    run_id = _start_run(wired)
    before = main.run_metrics_service.store.get(TENANT, run_id)
    response = client.post(
        f"/api/v1/runs/{run_id}/acceptance/decisions", headers=headers(), json=_body()
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["decision"] == "confirmed" and body["created"] is True
    assert body["structural_verdict"] == "met"
    assert body["decided_by"] == EMPLOYEE
    assert "tenant_id" not in body and "idempotency_key" not in body
    after = main.run_metrics_service.store.get(TENANT, run_id)
    assert after == before, "验收决议不得改动运行记录"
    snapshot = main.runtime_service.snapshot(UserContext(TENANT, EMPLOYEE, "employee"), run_id)
    assert snapshot.status == "completed"
    assert wired["probe"].calls == 0, "验收决议不得调用模型"


def test_reject_requires_reason_and_records_it(wired) -> None:
    run_id = _start_run(wired)
    missing = client.post(
        f"/api/v1/runs/{run_id}/acceptance/decisions",
        headers=headers(),
        json=_body(decision="rejected", reason="   "),
    )
    assert missing.status_code == 422
    assert "原因" in missing.json()["detail"]

    ok = client.post(
        f"/api/v1/runs/{run_id}/acceptance/decisions",
        headers=headers(),
        json=_body(decision="rejected", reason="结果与要求不符", idempotency_key="k-2"),
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["decision"] == "rejected" and ok.json()["reason"] == "结果与要求不符"


def test_audit_records_decision_without_reason_text(wired) -> None:
    run_id = _start_run(wired)
    client.post(
        f"/api/v1/runs/{run_id}/acceptance/decisions",
        headers=headers(),
        json=_body(decision="rejected", reason="客户不满意", idempotency_key="k-3"),
    )
    actions = [action for action, _detail in wired["audit"].records]
    assert actions == [AuditAction.RUN_ACCEPTANCE_DECIDED.value]
    detail = wired["audit"].records[0][1]
    assert detail == {"decision": "rejected", "structural_verdict": "met", "reason_present": True}
    assert "客户不满意" not in json.dumps(detail, ensure_ascii=False)


def test_audit_detail_keys_are_accepted_by_the_real_audit_builder() -> None:
    """用**真审计器**复核明细键：探针（`_AuditSpy`）会绕过 `ALLOWED_DETAIL_KEYS` 白名单，
    只看探针会得到「接口通了但生产写审计会抛异常」的假绿——这里把口径钉死。"""
    from app.audit.models import build_record

    record = build_record(
        AuditAction.RUN_ACCEPTANCE_DECIDED,
        tenant_id=TENANT,
        detail={"decision": "confirmed", "structural_verdict": "met", "reason_present": False},
    )
    assert record.detail == {
        "decision": "confirmed",
        "structural_verdict": "met",
        "reason_present": False,
    }


def test_replay_with_same_key_does_not_write_audit_twice(wired) -> None:
    run_id = _start_run(wired)
    first = client.post(
        f"/api/v1/runs/{run_id}/acceptance/decisions", headers=headers(), json=_body()
    )
    second = client.post(
        f"/api/v1/runs/{run_id}/acceptance/decisions", headers=headers(), json=_body()
    )
    assert first.json()["created"] is True and second.json()["created"] is False
    assert second.json()["decision_id"] == first.json()["decision_id"]
    assert len(wired["audit"].records) == 1, "幂等重放不得重复写审计"
    assert len(wired["decisions"].list_for_run(TENANT, run_id)) == 1


def test_decisions_are_append_only(wired) -> None:
    run_id = _start_run(wired)
    client.post(
        f"/api/v1/runs/{run_id}/acceptance/decisions",
        headers=headers(),
        json=_body(decision="rejected", reason="重做", idempotency_key="k-1"),
    )
    client.post(
        f"/api/v1/runs/{run_id}/acceptance/decisions",
        headers=headers(),
        json=_body(idempotency_key="k-2"),
    )
    listed = client.get(f"/api/v1/runs/{run_id}/acceptance/decisions", headers=headers()).json()
    assert [item["decision"] for item in listed["items"]] == ["confirmed", "rejected"]
    assert listed["latest"]["decision"] == "confirmed"
    assert len(wired["audit"].records) == 2


def test_non_terminal_run_cannot_be_accepted(wired) -> None:
    run_id = _start_run(wired, approval=True)  # 待审批 ⇒ 运行中
    response = client.post(
        f"/api/v1/runs/{run_id}/acceptance/decisions", headers=headers(), json=_body()
    )
    assert response.status_code == 409
    assert wired["audit"].records == []


def test_only_owner_or_admin_can_decide(wired) -> None:
    run_id = _start_run(wired)
    # 他人（同租户普通员工）⇒ 404（不区分「无权限」与「不存在」）
    assert (
        client.post(
            f"/api/v1/runs/{run_id}/acceptance/decisions", headers=headers("u-2"), json=_body()
        ).status_code
        == 404
    )
    # 跨租户（含 CEO）⇒ 404
    assert (
        client.post(
            f"/api/v1/runs/{run_id}/acceptance/decisions",
            headers=headers("ceo-1", "ceo", OTHER_TENANT),
            json=_body(),
        ).status_code
        == 404
    )
    # 未知运行 ⇒ 404
    assert (
        client.post(
            "/api/v1/runs/run-unknown/acceptance/decisions", headers=headers(), json=_body()
        ).status_code
        == 404
    )
    # 同租户 CEO 可决议（管理员兜底口径）
    assert (
        client.post(
            f"/api/v1/runs/{run_id}/acceptance/decisions",
            headers=headers("ceo-1", "ceo"),
            json=_body(idempotency_key="k-ceo"),
        ).status_code
        == 200
    )


def test_unknown_field_is_rejected(wired) -> None:
    run_id = _start_run(wired)
    response = client.post(
        f"/api/v1/runs/{run_id}/acceptance/decisions",
        headers=headers(),
        json={**_body(), "decided_by": "spoofed"},
    )
    assert response.status_code == 422


# ---------------------------------------------------------------- 端点：读侧


def test_list_is_empty_before_any_decision(wired) -> None:
    run_id = _start_run(wired)
    body = client.get(f"/api/v1/runs/{run_id}/acceptance/decisions", headers=headers()).json()
    assert body == {"run_id": run_id, "items": [], "latest": None, "promotion": None}


def test_list_not_found_for_unknown_and_foreign_runs(wired) -> None:
    run_id = _start_run(wired)
    assert (
        client.get("/api/v1/runs/run-unknown/acceptance/decisions", headers=headers()).status_code
        == 404
    )
    assert (
        client.get(
            f"/api/v1/runs/{run_id}/acceptance/decisions",
            headers=headers("u-2", "employee", OTHER_TENANT),
        ).status_code
        == 404
    )
    # 同租户他人：承载任务不可见且非成员 ⇒ 404（与 /acceptance 同一读口径）
    assert (
        client.get(f"/api/v1/runs/{run_id}/acceptance/decisions", headers=headers("u-2")).status_code
        == 404
    )


def test_decision_view_keeps_structural_verdict_for_traceability(wired) -> None:
    """未达标也能确认完成（人的结论不被机器结论卡住），但结构判定如实记录。"""
    run_id = _start_run(wired, approval=True)
    # 先驳回待审批 ⇒ 终态 failed（approval_rejected），结构判定 unmet
    main.runtime_service.decide_approval(
        UserContext(TENANT, "ceo-1", "ceo"), run_id, "step-1", False
    )
    record: RunRecord = main.run_metrics_service.store.get(TENANT, run_id)
    assert str(record.status) in {"failed", "completed"}
    response = client.post(
        f"/api/v1/runs/{run_id}/acceptance/decisions",
        headers=headers("ceo-1", "ceo"),
        json=_body(idempotency_key="k-unmet"),
    )
    assert response.status_code == 200, response.text
    assert response.json()["structural_verdict"] == "unmet"


# ---------------------------------------------------------------- 真库：PG 实现（迁移 040）
#
# 口径沿用 `tests/test_tool_action_store_postgres.py` 的先例：
#   * DSN 从 `WORKBENCH_TEST_DATABASE_URL` 读；**未设置即 skip**（默认全量不受影响）；
#   * 建表**必须调用仓库自身的迁移函数**（`apply_migrations`），不另写一套 DDL（否则库结构与代码漂移）；
#   * 只操作本文件自己的租户，用例前后自清。

PG_DSN = os.environ.get("WORKBENCH_TEST_DATABASE_URL", "")
PG_TENANT = "test-acceptance-pg"
PG_OTHER_TENANT = "test-acceptance-pg-other"
PG_RUN = "run-acceptance-pg"
PG_TASK = "task-acceptance-pg"


def _pg_row(*, decision: str, reason: str, idempotency_key: str, tenant: str = PG_TENANT) -> AcceptanceDecision:
    from datetime import UTC, datetime

    return AcceptanceDecision(
        tenant_id=tenant,
        run_id=PG_RUN,
        decision_id="",
        decision=decision,
        reason=reason,
        idempotency_key=idempotency_key,
        decided_by="pg-u-1",
        decided_by_role="employee",
        structural_verdict="met",
        created_at=datetime.now(UTC),
    )


@pytest.fixture()
def pg_store():
    if not PG_DSN:
        pytest.skip("未设置 WORKBENCH_TEST_DATABASE_URL，跳过真库集成测试")
    psycopg = pytest.importorskip("psycopg")
    from pathlib import Path

    from app.migrations import apply_migrations
    from app.runtime.acceptance_decisions import PostgresAcceptanceDecisionStore

    connection = psycopg.connect(PG_DSN, autocommit=True)
    apply_migrations(connection, Path(__file__).resolve().parents[1] / "migrations")
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO workbench_run_records (run_id, tenant_id, task_id, runtime_key, status)
            VALUES (%s, %s, %s, 'mock', 'completed')
            ON CONFLICT (run_id) DO NOTHING
            """,
            (PG_RUN, PG_TENANT, PG_TASK),
        )
        cursor.execute(
            "DELETE FROM workbench_run_acceptance_decisions WHERE tenant_id = %s", (PG_TENANT,)
        )
    yield PostgresAcceptanceDecisionStore(connection)
    with connection.cursor() as cursor:
        cursor.execute(
            "DELETE FROM workbench_run_acceptance_decisions WHERE tenant_id = %s", (PG_TENANT,)
        )
    connection.close()


def test_postgres_roundtrip_is_idempotent_and_ordered(pg_store) -> None:
    first, created = pg_store.record(
        _pg_row(decision="rejected", reason="重做", idempotency_key="pg-k-1")
    )
    replay, created_again = pg_store.record(
        _pg_row(decision="confirmed", reason="", idempotency_key="pg-k-1")
    )
    assert created is True and created_again is False
    assert replay.decision_id == first.decision_id and replay.decision == "rejected"

    pg_store.record(_pg_row(decision="confirmed", reason="", idempotency_key="pg-k-2"))
    items = pg_store.list_for_run(PG_TENANT, PG_RUN)
    assert [item.idempotency_key for item in items] == ["pg-k-2", "pg-k-1"]  # 最新在前
    assert all(item.tenant_id == PG_TENANT for item in items)


def test_postgres_rejects_cross_tenant_writes(pg_store) -> None:
    """复合外键 `(tenant_id, run_id)`：他人租户写不进去（租户隔离写进约束，不靠应用层自觉）。"""
    with pytest.raises(Exception):
        pg_store.record(
            _pg_row(
                decision="confirmed",
                reason="",
                idempotency_key="pg-k-other",
                tenant=PG_OTHER_TENANT,
            )
        )
    assert pg_store.list_for_run(PG_OTHER_TENANT, PG_RUN) == []