"""P2c-4 运行**结构判定**（自动验收）：`GET /api/v1/runs/{run_id}/acceptance`。

口径（真源）：`docs/superpowers/specs/2026-09-17-frontend-interaction-p2c-design.md` §2.5（含实现期裁定）
与 `docs/api-contract.md`「运行结构判定」；三条件**全满足** ⇒ `met`：
① 步骤全部完成 ② 无未决审批 ③ `finish_reason` 为正常终态（`run_completed`）。

关键断言（规格 §4「P2c-4 真库用例」⑧）：
  * 三条件**各造一例**（分别置为不满足 ⇒ 未达标；全满足 ⇒ 达标）；
  * **不调模型**：把规划器模型网关与生成器替换为「一调用即失败」的探针，端点仍 `200`（改接 LLM 必红）；
  * **不改运行状态**：调用前后运行记录与运行状态逐字段不变（纯读）；
  * 归属：未知 / 跨租户 / 他人运行一律 `404`。
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app import main
from app.domain import RiskLevel, Task, TaskStatus, UserContext
from app.main import app
from app.runtime.acceptance import AcceptanceVerdict, evaluate_acceptance
from app.runtime.records import FinishReason, InMemoryRunRecordStore, RunRecord
from app.runtime.run_metrics import RunMetricsService
from app.runtime.service import RuntimeService
from app.tool_execution.store import InMemoryToolActionStore
from app.domain import TaskStore

client = TestClient(app)
TENANT = "t-accept"
OTHER_TENANT = "t-accept-other"
EMPLOYEE = "u-1"


class _ModelProbe:
    """「一调用即失败」的模型探针：结构判定若改接 LLM，本探针必被触发 ⇒ 用例变红。"""

    def __init__(self) -> None:
        self.calls = 0
        # 结构判定若走「规划器 → 生成器 / 模型网关」任一路径，都会命中下面两个别名。
        self.generator = self
        self.model_gateway = self

    def generate(self, *args, **kwargs):  # noqa: ANN002, ANN003 - 探针只需失败
        self.calls += 1
        raise AssertionError("结构判定不得调用模型")

    def choose(self, *args, **kwargs):  # noqa: ANN002, ANN003
        self.calls += 1
        raise AssertionError("结构判定不得调用模型")


@pytest.fixture()
def wired(monkeypatch):
    tasks = TaskStore()
    runs = InMemoryRunRecordStore()
    metrics = RunMetricsService(runs)
    runtime = RuntimeService(tasks, run_metrics=metrics, tool_actions=InMemoryToolActionStore())
    probe = _ModelProbe()
    monkeypatch.setattr(main, "store", tasks)
    monkeypatch.setattr(main, "run_metrics_service", metrics)
    monkeypatch.setattr(main, "runtime_service", runtime)
    monkeypatch.setattr(main, "planner_service", probe, raising=False)
    return {"tasks": tasks, "runs": runs, "runtime": runtime, "probe": probe}


def headers(user_id: str = EMPLOYEE, role: str = "employee", tenant: str = TENANT) -> dict[str, str]:
    return {"X-Tenant-Id": tenant, "X-User-Id": user_id, "X-User-Role": role}


def _task(tenant: str = TENANT, user_id: str = EMPLOYEE) -> Task:
    task = Task(
        tenant_id=tenant,
        project_id=None,
        created_by=user_id,
        employee_key="content-writer",
        title="结构判定用例",
        risk_level=RiskLevel.LOW,
        budget=0,
        idempotency_key=f"accept-{tenant}-{user_id}",
        request_fingerprint="fp",
        status=TaskStatus.QUEUED,
    )
    context = UserContext(tenant, user_id, "employee")
    stored, _created = main.store.create(context, task)
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
    run_id, _key, _policy = wired["runtime"].start(
        UserContext(tenant, user_id, "employee"), task.id, "mock", steps, "product_manager"
    )
    return run_id


def _override_record(wired, run_id: str, **overrides) -> RunRecord:
    base = wired["runs"].get(TENANT, run_id)
    record = RunRecord(
        run_id=base.run_id,
        tenant_id=base.tenant_id,
        task_id=base.task_id,
        runtime_key=base.runtime_key,
        status=overrides.get("status", base.status),
        started_at=base.started_at,
        step_count=overrides.get("step_count", base.step_count),
        completed_step_count=overrides.get("completed_step_count", base.completed_step_count),
        tool_calls=base.tool_calls,
        successful_tools=base.successful_tools,
        knowledge_hits=base.knowledge_hits,
        latency_ms=base.latency_ms,
        finished_at=base.finished_at,
        finish_reason=overrides.get("finish_reason", base.finish_reason),
    )
    return wired["runs"].upsert(record)


# --------------------------------------------------------------- 纯函数（三条件）


def test_evaluate_acceptance_three_conditions_independently() -> None:
    met = evaluate_acceptance(
        status="completed",
        step_count=2,
        completed_step_count=2,
        finish_reason="run_completed",
        approval_statuses=("approved",),
    )
    assert met.verdict is AcceptanceVerdict.MET
    assert met.steps_complete and met.no_pending_approvals and met.finish_reason_ok

    # ① 步骤未完成
    steps = evaluate_acceptance(
        status="completed", step_count=2, completed_step_count=1, finish_reason="run_completed"
    )
    assert steps.verdict is AcceptanceVerdict.UNMET and steps.steps_complete is False

    # ② 有未决审批
    pending = evaluate_acceptance(
        status="completed", step_count=1, completed_step_count=1, finish_reason="run_completed",
        approval_statuses=("pending",),
    )
    assert pending.verdict is AcceptanceVerdict.UNMET and pending.no_pending_approvals is False
    assert pending.pending_approvals == 1

    # ③ 非正常终态（失败 / 驳回 / 取消 / 未终态）
    for reason, status in (
        ("step_failed", "failed"),
        ("approval_rejected", "failed"),
        ("cancelled_by_user", "cancelled"),
        (None, "running"),
    ):
        abnormal = evaluate_acceptance(
            status=status, step_count=1, completed_step_count=1, finish_reason=reason
        )
        assert abnormal.verdict is AcceptanceVerdict.UNMET, reason
        assert abnormal.finish_reason_ok is False

    # 退化：无步骤（step_count = 0）视为步骤满足（沿用既有展示口径）。
    empty = evaluate_acceptance(
        status="completed", step_count=0, completed_step_count=0, finish_reason="run_completed"
    )
    assert empty.verdict is AcceptanceVerdict.MET


# --------------------------------------------------------------- 端点（达标 / 未达标）


def test_acceptance_endpoint_met_and_unmet(wired) -> None:
    met_run = _start_run(wired)
    _override_record(
        wired, met_run, status="completed", step_count=1, completed_step_count=1,
        finish_reason=FinishReason.RUN_COMPLETED,
    )
    met = client.get(f"/api/v1/runs/{met_run}/acceptance", headers=headers())
    assert met.status_code == 200, met.text
    assert met.json() == {
        "run_id": met_run,
        "verdict": "met",
        "checks": {"steps_complete": True, "no_pending_approvals": True, "finish_reason_ok": True},
        "steps": {"completed": 1, "total": 1},
        "pending_approvals": 0,
        "finish_reason": "run_completed",
        "status": "completed",
    }

    unfinished = _start_run(wired)
    _override_record(
        wired, unfinished, status="completed", step_count=2, completed_step_count=1,
        finish_reason=FinishReason.RUN_COMPLETED,
    )
    unmet = client.get(f"/api/v1/runs/{unfinished}/acceptance", headers=headers())
    assert unmet.status_code == 200 and unmet.json()["verdict"] == "unmet"
    assert unmet.json()["checks"]["steps_complete"] is False


def test_acceptance_endpoint_reports_pending_approval(wired) -> None:
    run_id = _start_run(wired, approval=True)
    _override_record(
        wired, run_id, status="completed", step_count=1, completed_step_count=1,
        finish_reason=FinishReason.RUN_COMPLETED,
    )
    body = client.get(f"/api/v1/runs/{run_id}/acceptance", headers=headers()).json()
    assert body["verdict"] == "unmet"
    assert body["checks"]["no_pending_approvals"] is False and body["pending_approvals"] == 1


def test_acceptance_endpoint_reports_failed_finish_reason(wired) -> None:
    run_id = _start_run(wired)
    _override_record(
        wired, run_id, status="failed", step_count=1, completed_step_count=1,
        finish_reason=FinishReason.STEP_FAILED,
    )
    body = client.get(f"/api/v1/runs/{run_id}/acceptance", headers=headers()).json()
    assert body["verdict"] == "unmet"
    assert body["checks"] == {
        "steps_complete": True,
        "no_pending_approvals": True,
        "finish_reason_ok": False,
    }


# --------------------------------------------------------------- 纯读：不调模型 / 不改状态


def test_acceptance_endpoint_never_calls_model_and_keeps_state(wired) -> None:
    run_id = _start_run(wired)
    _override_record(
        wired, run_id, status="completed", step_count=1, completed_step_count=1,
        finish_reason=FinishReason.RUN_COMPLETED,
    )
    context = UserContext(TENANT, EMPLOYEE, "employee")
    before_record = wired["runs"].get(TENANT, run_id)
    before_state = json.dumps(vars(wired["runtime"].snapshot(context, run_id)), default=str, sort_keys=True)

    response = client.get(f"/api/v1/runs/{run_id}/acceptance", headers=headers())
    assert response.status_code == 200
    assert wired["probe"].calls == 0  # 「不调模型」断言（模型探针零调用）

    after_record = wired["runs"].get(TENANT, run_id)
    after_state = json.dumps(vars(wired["runtime"].snapshot(context, run_id)), default=str, sort_keys=True)
    assert before_record == after_record  # 判定不改运行记录
    assert before_state == after_state  # 判定不改运行状态


# --------------------------------------------------------------- 归属（404）


def test_acceptance_endpoint_not_found_for_unknown_and_foreign_runs(wired) -> None:
    assert client.get("/api/v1/runs/run-unknown/acceptance", headers=headers()).status_code == 404

    other_run = _start_run(wired, tenant=OTHER_TENANT, user_id="u-9")
    # 跨租户（本租户员工看不到他租户运行）⇒ 404。
    assert client.get(
        f"/api/v1/runs/{other_run}/acceptance", headers=headers("u-2", "employee")
    ).status_code == 404
    # 同租户内：本人可读；`ceo` 可读他人运行（沿用既有只读口径）。
    assert client.get(
        f"/api/v1/runs/{other_run}/acceptance", headers=headers("u-9", "employee", OTHER_TENANT)
    ).status_code == 200
    assert client.get(
        f"/api/v1/runs/{other_run}/acceptance", headers=headers("ceo-1", "ceo", OTHER_TENANT)
    ).status_code == 200
    # 同租户内的普通同事（非 CEO / 非本人）⇒ 404（不泄露存在性）。
    assert client.get(
        f"/api/v1/runs/{other_run}/acceptance", headers=headers("u-2", "employee", OTHER_TENANT)
    ).status_code == 404