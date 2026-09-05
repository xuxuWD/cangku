from fastapi.testclient import TestClient
from concurrent.futures import ThreadPoolExecutor

from app.main import app


client = TestClient(app)


def headers(role: str = "employee", user_id: str = "u-1", tenant_id: str = "t-1") -> dict[str, str]:
    return {
        "X-Tenant-Id": tenant_id,
        "X-User-Id": user_id,
        "X-User-Role": role,
    }


def test_health_endpoint_reports_service_ready() -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "company-workbench"}


def test_employee_can_create_low_risk_task() -> None:
    response = client.post(
        "/api/v1/tasks",
        headers=headers(),
        json={
            "title": "整理本周自媒体选题",
            "employee_key": "content-operator",
            "risk_level": "low",
            "budget": 2.5,
            "idempotency_key": "weekly-topic-001",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "queued"
    assert body["tenant_id"] == "t-1"
    assert body["risk_level"] == "low"
    assert body["audit_count"] == 1


def test_high_risk_task_requires_approval_and_ceo_can_approve() -> None:
    create = client.post(
        "/api/v1/tasks",
        headers=headers(),
        json={
            "title": "提交已审核内容到外部平台",
            "employee_key": "content-operator",
            "risk_level": "high",
            "budget": 10,
            "idempotency_key": "publish-001",
        },
    )

    assert create.status_code == 201
    task = create.json()
    assert task["status"] == "pending_approval"

    approve = client.post(
        f"/api/v1/tasks/{task['id']}/approve",
        headers=headers(role="ceo", user_id="ceo-1"),
    )

    assert approve.status_code == 200
    assert approve.json()["status"] == "queued"
    assert approve.json()["audit_count"] == 2


def test_same_idempotency_key_returns_same_task_without_duplicate_audit() -> None:
    payload = {
        "title": "生成日报摘要",
        "employee_key": "ceo-dashboard",
        "risk_level": "low",
        "budget": 1,
        "idempotency_key": "daily-report-001",
    }

    first = client.post("/api/v1/tasks", headers=headers(), json=payload)
    second = client.post("/api/v1/tasks", headers=headers(), json=payload)

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["audit_count"] == 1


def test_task_data_isolated_between_tenants() -> None:
    create = client.post(
        "/api/v1/tasks",
        headers=headers(tenant_id="t-private"),
        json={
            "title": "私有任务",
            "employee_key": "content-operator",
            "risk_level": "low",
            "budget": 1,
            "idempotency_key": "private-001",
        },
    )
    task_id = create.json()["id"]

    response = client.get(f"/api/v1/tasks/{task_id}", headers=headers(tenant_id="t-other"))

    assert response.status_code == 404


def test_employee_cannot_read_another_employees_task() -> None:
    create = client.post(
        "/api/v1/tasks",
        headers=headers(user_id="owner"),
        json={
            "title": "仅创建人可见",
            "employee_key": "content-operator",
            "risk_level": "low",
            "budget": 1,
            "idempotency_key": "owner-only-001",
        },
    )

    response = client.get(
        f"/api/v1/tasks/{create.json()['id']}",
        headers=headers(user_id="other"),
    )

    assert response.status_code == 404


def test_same_idempotency_key_with_different_payload_is_rejected() -> None:
    payload = {
        "title": "原始任务",
        "employee_key": "content-operator",
        "risk_level": "low",
        "budget": 1,
        "idempotency_key": "conflict-001",
    }
    client.post("/api/v1/tasks", headers=headers(), json=payload)

    changed = {**payload, "budget": 99}
    response = client.post("/api/v1/tasks", headers=headers(), json=changed)

    assert response.status_code == 409


def test_production_mode_does_not_trust_development_headers() -> None:
    from app import main

    original = main.settings.env
    main.settings.env = "production"
    try:
        response = client.get("/api/v1/tasks/task-does-not-matter", headers=headers(role="super_admin"))
    finally:
        main.settings.env = original

    assert response.status_code == 401


def test_production_mode_accepts_only_signed_access_token() -> None:
    from app import main
    from app.auth import create_access_token
    from app.domain import UserContext

    original_env, original_secret = main.settings.env, main.settings.auth_secret
    main.settings.env = "production"
    main.settings.auth_secret = "test-secret"
    try:
        token = create_access_token(UserContext("t-signed", "u-signed", "employee"), "test-secret")
        response = client.get(
            "/api/v1/tasks/missing",
            headers={"Authorization": f"Bearer {token}", "X-Tenant-Id": "forged"},
        )
    finally:
        main.settings.env, main.settings.auth_secret = original_env, original_secret

    assert response.status_code == 404


def test_concurrent_approval_allows_only_one_state_transition() -> None:
    create = client.post(
        "/api/v1/tasks",
        headers=headers(),
        json={
            "title": "并发审批",
            "employee_key": "content-operator",
            "risk_level": "high",
            "budget": 2,
            "idempotency_key": "concurrent-approve-001",
        },
    )
    task_id = create.json()["id"]

    def approve() -> int:
        return client.post(
            f"/api/v1/tasks/{task_id}/approve",
            headers=headers(role="ceo", user_id="ceo-concurrent"),
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: approve(), range(2)))

    assert sorted(results) == [200, 409]
