from datetime import UTC, datetime, timedelta

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


# ---------------------------------------------------------------------------
# 组 10.7 加固：导出包取回端点（admin-only + 租户归属 + 过期 404）
# ---------------------------------------------------------------------------


def test_customer_admin_can_fetch_own_export_package_only():
    from app import main

    tenant = "tenant-commercial-package"
    other = "tenant-commercial-package-other"
    main.commercial_repository.ensure_test_tenant(tenant, owner_id="owner-1", admins={"admin-1"})
    # 他租户也**登记在册**（否则会先因"租户不存在"404，测不到导出包的归属比对）。
    main.commercial_repository.ensure_test_tenant(other, owner_id="owner-2", admins={"admin-9"})
    now = datetime(2026, 9, 14, 8, 0, tzinfo=UTC)
    package = main.commercial_lifecycle.store_export_package(
        tenant, "job-api-1", created_at=now, expires_at=now + timedelta(days=7)
    )
    admin = headers(user="admin-1", tenant=tenant)

    response = client.get(f"/api/v1/commercial/exports/{package.id}", headers=admin)

    assert response.status_code == 200
    body = response.json()
    assert body["package_id"] == package.id
    assert body["tenant_id"] == tenant
    assert body["created_at"] and body["expires_at"]
    assert body["payload"]["tenant_id"] == tenant
    assert "password" not in body["payload"]
    # 普通员工：403（不因"是管理员创建"而放行）。
    denied = client.get(
        f"/api/v1/commercial/exports/{package.id}",
        headers=headers(role="employee", user="admin-1", tenant=tenant),
    )
    assert denied.status_code == 403
    # 他租户管理员取同一个包：404「导出包不存在」（不泄露他租户资源存在性）。
    foreign = client.get(
        f"/api/v1/commercial/exports/{package.id}", headers=headers(user="admin-9", tenant=other)
    )
    assert foreign.status_code == 404
    # 不存在的包号：同样是 404。
    missing = client.get("/api/v1/commercial/exports/export-not-exist", headers=admin)
    assert missing.status_code == 404


def test_expired_export_package_is_rejected_with_explicit_detail():
    from app import main

    tenant = "tenant-commercial-package-expired"
    main.commercial_repository.ensure_test_tenant(tenant, owner_id="owner-1", admins={"admin-1"})
    past = datetime(2026, 9, 1, 8, 0, tzinfo=UTC)
    package = main.commercial_lifecycle.store_export_package(
        tenant, "job-api-expired", created_at=past, expires_at=past + timedelta(days=7)
    )

    response = client.get(
        f"/api/v1/commercial/exports/{package.id}", headers=headers(user="admin-1", tenant=tenant)
    )

    assert response.status_code == 404
    # 过期与不存在同为 404，但文案可区分（全仓无 410 先例 ⇒ 不新引入状态码）。
    assert "已过期" in response.json()["detail"]
