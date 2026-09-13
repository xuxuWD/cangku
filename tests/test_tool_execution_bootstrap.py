"""`build_tool_execution` 的装配与启动期断言（规格 §4.1.6-2 / -3）。

判据：
    - `backend=mock` → `tool_execution is None`；
    - `backend=dsh` 且缺件 → **不抛进程级异常**，返回 `None` 且记 `error`；
    - 启动期断言拒绝未声明 `param_roles` 的目录。
"""

from __future__ import annotations

import base64
import logging
import os

from app.bootstrap import build_tool_execution
from app.runtime.records import InMemoryRunRecordStore
from app.runtime.run_metrics import RunMetricsService
from app.settings import Settings
from app.tool_execution.startup import assert_real_execution_ready

LOGGER_NAME = "company_workbench.tool_execution"


class RecordingAudit:
    def __init__(self) -> None:
        self.calls: list[tuple[object, dict]] = []

    def record(self, action, **kwargs) -> None:
        self.calls.append((action, kwargs))


def _dsh_settings(tmp_path, **overrides) -> Settings:
    base = dict(
        env="development",
        storage_backend="memory",
        agent_runtime_backend="dsh",
        body_encryption_key=base64.b64encode(os.urandom(32)).decode("ascii"),
        exec_workspace_root=str(tmp_path),
        exec_image_digest="registry.local/dsh@sha256:abc",
    )
    base.update(overrides)
    return Settings(**base)


def test_mock_backend_returns_none() -> None:
    settings = Settings(env="development", storage_backend="memory", agent_runtime_backend="mock")
    assert build_tool_execution(settings) is None


def test_dsh_backend_assembles_when_every_piece_present(tmp_path) -> None:
    settings = _dsh_settings(tmp_path)
    metrics = RunMetricsService(InMemoryRunRecordStore())
    service = build_tool_execution(settings, run_metrics=metrics, audit=RecordingAudit())
    assert service is not None


def test_dsh_backend_missing_body_key_refuses_without_raising(tmp_path, caplog) -> None:
    settings = _dsh_settings(tmp_path, body_encryption_key="")
    metrics = RunMetricsService(InMemoryRunRecordStore())
    with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
        service = build_tool_execution(settings, run_metrics=metrics)
    assert service is None
    assert any(record.levelno == logging.ERROR for record in caplog.records)


def test_dsh_backend_missing_run_records_refuses(tmp_path, caplog) -> None:
    settings = _dsh_settings(tmp_path)
    with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
        service = build_tool_execution(settings, run_metrics=None)
    assert service is None
    assert any("run_records" in record.getMessage() for record in caplog.records)


def test_startup_assertion_rejects_undeclared_param_roles(caplog) -> None:
    class _BadCatalog:
        def param_role_problems(self) -> list[str]:
            return ["fs.write.content 未声明 param_roles"]

    with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
        ok = assert_real_execution_ready(
            tool_execution=object(),
            run_records=object(),
            tool_actions=object(),
            catalog=_BadCatalog(),
        )
    assert ok is False
    assert any("param_roles" in record.getMessage() for record in caplog.records)


def test_startup_assertion_passes_when_complete() -> None:
    class _GoodCatalog:
        def param_role_problems(self) -> list[str]:
            return []

    assert assert_real_execution_ready(
        tool_execution=object(),
        run_records=object(),
        tool_actions=object(),
        catalog=_GoodCatalog(),
    ) is True
