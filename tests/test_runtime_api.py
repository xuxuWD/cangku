from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def h(role='employee', user='runtime-user', tenant='runtime-tenant'):
    return {'X-Tenant-Id': tenant, 'X-User-Id': user, 'X-User-Role': role}


def make_task(tenant='runtime-tenant'):
    response=client.post('/api/v1/tasks', headers=h(tenant=tenant), json={'title':'运行任务','employee_key':'content-operator','risk_level':'low','budget':10,'idempotency_key':f'run-{tenant}-{datetime.now(UTC).timestamp()}'})
    assert response.status_code == 201
    return response.json()['id']


def test_run_api_creates_streams_and_controls_runtime():
    task_id=make_task(); created=client.post(f'/api/v1/tasks/{task_id}/runs', headers=h(), json={'runtime_key':'mock','steps':[{'step_id':'s1','kind':'read','tool':'knowledge.search'}]})
    assert created.status_code == 201
    body=created.json(); assert body['runtime_key']=='mock'; assert body['status']=='completed'; run_id=body['run_id']
    events=client.get(f'/api/v1/runs/{run_id}/events', headers=h()); assert events.status_code == 200; assert events.json()[0]['event_type']=='plan.created'
    cursor=events.json()[-1]['cursor']; assert client.get(f'/api/v1/runs/{run_id}/events?cursor={cursor}', headers=h()).json()==[]
    paused=client.post(f'/api/v1/runs/{run_id}/pause', headers=h(), json={'reason':'等待确认'}); assert paused.status_code==200
    resumed=client.post(f'/api/v1/runs/{run_id}/resume', headers=h()); assert resumed.status_code==200
    cancelled=client.post(f'/api/v1/runs/{run_id}/cancel', headers=h(), json={'reason':'测试取消'}); assert cancelled.status_code==200


def test_run_api_requires_owner_or_admin_and_hides_other_tenants():
    task_id=make_task(); created=client.post(f'/api/v1/tasks/{task_id}/runs', headers=h(), json={'runtime_key':'mock','steps':[]}); run_id=created.json()['run_id']
    assert client.get(f'/api/v1/runs/{run_id}/events', headers=h(user='other')).status_code == 403
    assert client.get(f'/api/v1/runs/{run_id}/events', headers=h(tenant='other-tenant')).status_code == 404


def test_unknown_runtime_and_approval_return_safe_errors():
    task_id=make_task(); unknown=client.post(f'/api/v1/tasks/{task_id}/runs', headers=h(), json={'runtime_key':'missing','steps':[]}); assert unknown.status_code==400
    created=client.post(f'/api/v1/tasks/{task_id}/runs', headers=h(), json={'runtime_key':'mock','steps':[{'step_id':'s1','kind':'write','tool':'file.write'}]}); run_id=created.json()['run_id']
    approval=client.post(f'/api/v1/runs/{run_id}/approvals', headers=h(), json={'action':{'tool':'file.write'}}); assert approval.status_code==202; assert approval.json()['approval_id'].startswith('approval-')


def test_runtime_health_is_limited_to_management_roles():
    assert client.get('/api/v1/runtimes/health', headers=h()).status_code == 403
    response = client.get('/api/v1/runtimes/health', headers=h(role='super_admin', user='admin'))
    assert response.status_code == 200
    assert response.json()['mock']['status'] == 'ok'
    assert 'session' not in response.text.lower()
