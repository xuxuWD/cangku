from __future__ import annotations

from datetime import UTC, datetime
from math import ceil
from typing import Any

from .contracts import RuntimeEventType
from .records import FinishReason, RunRecord, RunRecordNotFound, RunRecordStore


_TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})
# 结束原因由状态单向推导，保证状态与原因不可能互相漂移。
_FINISH_REASONS = {
    "completed": FinishReason.RUN_COMPLETED,
    "failed": FinishReason.STEP_FAILED,
    "cancelled": FinishReason.CANCELLED_BY_USER,
}
_SUMMARY_LIMIT = 100_000


class RunMetricsService:
    """把运行状态折算为可查询的运行记录与聚合指标。"""

    def __init__(self, store: RunRecordStore) -> None:
        self.store = store

    def record_state(
        self,
        *,
        tenant_id: str,
        proposal_id: str | None,
        runtime_key: str,
        state: Any,
        latency_ms: int,
        now: datetime | None = None,
    ) -> RunRecord:
        """写入或回写一条运行记录。

        同一 run_id 的后续回写（暂停/恢复/取消）必须**保留**首次写入的 `started_at` 与
        `proposal_id`，否则启动时间会被反复重置、计划关联会被抹掉。
        """
        current = now or datetime.now(UTC)
        existing = self._existing(tenant_id, state.run_id)
        knowledge_hits = sum(
            1
            for event in state.events
            if event.event_type == RuntimeEventType.TOOL_RESULT
            and event.payload.get("knowledge_hit") is True
        )
        terminal = state.status in _TERMINAL_STATUSES
        record = RunRecord(
            run_id=state.run_id,
            tenant_id=tenant_id,
            task_id=state.context.task_id,
            runtime_key=runtime_key,
            status=state.status,
            started_at=existing.started_at if existing is not None else current,
            proposal_id=proposal_id or (existing.proposal_id if existing is not None else None),
            step_count=len(state.plan.steps),
            completed_step_count=len(state.completed_steps),
            tool_calls=state.usage["tool_calls"],
            successful_tools=state.usage["successful_tools"],
            knowledge_hits=knowledge_hits,
            latency_ms=latency_ms,
            finished_at=current if terminal else None,
            finish_reason=_FINISH_REASONS.get(state.status),
        )
        return self.store.upsert(record)

    def _existing(self, tenant_id: str, run_id: str) -> RunRecord | None:
        try:
            return self.store.get(tenant_id, run_id)
        except RunRecordNotFound:
            return None

    def summary(self, tenant_id: str, *, runtime_key: str | None = None) -> dict[str, Any]:
        records = self.store.list_recent(tenant_id, limit=_SUMMARY_LIMIT)
        if runtime_key is not None:
            records = [item for item in records if item.runtime_key == runtime_key]
        by_runtime = [
            {"runtime_key": key, **self._aggregate([item for item in records if item.runtime_key == key])}
            for key in sorted({item.runtime_key for item in records})
        ]
        return {
            "tenant_id": tenant_id,
            "runtime_key": runtime_key,
            **self._aggregate(records),
            "by_runtime": by_runtime,
        }

    @staticmethod
    def _aggregate(records: list[RunRecord]) -> dict[str, Any]:
        run_count = len(records)
        if run_count == 0:
            return {
                "run_count": 0,
                "task_completion_rate": 0.0,
                "tool_success_rate": 0.0,
                "knowledge_hit_rate": 0.0,
                "latency_p95_ms": 0,
            }
        completed = sum(1 for item in records if item.status == "completed")
        total_tool_calls = sum(item.tool_calls for item in records)
        total_successful = sum(item.successful_tools for item in records)
        knowledge_hits = sum(item.knowledge_hits for item in records)
        latencies = sorted(item.latency_ms for item in records)
        index = ceil(0.95 * run_count) - 1
        return {
            "run_count": run_count,
            "task_completion_rate": completed / run_count,
            "tool_success_rate": (total_successful / total_tool_calls) if total_tool_calls else 0.0,
            "knowledge_hit_rate": knowledge_hits / run_count,
            "latency_p95_ms": latencies[index],
        }
