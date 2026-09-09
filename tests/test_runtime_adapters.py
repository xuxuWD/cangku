from datetime import UTC, datetime, timedelta

import pytest

from app.runtime.adapters import AgentScopeAdapter, FakeTransport
from app.runtime.registry import RuntimeRegistry
from app.runtime.service import RuntimeService
from app.runtime.state import RuntimeStateStore
from app.domain import RiskLevel, Task, TaskStatus, UserContext
from app.runtime.adapters.codex_worker import CodexWorkerAdapter
from app.runtime.adapters.deerflow import DeerFlowAdapter
from app.runtime.adapters.hermes import HermesAdapter
from app.runtime.contracts import AgentPlan, RuntimeContext


def context(mode='product_manager'):
    return RuntimeContext('t1','u1','role',mode,'p1','task-1','device-1',('kb-1',),('D:/staging/project-1',),100,'low','policy-1',datetime.now(UTC)+timedelta(minutes=5))


def test_deerflow_adapter_sends_redacted_context_and_maps_events():
    transport=FakeTransport(); adapter=DeerFlowAdapter(transport, 'http://deerflow')
    run=adapter.start_run(context(), AgentPlan.from_steps([{'step_id':'s1','kind':'read','tool':'research'}]))
    request=transport.requests[-1]
    assert request['context']['tenant_id']=='t1'
    assert 'api_key' not in request
    assert adapter.stream_events(run)[0].event_type.value == 'plan.created'


def test_codex_worker_requires_fde_and_file_scope():
    transport=FakeTransport(); adapter=CodexWorkerAdapter(transport, 'http://codex')
    with pytest.raises(ValueError):
        adapter.start_run(context(), AgentPlan.from_steps([]))
    run=adapter.start_run(context('fde'), AgentPlan.from_steps([{'step_id':'s1','kind':'read','tool':'file.read'}]))
    assert run.startswith('run-')


def test_hermes_only_returns_pending_review_proposal():
    transport=FakeTransport(); adapter=HermesAdapter(transport, 'http://hermes')
    run=adapter.start_run(context(), AgentPlan.from_steps([{'step_id':'s1','kind':'proposal','tool':'memory.propose'}]))
    events=adapter.stream_events(run)
    assert any(event.payload.get('status') == 'pending_review' for event in events)


def test_unknown_remote_event_becomes_failure_and_secrets_are_redacted():
    transport=FakeTransport(events=[{'type':'mystery','payload':{'cookie':'x','api_key':'y','extra':'z'}}]); adapter=DeerFlowAdapter(transport, 'http://deerflow')
    run=adapter.start_run(context(), AgentPlan.from_steps([]))
    event=adapter.stream_events(run)[0]
    assert event.event_type.value == 'run.failed'
    assert event.payload == {'reason': '外部运行时返回未知事件', 'remote_type': 'mystery'}
    assert event.to_public_dict()['payload'] == event.payload


def test_agentscope_adds_fixed_runtime_key_and_preserves_approval_flags():
    transport = FakeTransport()
    adapter = AgentScopeAdapter(transport, "https://agentscope")
    run = adapter.start_run(
        context(), AgentPlan.from_steps([{"step_id": "s1", "kind": "write", "tool": "file.write"}])
    )
    payload = transport.requests[-1]
    assert run.startswith("run-")
    assert payload["runtime_key"] == "agentscope"
    assert payload["plan"][0]["requires_approval"] is True
    assert payload["context"]["tenant_id"] == "t1"


def test_agentscope_maps_known_events_and_unknown_events_to_failure():
    transport = FakeTransport(events=[
        {"type": "step.started", "payload": {"step_id": "s1"}},
        {"type": "checkpoint.saved", "payload": {"token": "hidden"}},
        {"type": "vendor.new_event", "payload": {"cookie": "hidden", "api_key": "hidden", "arbitrary": "hidden"}},
    ])
    adapter = AgentScopeAdapter(transport, "https://agentscope")
    run = adapter.start_run(context(), AgentPlan.from_steps([]))
    events = adapter.stream_events(run)
    assert [event.event_type.value for event in events] == ["step.started", "checkpoint.saved", "run.failed"]
    assert events[-1].payload == {"reason": "外部运行时返回未知事件", "remote_type": "vendor.new_event"}
    assert events[-1].to_public_dict()["payload"] == events[-1].payload


def test_known_event_payload_redacts_authorization_tokens_and_sessions():
    transport = FakeTransport(events=[{
        "type": "tool.call",
        "payload": {
            "authorization": "Bearer secret",
            "access_token": "access",
            "refresh_token": "refresh",
            "session": "session",
            "nested": {"Authorization": "nested-secret"},
        },
    }])
    adapter = AgentScopeAdapter(transport, "https://agentscope")
    run = adapter.start_run(context(), AgentPlan.from_steps([]))

    public_payload = adapter.stream_events(run)[0].to_public_dict()["payload"]

    assert public_payload["authorization"] == "[已隐藏]"
    assert public_payload["access_token"] == "[已隐藏]"
    assert public_payload["refresh_token"] == "[已隐藏]"
    assert public_payload["session"] == "[已隐藏]"
    assert public_payload["nested"]["Authorization"] == "[已隐藏]"


def test_unknown_remote_event_uses_safe_remote_type():
    transport = FakeTransport(events=[
        {"type": {"api_key": "hidden"}, "payload": {"cookie": "hidden"}},
        {"type": "bad type with spaces", "payload": {"token": "hidden"}},
    ])
    adapter = DeerFlowAdapter(transport, "http://deerflow")
    run = adapter.start_run(context(), AgentPlan.from_steps([]))

    events = adapter.stream_events(run)

    assert [event.payload for event in events] == [
        {"reason": "外部运行时返回未知事件", "remote_type": "unknown"},
        {"reason": "外部运行时返回未知事件", "remote_type": "unknown"},
    ]


def test_agentscope_reuses_lifecycle_commands_without_automatic_retry():
    transport = FakeTransport()
    adapter = AgentScopeAdapter(transport, "https://agentscope")
    run = adapter.start_run(context(), AgentPlan.from_steps([]))
    adapter.pause_run(run, "人工检查")
    adapter.resume_run(run)
    adapter.cancel_run(run, "取消")
    approval_id = adapter.request_approval(run, {"step_id": "s1"})
    adapter.replay_run(run, "s1")
    assert approval_id.startswith("approval-")
    assert [request["action"] for request in transport.requests[1:]] == [
        "pause", "resume", "cancel", "approvals", "replay",
    ]


def test_external_run_is_registered_in_service_state_store_for_control_plane():
    task = Task(
        tenant_id="t1", project_id="p1", created_by="u1", employee_key="role",
        title="external", risk_level=RiskLevel.LOW, budget=10,
        idempotency_key="external-1", request_fingerprint="fp-1", status=TaskStatus.QUEUED,
    )
    actor = UserContext(tenant_id="t1", user_id="u1", role="employee")
    store = RuntimeStateStore()
    adapter = AgentScopeAdapter(FakeTransport(), "https://agentscope")
    registry = RuntimeRegistry()
    registry.register("agentscope", adapter)
    service = RuntimeService(type("TaskStore", (), {"get": lambda _self, _ctx, _id: task})(), registry=registry, state_store=store)

    run_id, _, _ = service.start(actor, task.id, "agentscope", [], "product_manager")
    key, selected, state = service.adapter_for_task(actor, run_id)

    assert key == "agentscope"
    assert selected is adapter
    assert state.run_id == run_id
    adapter.pause_run(run_id, "检查")
    adapter.resume_run(run_id)
    adapter.cancel_run(run_id, "结束")
    adapter.request_approval(run_id, {"tool": "x"})
    adapter.replay_run(run_id, "plan")


def test_external_health_is_reduced_to_safe_summary():
    class LeakyTransport(FakeTransport):
        def health(self, endpoint):
            return {
                "runtime": endpoint,
                "status": "unavailable",
                "version": "v2",
                "capabilities": ["run"],
                "sandbox": "isolated",
                "reason": "ok",
                "authorization": "Bearer secret",
                "session": "session-secret",
                "cookie": "cookie-secret",
                "api_key": "api-secret",
                "extra": "drop",
            }

    health = AgentScopeAdapter(LeakyTransport(), "https://agentscope").health()

    assert health == {
        "runtime": "https://agentscope",
        "status": "ok",
        "version": "v2",
        "capabilities": ["run"],
        "sandbox": "isolated",
        "reason": "ok",
    }


def test_runtime_registry_health_filters_untrusted_adapter_summary():
    class UntrustedAdapter:
        def health(self):
            return {
                "runtime": "https://runtime",
                "status": "unavailable",
                "version": {"token": "secret"},
                "capabilities": ["run", {"session": "secret"}],
                "reason": {"authorization": "secret"},
                "authorization": "Bearer secret",
            }

    registry = RuntimeRegistry()
    registry.register("external", UntrustedAdapter())

    assert registry.health() == {
        "external": {
            "runtime": "https://runtime",
            "status": "ok",
        }
    }
