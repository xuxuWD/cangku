from datetime import UTC, datetime, timedelta

from app.runtime.contracts import (
    AgentPlan,
    AgentRuntimeAdapter,
    KnowledgeCitation,
    RuntimeContext,
    RuntimeEvent,
    RuntimeEventType,
)


def test_knowledge_citation_requires_the_public_reference_fields() -> None:
    citation = KnowledgeCitation(
        document_id="doc-1",
        knowledge_base_id="kb-1",
        title="设备维护手册",
        snippet="检查电源和散热。",
        score=0.92,
    )

    assert citation.document_id == "doc-1"
    assert citation.knowledge_base_id == "kb-1"
    assert citation.score == 0.92


def test_runtime_context_requires_scope_and_expiry() -> None:
    expires_at = datetime.now(UTC) + timedelta(minutes=5)
    context = RuntimeContext(
        tenant_id="tenant-1",
        user_id="user-1",
        role_key="ai-product-delivery",
        mode="product_manager",
        project_id="project-1",
        task_id="task-1",
        device_id="device-1",
        knowledge_scope=("kb-product",),
        file_scope=("D:/staging/project-1",),
        budget_cents=5000,
        risk_level="low",
        policy_version="policy-1",
        expires_at=expires_at,
    )
    assert context.is_valid_at(datetime.now(UTC))
    assert not context.is_valid_at(expires_at + timedelta(seconds=1))


def test_plan_marks_side_effects_as_approval_required() -> None:
    plan = AgentPlan.from_steps(
        [
            {"step_id": "s1", "kind": "read", "tool": "knowledge.search"},
            {"step_id": "s2", "kind": "write", "tool": "file.write"},
        ]
    )
    assert plan.steps[1].requires_approval is True
    assert plan.steps[0].requires_approval is False


def test_event_serialization_keeps_cursor_and_redacts_secrets() -> None:
    event = RuntimeEvent(
        run_id="run-1",
        sequence=3,
        event_type=RuntimeEventType.TOOL_RESULT,
        payload={"text": "ok", "api_key": "secret", "cookie": "session"},
    )
    data = event.to_public_dict()
    assert data["cursor"] == "run-1:3"
    assert data["payload"]["api_key"] == "[已隐藏]"
    assert data["payload"]["cookie"] == "[已隐藏]"


def test_adapter_protocol_exposes_lifecycle_methods() -> None:
    methods = {name for name in dir(AgentRuntimeAdapter) if not name.startswith("_")}
    assert {
        "start_run",
        "stream_events",
        "pause_run",
        "resume_run",
        "cancel_run",
        "request_approval",
        "get_checkpoint",
        "replay_run",
        "get_usage",
        "health",
    } <= methods
