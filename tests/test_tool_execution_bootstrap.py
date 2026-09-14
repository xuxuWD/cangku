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
from datetime import UTC, datetime, timedelta

import pytest

from app.bootstrap import (
    build_runtime_service,
    build_tool_action_store,
    build_tool_execution,
)
from app.domain import RiskLevel, Task, TaskStatus, TaskStore, UserContext
from app.runtime.authorization import ExecutionNotAuthorized, plan_digest
from app.runtime.records import InMemoryRunRecordStore
from app.runtime.run_metrics import RunMetricsService
from app.settings import Settings
from app.tool_execution.cleanup import build_body_cleanup_task
from app.tool_execution.errors import BodyCipherError
from app.tool_execution.startup import assert_real_execution_ready
from app.tool_execution.store import InMemoryToolActionStore, ToolAction, ToolActionStatus

LOGGER_NAME = "company_workbench.tool_execution"

_ACTOR = UserContext("t-1", "u-1", "employee")
_DECIDER = UserContext("t-1", "ceo-1", "ceo")
_RUNTIME_STEPS = [
    {"step_id": "s1", "kind": "read", "tool": "knowledge.search"},
    {"step_id": "s2", "kind": "write", "tool": "file.write"},
]
_NOW = datetime(2026, 9, 13, 12, 0, tzinfo=UTC)


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
        # §3.5 P1 第 3 条 ②④⑤：令牌控制面为**真实执行的前置件**（缺件即拒绝启用，见 startup 断言）。
        model_gateway_base_url="http://gw.internal:8080",
        model_gateway_mint_secret="unit-test-mint-secret",
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


# ------------------------------------- 027 仓储接线：RuntimeService ↔ ToolExecutionService


def _dsh_task_store() -> tuple[TaskStore, Task]:
    store = TaskStore()
    task = Task(
        tenant_id="t-1",
        project_id=None,
        created_by="u-1",
        employee_key="content-operator",
        title="027 接线",
        risk_level=RiskLevel.LOW,
        budget=1,
        idempotency_key="wiring-1",
        request_fingerprint="fp",
        status=TaskStatus.QUEUED,
    )
    store.create(_ACTOR, task)
    return store, task


def _wired_pair(tmp_path):
    """复现 `app/main.py` 的接线顺序：同一 027 仓储实例装配 Runtime 与工具执行。"""
    settings = _dsh_settings(tmp_path)
    metrics = RunMetricsService(InMemoryRunRecordStore())
    task_store, task = _dsh_task_store()
    tool_actions = build_tool_action_store(settings)
    runtime_service = build_runtime_service(
        settings, store=task_store, run_metrics=metrics, tool_actions=tool_actions
    )
    service = build_tool_execution(
        settings,
        run_metrics=metrics,
        audit=RecordingAudit(),
        runtime_service=runtime_service,
        tool_actions=tool_actions,
    )
    return runtime_service, service, task, tool_actions


def _approval_row(run_id: str, *, plan_digest_value: str, **overrides) -> ToolAction:
    """一行「需审批」的 027 待批动作（`requires_approval=True`）。"""
    base = dict(
        tenant_id="t-1",
        action_id="act-1",
        approval_id="appr-1",
        run_id=run_id,
        task_id="task-1",
        step_id="s2",
        tool_key="fs.list",
        args_digest="sha256:args",
        args_json={"path": "/workspace"},
        plan_digest=plan_digest_value,
        risk_level=RiskLevel.MEDIUM,
        requires_approval=True,
        status=ToolActionStatus.PENDING,
        requested_by="u-1",
        requested_at=_NOW,
    )
    base.update(overrides)
    return ToolAction(**base)


def test_mock_backend_wires_no_tool_actions() -> None:
    """(a) 默认 / mock：不存在真实执行 → 027 仓储为 None，RuntimeService 保持既有行为。"""
    settings = Settings(env="development", storage_backend="memory", agent_runtime_backend="mock")

    tool_actions = build_tool_action_store(settings)
    runtime_service = build_runtime_service(settings, store=object(), tool_actions=tool_actions)

    assert tool_actions is None
    assert runtime_service.tool_actions is None
    assert build_tool_execution(settings) is None


def test_mock_backend_builds_no_body_cleanup_task() -> None:
    """mock（`tool_execution is None`）→ 不注册正文密文 TTL 清理（不引入后台线程）。"""
    settings = Settings(env="development", storage_backend="memory", agent_runtime_backend="mock")
    assert build_body_cleanup_task(settings, None) is None


def test_dsh_backend_body_cleanup_task_uses_configured_interval_and_store(tmp_path) -> None:
    """清理任务用的周期 = `WORKBENCH_BODY_CLEANUP_INTERVAL_SECONDS`，仓储 = 服务的 027 仓储。"""
    _runtime_service, service, _task, tool_actions = _wired_pair(tmp_path)
    assert service is not None

    task = build_body_cleanup_task(_dsh_settings(tmp_path, body_cleanup_interval_seconds=45), service)

    assert task is not None
    assert task.interval_seconds == 45
    assert task.store is tool_actions
    assert task.store is service.tool_actions


def test_dsh_backend_shares_one_tool_action_store(tmp_path) -> None:
    """(b) 装配后 RuntimeService 与 ToolExecutionService 拿到的是**同一个** 027 仓储实例。"""
    runtime_service, service, _task, tool_actions = _wired_pair(tmp_path)

    assert service is not None
    assert isinstance(tool_actions, InMemoryToolActionStore)
    assert runtime_service.tool_actions is service.tool_actions
    assert runtime_service.tool_actions is tool_actions


def test_dsh_wiring_enforces_approval_path_without_actions(tmp_path) -> None:
    """(c) 端到端（服务层）：`actions` 缺省且存在需审批行 → `ExecutionNotAuthorized`。"""
    runtime_service, service, task, tool_actions = _wired_pair(tmp_path)
    assert service is not None
    assert runtime_service.tool_actions is not None

    run_id, _key, _version = runtime_service.start(
        _ACTOR, task.id, "mock", _RUNTIME_STEPS, "product_manager"
    )
    state = runtime_service.snapshot(_DECIDER, run_id)
    tool_actions.upsert(_approval_row(run_id, plan_digest_value=plan_digest(state.plan)))

    with pytest.raises(ExecutionNotAuthorized):
        runtime_service.ensure_execution_authorized(_DECIDER, run_id, state.plan)


# ------------------------- 用例 32③：审批落定（rejected 分支）即清空密文两列

_APPROVAL_STEPS = [
    {"step_id": "s1", "kind": "read", "tool": "knowledge.search"},
    {"step_id": "s2", "kind": "write", "tool": "fs.write", "requires_approval": True},
]


def test_decide_rejection_clears_body_ciphertext_and_expiry(tmp_path) -> None:
    """用例 32③（`rejected` 分支；§3.4 约束 2 / §4.1.5 ①）：审批**落定即清空**密文两列。

    驳回 = 不再执行 → 密文无保留必要，必须在**写入决议的同一次 upsert** 里清空两列
    （`body_check` 要求同有同无）。此分支与 `expired` 同口径，**不含** `approved`。
    """
    runtime_service, service, task, tool_actions = _wired_pair(tmp_path)
    assert service is not None
    run_id, _key, _version = runtime_service.start(
        _ACTOR, task.id, "mock", _APPROVAL_STEPS, "product_manager"
    )
    state = runtime_service.snapshot(_DECIDER, run_id)
    tool_actions.upsert(
        _approval_row(
            run_id,
            plan_digest_value=plan_digest(state.plan),
            approval_id="s2",
            body_ciphertext=b"\x00" * 28,
            body_expires_at=_NOW + timedelta(minutes=1),
        )
    )

    runtime_service.decide_approval(_DECIDER, run_id, "s2", False)

    row = tool_actions.get("t-1", "act-1")
    assert row.status is ToolActionStatus.REJECTED
    assert row.body_ciphertext is None
    assert row.body_expires_at is None
    assert row.decision_source == "user"


# ------------- §8 U22：正文密钥轮换「触发方式 = 启动时读配置」（装配处 `build_tool_execution`）


def _cipher_service(tmp_path, **overrides):
    """按装配处口径重新装配一次（= 「重启后读入配置」的等价模拟，**非真进程重启**）。"""
    settings = _dsh_settings(tmp_path, **overrides)
    metrics = RunMetricsService(InMemoryRunRecordStore())
    service = build_tool_execution(settings, run_metrics=metrics, audit=RecordingAudit())
    assert service is not None
    return service


def test_body_key_rotation_end_to_end_via_bootstrap(tmp_path) -> None:
    """§8 U22 轮换端到端：轮换 = 改配置 + 重启。

    旧密钥加密 → 构造「新配置同时含新密钥 + 旧密钥（`previous_keys`）」的新实例
    （等价于重启后重新装配读入配置）→ 旧密文**解密成功**。
    """
    old_key = base64.b64encode(os.urandom(32)).decode("ascii")
    new_key = base64.b64encode(os.urandom(32)).decode("ascii")

    before = _cipher_service(tmp_path, body_encryption_key=old_key)
    old_blob = before.body_cipher.encrypt("轮换前的正文")

    after = _cipher_service(
        tmp_path,
        body_encryption_key=new_key,
        body_encryption_previous_keys=old_key,
    )

    assert after.body_cipher.decrypt(old_blob) == "轮换前的正文"
    # 旧密钥**只**用于解密：旧实例解不开新活动密钥产出的密文。
    with pytest.raises(BodyCipherError):
        before.body_cipher.decrypt(after.body_cipher.encrypt("轮换后的正文"))


def test_body_key_rotation_outside_window_fails_closed(tmp_path) -> None:
    """§8 U22 窗口外失效：新实例**只含新密钥** → 解旧密文**必须抛 `BodyCipherError`**。"""
    old_key = base64.b64encode(os.urandom(32)).decode("ascii")
    old_blob = _cipher_service(tmp_path, body_encryption_key=old_key).body_cipher.encrypt("旧正文")

    outside = _cipher_service(
        tmp_path,
        body_encryption_key=base64.b64encode(os.urandom(32)).decode("ascii"),
    )

    with pytest.raises(BodyCipherError):
        outside.body_cipher.decrypt(old_blob)


def test_body_previous_keys_missing_or_blank_is_fail_closed(tmp_path) -> None:
    """§8 U22 fail-closed：配置缺失 / 为空 / 仅分隔符 ⇒ 不使用旧密钥（= 只含新密钥的行为）。"""
    old_key = base64.b64encode(os.urandom(32)).decode("ascii")
    old_blob = _cipher_service(tmp_path, body_encryption_key=old_key).body_cipher.encrypt("旧正文")
    new_key = base64.b64encode(os.urandom(32)).decode("ascii")

    for blank in ("", "   ", " , ", ","):
        service = _cipher_service(
            tmp_path,
            body_encryption_key=new_key,
            body_encryption_previous_keys=blank,
        )
        with pytest.raises(BodyCipherError):
            service.body_cipher.decrypt(old_blob)

