from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def headers(role="customer_admin", user="admin-1", tenant="tenant-commercial"):
    return {"X-Tenant-Id": tenant, "X-User-Id": user, "X-User-Role": role}


def test_customer_admin_can_view_tenant_summary_and_request_export():
    from app import main

    main.commercial_repository.ensure_test_tenant("tenant-commercial", owner_id="owner-1", admins={"admin-1"})
    summary = client.get("/api/v1/commercial/tenant", headers=headers())
    assert summary.status_code == 200
    assert summary.json()["tenant_id"] == "tenant-commercial"

    export = client.post("/api/v1/commercial/exports", headers=headers())
    assert export.status_code == 202
    assert export.json()["status"] == "queued"


def test_employee_cannot_request_delete_and_client_cannot_override_tenant():
    from app import main

    main.commercial_repository.ensure_test_tenant("tenant-commercial", owner_id="owner-1", admins={"admin-1"})
    denied = client.post("/api/v1/commercial/deletion-requests", headers=headers(role="employee"))
    assert denied.status_code == 403
    forged = client.get(
        "/api/v1/commercial/tenant?tenant_id=other-tenant",
        headers=headers(),
    )
    assert forged.status_code == 200
    assert forged.json()["tenant_id"] == "tenant-commercial"


def test_usage_endpoint_returns_server_calculated_values_only():
    from app import main
    from app.commercial.usage import UsageEntry

    main.commercial_repository.ensure_test_tenant("tenant-commercial", owner_id="owner-1", admins={"admin-1"})
    main.commercial_usage.append(UsageEntry("api-1", "tenant-commercial", 3, 25))
    response = client.get("/api/v1/commercial/usage?tenant_id=forged", headers=headers())
    assert response.status_code == 200
    assert response.json()["tenant_id"] == "tenant-commercial"
    assert response.json()["units"] >= 3


def test_customer_admin_can_cancel_delete_request_and_return_active():
    from app import main

    main.commercial_repository.ensure_test_tenant(
        "tenant-commercial-cancel", owner_id="owner-1", admins={"admin-1"}
    )
    owner = headers(user="owner-1", tenant="tenant-commercial-cancel")
    delete = client.post("/api/v1/commercial/deletion-requests", headers=owner)
    assert delete.status_code == 202
    assert delete.json()["status"] == "cooling_down"

    cancel = client.post("/api/v1/commercial/deletion-requests/cancel", headers=owner)

    assert cancel.status_code == 200
    assert cancel.json()["status"] == "cancelled"
    summary = client.get("/api/v1/commercial/tenant", headers=owner)
    assert summary.json()["status"] == "active"


def test_cancel_without_pending_request_returns_409_and_employee_403():
    from app import main

    main.commercial_repository.ensure_test_tenant(
        "tenant-commercial-cancel-none", owner_id="owner-1", admins={"admin-1"}
    )
    owner = headers(user="owner-1", tenant="tenant-commercial-cancel-none")

    nothing = client.post("/api/v1/commercial/deletion-requests/cancel", headers=owner)
    assert nothing.status_code == 409

    denied = client.post(
        "/api/v1/commercial/deletion-requests/cancel",
        headers=headers(role="employee", user="owner-1", tenant="tenant-commercial-cancel-none"),
    )
    assert denied.status_code == 403
