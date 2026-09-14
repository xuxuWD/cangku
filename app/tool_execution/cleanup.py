"""孤儿容器清扫（规格 §3.3 生命周期 / §8 U17 ⑥）与正文密文 TTL 清理（§4.1.5 / §4.1.6-8）。

口径（2026-09-13 用户裁决，保守 fail-closed）：
    - **清扫时机 = 启动时 + 按 `WORKBENCH_BODY_CLEANUP_INTERVAL_SECONDS` 周期**（与 §4.1.5 的
      清理任务**同批**）；
    - **跑在 API 进程内**（本模块为进程内后台线程，随应用启动 / 停止）；
    - 清扫失败**必须告警并登记**，且**不得**影响既有读路径与段一行为。

§4.1.5「受控正文密文列」清理策略（②到期即清 / ③启动时 + 周期 / ④失败告警登记）与 §4.1.6-8
「审批超时 → `expired` 的执行方」由 `BodyCleanupTask` 承担：**同一个事务**内完成
「置 `expired` + 写 `decided_by`/`decided_at`/`decision_source` + 清空两列」。
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import UTC, datetime

from ..audit.models import AuditAction
from .log import get_logger
from .store import EXPIRY_DECIDED_BY

DEFAULT_CLEANUP_INTERVAL_SECONDS = 60
THREAD_NAME = "workbench-orphan-cleanup"
BODY_CLEANUP_THREAD_NAME = "workbench-body-cleanup"


@dataclass(frozen=True)
class CleanupReport:
    """一次清扫的结果（只含计数，不含容器 id 之外的任何宿主信息）。"""

    orphans_removed: int = 0
    failures: int = 0


@dataclass(frozen=True)
class BodyCleanupReport:
    """一次正文密文 TTL 清理的结果（**只含计数**，不落正文、不落任何行标识）。"""

    expired: int = 0
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


class BodyCleanupTask:
    """正文密文 TTL 清理 + 审批超时置 `expired`（§4.1.5 / §4.1.6-8，进程内后台线程）。

    * **到期即清**：到期时刻（`body_expires_at`，= 该动作的审批超时时刻）已过的 `pending` 行 →
      同事务置 `expired` + 清空 `body_ciphertext` / `body_expires_at`；**未到期的绝不动**；
    * **启动时 + 按周期**执行（周期 = `WORKBENCH_BODY_CLEANUP_INTERVAL_SECONDS`，与孤儿回收同批）；
    * 清理失败**告警并登记**（记 `error` + 计数），**不新增审计动作码**（§4.1.5 ⑤ / §4.1.7-6）、
      **不落正文**；异常**不抛出**、**不得**影响既有读路径与段一行为（§4.1.5 ⑦）。
    * 每清一行，按**既有**动作码 `run.approval_decided` 留审计证据（§4.1.7-6「决议事实由既有
      `run.approval_decided` 表达」）：`status="expired"`、`actor_id` = 受控常量
      `system:approval-timeout`、`target` = 该行的 `run`；**只落标识与受控值，不含正文**。
    """

    def __init__(self, store, *, interval_seconds: int = DEFAULT_CLEANUP_INTERVAL_SECONDS, now=None, audit=None):
        # 仓储是**必需**依赖：为 `None` 时不静默跳过，交由 `run_once` 的告警路径暴露（fail-visible）。
        self.store = store
        self.interval_seconds = max(1, int(interval_seconds))
        self._now = now or (lambda: datetime.now(UTC))
        # 审计为**可选**依赖：未装配（测试 / 段一路径）时不写审计，清理本身仍照常执行。
        self.audit = audit
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_report: BodyCleanupReport | None = None

    def run_once(self) -> BodyCleanupReport:
        """执行一次到期清理；异常一律走告警路径（**不抛出**，§4.1.5 ④⑦）。"""
        try:
            expired_rows = self.store.expire_pending_bodies(now=self._now())
        except Exception as exc:  # noqa: BLE001 - 清理失败必须告警并登记（不得静默吞掉）
            get_logger().error("正文密文 TTL 清理失败，需人工介入：%s", exc)
            self.last_report = BodyCleanupReport(failures=1)
            return self.last_report
        if expired_rows:
            get_logger().info("正文密文 TTL 清理：到期置 expired 并清空密文 %d 行", len(expired_rows))
        try:
            self._record_expiry_audit(expired_rows)
        except Exception as exc:  # noqa: BLE001 - 审计写入失败同样必须告警并登记
            get_logger().error("到期决议写入审计失败，需人工介入：%s", exc)
            self.last_report = BodyCleanupReport(expired=len(expired_rows), failures=1)
            return self.last_report
        self.last_report = BodyCleanupReport(expired=len(expired_rows))
        return self.last_report

    def _record_expiry_audit(self, expired_rows) -> None:
        """按**既有**动作码为每个到期行留决议事实（§4.1.7-6；不新增动作码、不落正文）。"""
        if self.audit is None:
            return
        for row in expired_rows:
            self.audit.record(
                AuditAction.RUN_APPROVAL_DECIDED,
                tenant_id=row.tenant_id,
                actor_id=EXPIRY_DECIDED_BY,
                target_type="run",
                target_id=row.run_id,
                detail={"status": "expired"},
            )

    def start(self) -> None:
        """启动时先清一次，再按周期循环（幂等：重复调用不重复起线程）。"""
        if self._thread is not None and self._thread.is_alive():
            return
        self.run_once()
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name=BODY_CLEANUP_THREAD_NAME, daemon=True)
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


def build_body_cleanup_task(settings, tool_execution, audit=None) -> BodyCleanupTask | None:
    """按配置装配正文密文 TTL 清理任务；未启用真实执行（`tool_execution is None`）时返回 `None`。

    与孤儿清扫**同批**（§4.1.5 ③）：同处注册、同款周期循环、同一个 `WORKBENCH_BODY_CLEANUP_INTERVAL_SECONDS`。
    `tool_actions` 是 `ToolExecutionService` 的**必需**依赖（§4.1.6-1），此处直接取用；
    缺失即 `AttributeError`（fail-loud），**不**用 `getattr(..., None)` 静默跳过。
    `audit` 用于留「到期 ⇒ `expired`」的决议事实（§4.1.7-6）；未传时不写审计（清理本身不受影响）。
    """
    if tool_execution is None:
        return None
    return BodyCleanupTask(
        tool_execution.tool_actions,
        interval_seconds=settings.body_cleanup_interval_seconds,
        audit=audit,
    )
