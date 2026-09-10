import pytest
from fastapi.testclient import TestClient

from app import main
from app.accounts.models import SUPER_ADMIN_ROLE
from app.accounts.rate_limit import InMemoryLoginAttemptStore, LoginRateLimiter
from app.accounts.repository import InMemoryAccountRepository
from app.accounts.service import AccountService
from app.audit.service import AuditService
from app.audit.store import InMemoryAuditStore
from app.main import app

client = TestClient(app)

BOOTSTRAP = "bootstrap-secret-value"
PASSWORD = "correct-horse-battery"
SECRET = "s" * 40


@pytest.fixture
def accounts(monkeypatch) -> AccountService:
    service = AccountService(
        InMemoryAccountRepository(),
        bootstrap_token=BOOTSTRAP,
        audit=AuditService(InMemoryAuditStore()),
        login_limiter=LoginRateLimiter(
            InMemoryLoginAttemptStore(),
            secret="s" * 40,
            max_failures=5,
            window_seconds=300,
            lock_seconds=900,
        ),
    )
    monkeypatch.setattr(main, "account_service", service)
    monkeypatch.setattr(main.settings, "auth_secret", SECRET)
    monkeypatch.setattr(main.settings, "session_ttl_seconds", 900)
    return service


def registration_body(phone: str = "13800000001", **overrides) -> dict[str, object]:
    body = {
        "phone": phone,
        "password": PASSWORD,
        "position": "内容运营",
        "full_name": "张三",
    }
    body.update(overrides)
    return body


def register_admin(accounts: AccountService) -> dict[str, object]:
    response = client.post(
        "/api/v1/auth/registrations",
        json=registration_body(tenant_id="t-1", bootstrap_token=BOOTSTRAP),
    )
    assert response.status_code == 201
    return response.json()


def login(phone: str, password: str = PASSWORD) -> dict[str, object]:
    return client.post("/api/v1/auth/sessions", json={"phone": phone, "password": password})


def test_first_registration_without_bootstrap_token_is_forbidden(accounts: AccountService) -> None:
    response = client.post("/api/v1/auth/registrations", json=registration_body(tenant_id="t-1"))

    assert response.status_code == 403


def test_first_registration_creates_approved_admin(accounts: AccountService) -> None:
    body = register_admin(accounts)

    assert body["status"] == "approved"
    assert body["role"] == SUPER_ADMIN_ROLE
    assert body["tenant_id"] == "t-1"
    assert "password" not in body
    assert "password_hash" not in body
    assert BOOTSTRAP not in str(body)


def test_registration_response_masks_phone(accounts: AccountService) -> None:
    body = register_admin(accounts)

    assert body["phone"] == "138****0001"


def test_duplicate_phone_returns_conflict(accounts: AccountService) -> None:
    register_admin(accounts)

    response = client.post(
        "/api/v1/auth/registrations", json=registration_body(tenant_id="t-1", bootstrap_token=BOOTSTRAP)
    )

    assert response.status_code == 409


def test_short_password_is_rejected_by_schema(accounts: AccountService) -> None:
    response = client.post("/api/v1/auth/registrations", json=registration_body(password="short"))

    assert response.status_code == 422


def test_pending_account_cannot_login_then_can_after_approval(accounts: AccountService) -> None:
    admin = register_admin(accounts)
    pending = client.post("/api/v1/auth/registrations", json=registration_body("13800000002")).json()

    assert login("13800000002").status_code == 401

    admin_headers = {
        "X-Tenant-Id": "t-1",
        "X-User-Id": admin["account_id"],
        "X-User-Role": SUPER_ADMIN_ROLE,
    }
    listed = client.get("/api/v1/auth/registrations", headers=admin_headers)
    assert listed.status_code == 200
    assert [item["account_id"] for item in listed.json()] == [pending["account_id"]]

    approved = client.post(
        f"/api/v1/auth/registrations/{pending['account_id']}/approval",
        headers=admin_headers,
        json={"role": "employee", "tenant_id": "t-1"},
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"

    session = login("13800000002")
    assert session.status_code == 200
    assert session.json()["role"] == "employee"
    assert session.json()["tenant_id"] == "t-1"
    assert session.json()["expires_in"] == 900


def test_rejection_keeps_account_locked(accounts: AccountService) -> None:
    admin = register_admin(accounts)
    pending = client.post("/api/v1/auth/registrations", json=registration_body("13800000002")).json()
    admin_headers = {
        "X-Tenant-Id": "t-1",
        "X-User-Id": admin["account_id"],
        "X-User-Role": SUPER_ADMIN_ROLE,
    }

    rejected = client.post(
        f"/api/v1/auth/registrations/{pending['account_id']}/rejection",
        headers=admin_headers,
        json={"reason": "资料不完整"},
    )

    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    assert login("13800000002").status_code == 401


def test_non_admin_cannot_read_registrations(accounts: AccountService) -> None:
    register_admin(accounts)

    response = client.get(
        "/api/v1/auth/registrations",
        headers={"X-Tenant-Id": "t-1", "X-User-Id": "acct-x", "X-User-Role": "employee"},
    )

    assert response.status_code == 403


def test_session_token_authorizes_requests_and_overrides_forged_headers(accounts: AccountService) -> None:
    register_admin(accounts)
    # 注册响应中的 phone 已脱敏，登录必须使用真实手机号。
    token = login("13800000001", PASSWORD).json()["access_token"]

    response = client.get(
        "/api/v1/auth/registrations",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Tenant-Id": "forged-tenant",
            "X-User-Id": "forged-user",
            "X-User-Role": "employee",
        },
    )

    assert response.status_code == 200


def test_login_with_wrong_password_is_unauthorized(accounts: AccountService) -> None:
    register_admin(accounts)

    assert login("13800000001", "wrong-horse-battery").status_code == 401


def test_change_own_password_requires_current_password(accounts: AccountService) -> None:
    admin = register_admin(accounts)
    headers = {"X-Tenant-Id": "t-1", "X-User-Id": admin["account_id"], "X-User-Role": SUPER_ADMIN_ROLE}

    wrong = client.put(
        "/api/v1/auth/me/password",
        headers=headers,
        json={"old_password": "wrong-horse-battery", "new_password": "brand-new-passphrase"},
    )
    assert wrong.status_code == 401

    updated = client.put(
        "/api/v1/auth/me/password",
        headers=headers,
        json={"old_password": PASSWORD, "new_password": "brand-new-passphrase"},
    )
    assert updated.status_code == 200
    # 注册响应中的 phone 已脱敏，登录必须使用真实手机号。
    assert login("13800000001", "brand-new-passphrase").status_code == 200
    assert login("13800000001", PASSWORD).status_code == 401


def test_admin_can_reset_password_and_employee_cannot(accounts: AccountService) -> None:
    admin = register_admin(accounts)
    other = client.post("/api/v1/auth/registrations", json=registration_body("13800000002")).json()
    admin_headers = {
        "X-Tenant-Id": "t-1",
        "X-User-Id": admin["account_id"],
        "X-User-Role": SUPER_ADMIN_ROLE,
    }
    client.post(
        f"/api/v1/auth/registrations/{other['account_id']}/approval",
        headers=admin_headers,
        json={"role": "employee", "tenant_id": "t-1"},
    )

    forbidden = client.post(
        f"/api/v1/auth/accounts/{other['account_id']}/password",
        headers={"X-Tenant-Id": "t-1", "X-User-Id": other["account_id"], "X-User-Role": "employee"},
        json={"new_password": "another-passphrase"},
    )
    assert forbidden.status_code == 403

    reset = client.post(
        f"/api/v1/auth/accounts/{other['account_id']}/password",
        headers=admin_headers,
        json={"new_password": "another-passphrase"},
    )
    assert reset.status_code == 200
    assert login("13800000002", "another-passphrase").status_code == 200


def test_reset_unknown_account_returns_not_found(accounts: AccountService) -> None:
    admin = register_admin(accounts)

    response = client.post(
        "/api/v1/auth/accounts/acct-missing/password",
        headers={"X-Tenant-Id": "t-1", "X-User-Id": admin["account_id"], "X-User-Role": SUPER_ADMIN_ROLE},
        json={"new_password": "another-passphrase"},
    )

    assert response.status_code == 404


def test_session_endpoint_requires_configured_secret(monkeypatch, accounts: AccountService) -> None:
    admin = register_admin(accounts)
    monkeypatch.setattr(main.settings, "auth_secret", "")

    assert login(admin["phone"]).status_code == 503


def test_production_mode_rejects_header_only_identity(monkeypatch, accounts: AccountService) -> None:
    register_admin(accounts)
    monkeypatch.setattr(main.settings, "env", "production")

    response = client.get(
        "/api/v1/auth/registrations",
        headers={"X-Tenant-Id": "t-1", "X-User-Id": "acct-admin", "X-User-Role": SUPER_ADMIN_ROLE},
    )

    assert response.status_code == 401


def test_invalid_status_filter_is_rejected(accounts: AccountService) -> None:
    admin = register_admin(accounts)

    response = client.get(
        "/api/v1/auth/registrations?status=bogus",
        headers={"X-Tenant-Id": "t-1", "X-User-Id": admin["account_id"], "X-User-Role": SUPER_ADMIN_ROLE},
    )

    assert response.status_code == 400


def test_approval_of_unknown_account_returns_not_found(accounts: AccountService) -> None:
    admin = register_admin(accounts)

    response = client.post(
        "/api/v1/auth/registrations/acct-missing/approval",
        headers={"X-Tenant-Id": "t-1", "X-User-Id": admin["account_id"], "X-User-Role": SUPER_ADMIN_ROLE},
        json={"role": "employee", "tenant_id": "t-1"},
    )

    assert response.status_code == 404


def test_locked_account_returns_429_on_login(accounts: AccountService) -> None:
    # 调低阈值，避免与既有用例的失败次数叠加造成干扰
    accounts.login_limiter.max_failures = 3
    register_admin(accounts)

    for _index in range(3):
        assert login("13800000001", "wrong-horse-battery").status_code == 401

    locked = login("13800000001", PASSWORD)

    assert locked.status_code == 429
    assert "稍后再试" in locked.json()["detail"]
