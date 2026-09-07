from __future__ import annotations

from collections import Counter


class RuntimeMetrics:
    def __init__(self) -> None:
        self._rows: list[dict[str, object]] = []

    def record(self, run_id: str, *, completed: bool, tool_success: bool, knowledge_hit: bool, latency_ms: int) -> None:
        self._rows.append({"run_id": run_id, "completed": completed, "tool_success": tool_success, "knowledge_hit": knowledge_hit, "latency_ms": latency_ms})

    def report(self) -> dict[str, float | int]:
        if not self._rows: return {"task_completion_rate":0.0,"tool_success_rate":0.0,"knowledge_hit_rate":0.0,"latency_p95_ms":0}
        total=len(self._rows); latencies=sorted(int(row["latency_ms"]) for row in self._rows); index=max(0, min(total-1, int(total*0.95 + 0.999999)-1))
        return {"task_completion_rate": sum(bool(row["completed"]) for row in self._rows)/total, "tool_success_rate": sum(bool(row["tool_success"]) for row in self._rows)/total, "knowledge_hit_rate": sum(bool(row["knowledge_hit"]) for row in self._rows)/total, "latency_p95_ms": latencies[index]}
