"""`ToolExecutionService` 的装配与 `resume` 失败语义骨架（规格 §4.1.6-1 / -1.1 / -5）。

本步骤**不实现** ①–⑨ 闸门全流程：正常路径必须显式 `NotImplementedError`，不得假装成功。
本文件覆盖：构造依赖装配、两条加解密失败语义、失败表码位映射。
"""

from __future__ import annotations

import base64
import os
from datetime import UTC, datetime

import pytest

from app.audit.models import AuditAction
from app.domain import RiskLevel
from app.tool_execution.body_cipher import BodyCipher
from app.tool_execution.catalog import ToolSpecCatalog, default_tool_specs
from app.tool_execution.errors import BodyCipherError
from app.tool_execution.executor import ContainerExecutor
from app.tool_execution.service import (
    ENCRYPT_FAILURE_SEMANTICS,
    RE_RUN_FAILURE_SEMANTICS,
    ToolExecutionError,
    ToolExecutionService,
)
from app.tool_execution.store import (
    InMemoryToolActionStore,
    ReasonCode,
    ToolAction,
    ToolActionStatus,
)
from app.tool_execution.workspace import WorkspaceManager
from app.runtime.records import InMemoryRunRecordStore


class RecordingAudit:
    def __init__(self) -> None:
        self.calls: list[tuple[AuditAction, dict]] = []

    def record(self, action: AuditAction, **kwargs) -> None:
        self.calls.append((action, kwargs))


class ExplodingCipher:
    """加密必失败的假件，用于验证 ⑥ 的 503 失败语义。"""

    def encrypt(self, plaintext: str) -> bytes:
        raise BodyCipherError("boom")

    def decrypt(self, blob: bytes) -> str:  # pragma: no cover - 本用例不触发
        raise BodyCipherError("boom")


def _key() -> str:
    return base64.b64encode(os.urandom(32)).decode("ascii")


def _executor() -> ContainerExecutor:
    return ContainerExecutor(
        image_digest="registry.local/dsh@sha256:abc",
        pids_limit=64,
        memory_mb=512,
        cpu_quota=1.5,
        timeout_seconds=120,
    )


def _service(tmp_path, *, store=None, cipher=None, audit=None) -> ToolExecutionService:
    return ToolExecutionService(
        catalog=ToolSpecCatalog(default_tool_specs()),
        body_cipher=cipher or BodyCipher.from_base64(_key()),
        executor=_executor(),
        workspace=WorkspaceManager(str(tmp_path)),
        tool_actions=store or InMemoryToolActionStore(),
        run_records=InMemoryRunRecordStore(),
        audit=audit,
    )


def _approved_action(*, tool_key: str, args_json: dict, **overrides) -> ToolAction:
    base = dict(
        tenant_id="t-1",
        action_id="act-1",
        approval_id="appr-1",
        run_id="run-1",
        task_id="task-1",
        step_id="step-1",
        tool_key=tool_key,
        args_digest="sha256:digest",
        args_json=args_json,
        plan_digest="sha256:plan",
        risk_level=RiskLevel.MEDIUM,
        requires_approval=True,
        status=ToolActionStatus.APPROVED,
        requested_by="user-1",
        requested_at=datetime(2026, 9, 13, tzinfo=UTC),
        decided_by="ceo-1",
        decided_at=datetime(2026, 9, 13, tzinfo=UTC),
        decision_source="user",
    )
    base.update(overrides)
    return ToolAction(**base)


def test_encrypt_failure_maps_to_503_without_audit(tmp_path) -> None:
    audit = RecordingAudit()
    service = _service(tmp_path, cipher=ExplodingCipher(), audit=audit)
    with pytest.raises(ToolExecutionError) as excinfo:
        service.encrypt_body("机密正文")
    assert excinfo.value.http_status == ENCRYPT_FAILURE_SEMANTICS.http_status == 503
    assert excinfo.value.reason_code is None
    # §4.1.6-1.1①：未产生副作用，**不写 tool.* 审计**。
    assert audit.calls == []


def test_resume_decrypt_failure_maps_to_502_and_blocks(tmp_path) -> None:
    cipher = BodyCipher.from_base64(_key())
    store = InMemoryToolActionStore()
    tampered = bytearray(cipher.encrypt("机密正文"))
    tampered[-1] ^= 0x01
    store.upsert(
        _approved_action(
            tool_key="fs.write",
            args_json={"path": "/workspace/a.txt", "content": "«body»"},
            body_ciphertext=bytes(tampered),
            body_expires_at=datetime(2026, 9, 13, tzinfo=UTC),
        )
    )
    audit = RecordingAudit()
    service = _service(tmp_path, store=store, cipher=cipher, audit=audit)

    with pytest.raises(ToolExecutionError) as excinfo:
        service.resume(tenant_id="t-1", run_id="run-1", approval_id="appr-1")

    semantics = RE_RUN_FAILURE_SEMANTICS["body_decrypt_failed"]
    assert excinfo.value.http_status == semantics.http_status == 502
    assert excinfo.value.reason_code is ReasonCode.RUNTIME_ERROR
    assert excinfo.value.keep_approved is True
    # 记 tool.blocked；027 行保持 approved（可重试 / 可人工介入）。
    assert [action for action, _ in audit.calls] == [AuditAction.TOOL_BLOCKED]
    detail = audit.calls[0][1]["detail"]
    assert detail["tool_key"] == "fs.write"
    assert detail["risk_level"] == "medium"
    assert detail["reason"] == "runtime_error"
    assert store.get("t-1", "act-1").status is ToolActionStatus.APPROVED
    # 审计/日志不得落正文或密文。
    assert "«body»" not in str(detail)
    assert "cipher" not in str(detail).lower()


def test_resume_missing_body_ciphertext_is_decrypt_failure(tmp_path) -> None:
    store = InMemoryToolActionStore()
    store.upsert(
        _approved_action(
            tool_key="fs.write",
            args_json={"path": "/workspace/a.txt", "content": "«body»"},
        )
    )
    audit = RecordingAudit()
    service = _service(tmp_path, store=store, audit=audit)
    with pytest.raises(ToolExecutionError) as excinfo:
        service.resume(tenant_id="t-1", run_id="run-1", approval_id="appr-1")
    assert excinfo.value.http_status == 502
    assert [action for action, _ in audit.calls] == [AuditAction.TOOL_BLOCKED]


def test_resume_without_approved_row_is_not_authorized(tmp_path) -> None:
    service = _service(tmp_path)
    with pytest.raises(ToolExecutionError) as excinfo:
        service.resume(tenant_id="t-1", run_id="run-1", approval_id="missing")
    assert excinfo.value.http_status == 409
    assert excinfo.value.reason_code is ReasonCode.NOT_AUTHORIZED


def test_resume_gate_pipeline_is_not_implemented(tmp_path) -> None:
    """①–⑨ 全流程未实现：参数可还原时也必须显式 NotImplementedError，不得假装成功。"""
    store = InMemoryToolActionStore()
    store.upsert(
        _approved_action(tool_key="fs.list", args_json={"path": "/workspace"})
    )
    service = _service(tmp_path, store=store)
    with pytest.raises(NotImplementedError):
        service.resume(tenant_id="t-1", run_id="run-1", approval_id="appr-1")


def test_failure_code_table_matches_spec() -> None:
    expected = {
        "not_in_catalog": (409, ReasonCode.NOT_IN_CATALOG, ToolActionStatus.APPROVED),
        "param_invalid": (422, ReasonCode.PARAM_INVALID, ToolActionStatus.APPROVED),
        "path_denied": (403, ReasonCode.PATH_DENIED, ToolActionStatus.APPROVED),
        "blacklisted": (403, ReasonCode.BLACKLISTED, ToolActionStatus.REJECTED),
        "body_decrypt_failed": (502, ReasonCode.RUNTIME_ERROR, ToolActionStatus.APPROVED),
        "timeout": (504, ReasonCode.TIMEOUT, ToolActionStatus.APPROVED),
        "runtime_error": (502, ReasonCode.RUNTIME_ERROR, ToolActionStatus.APPROVED),
        "executed": (201, None, ToolActionStatus.APPROVED),
    }
    for key, (status, reason, action_status) in expected.items():
        semantics = RE_RUN_FAILURE_SEMANTICS[key]
        assert semantics.http_status == status, key
        assert semantics.reason_code is reason, key
        assert semantics.action_status is action_status, key
        assert semantics.audit_action is (
            AuditAction.TOOL_EXECUTED if key == "executed" else AuditAction.TOOL_BLOCKED
        ), key
    assert ENCRYPT_FAILURE_SEMANTICS.http_status == 503
    assert ENCRYPT_FAILURE_SEMANTICS.audit_action is None
