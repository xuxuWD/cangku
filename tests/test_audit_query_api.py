"""审计查询接口：权限矩阵、参数校验、租户隔离与响应形状。"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app import main
from app.audit.models import AuditAction, build_record
from app.audit.service import AuditService
from app.audit.store import InMemoryAuditStore
from app.main import app

client = TestClient(app)
BASE = datetime(2026, 9, 11, 8, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    store = InMemoryAuditStore()
    store.append(
        build_record(
            AuditAction.ACCOUNT_LOGIN_SUCCEEDED,
            tenant_id="t-1",
            actor_id="u-1",
            detail={"status": "ok"},
        )
    )
    store.append(
        build_record(
            AuditAction.PLAN_APPROVED,
            tenant_id="t-1",
            actor_id="ceo-1",
            target_type="plan_proposal",
            target_id="p-1",
            detail={"step_count": 2},
        )
    )
    store.append(
        build_record(AuditAction.PLAN_APPROVED, tenant_id="t-2", actor_id="u-2", target_id="p-9")
    )
    audit = AuditService(store)
    monkeypatch.setattr(main, "audit_service", audit)
    return audit


def headers(role: str = "ceo", user_id: str = "ceo-1", tenant_id: str = "t-1") -> dict[str, str]:
    return {"X-Tenant-Id": tenant_id, "X-User-Id": user_id, "X-User-Role": role}


def test_ceil_and_super_admin_can_read_audits() -> None:
    for role in ("ceo", "super_admin"):
        response = client.get("/api/v1/audits", headers=headers(role=role))

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 2
        assert body["limit"] == 50
        assert body["offset"] == 0
        assert [item["action"] for item in body["items"]] == ["plan.approved", "account.login.succeeded"]
        assert set(body["items"][0]) == {
            "record_id",
            "action",
            "actor_id",
            "target_type",
            "target_id",
            "phone_masked",
            "detail",
            "occurred_at",
        }


def test_role_tiers_follow_permission_matrix() -> None:
    """角色分档（**2026-09-20 第 10 轮按矩阵 §3「审计：查询」对齐**）。

    原实现把审计查询收在 `{ceo, super_admin}` 之下 ⇒ `employee` / `department_lead` 一律 `403`，
    与矩阵冲突（矩阵：`employee` ⚠️**仅本人相关** / `department_lead` ✅本租户 / `ceo` ✅ / `super_admin` ✅ / `customer_admin` ❌）。
    本用例原为 `test_requires_login_and_approver_role`（**钉住旧口径**），本轮随实现一并更正；
    逐档细节（含"传他人 `actor_id` ⇒ 403"）见 `tests/test_audit_role_matrix.py`。
    """
    assert client.get("/api/v1/audits").status_code == 401

    employee = client.get("/api/v1/audits", headers=headers(role="employee", user_id="u-1"))
    assert employee.status_code == 200
    assert employee.json()["total"] == 1  # 仅本人相关（t-1 里只有 u-1 的一条）
    assert {item["actor_id"] for item in employee.json()["items"]} == {"u-1"}

    lead = client.get("/api/v1/audits", headers=headers(role="department_lead", user_id="lead-1"))
    assert lead.status_code == 200
    assert lead.json()["total"] == 2  # 本租户全量（不含他租户）

    denied = client.get("/api/v1/audits", headers=headers(role="customer_admin", user_id="cust-1"))
    assert denied.status_code == 403
    assert denied.json()["detail"] == "当前岗位不能查看审计日志"


def test_other_tenant_records_are_invisible() -> None:
    body = client.get("/api/v1/audits", headers=headers(tenant_id="t-3")).json()

    assert body["total"] == 0
    assert body["items"] == []


def test_filters_and_pagination_are_applied() -> None:
    approved = client.get("/api/v1/audits?action=plan.approved", headers=headers()).json()
    assert approved["total"] == 1
    assert approved["items"][0]["target_id"] == "p-1"

    paged = client.get("/api/v1/audits?limit=1&offset=1", headers=headers()).json()
    assert paged["total"] == 2
    assert paged["limit"] == 1
    assert paged["offset"] == 1
    assert len(paged["items"]) == 1

    by_actor = client.get("/api/v1/audits?actor_id=ceo-1", headers=headers()).json()
    assert by_actor["total"] == 1

    by_target = client.get("/api/v1/audits?target_type=plan_proposal&target_id=p-1", headers=headers()).json()
    assert by_target["total"] == 1


def test_multiple_actions_are_accepted() -> None:
    body = client.get(
        "/api/v1/audits?action=plan.approved&action=account.login.succeeded", headers=headers()
    ).json()

    assert body["total"] == 2


def test_time_range_filter_requires_timezone() -> None:
    # 注意：URL 里的 "+00:00" 会被解码成空格，客户端应使用 Z 形式（toISOString）。
    aware = client.get(f"/api/v1/audits?since={BASE.isoformat().replace('+00:00', 'Z')}", headers=headers())
    assert aware.status_code == 200
    assert aware.json()["total"] == 2

    naive = client.get("/api/v1/audits?since=2026-09-11T08:00:00", headers=headers())
    assert naive.status_code == 422

    plus_form = client.get(f"/api/v1/audits?since={BASE.isoformat()}", headers=headers())
    assert plus_form.status_code == 422


def test_invalid_parameters_are_rejected() -> None:
    assert client.get("/api/v1/audits?action=not.an.action", headers=headers()).status_code == 422
    assert client.get("/api/v1/audits?limit=0", headers=headers()).status_code == 422
    assert client.get("/api/v1/audits?limit=201", headers=headers()).status_code == 422
    assert client.get("/api/v1/audits?offset=-1", headers=headers()).status_code == 422


def test_phone_masked_is_returned_when_present() -> None:
    main.audit_service.store.append(
        build_record(
            AuditAction.ACCOUNT_REGISTRATION_REQUESTED,
            tenant_id="t-1",
            phone_masked="138****0000",
            detail={"role": "employee"},
        )
    )

    body = client.get("/api/v1/audits?action=account.registration.requested", headers=headers()).json()

    assert body["items"][0]["phone_masked"] == "138****0000"
    assert body["items"][0]["detail"] == {"role": "employee"}
