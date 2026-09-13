"""孤儿容器清扫（规格 §3.3 生命周期 / §8 U17 ⑥）。

口径（2026-09-13 用户裁决，保守 fail-closed）：
    - **清扫时机 = 启动时 + 按 `WORKBENCH_BODY_CLEANUP_INTERVAL_SECONDS` 周期**（与 §4.1.5 的
      清理任务**同批**）；
    - **跑在 API 进程内**（本模块为进程内后台线程，随应用启动 / 停止）；
    - 清扫失败**必须告警并登记**，且**不得**影响既有读路径与段一行为。
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

from .log import get_logger

DEFAULT_CLEANUP_INTERVAL_SECONDS = 60
THREAD_NAME = "workbench-orphan-cleanup"


@dataclass(frozen=True)
class CleanupReport:
    """一次清扫的结果（只含计数，不含容器 id 之外的任何宿主信息）。"""

    orphans_removed: int = 0
    failures: int = 0


class OrphanCleanupTask:
    """孤儿容器的启动期清扫 + 周期清扫（进程内后台线程）。"""

    def __init__(self, executor, *, interval_seconds: int = DEFAULT_CLEANUP_INTERVAL_SECONDS):
        self.executor = executor
        self.interval_seconds = max(1, int(interval_seconds))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_report: CleanupReport | None = None

    def run_once(self) -> CleanupReport:
        """执行一次清扫；异常一律吞到告警层（**不抛出**，§4.1.5 ⑦）。"""
        if self.executor is None:
            return CleanupReport()
        try:
            removed = int(self.executor.cleanup_orphans())
        except Exception as exc:  # noqa: BLE001 - 清扫失败只告警
            get_logger().error("孤儿容器清扫失败，需人工介入：%s", exc)
            self.last_report = CleanupReport(failures=1)
            return self.last_report
        self.last_report = CleanupReport(orphans_removed=removed)
        return self.last_report

    def start(self) -> None:
        """启动时先扫一次，再按周期循环（幂等：重复调用不重复起线程）。"""
        if self._thread is not None and self._thread.is_alive():
            return
        self.run_once()
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name=THREAD_NAME, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=5)
        self._thread = None

    def _loop(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            self.run_once()


def build_orphan_cleanup_task(settings, tool_execution) -> OrphanCleanupTask | None:
    """按配置装配孤儿清扫任务；未启用真实执行（`tool_execution is None`）时返回 `None`。"""
    if tool_execution is None:
        return None
    executor = getattr(tool_execution, "executor", None)
    if executor is None:
        return None
    return OrphanCleanupTask(
        executor, interval_seconds=settings.body_cleanup_interval_seconds
    )
