from datetime import UTC, datetime, timedelta

import pytest

from app.runtime.adapters import FakeTransport
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
