from datetime import UTC, datetime, timedelta

import pytest

from app.runtime.adapters import AgentScopeAdapter, FakeTransport
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
    transport=FakeTransport(events=[{'type':'mystery','payload':{'cookie':'x'}}]); adapter=DeerFlowAdapter(transport, 'http://deerflow')
    run=adapter.start_run(context(), AgentPlan.from_steps([]))
    event=adapter.stream_events(run)[0]
    assert event.event_type.value == 'run.failed'
    assert event.to_public_dict()['payload']['cookie'] == '[已隐藏]'


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
        {"type": "vendor.new_event", "payload": {"cookie": "hidden"}},
    ])
    adapter = AgentScopeAdapter(transport, "https://agentscope")
    run = adapter.start_run(context(), AgentPlan.from_steps([]))
    events = adapter.stream_events(run)
    assert [event.event_type.value for event in events] == ["step.started", "checkpoint.saved", "run.failed"]
    assert events[-1].to_public_dict()["payload"]["cookie"] == "[已隐藏]"


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
