from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)
HEADERS = {"X-Tenant-Id": "alpha-tenant", "X-User-Id": "alpha-user", "X-User-Role": "employee"}


def test_ten_repeated_content_delivery_flows_are_idempotent_and_exportable():
    for index in range(10):
        payload = {
            "topic": f"Alpha 选题 {index}",
            "sources": [{"url": "https://example.com/source", "excerpt": "脱敏业务素材摘录"}],
            "knowledge_references": [],
            "idempotency_key": f"alpha-{index}",
        }
        created = client.post("/api/v1/content-tasks", headers=HEADERS, json=payload)
        assert created.status_code == 201
        replay = client.post("/api/v1/content-tasks", headers=HEADERS, json=payload)
        assert replay.status_code == 200
        assert replay.json()["task_id"] == created.json()["task_id"]
        task_id = created.json()["task_id"]
        assert created.json()["status"] == "reviewing"
        updated = client.put(
            f"/api/v1/content-tasks/{task_id}/draft", headers=HEADERS,
            json={"revision": 1, "title": f"已确认标题 {index}", "summary": "摘要", "body_markdown": "正文", "image_suggestions": []},
        )
        assert updated.status_code == 200
        confirmed = client.post(f"/api/v1/content-tasks/{task_id}/confirmation", headers=HEADERS, json={"revision": 2})
        assert confirmed.status_code == 200
        exported = client.get(f"/api/v1/content-tasks/{task_id}/export.md", headers=HEADERS)
        assert exported.status_code == 200
        assert f"已确认标题 {index}" in exported.text
