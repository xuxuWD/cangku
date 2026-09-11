from __future__ import annotations

from datetime import UTC, datetime
from math import ceil
from typing import Any

from .contracts import RuntimeEventType
from .records import RunRecord, RunRecordStore


_TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})
_SUMMARY_LIMIT = 100_000


class RunMetricsService:
    """把运行终态折算为可查询的运行记录与聚合指标。"""

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
        started_at = now or datetime.now(UTC)
        knowledge_hits = sum(
            1
            for event in state.events
            if event.event_type == RuntimeEventType.TOOL_RESULT
            and event.payload.get("knowledge_hit") is True
        )
        finished_at = started_at if state.status in _TERMINAL_STATUSES else None
        record = RunRecord(
            run_id=state.run_id,
            tenant_id=tenant_id,
            task_id=state.context.task_id,
            runtime_key=runtime_key,
            status=state.status,
            started_at=started_at,
            proposal_id=proposal_id,
            step_count=len(state.plan.steps),
            completed_step_count=len(state.completed_steps),
            tool_calls=state.usage["tool_calls"],
            successful_tools=state.usage["successful_tools"],
            knowledge_hits=knowledge_hits,
            latency_ms=latency_ms,
            finished_at=finished_at,
        )
        return self.store.upsert(record)

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
