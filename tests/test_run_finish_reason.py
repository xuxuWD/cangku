"""运行结束原因（finish_reason）与运行记录回写语义。

先写测试：`FinishReason`、状态→原因的单向推导、以及「回写不重置启动时间 / 不丢 proposal_id」。
"""

from datetime import UTC, datetime, timedelta

from app.runtime.contracts import AgentPlan, RuntimeContext, RuntimeEvent, RuntimeEventType
from app.runtime.records import FinishReason, InMemoryRunRecordStore, PostgresRunRecordStore, RunRecord
from app.runtime.run_metrics import RunMetricsService
from app.runtime.state import RuntimeState

NOW = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)


def context() -> RuntimeContext:
    return RuntimeContext(
        tenant_id="t-1",
        user_id="u-1",
        role_key="content-operator",
        mode="product_manager",
        project_id=None,
        task_id="task-1",
        device_id="device:u-1",
        knowledge_scope=(),
        file_scope=(),
        budget_cents=100,
        risk_level="low",
        policy_version="policy-1",
        expires_at=NOW + timedelta(minutes=15),
    )


def state_with(status: str) -> RuntimeState:
    plan = AgentPlan.from_steps(
        [{"step_id": "s0", "kind": "read", "tool": "knowledge.search"}]
    )
    state = RuntimeState(run_id="run-1", context=context(), plan=plan)
    state.status = status
    state.completed_steps = ["s0"] if status == "completed" else []
    state.usage = {"tool_calls": 1, "successful_tools": 1 if status == "completed" else 0}
    state.events = [
        RuntimeEvent("run-1", 1, RuntimeEventType.TOOL_RESULT, {"status": "success"})
    ]
    return state


def test_finish_reason_is_derived_from_status() -> None:
    service = RunMetricsService(InMemoryRunRecordStore())

    completed = service.record_state(
        tenant_id="t-1", proposal_id=None, runtime_key="mock",
        state=state_with("completed"), latency_ms=1, now=NOW,
    )
    failed = service.record_state(
        tenant_id="t-1", proposal_id=None, runtime_key="mock",
        state=state_with("failed"), latency_ms=1, now=NOW,
    )
    cancelled = service.record_state(
        tenant_id="t-1", proposal_id=None, runtime_key="mock",
        state=state_with("cancelled"), latency_ms=1, now=NOW,
    )

    assert completed.finish_reason is FinishReason.RUN_COMPLETED
    assert failed.finish_reason is FinishReason.STEP_FAILED
    assert cancelled.finish_reason is FinishReason.CANCELLED_BY_USER
    assert FinishReason.RUN_COMPLETED == "run_completed"
    assert FinishReason.CANCELLED_BY_USER == "cancelled_by_user"
    assert FinishReason.STEP_FAILED == "step_failed"


def test_non_terminal_status_has_no_finish_reason() -> None:
    service = RunMetricsService(InMemoryRunRecordStore())

    for status in ("running", "paused"):
        record = service.record_state(
            tenant_id="t-1", proposal_id=None, runtime_key="mock",
            state=state_with(status), latency_ms=0, now=NOW,
        )
        assert record.finish_reason is None
        assert record.finished_at is None


def test_rewrite_preserves_started_at_and_proposal_id() -> None:
    store = InMemoryRunRecordStore()
    service = RunMetricsService(store)
    first = service.record_state(
        tenant_id="t-1", proposal_id="plan-1", runtime_key="mock",
        state=state_with("running"), latency_ms=5, now=NOW,
    )
    later = NOW + timedelta(minutes=3)

    second = service.record_state(
        tenant_id="t-1", proposal_id=None, runtime_key="mock",
        state=state_with("completed"), latency_ms=9, now=later,
    )

    assert second.started_at == first.started_at == NOW
    assert second.proposal_id == "plan-1"
    assert second.status == "completed"
    assert second.finish_reason is FinishReason.RUN_COMPLETED
    assert second.finished_at == later
    assert second.latency_ms == 9


def test_rewrite_clears_finished_at_when_run_returns_to_running() -> None:
    service = RunMetricsService(InMemoryRunRecordStore())

    cancelled = service.record_state(
        tenant_id="t-1", proposal_id=None, runtime_key="mock",
        state=state_with("cancelled"), latency_ms=0, now=NOW,
    )
    assert cancelled.finished_at == NOW

    resumed = service.record_state(
        tenant_id="t-1", proposal_id=None, runtime_key="mock",
        state=state_with("running"), latency_ms=0, now=NOW + timedelta(minutes=1),
    )

    assert resumed.status == "running"
    assert resumed.finished_at is None
    assert resumed.finish_reason is None


class RecordingCursor:
    def __init__(self, rows) -> None:
        self.rows = list(rows)
        self.statements: list[tuple[str, tuple]] = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, statement, params=None):
        self.statements.append((statement, params))

    def fetchone(self):
        return self.rows.pop(0)


class RecordingTransaction:
    def __init__(self, connection) -> None:
        self.connection = connection

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class RecordingConnection:
    def __init__(self, rows) -> None:
        self.cursor_instance = RecordingCursor(rows)

    def transaction(self):
        return RecordingTransaction(self)

    def cursor(self):
        return self.cursor_instance


def test_postgres_upsert_persists_finish_reason() -> None:
    row = (
        "run-1", "t-1", "task-1", "plan-1", "mock", "failed",
        1, 0, 1, 0, 0, 7,
        NOW, NOW, "step_failed",
        # 授权位（026）三列：无授权即三列皆 NULL（数据库 CHECK 保证同生同灭）
        None, None, None,
    )
    connection = RecordingConnection([row])
    store = PostgresRunRecordStore(connection)
    record = RunRecord(
        run_id="run-1", tenant_id="t-1", task_id="task-1", proposal_id="plan-1",
        runtime_key="mock", status="failed", started_at=NOW, finished_at=NOW,
        finish_reason=FinishReason.STEP_FAILED,
    )

    saved = store.upsert(record)

    statement, params = connection.cursor_instance.statements[0]
    assert "finish_reason" in statement
    # 尾四参 = finish_reason + 授权位三列；本用例未授权，后三参必须是 None。
    assert params[-4:] == ("step_failed", None, None, None)
    assert saved.finish_reason is FinishReason.STEP_FAILED
