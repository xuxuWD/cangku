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


def test_task_lifecycle_publishes_events_once() -> None:
    from app import main

    create = client.post(
        "/api/v1/tasks",
        headers=headers(),
        json={
            "title": "事件任务",
            "employee_key": "content-operator",
            "risk_level": "high",
            "budget": 2,
            "idempotency_key": "events-001",
        },
    )
    task_id = create.json()["id"]
    client.post(
        "/api/v1/tasks",
        headers=headers(),
        json={
            "title": "事件任务",
            "employee_key": "content-operator",
            "risk_level": "high",
            "budget": 2,
            "idempotency_key": "events-001",
        },
    )
    client.post(f"/api/v1/tasks/{task_id}/approve", headers=headers(role="ceo", user_id="ceo-events"))

    events = main.event_bus.read("test", after_sequence=0)
    matching = [event for event in events if event.aggregate_id == task_id]
    assert [event.action for event in matching] == ["task.created", "task.approved"]


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


def test_super_admin_can_list_and_replay_dead_letter() -> None:
    from app import main
    from app.dead_letters import DeadLetterStore
    from app.events import EventEnvelope
    from datetime import UTC, datetime

    main.dead_letter_store = DeadLetterStore(main.event_bus)
    main.dead_letter_store.record(
        EventEnvelope(
            event_id="dead-1", tenant_id="t-1", aggregate_type="task", aggregate_id="task-1",
            version=1, sequence=999, dedupe_key="task-1:failed:1", action="task.failed",
            occurred_at=datetime.now(UTC), payload={"reason": "timeout"},
        ),
        "timeout",
    )

    listed = client.get("/api/v1/dead-letters", headers=headers(role="super_admin", user_id="admin"))
    assert listed.status_code == 200
    assert listed.json()[0]["event_id"] == "dead-1"

    replay = client.post("/api/v1/dead-letters/dead-1/replay", headers=headers(role="super_admin", user_id="admin"))
    assert replay.status_code == 200
    assert replay.json() == {"status": "replayed", "event_id": "dead-1"}


def test_employee_cannot_list_dead_letters() -> None:
    response = client.get("/api/v1/dead-letters", headers=headers())

    assert response.status_code == 403


def test_collaboration_dynamics_are_filtered_by_task_access() -> None:
    from app import main

    own = client.post(
        "/api/v1/tasks",
        headers=headers(user_id="dynamic-owner"),
        json={
            "title": "自己的动态",
            "employee_key": "content-operator",
            "risk_level": "low",
            "budget": 1,
            "idempotency_key": "dynamic-own-001",
        },
    )
    other = client.post(
        "/api/v1/tasks",
        headers=headers(user_id="dynamic-other"),
        json={
            "title": "他人的动态",
            "employee_key": "content-operator",
            "risk_level": "low",
            "budget": 1,
            "idempotency_key": "dynamic-other-001",
        },
    )

    employee_view = client.get(
        "/api/v1/collaboration-dynamics",
        headers=headers(user_id="dynamic-owner"),
    )
    assert employee_view.status_code == 200
    assert {item["aggregate_id"] for item in employee_view.json()} >= {own.json()["id"]}
    assert other.json()["id"] not in {item["aggregate_id"] for item in employee_view.json()}

    ceo_view = client.get(
        "/api/v1/collaboration-dynamics",
        headers=headers(role="ceo", user_id="dynamic-ceo"),
    )
    assert ceo_view.status_code == 200
    assert other.json()["id"] in {item["aggregate_id"] for item in ceo_view.json()}


def test_super_admin_can_configure_role_knowledge_access() -> None:
    response = client.put(
        "/api/v1/knowledge-access/roles/content-operator",
        headers=headers(role="super_admin", user_id="admin-knowledge"),
        json={"knowledge_base_ids": ["kb-content", "kb-brand", "kb-content"]},
    )

    assert response.status_code == 200
    assert response.json() == {
        "binding_type": "role",
        "binding_key": "content-operator",
        "knowledge_base_ids": ["kb-brand", "kb-content"],
    }

    listed = client.get(
        "/api/v1/knowledge-access/roles/content-operator",
        headers=headers(role="super_admin", user_id="admin-knowledge"),
    )
    assert listed.status_code == 200
    assert listed.json()["knowledge_base_ids"] == ["kb-brand", "kb-content"]


def test_non_super_admin_cannot_configure_knowledge_access() -> None:
    response = client.put(
        "/api/v1/knowledge-access/agents/content-writer",
        headers=headers(role="ceo", user_id="ceo-knowledge"),
        json={"knowledge_base_ids": ["kb-content"]},
    )

    assert response.status_code == 403


def test_super_admin_can_read_knowledge_access_audits() -> None:
    response = client.get(
        "/api/v1/knowledge-access/audits?limit=10",
        headers=headers(role="super_admin", user_id="admin-knowledge"),
    )

    assert response.status_code == 200
    assert response.json()[0]["binding_key"] == "content-operator"
    assert response.json()[0]["actor_id"] == "admin-knowledge"
