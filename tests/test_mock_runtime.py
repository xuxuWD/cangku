from datetime import UTC, datetime, timedelta

from app.runtime.contracts import AgentPlan, RuntimeContext, RuntimeEventType
from app.runtime.mock import MockRuntime
from app.runtime.state import RuntimeStateStore


def ctx():
    return RuntimeContext('t1','u1','role','fde','p1','task-1','device-1',('kb-1',),('D:/staging/project-1',),100,'low','policy-1',datetime.now(UTC)+timedelta(minutes=5))


def test_mock_runtime_lifecycle_and_resume_is_idempotent():
    store=RuntimeStateStore(); runtime=MockRuntime(store)
    plan=AgentPlan.from_steps([{'step_id':'s1','kind':'read','tool':'file.read'},{'step_id':'s2','kind':'write','tool':'file.write'}])
    run=runtime.start_run(ctx(),plan)
    events=runtime.stream_events(run)
    assert events[0].event_type == RuntimeEventType.PLAN_CREATED
    assert any(e.event_type == RuntimeEventType.APPROVAL_REQUESTED for e in events)
    runtime.pause_run(run,'等待审批')
    assert runtime.get_checkpoint(run)['status'] == 'paused'
    runtime.resume_run(run)
    assert runtime.get_checkpoint(run)['completed_steps'] == ['s1']
    runtime.resume_run(run)
    assert runtime.get_checkpoint(run)['completed_steps'] == ['s1']


def test_cancel_and_cursor_replay_do_not_duplicate_events():
    runtime=MockRuntime(RuntimeStateStore())
    run=runtime.start_run(ctx(),AgentPlan.from_steps([{'step_id':'s1','kind':'read','tool':'knowledge.search'}]))
    first=runtime.stream_events(run); cursor=first[-1].to_public_dict()['cursor']
    assert runtime.stream_events(run,cursor) == []
    runtime.cancel_run(run,'用户取消')
    assert runtime.get_checkpoint(run)['status'] == 'cancelled'


def test_mock_runtime_marks_run_completed_when_no_approvals_pending():
    runtime=MockRuntime(RuntimeStateStore())
    run=runtime.start_run(ctx(),AgentPlan.from_steps([{'step_id':'s1','kind':'read','tool':'knowledge.search'}]))
    assert runtime.get_checkpoint(run)['status'] == 'completed'
    events=runtime.stream_events(run)
    completed=[event for event in events if event.event_type == RuntimeEventType.RUN_COMPLETED]
    assert completed and completed[-1].payload == {'step_count': 1}


def test_mock_runtime_stays_running_when_approval_is_required():
    runtime=MockRuntime(RuntimeStateStore())
    run=runtime.start_run(ctx(),AgentPlan.from_steps([{'step_id':'s1','kind':'write','tool':'file.write'}]))
    assert runtime.get_checkpoint(run)['status'] == 'running'
    assert not any(event.event_type == RuntimeEventType.RUN_COMPLETED for event in runtime.stream_events(run))
