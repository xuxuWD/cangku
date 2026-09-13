"""`ToolActionStore` 的 `workbench_tool_actions` 读写约束（迁移 027 / 规格 §4.1.1）。

判据：
    - `reason_code` 只能取 9 值受控枚举；
    - `body_ciphertext` 与 `body_expires_at` **同有同无**（迁移 027 的 `body_check`）。
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.domain import RiskLevel
from app.tool_execution.store import (
    InMemoryToolActionStore,
    ReasonCode,
    ToolAction,
    ToolActionStatus,
)


def _pending(**overrides) -> ToolAction:
    base = dict(
        tenant_id="t-1",
        action_id="act-1",
        approval_id="appr-1",
        run_id="run-1",
        task_id="task-1",
        step_id="step-1",
        tool_key="fs.write",
        args_digest="sha256:digest",
        args_json={"path": "/workspace/a.txt", "content": "«body»"},
        body_ciphertext=b"cipher",
        body_expires_at=datetime(2026, 9, 13, tzinfo=UTC),
        plan_digest="sha256:plan",
        risk_level=RiskLevel.MEDIUM,
        requires_approval=True,
        status=ToolActionStatus.PENDING,
        requested_by="user-1",
        requested_at=datetime(2026, 9, 13, tzinfo=UTC),
    )
    base.update(overrides)
    return ToolAction(**base)


def test_reason_code_enum_has_exactly_nine_values() -> None:
    assert {code.value for code in ReasonCode} == {
        "path_denied",
        "blacklisted",
        "param_invalid",
        "not_authorized",
        "not_in_catalog",
        "timeout",
        "runtime_error",
        "approval_denied",
        "approval_expired",
    }


def test_store_rejects_unknown_reason_code() -> None:
    store = InMemoryToolActionStore()
    with pytest.raises(ValueError):
        store.upsert(_pending(reason_code="free_text_reason"))  # type: ignore[arg-type]


@pytest.mark.parametrize("code", [code.value for code in ReasonCode])
def test_store_accepts_each_controlled_reason_code(code: str) -> None:
    store = InMemoryToolActionStore()
    action = _pending(
        status=ToolActionStatus.REJECTED,
        decided_by="ceo-1",
        decided_at=datetime(2026, 9, 13, tzinfo=UTC),
        decision_source="user",
        reason_code=ReasonCode(code),
    )
    assert store.upsert(action).reason_code is ReasonCode(code)


def test_store_rejects_ciphertext_without_expiry() -> None:
    store = InMemoryToolActionStore()
    with pytest.raises(ValueError):
        store.upsert(_pending(body_expires_at=None))


def test_store_rejects_expiry_without_ciphertext() -> None:
    store = InMemoryToolActionStore()
    with pytest.raises(ValueError):
        store.upsert(_pending(body_ciphertext=None))


def test_store_roundtrip_preserves_body_and_decision() -> None:
    store = InMemoryToolActionStore()
    store.upsert(_pending())
    loaded = store.get("t-1", "act-1")
    assert loaded.body_ciphertext == b"cipher"
    assert loaded.body_expires_at == datetime(2026, 9, 13, tzinfo=UTC)

    decided = store.upsert(
        _pending(
            status=ToolActionStatus.APPROVED,
            decided_by="ceo-1",
            decided_at=datetime(2026, 9, 13, tzinfo=UTC),
            decision_source="user",
        )
    )
    assert decided.status is ToolActionStatus.APPROVED
    assert store.find_approved(tenant_id="t-1", run_id="run-1", approval_id="appr-1") is not None


def test_store_isolates_tenants() -> None:
    store = InMemoryToolActionStore()
    store.upsert(_pending())
    assert store.list_for_run("t-2", "run-1") == []
    assert store.find_approved(tenant_id="t-2", run_id="run-1", approval_id="appr-1") is None
