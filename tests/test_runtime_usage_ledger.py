"""运行终态 → 商业化用量账本（E1 / 方案 A）。

先写测试（本文件即验收证据）：

- 一次运行走到**终态** ⇒ 追加式账本多一条：`units=1`、`cost_cents=0`
  （`docs/superpowers/specs/2026-09-06-commercial-g0-design.md:72`「内部版……记录用量，
  **不向员工计费**」）。
- **幂等**：同一 `(task_id, run_id)` 重复触发终态同步 ⇒ 不产生第二条
  （真源 `:171`「用量账本按任务和运行幂等记账」）。
- **租户隔离**：`total` 只汇总本租户。
- **只记 1 run = 1 unit**：不拿运行内 `tool_calls` 当 units。
- `GET /api/v1/commercial/usage` 的 `units`/`cost_cents` **不再恒 0**（`units>0`、`cost_cents==0`）。

`units` 语义沿用「未定义、只展示原值」口径
（`docs/superpowers/specs/2026-09-12-usage-billing-page-design.md:49/:66`）；
冲正（`reverse` / `reverse_usage`）**未接线（本期不做）**。
"""

from fastapi.testclient import TestClient

from app import main
from app.commercial.usage import InMemoryUsageLedger
from app.domain import RiskLevel, Task, TaskStatus, TaskStore, UserContext
from app.main import app
from app.runtime.records import InMemoryRunRecordStore
from app.runtime.run_metrics import RunMetricsService
from app.runtime.service import RuntimeService

client = TestClient(app)

OWNER = UserContext("t-1", "u-1", "employee")
# 两步「读」：运行内 `tool_calls=2`，用来证明 units **不是** tool_calls（应为 1）。
TWO_READ_STEPS = [
    {"step_id": "s1", "kind": "read", "tool": "knowledge.search"},
    {"step_id": "s2", "kind": "read", "tool": "knowledge.search"},
]
# 待审批步骤：运行停在「运行中」（终态不可再干预，故干预类用例必须用非终态运行）。
PENDING_STEPS = [{"step_id": "s1", "kind": "write", "tool": "fs.write", "requires_approval": True}]


def make_task(task_store: TaskStore, *, tenant_id: str = "t-1", created_by: str = "u-1") -> Task:
    task = Task(
        tenant_id=tenant_id,
        project_id=None,
        created_by=created_by,
        employee_key="content-operator",
        title="整理选题",
        risk_level=RiskLevel.LOW,
        budget=1,
        idempotency_key=f"usage-{tenant_id}-{created_by}",
        request_fingerprint="fp",
        status=TaskStatus.QUEUED,
    )
    task_store.create(UserContext(tenant_id, created_by, "employee"), task)
    return task


def build() -> tuple[RuntimeService, InMemoryUsageLedger, Task]:
    task_store = TaskStore()
    task = make_task(task_store)
    ledger = InMemoryUsageLedger()
    runtime = RuntimeService(
        task_store,
        run_metrics=RunMetricsService(InMemoryRunRecordStore()),
        usage_ledger=ledger,
    )
    return runtime, ledger, task


def test_terminal_run_appends_exactly_one_unit_with_zero_cost() -> None:
    runtime, ledger, task = build()

    run_id, _key, _policy = runtime.start(OWNER, task.id, "mock", TWO_READ_STEPS, "product_manager")
    state = runtime.snapshot(OWNER, run_id)
    # 前提：运行确实到终态，且运行内 tool_calls=2（用于区分 units 与 tool_calls）。
    assert state.status == "completed"
    assert state.usage["tool_calls"] == 2

    assert ledger.total("t-1") == 1
    assert ledger.total_cost_cents("t-1") == 0


def test_same_task_and_run_is_recorded_once() -> None:
    runtime, ledger, task = build()

    run_id, _key, _policy = runtime.start(OWNER, task.id, "mock", TWO_READ_STEPS, "product_manager")
    assert ledger.total("t-1") == 1

    # 终态即终态（2026-09-18 收紧：终态上暂停 / 取消一律 409）⇒ 公开接口不再能对同一运行触发第二次终态同步。
    # 账本幂等键（task_id + run_id）仍必须守住「重复终态同步只落一条」（补偿写 / 重试路径），故直接调回写钩子。
    runtime._sync_run_record(OWNER, run_id, "mock", latency_ms=0)

    assert ledger.total("t-1") == 1
    assert ledger.total_cost_cents("t-1") == 0


def test_non_terminal_sync_does_not_write_usage() -> None:
    runtime, ledger, task = build()

    # 待审批步骤 ⇒ 运行停在「运行中」：非终态同步一律不记账（暂停 / 恢复同理）。
    run_id, _key, _policy = runtime.start(OWNER, task.id, "mock", PENDING_STEPS, "product_manager")
    assert ledger.total("t-1") == 0

    runtime.pause(OWNER, run_id, "暂停")
    assert ledger.total("t-1") == 0

    runtime.resume(OWNER, run_id)
    assert ledger.total("t-1") == 0


def test_usage_total_is_tenant_scoped() -> None:
    runtime, ledger, task = build()

    runtime.start(OWNER, task.id, "mock", TWO_READ_STEPS, "product_manager")

    assert ledger.total("t-1") == 1
    assert ledger.total_cost_cents("t-1") == 0
    assert ledger.total("t-other") == 0
    assert ledger.total_cost_cents("t-other") == 0


def test_usage_endpoint_reflects_terminal_run(monkeypatch) -> None:
    """接口读到的是运行终态写下的账本，而不是恒 0。"""
    tenant_id = "tenant-usage-e1"
    task_store = TaskStore()
    ledger = InMemoryUsageLedger()
    runtime = RuntimeService(
        task_store,
        run_metrics=RunMetricsService(InMemoryRunRecordStore()),
        usage_ledger=ledger,
    )
    task = make_task(task_store, tenant_id=tenant_id, created_by="u-1")
    main.commercial_repository.ensure_test_tenant(
        tenant_id, owner_id="owner-e1", admins={"admin-e1"}
    )
    monkeypatch.setattr(main, "store", task_store)
    monkeypatch.setattr(main, "runtime_service", runtime)
    monkeypatch.setattr(main, "commercial_usage", ledger)

    started = client.post(
        f"/api/v1/tasks/{task.id}/runs",
        headers={"X-Tenant-Id": tenant_id, "X-User-Id": "u-1", "X-User-Role": "employee"},
        json={"runtime_key": "mock", "mode": "product_manager", "steps": TWO_READ_STEPS},
    )
    assert started.status_code == 201
    assert started.json()["status"] == "completed"

    usage = client.get(
        "/api/v1/commercial/usage",
        headers={
            "X-Tenant-Id": tenant_id,
            "X-User-Id": "admin-e1",
            "X-User-Role": "customer_admin",
        },
    )
    assert usage.status_code == 200
    assert usage.json()["units"] > 0
    assert usage.json()["cost_cents"] == 0
