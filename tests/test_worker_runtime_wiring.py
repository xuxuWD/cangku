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

import pytest

from app import worker


@pytest.fixture(autouse=True)
def _clean_wiring(monkeypatch):
    """每个用例前后清空接线状态与注入点，避免相互污染。"""
    monkeypatch.setattr(worker, "_outbox_publisher", None)
    monkeypatch.setattr(worker, "_lifecycle_runner", None)
    monkeypatch.setattr(worker, "_knowledge_review_scanner", None)
    monkeypatch.setattr(worker, "_runtime_builder", None)
    yield


class _Settings:
    def __init__(self, env: str) -> None:
        self.env = env


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


def test_wiring_failure_fails_the_task(monkeypatch) -> None:
    """装配失败**不吞**：任务显式失败（不静默返回零值，避免「任务看起来成功但其实没跑」）。"""
    _use_env(monkeypatch, "staging")

    def _broken() -> None:
        raise RuntimeError("缺数据库连接串")

    monkeypatch.setattr(worker, "_runtime_builder", _broken)

    with pytest.raises(RuntimeError):
        worker.scan_knowledge_review_due()