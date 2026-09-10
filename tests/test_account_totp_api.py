"""动态口令（TOTP）接口层测试：登录响应、受限令牌、绑定与重置。"""

import base64
import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app import main
from app.accounts.rate_limit import InMemoryLoginAttemptStore, LoginRateLimiter
from app.accounts.repository import InMemoryAccountRepository
from app.accounts.service import AccountService
from app.accounts.totp import current_step, hotp
from app.audit.service import AuditService
from app.audit.store import InMemoryAuditStore
from app.auth import create_access_token, verify_access_token
from app.domain import UserContext
from app.main import app

client = TestClient(app)

BOOTSTRAP = "bootstrap-secret-value"
PASSWORD = "correct-horse-battery"
SECRET = "s" * 40


def build_service(*, require_admin_totp: bool) -> AccountService:
    return AccountService(
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
        require_admin_totp=require_admin_totp,
    )


def install(monkeypatch, *, require_admin_totp: bool) -> AccountService:
    service = build_service(require_admin_totp=require_admin_totp)
    monkeypatch.setattr(main, "account_service", service)
    monkeypatch.setattr(main.settings, "auth_secret", SECRET)
    monkeypatch.setattr(main.settings, "session_ttl_seconds", 900)
    monkeypatch.setattr(main.settings, "totp_enrollment_ttl_seconds", 300)
    monkeypatch.setattr(main.settings, "require_admin_totp", require_admin_totp)
    return service


@pytest.fixture
def accounts(monkeypatch) -> AccountService:
    return install(monkeypatch, require_admin_totp=True)


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def register_admin(phone: str = "13800000001") -> dict[str, object]:
    response = client.post(
        "/api/v1/auth/registrations",
        json={
            "phone": phone,
            "password": PASSWORD,
            "position": "内容运营",
            "full_name": "张三",
            "tenant_id": "t-1",
            "bootstrap_token": BOOTSTRAP,
        },
    )
    assert response.status_code == 201
    return response.json()


def login(phone: str = "13800000001", *, totp_code: str | None = None):
    body: dict[str, object] = {"phone": phone, "password": PASSWORD}
    if totp_code is not None:
        body["totp_code"] = totp_code
    return client.post("/api/v1/auth/sessions", json=body)


def start_enrollment(token: str) -> str:
    response = client.post("/api/v1/auth/me/totp", headers=bearer(token))

    assert response.status_code == 200
    body = response.json()
    assert body["digest"] == "SHA1"
    assert body["digits"] == "6"
    assert body["period"] == "30"
    assert body["otpauth_uri"].startswith("otpauth://totp/")
    return body["secret"]


def confirm_enrollment(token: str, secret: str) -> None:
    response = client.post(
        "/api/v1/auth/me/totp/confirmation",
        headers=bearer(token),
        json={"totp_code": hotp(secret, current_step(datetime.now(UTC)))},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "confirmed"}


def decode_payload(token: str) -> dict[str, object]:
    encoded = token.split(".", 1)[0]
    return json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))


def enroll_and_confirm(token: str) -> str:
    secret = start_enrollment(token)
    confirm_enrollment(token, secret)
    return secret


def test_missing_code_is_rejected(accounts: AccountService) -> None:
    register_admin()
    token = login().json()["access_token"]
    enroll_and_confirm(token)

    response = login()

    assert response.status_code == 401
    assert response.json()["detail"] == "需要动态验证码"


def test_wrong_code_is_rejected(accounts: AccountService) -> None:
    register_admin()
    token = login().json()["access_token"]
    secret = enroll_and_confirm(token)

    response = login(totp_code=hotp(secret, current_step(datetime.now(UTC)) + 5))

    assert response.status_code == 401
    assert response.json()["detail"] == "动态验证码不正确"


def test_valid_code_returns_full_session(accounts: AccountService) -> None:
    register_admin()
    token = login().json()["access_token"]
    secret = enroll_and_confirm(token)

    response = login(totp_code=hotp(secret, current_step(datetime.now(UTC)) + 1))

    assert response.status_code == 200
    body = response.json()
    assert body["scope"] == "full"
    assert body["access_token"]
    assert body["expires_in"] == 900
    assert verify_access_token(body["access_token"], SECRET).scope == "full"


def test_unenrolled_admin_receives_restricted_session(accounts: AccountService) -> None:
    register_admin()

    response = login()

    assert response.status_code == 200
    body = response.json()
    assert body["scope"] == "totp_enrollment"
    assert body["expires_in"] <= 300
    assert verify_access_token(body["access_token"], SECRET).scope == "totp_enrollment"


def test_restricted_token_is_blocked_on_protected_routes(accounts: AccountService) -> None:
    register_admin()
    token = login().json()["access_token"]

    response = client.get("/api/v1/auth/registrations", headers=bearer(token))

    assert response.status_code == 403
    assert response.json()["detail"] == "账号需要先完成动态口令绑定"


def test_restricted_token_can_complete_enrollment(accounts: AccountService) -> None:
    register_admin()
    token = login().json()["access_token"]

    secret = start_enrollment(token)
    confirm_enrollment(token, secret)

    response = login(totp_code=hotp(secret, current_step(datetime.now(UTC)) + 1))

    assert response.status_code == 200
    assert response.json()["scope"] == "full"


def test_reset_totp_endpoint_guards_role_and_missing_account(monkeypatch) -> None:
    install(monkeypatch, require_admin_totp=False)
    admin = register_admin()
    admin_token = login().json()["access_token"]
    enroll_and_confirm(admin_token)

    employee_token = create_access_token(
        UserContext("t-1", "acct-x", "employee"), SECRET, ttl_seconds=900
    )
    forbidden = client.post(
        "/api/v1/auth/accounts/acct-x/totp-reset", headers=bearer(employee_token)
    )
    assert forbidden.status_code == 403

    missing = client.post(
        "/api/v1/auth/accounts/acct-missing/totp-reset", headers=bearer(admin_token)
    )
    assert missing.status_code == 404

    reset = client.post(
        f"/api/v1/auth/accounts/{admin['account_id']}/totp-reset", headers=bearer(admin_token)
    )
    assert reset.status_code == 200
    assert reset.json() == {"status": "reset"}
    assert login().status_code == 200


def test_totp_secret_never_leaks_into_responses_tokens_or_audits(
    accounts: AccountService,
) -> None:
    register_admin()
    restricted_token = login().json()["access_token"]
    secret = enroll_and_confirm(restricted_token)

    session = login(totp_code=hotp(secret, current_step(datetime.now(UTC)) + 1))
    rendered = json.dumps(session.json())

    assert session.status_code == 200
    assert "totp_secret" not in rendered
    assert secret not in rendered
    assert "totp_secret" not in decode_payload(restricted_token)
    assert "totp_secret" not in decode_payload(session.json()["access_token"])
    assert secret not in json.dumps(decode_payload(session.json()["access_token"]))

    audits = accounts.audit.store.list_recent(None, limit=200)
    audit_text = str(
        [(item.action.value, item.detail, item.phone_masked, item.target_id) for item in audits]
    )
    assert secret not in audit_text
