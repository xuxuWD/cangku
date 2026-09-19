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


# ---------------------------------------------------------------------------
# B-1（2026-09-19）：列出本租户导出包（契约「GET /api/v1/commercial/exports」）
# 为什么需要它：取回端点要 `package_id`，而申请响应与作业视图都不携带 ⇒ 没有列表时
# 客户端**无法发现包号**，取回能力实际不可用（本轮补链）。
# ---------------------------------------------------------------------------


def test_list_export_packages_is_admin_only_scoped_and_paginated():
    from app import main

    tenant = "tenant-commercial-list"
    other = "tenant-commercial-list-other"
    main.commercial_repository.ensure_test_tenant(tenant, owner_id="owner-1", admins={"admin-1"})
    main.commercial_repository.ensure_test_tenant(other, owner_id="owner-2", admins={"admin-9"})
    now = datetime(2026, 9, 19, 8, 0, tzinfo=UTC)
    first = main.commercial_lifecycle.store_export_package(
        tenant, "job-api-list-1", created_at=now, expires_at=now + timedelta(days=7)
    )
    second = main.commercial_lifecycle.store_export_package(
        tenant, "job-api-list-2", created_at=now + timedelta(minutes=1), expires_at=now + timedelta(days=7)
    )
    # 他租户的包更新 ⇒ 若租户过滤缺失，它必然排在首位（可构造的反假探针）。
    main.commercial_lifecycle.store_export_package(
        other, "job-api-list-3", created_at=now + timedelta(minutes=2), expires_at=now + timedelta(days=7)
    )
    admin = headers(user="admin-1", tenant=tenant)

    response = client.get("/api/v1/commercial/exports", headers=admin)

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2 and body["limit"] == 50 and body["offset"] == 0
    assert [item["package_id"] for item in body["items"]] == [second.id, first.id]
    # 列表是元数据面：不含载荷，字段集固定。
    assert set(body["items"][0]) == {"package_id", "tenant_id", "job_id", "created_at", "expires_at"}
    assert {item["tenant_id"] for item in body["items"]} == {tenant}

    page = client.get("/api/v1/commercial/exports?limit=1&offset=1", headers=admin)
    assert [item["package_id"] for item in page.json()["items"]] == [first.id]
    assert page.json()["total"] == 2  # 计数不受分页影响

    # 分页参数越界 / 非法 ⇒ 422（不静默夹取）。
    assert client.get("/api/v1/commercial/exports?limit=0", headers=admin).status_code == 422
    assert client.get("/api/v1/commercial/exports?limit=201", headers=admin).status_code == 422
    assert client.get("/api/v1/commercial/exports?offset=-1", headers=admin).status_code == 422

    # 普通员工：403（不因「同租户」而放行）。
    denied = client.get(
        "/api/v1/commercial/exports", headers=headers(role="employee", user="admin-1", tenant=tenant)
    )
    assert denied.status_code == 403

    # 他租户管理员：只看到自己租户的包（此处为空）。
    foreign = client.get("/api/v1/commercial/exports", headers=headers(user="admin-9", tenant=other))
    assert foreign.status_code == 200
    assert [item["job_id"] for item in foreign.json()["items"]] == ["job-api-list-3"]


def test_list_export_packages_includes_expired_rows_until_purged():
    from app import main

    tenant = "tenant-commercial-list-expired"
    main.commercial_repository.ensure_test_tenant(tenant, owner_id="owner-1", admins={"admin-1"})
    past = datetime(2026, 9, 1, 8, 0, tzinfo=UTC)
    expired = main.commercial_lifecycle.store_export_package(
        tenant, "job-api-expired-list", created_at=past, expires_at=past + timedelta(days=7)
    )
    admin = headers(user="admin-1", tenant=tenant)

    listed = client.get("/api/v1/commercial/exports", headers=admin)
    fetched = client.get(f"/api/v1/commercial/exports/{expired.id}", headers=admin)

    assert [item["package_id"] for item in listed.json()["items"]] == [expired.id]
    # 列表可见 ≠ 可取回：过期包取回仍 404（列表与取回的口径差**由 expires_at 表达**）。
    assert fetched.status_code == 404 and "已过期" in fetched.json()["detail"]


# ---------------------------------------------------------------------------
# B-3（2026-09-19）：删除确认（记录确认人）—— admin-only、冷静期、最终导出、审计
# ---------------------------------------------------------------------------


def test_customer_admin_can_confirm_deletion_with_context():
    from app import main

    tenant = "tenant-commercial-confirm"
    main.commercial_repository.ensure_test_tenant(tenant, owner_id="owner-1", admins={"admin-1"})
    delete = client.post("/api/v1/commercial/deletion-requests", headers=headers(user="admin-1", tenant=tenant))
    assert delete.status_code == 202
    job_id = delete.json()["job_id"]

    # 未完成最终导出 ⇒ 确认被拒（读取失败路径，诚实 409/403 而非静默放行）。
    no_export = client.post(f"/api/v1/commercial/deletion-requests/{job_id}/confirm", headers=headers(user="admin-1", tenant=tenant))
    assert no_export.status_code == 409

    # 先用 API 直接落一个导出包（等价 worker「完成最终导出并置 final_exported」）。
    main.commercial_lifecycle.mark_final_exported(job_id)

    confirmed = client.post(
        f"/api/v1/commercial/deletion-requests/{job_id}/confirm",
        headers=headers(user="admin-1", tenant=tenant),
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["confirmed_by"] == "admin-1"
    assert confirmed.json()["status"] == "cooling_down"  # 确认不改状态：仍待执行

    # 非管理员：403
    denied = client.post(
        f"/api/v1/commercial/deletion-requests/{job_id}/confirm",
        headers=headers(role="employee", user="admin-1", tenant=tenant),
    )
    assert denied.status_code == 403

    # 他租户：404（不泄露他租户是否存在删除作业）
    foreign = client.post(
        f"/api/v1/commercial/deletion-requests/{job_id}/confirm",
        headers=headers(user="admin-9", tenant="tenant-commercial-confirm-other"),
    )
    assert foreign.status_code in (403, 404)
