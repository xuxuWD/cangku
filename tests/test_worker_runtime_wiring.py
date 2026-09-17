"""worker 运行时装配的 fork 安全契约（2026-09-15 容器演练暴露的既有缺陷修复）。

背景：导入期装配会在 worker 主进程里创建 psycopg 连接池；Celery 默认 prefork 池 fork 出的
子进程继承该池（psycopg_pool 不支持跨 fork 共享）⇒ 周期任务全部 `PoolTimeout`。
修复 = **任务进程内惰性装配**（`_ensure_runtime`）。本测试锁定四条行为：

  1. development 下**不自动装配**（保持「未接线 ⇒ 零值」，不偷偷连库）；
  2. 非 development 下**首次任务调用装配一次**，后续调用不重复装配；
  3. **部分显式装配**（测试 / 运维脚本注入其一）时不再自动装配（不覆盖显式注入）；
  4. 装配失败**不吞**：任务显式失败（不返回零值）。

真实 fork 场景（prefork 子进程可用）由容器化演练取证，不能靠本文件断言。
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app import worker


@pytest.fixture(autouse=True)
def _clean_wiring(monkeypatch):
    """每个用例前后清空接线状态与注入点，避免相互污染。

    ⚠️ 注入点**必须逐个列全**：`_ensure_runtime` 的「已接线即不再自动装配」判定读的是这几个
    模块级全局。2026-09-16 新增第 4 个注入点（运行事件保留期清理器）时此处漏列，导致某个用例
    直接赋值后残留到后续用例 ⇒ `_ensure_runtime` 提前返回、本文件两条用例失败（已修复）。
    """
    monkeypatch.setattr(worker, "_outbox_publisher", None)
    monkeypatch.setattr(worker, "_lifecycle_runner", None)
    monkeypatch.setattr(worker, "_knowledge_review_scanner", None)
    monkeypatch.setattr(worker, "_runtime_event_purger", None)
    # 2026-09-17 新增第 5/6 个注入点（P5a CRM 服务 / 站内通知）；「必须逐个列全」的口径见上。
    monkeypatch.setattr(worker, "_crm_service", None)
    monkeypatch.setattr(worker, "_crm_notifier", None)
    # 2026-09-17 新增第 7 个注入点（P2b 流帧清理器）；「必须逐个列全」的口径见上。
    monkeypatch.setattr(worker, "_conversation_stream_purger", None)
    monkeypatch.setattr(worker, "_runtime_builder", None)
    yield


class _Settings:
    """最小 settings 桩；数值字段与 `app.settings.Settings` 缺省一致（仅任务读取所需项）。"""

    def __init__(self, env: str) -> None:
        self.env = env

    # 流帧清理任务（P2b）读取的两项（其余用例不读）。
    stream_stalled_hours = 6
    stream_retention_days = 7


def _use_env(monkeypatch, env: str) -> None:
    monkeypatch.setattr(worker, "get_settings", lambda: _Settings(env))


def _stub_runtime() -> None:
    """把三个运行时都注入为最小桩（模拟一次成功装配）。"""

    class _Publisher:
        def publish_pending(self, *, limit: int = 100) -> int:
            return 42

    class _Runner:
        def run_pending_jobs(self, *, limit: int = 100) -> dict[str, int]:
            return {"exports": 7, "deletions": 0}

    class _Scanner:
        def scan_review_due_across_tenants(self, *, now=None, limit: int = 500) -> dict[str, int]:
            return {"candidates": 3, "flipped": 3}

    worker.configure_outbox_publisher(_Publisher())
    worker.configure_lifecycle(_Runner())
    worker.configure_knowledge_review(_Scanner())


# ------------------------------------------------------------ development：不自动装配

def test_development_never_autowires(monkeypatch) -> None:
    """development 下任务保持「未接线 ⇒ 零值」：**不偷偷连库**（反假锚点：删掉 env 判断必须变红）。"""
    _use_env(monkeypatch, "development")
    calls: list[str] = []
    monkeypatch.setattr(worker, "_runtime_builder", lambda: calls.append("built"))

    assert worker.publish_outbox() == 0
    assert worker.run_lifecycle_jobs() == {"exports": 0, "deletions": 0}
    assert worker.scan_knowledge_review_due() == {"candidates": 0, "flipped": 0}
    assert calls == [], "development 下不得自动装配"


# ------------------------------------------------------------ 非 development：首调装配一次

def test_production_wires_once_on_first_task_call(monkeypatch) -> None:
    """非 development：首次任务调用装配一次，三个任务都用上装配结果；重复调用不重复装配。"""
    _use_env(monkeypatch, "staging")
    calls: list[str] = []

    def _builder() -> None:
        calls.append("built")
        _stub_runtime()

    monkeypatch.setattr(worker, "_runtime_builder", _builder)

    assert worker.publish_outbox() == 42  # 首调触发装配并生效
    assert worker.scan_knowledge_review_due() == {"candidates": 3, "flipped": 3}
    assert worker.run_lifecycle_jobs() == {"exports": 7, "deletions": 0}
    assert calls == ["built"], "只应装配一次"


def test_partial_explicit_wiring_is_not_overwritten(monkeypatch) -> None:
    """已显式注入任一运行时 ⇒ 视为已接线，不再自动装配（不覆盖显式注入）。"""
    _use_env(monkeypatch, "staging")
    calls: list[str] = []
    monkeypatch.setattr(worker, "_runtime_builder", lambda: calls.append("built"))

    class _Scanner:
        def scan_review_due_across_tenants(self, *, now=None, limit: int = 500) -> dict[str, int]:
            return {"candidates": 1, "flipped": 1}

    worker.configure_knowledge_review(_Scanner())

    assert worker.scan_knowledge_review_due() == {"candidates": 1, "flipped": 1}
    assert calls == [], "已接线时不得自动装配"


def test_conversation_stream_purger_is_an_explicit_wiring_point(monkeypatch) -> None:
    """P2b 流帧清理器同样是显式注入点：注入其一即视为已接线（不触发自动装配）。"""
    _use_env(monkeypatch, "staging")
    calls: list[str] = []
    monkeypatch.setattr(worker, "_runtime_builder", lambda: calls.append("built"))

    class _Purger:
        def mark_stalled(self, *, cutoff, expires_at) -> int:
            return 0

        def purge_expired(self, *, cutoff) -> int:
            return 0

    worker.configure_conversation_stream_purger(_Purger())

    assert worker.purge_conversation_stream() == {"stalled": 0, "purged": 0}
    assert calls == [], "已接线时不得自动装配"


def test_wiring_failure_fails_the_task(monkeypatch) -> None:
    """装配失败**不吞**：任务显式失败（不静默返回零值，避免「任务看起来成功但其实没跑」）。"""
    _use_env(monkeypatch, "staging")

    def _broken() -> None:
        raise RuntimeError("缺数据库连接串")

    monkeypatch.setattr(worker, "_runtime_builder", _broken)

    with pytest.raises(RuntimeError):
        worker.scan_knowledge_review_due()


# ------------------------------------------------------------ 导出包过期清理任务（组 10.7 加固）
#
# 口径：docs/api-contract.md「GET /api/v1/commercial/exports/{package_id}」——
# 过期包（`expires_at <= now`）不提供取回，由 beat 排程的任务按 `expires_at` 物理清理。
# 该任务**复用既有 `_lifecycle_runner` 注入点**（导出包仓储归生命周期服务持有，
# 不为清理另开注入点），与 `run_lifecycle_jobs` 同口径：未接线即返回 0。


def test_export_package_purge_task_is_scheduled_alongside_existing_periodic_tasks() -> None:
    from app.settings import Settings
    from app.worker import celery_app

    entry = celery_app.conf.beat_schedule["export-packages-purge"]
    settings = Settings()

    assert entry["task"] == "app.worker.purge_export_packages"
    assert entry["schedule"] == settings.export_package_purge_interval_seconds
    assert entry["schedule"] > 0


def test_export_package_purge_interval_defaults_and_bounds() -> None:
    from app.settings import Settings

    field = Settings.model_fields["export_package_purge_interval_seconds"]

    # 判定依据（本批拍板口径）：默认 1h 扫一次，范围 30s–7 天（与运行事件清理间隔同口径）。
    assert field.default == 3600
    assert Settings(export_package_purge_interval_seconds=30).export_package_purge_interval_seconds == 30
    assert (
        Settings(export_package_purge_interval_seconds=7 * 24 * 3600).export_package_purge_interval_seconds
        == 7 * 24 * 3600
    )
    for invalid in (29, 7 * 24 * 3600 + 1):
        with pytest.raises(Exception):
            Settings(export_package_purge_interval_seconds=invalid)


def test_export_package_purge_returns_zero_when_worker_is_not_wired(monkeypatch) -> None:
    monkeypatch.setattr(worker, "_ensure_runtime", lambda: None)

    assert worker.purge_export_packages() == 0


def test_export_package_purge_delegates_to_the_wired_lifecycle_runner(monkeypatch) -> None:
    calls: list[str] = []

    class _Runner:
        def run_pending_jobs(self, *, limit: int = 100) -> dict[str, int]:
            return {"exports": 0, "deletions": 0}

        def purge_expired_export_packages(self, *, now=None) -> int:
            calls.append("purged")
            return 5

    monkeypatch.setattr(worker, "_ensure_runtime", lambda: None)
    worker.configure_lifecycle(_Runner())

    assert worker.purge_export_packages() == 5
    assert calls == ["purged"]


# ------------------------------------------------------------ 流帧清理任务（P2b §2.6）
#
# 口径：先**悬挂兜底**（未终态且 `updated_at` 超阈 ⇒ `unavailable('stalled')` + `expires_at`），
# 再按 `expires_at` 删除到期 run 的帧与状态行；**只清流帧**（消息表 / 审计 / 运行事件不受影响）。
# 与既有周期任务同口径：**未接线即返回零值**，绝不伪造清理结果。


def test_conversation_stream_purge_task_is_scheduled_alongside_existing_periodic_tasks() -> None:
    from app.settings import Settings
    from app.worker import celery_app

    entry = celery_app.conf.beat_schedule["conversation-stream-purge"]
    settings = Settings()

    assert entry["task"] == "app.worker.purge_conversation_stream"
    assert entry["schedule"] == settings.stream_purge_interval_seconds
    assert entry["schedule"] > 0


def test_conversation_stream_purge_returns_zero_when_worker_is_not_wired(monkeypatch) -> None:
    monkeypatch.setattr(worker, "_ensure_runtime", lambda: None)

    assert worker.purge_conversation_stream() == {"stalled": 0, "purged": 0}


def test_conversation_stream_purge_stalls_then_purges_with_configured_windows(monkeypatch) -> None:
    """一次调用两段都跑：先悬挂兜底（阈值取自配置），再按到期时刻清理——**顺序不可颠倒**。"""
    from app.settings import Settings

    settings = Settings()
    seen: list[tuple[str, object]] = []

    class _Purger:
        def mark_stalled(self, *, cutoff, expires_at) -> int:
            seen.append(("stalled", (cutoff, expires_at)))
            return 2

        def purge_expired(self, *, cutoff) -> int:
            seen.append(("purged", cutoff))
            return 3

    monkeypatch.setattr(worker, "_ensure_runtime", lambda: None)
    worker.configure_conversation_stream_purger(_Purger())

    assert worker.purge_conversation_stream() == {"stalled": 2, "purged": 3}
    assert [name for name, _ in seen] == ["stalled", "purged"]
    # 悬挂窗口 = now - STALLED_HOURS（阈值取自配置，不写死 6h）
    stalled_cutoff, stalled_expiry = seen[0][1]
    assert 5 * 3600 < (datetime.now(UTC) - stalled_cutoff).total_seconds() < 7 * 3600
    assert settings.stream_stalled_hours == 6
    # 兜底置位的过期时刻 = now + 保留期（默认 7 天）
    assert 6 < (stalled_expiry - datetime.now(UTC)).total_seconds() / 86400 < 8