from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def h(role="employee", user="content-user", tenant="content-tenant"):
    return {"X-Tenant-Id": tenant, "X-User-Id": user, "X-User-Role": role}


def create_content_task(*, user="content-user", tenant="content-tenant"):
    return client.post(
        "/api/v1/content-tasks",
        headers=h(user=user, tenant=tenant),
        json={
            "topic": "本周选题",
            "sources": [{"url": "https://example.com/a", "excerpt": "参考摘录"}],
            "knowledge_references": [],
            "idempotency_key": f"content-{user}-{tenant}",
        },
    )


def test_content_api_creates_reads_edits_confirms_and_exports():
    created = create_content_task()
    assert created.status_code == 201
    task_id = created.json()["task_id"]
    assert client.get(f"/api/v1/content-tasks/{task_id}", headers=h()).json()["status"] == "reviewing"
    updated = client.put(
        f"/api/v1/content-tasks/{task_id}/draft", headers=h(),
        json={"revision": 1, "title": "新标题", "summary": "摘要", "body_markdown": "正文", "image_suggestions": ["配图"]},
    )
    assert updated.status_code == 200
    assert client.post(f"/api/v1/content-tasks/{task_id}/confirmation", headers=h(), json={"revision": 2}).status_code == 200
    exported = client.get(f"/api/v1/content-tasks/{task_id}/export.md", headers=h())
    assert exported.status_code == 200
    assert exported.headers["content-type"].startswith("text/markdown")
    assert "# 新标题" in exported.text


def test_content_api_hides_cross_user_and_rejects_unconfirmed_export():
    created = create_content_task(user="owner")
    task_id = created.json()["task_id"]
    assert client.get(f"/api/v1/content-tasks/{task_id}", headers=h(user="other")).status_code == 404
    assert client.get(f"/api/v1/content-tasks/{task_id}/export.md", headers=h(user="owner")).status_code == 409


def test_content_api_validates_input_and_idempotency_conflicts():
    first = create_content_task(user="same")
    assert first.status_code == 201
    replay = create_content_task(user="same")
    assert replay.status_code == 200
    assert replay.json()["task_id"] == first.json()["task_id"]
    invalid = client.post(
        "/api/v1/content-tasks", headers=h(user="invalid"),
        json={"topic": "", "sources": [], "knowledge_references": [], "idempotency_key": "invalid"},
    )
    assert invalid.status_code == 422


def test_development_frontend_origin_can_preflight_content_requests():
    response = client.options(
        "/api/v1/content-tasks",
        headers={"Origin": "http://127.0.0.1:5173", "Access-Control-Request-Method": "POST"},
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"
    second_port = client.options(
        "/api/v1/content-tasks",
        headers={"Origin": "http://127.0.0.1:5174", "Access-Control-Request-Method": "POST"},
    )
    assert second_port.status_code == 200
    assert second_port.headers["access-control-allow-origin"] == "http://127.0.0.1:5174"


def test_content_api_regenerates_with_same_task_and_new_run():
    created = create_content_task(user="regenerate")
    task_id = created.json()["task_id"]
    original_run = created.json()["run_id"]
    regenerated = client.post(
        f"/api/v1/content-tasks/{task_id}/regenerations", headers=h(user="regenerate"),
        json={"idempotency_key": "regen-key-1"},
    )
    assert regenerated.status_code == 200
    assert regenerated.json()["task_id"] == task_id
    assert regenerated.json()["run_id"] != original_run
    replay = client.post(
        f"/api/v1/content-tasks/{task_id}/regenerations", headers=h(user="regenerate"),
        json={"idempotency_key": "regen-key-1"},
    )
    assert replay.status_code == 200
    assert replay.json()["run_id"] == regenerated.json()["run_id"]


def test_content_api_lists_scoped_paginated_summaries():
    tenant = "history-api-tenant"
    create_content_task(user="owner-a", tenant=tenant)
    create_content_task(user="owner-b", tenant=tenant)
    create_content_task(user="other-tenant", tenant="history-api-other")

    employee = client.get(
        "/api/v1/content-tasks?page=1&page_size=1", headers=h(user="owner-a", tenant=tenant)
    )
    assert employee.status_code == 200
    employee_payload = employee.json()
    assert employee_payload["total"] == 1
    assert employee_payload["items"][0]["created_by"] == "owner-a"
    assert "draft" not in employee_payload["items"][0]
    assert employee_payload["items"][0]["topic"] == "本周选题"
    assert employee_payload["has_next"] is False

    admin = client.get(
        "/api/v1/content-tasks?page=1&page_size=20", headers=h(role="super_admin", user="admin", tenant=tenant)
    )
    assert admin.status_code == 200
    assert admin.json()["total"] == 2
    assert {item["created_by"] for item in admin.json()["items"]} == {"owner-a", "owner-b"}

    assert client.get(
        "/api/v1/content-tasks?status=bad", headers=h(user="owner-a", tenant=tenant)
    ).status_code == 400
    assert client.get(
        "/api/v1/content-tasks?page=0", headers=h(user="owner-a", tenant=tenant)
    ).status_code == 400
    assert client.get(
        "/api/v1/content-tasks?page_size=101", headers=h(user="owner-a", tenant=tenant)
    ).status_code == 400


def test_content_api_lists_status_filtered_history():
    tenant = "history-status-tenant"
    created = create_content_task(user="status-owner", tenant=tenant)
    task_id = created.json()["task_id"]
    confirmed = client.post(
        f"/api/v1/content-tasks/{task_id}/confirmation",
        headers=h(user="status-owner", tenant=tenant),
        json={"revision": 1},
    )
    assert confirmed.status_code == 200

    reviewing = client.get(
        "/api/v1/content-tasks?status=reviewing", headers=h(user="status-owner", tenant=tenant)
    )
    assert reviewing.status_code == 200
    assert reviewing.json()["total"] == 0

    confirmed_list = client.get(
        "/api/v1/content-tasks?status=confirmed", headers=h(user="status-owner", tenant=tenant)
    )
    assert confirmed_list.status_code == 200
    assert confirmed_list.json()["total"] == 1
    assert confirmed_list.json()["items"][0]["status"] == "confirmed"
