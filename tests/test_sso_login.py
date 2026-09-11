"""SSO 服务编排与接口测试（全程离线）。

设计要点：
- token 端点与 jwks 一律通过注入的 transport 假实现；id_token 用 client_secret 做真实 HS256 签名。
- 账号仓储为内存实现；TOTP 用真实 RFC 6238 计算。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app import main
from app.accounts.models import (
    Account,
    AccountStatus,
    LoginFailed,
    TotpInvalid,
)
from app.accounts.passwords import hash_password
from app.accounts.rate_limit import InMemoryLoginAttemptStore, LoginRateLimiter
from app.accounts.repository import InMemoryAccountRepository
from app.accounts.service import AccountService
from app.accounts.sso import SsoConfig, SsoError, SsoNotConfigured
from app.accounts.sso_store import InMemorySsoStateStore, SsoState
from app.accounts.totp import current_step, generate_secret, hotp
from app.audit.models import AuditAction
from app.audit.service import AuditService
from app.audit.store import InMemoryAuditStore
from app.auth import SSO_PENDING_SCOPE, create_access_token, verify_access_token
from app.domain import UserContext
from app.main import app

client = TestClient(app)

ISSUER = "https://idp.example"
CLIENT_ID = "workbench-client"
CLIENT_SECRET = "s3cret"
REDIRECT_URI = "https://workbench.example/auth/callback"
SECRET = "s" * 40
PASSWORD = "correct-horse-battery"
NONCE = "nonce-1"


def make_config(**overrides) -> SsoConfig:
    values = {
        "issuer": ISSUER,
        "authorization_endpoint": "https://idp.example/authorize",
        "token_endpoint": "https://idp.example/token",
        "jwks_uri": "https://idp.example/jwks",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "redirect_uri": REDIRECT_URI,
    }
    values.update(overrides)
    return SsoConfig(**values)


class FakeResponse:
    def __init__(self, *, status_code: int = 200, payload=None) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _segment(value: dict) -> str:
    return _b64url(json.dumps(value, separators=(",", ":")).encode("utf-8"))


def _hs256_token(claims: dict) -> str:
    signing_input = f"{_segment({'alg': 'HS256', 'typ': 'JWT'})}.{_segment(claims)}".encode("ascii")
    signature = hmac.new(CLIENT_SECRET.encode("utf-8"), signing_input, hashlib.sha256).digest()
    return f"{signing_input.decode('ascii')}.{_b64url(signature)}"


def claims_for(
    nonce: str, *, sub: str = "user-1", email: str = "user@example.com", email_verified: bool = True
) -> dict:
    now = int(datetime.now(UTC).timestamp())
    return {
        "iss": ISSUER,
        "aud": CLIENT_ID,
        "exp": now + 300,
        "iat": now,
        "nonce": nonce,
        "sub": sub,
        "email": email,
        "email_verified": email_verified,
    }


class IdentityTransport:
    """假传输层：POST 返回按当前 claims 签名的 id_token，GET 返回空 jwks。"""

    def __init__(self) -> None:
        self.claims: dict | None = None
        self.calls: list[str] = []

    def __call__(self, method, url, *, headers, data=None, params=None, timeout):
        self.calls.append(method)
        if method == "POST":
            return FakeResponse(payload={"id_token": _hs256_token(self.claims or {})})
        return FakeResponse(payload={"keys": []})


def build_service(*, trust: bool = False, require_admin_totp: bool = True, transport=None, config=None):
    repo = InMemoryAccountRepository()
    audit = AuditService(InMemoryAuditStore())
    limiter = LoginRateLimiter(
        InMemoryLoginAttemptStore(), secret=SECRET, max_failures=5, window_seconds=300, lock_seconds=900
    )
    state_store = InMemorySsoStateStore()
    service = AccountService(
        repo,
        bootstrap_token="bootstrap-secret-value",
        audit=audit,
        login_limiter=limiter,
        require_admin_totp=require_admin_totp,
        sso_config=make_config() if config is None else config,
        sso_state_store=state_store,
        sso_provider="generic_oidc",
        sso_trust_idp_mfa=trust,
        sso_state_ttl_seconds=300,
        sso_transport=transport,
    )
    return service, repo, state_store


def add_account(
    repo: InMemoryAccountRepository,
    *,
    phone: str = "13800000001",
    email: str = "user@example.com",
    role: str = "employee",
    status: AccountStatus = AccountStatus.APPROVED,
    tenant_id: str = "t-1",
    subject: str | None = None,
    totp_secret: str | None = None,
    totp_confirmed: bool = False,
) -> Account:
    account = repo.add(
        Account(
            phone=phone,
            password_hash=hash_password(PASSWORD),
            position="内容运营",
            full_name="张三",
            email=email,
            role=role,
            tenant_id=tenant_id,
            status=status,
        )
    )
    if totp_secret is not None:
        repo.set_totp(account.account_id, totp_secret)
        if totp_confirmed:
            repo.confirm_totp(account.account_id, step=current_step(datetime.now(UTC)) - 5)
    if subject is not None:
        repo.set_sso_identity(account.account_id, provider="generic_oidc", subject=subject)
    return account


def complete(
    service: AccountService,
    store: InMemorySsoStateStore,
    transport: IdentityTransport,
    *,
    state: str = "st-1",
    sub: str = "user-1",
    email: str = "user@example.com",
    email_verified: bool = True,
    created_at: datetime | None = None,
    code: str = "auth-code",
):
    transport.claims = claims_for(NONCE, sub=sub, email=email, email_verified=email_verified)
    store.add(
        SsoState(
            state=state,
            nonce=NONCE,
            code_verifier="verifier-1",
            redirect_uri=REDIRECT_URI,
            created_at=created_at or datetime.now(UTC),
        )
    )
    return service.complete_sso_login(code=code, state=state)


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# --- begin_sso_login ----------------------------------------------------------


def test_begin_sso_login_unconfigured_is_rejected() -> None:
    service = AccountService(
        InMemoryAccountRepository(),
        audit=AuditService(InMemoryAuditStore()),
        login_limiter=LoginRateLimiter(
            InMemoryLoginAttemptStore(), secret=SECRET, max_failures=5, window_seconds=300, lock_seconds=900
        ),
        require_admin_totp=True,
    )

    with pytest.raises(SsoNotConfigured):
        service.begin_sso_login()


def test_begin_sso_login_builds_url_and_stores_state() -> None:
    service, _repo, store = build_service()

    url, state = service.begin_sso_login()

    assert url.startswith("https://idp.example/authorize?")
    assert f"state={state}" in url
    assert "code_challenge_method=S256" in url
    stored = store.consume(state, ttl_seconds=300)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(stored.code_verifier.encode("ascii")).digest()
    ).rstrip(b"=").decode("ascii")
    assert f"code_challenge={challenge}" in url
    assert f"nonce={stored.nonce}" in url


# --- complete_sso_login -------------------------------------------------------


def test_complete_sso_login_binds_subject_and_audits() -> None:
    transport = IdentityTransport()
    service, repo, store = build_service(transport=transport)
    account = add_account(repo, role="employee")

    result, requires_totp = complete(service, store, transport)

    assert result.account_id == account.account_id
    assert requires_totp is False
    bound = repo.get(account.account_id)
    assert bound.sso_subject == "user-1"
    assert bound.sso_provider == "generic_oidc"
    actions = {record.action for record in service.audit.store.list_recent(None, limit=50)}
    assert AuditAction.ACCOUNT_SSO_IDENTITY_BOUND in actions
    assert AuditAction.ACCOUNT_SSO_LOGIN_SUCCEEDED in actions


def test_complete_sso_login_rejects_unapproved_account() -> None:
    transport = IdentityTransport()
    service, repo, store = build_service(transport=transport)
    add_account(repo, status=AccountStatus.PENDING)

    with pytest.raises(SsoError, match="尚未通过审批"):
        complete(service, store, transport)


def test_complete_sso_login_rejects_unknown_email_without_creating_account() -> None:
    transport = IdentityTransport()
    service, repo, store = build_service(transport=transport)
    add_account(repo, email="someone@example.com")

    with pytest.raises(SsoError, match="没有已审批的账号"):
        complete(service, store, transport, email="stranger@example.com")

    assert len(repo.list_by_status(AccountStatus.APPROVED)) == 1
    assert repo.find_by_email("stranger@example.com") is None


def test_complete_sso_login_rejects_subject_mismatch() -> None:
    transport = IdentityTransport()
    service, repo, store = build_service(transport=transport)
    add_account(repo, subject="sub-other")

    with pytest.raises(SsoError, match="已绑定其他 SSO 身份"):
        complete(service, store, transport)


def test_complete_sso_login_rejects_state_reuse() -> None:
    transport = IdentityTransport()
    service, repo, store = build_service(transport=transport)
    add_account(repo)
    complete(service, store, transport)

    transport.claims = claims_for(NONCE)
    with pytest.raises(SsoError, match="登录会话已失效"):
        service.complete_sso_login(code="auth-code", state="st-1")


def test_complete_sso_login_rejects_expired_state() -> None:
    transport = IdentityTransport()
    service, repo, store = build_service(transport=transport)
    add_account(repo)

    with pytest.raises(SsoError, match="登录会话已失效"):
        complete(service, store, transport, created_at=datetime.now(UTC) - timedelta(seconds=600))


def test_complete_sso_login_requires_totp_for_bound_admin() -> None:
    transport = IdentityTransport()
    service, repo, store = build_service(transport=transport, trust=False)
    add_account(repo, role="super_admin", totp_secret=generate_secret(), totp_confirmed=True)

    _account, requires_totp = complete(service, store, transport)

    assert requires_totp is True
    actions = {record.action for record in service.audit.store.list_recent(None, limit=50)}
    assert AuditAction.ACCOUNT_SSO_MFA_REQUIRED in actions


def test_complete_sso_login_trusts_idp_mfa_when_configured() -> None:
    transport = IdentityTransport()
    service, repo, store = build_service(transport=transport, trust=True)
    add_account(repo, role="super_admin", totp_secret=generate_secret(), totp_confirmed=True)

    _account, requires_totp = complete(service, store, transport)

    assert requires_totp is False
    actions = {record.action for record in service.audit.store.list_recent(None, limit=50)}
    assert AuditAction.ACCOUNT_SSO_LOGIN_SUCCEEDED in actions


def test_complete_sso_login_rejects_admin_without_bound_totp() -> None:
    """未绑定动态口令的管理员不得借 SSO 绕过绑定流程，也不发放待验证令牌。"""
    transport = IdentityTransport()
    service, repo, store = build_service(transport=transport, trust=False)
    add_account(repo, role="super_admin")

    with pytest.raises(SsoError):
        complete(service, store, transport)

    actions = {record.action for record in service.audit.store.list_recent(None, limit=50)}
    assert AuditAction.ACCOUNT_SSO_LOGIN_REJECTED in actions
    assert AuditAction.ACCOUNT_SSO_MFA_REQUIRED not in actions


def test_complete_sso_login_rejects_unverified_email() -> None:
    transport = IdentityTransport()
    service, repo, store = build_service(transport=transport)
    add_account(repo)

    with pytest.raises(SsoError):
        complete(service, store, transport, email_verified=False)


# --- verify_sso_totp ----------------------------------------------------------


def test_verify_sso_totp_accepts_valid_code() -> None:
    service, repo, _store = build_service()
    secret = generate_secret()
    account = add_account(repo, role="super_admin", totp_secret=secret, totp_confirmed=True)

    result = service.verify_sso_totp(account, hotp(secret, current_step(datetime.now(UTC))))

    assert result.account_id == account.account_id


def test_verify_sso_totp_rejects_wrong_code() -> None:
    service, repo, _store = build_service()
    secret = generate_secret()
    account = add_account(repo, role="super_admin", totp_secret=secret, totp_confirmed=True)

    with pytest.raises(TotpInvalid):
        service.verify_sso_totp(account, hotp(secret, current_step(datetime.now(UTC)) + 5))


def test_verify_sso_totp_rejects_replay() -> None:
    service, repo, _store = build_service()
    secret = generate_secret()
    account = add_account(repo, role="super_admin", totp_secret=secret, totp_confirmed=True)
    code = hotp(secret, current_step(datetime.now(UTC)))

    service.verify_sso_totp(account, code)

    with pytest.raises(LoginFailed):
        service.verify_sso_totp(account, code)


# --- 审计约束 -----------------------------------------------------------------


def test_sso_audits_cover_four_actions_and_never_leak_email() -> None:
    transport = IdentityTransport()
    service, repo, store = build_service(transport=transport)
    add_account(repo, email="user@example.com")
    add_account(
        repo,
        phone="13800000002",
        email="admin@example.com",
        role="super_admin",
        totp_secret=generate_secret(),
        totp_confirmed=True,
    )

    complete(service, store, transport, state="s-ok")
    with pytest.raises(SsoError):
        complete(service, store, transport, state="s-missing", email="stranger@example.com")
    _account, requires_totp = complete(service, store, transport, state="s-mfa", email="admin@example.com")
    assert requires_totp is True

    records = service.audit.store.list_recent(None, limit=100)
    actions = {record.action for record in records}
    assert {
        AuditAction.ACCOUNT_SSO_LOGIN_SUCCEEDED,
        AuditAction.ACCOUNT_SSO_LOGIN_REJECTED,
        AuditAction.ACCOUNT_SSO_IDENTITY_BOUND,
        AuditAction.ACCOUNT_SSO_MFA_REQUIRED,
    } <= actions
    serialized = json.dumps([(record.detail, record.phone_masked, record.target_id) for record in records])
    assert "example.com" not in serialized


# --- 接口层 -------------------------------------------------------------------


def install(monkeypatch, *, transport=None):
    service, repo, store = build_service(transport=transport)
    monkeypatch.setattr(main, "account_service", service)
    monkeypatch.setattr(main.settings, "auth_secret", SECRET)
    monkeypatch.setattr(main.settings, "session_ttl_seconds", 900)
    monkeypatch.setattr(main.settings, "sso_state_ttl_seconds", 300)
    return service, repo, store


def test_authorize_returns_503_when_sso_disabled(monkeypatch) -> None:
    service = AccountService(
        InMemoryAccountRepository(),
        audit=AuditService(InMemoryAuditStore()),
        login_limiter=LoginRateLimiter(
            InMemoryLoginAttemptStore(), secret=SECRET, max_failures=5, window_seconds=300, lock_seconds=900
        ),
        require_admin_totp=False,
    )
    monkeypatch.setattr(main, "account_service", service)

    response = client.get("/api/v1/auth/sso/authorize")

    assert response.status_code == 503
    assert response.json()["detail"] == "SSO 未启用"


def test_authorize_returns_url_and_state(monkeypatch) -> None:
    _service, _repo, store = install(monkeypatch, transport=IdentityTransport())

    response = client.get("/api/v1/auth/sso/authorize")

    assert response.status_code == 200
    body = response.json()
    assert body["authorization_url"].startswith("https://idp.example/authorize?")
    assert f"state={body['state']}" in body["authorization_url"]
    assert store.consume(body["state"], ttl_seconds=300).state == body["state"]


def test_callback_returns_restricted_token_and_guards_routes(monkeypatch) -> None:
    transport = IdentityTransport()
    _service, repo, store = install(monkeypatch, transport=transport)
    secret = generate_secret()
    add_account(repo, role="super_admin", totp_secret=secret, totp_confirmed=True)
    transport.claims = claims_for(NONCE)
    store.add(
        SsoState(state="st-1", nonce=NONCE, code_verifier="v", redirect_uri=REDIRECT_URI, created_at=datetime.now(UTC))
    )

    response = client.post("/api/v1/auth/sso/callback", json={"code": "c", "state": "st-1"})

    assert response.status_code == 200
    body = response.json()
    assert body["scope"] == SSO_PENDING_SCOPE
    assert body["requires_totp"] is True
    assert body["expires_in"] == 300
    token = body["access_token"]
    assert verify_access_token(token, SECRET).scope == SSO_PENDING_SCOPE

    assert client.get("/api/v1/approvals/pending", headers=bearer(token)).status_code == 403
    assert client.get("/api/v1/health", headers=bearer(token)).status_code == 200

    verified = client.post(
        "/api/v1/auth/sso/verification",
        headers=bearer(token),
        json={"totp_code": hotp(secret, current_step(datetime.now(UTC)))},
    )
    assert verified.status_code == 200
    assert verified.json()["scope"] == "full"


def test_callback_full_session_without_totp(monkeypatch) -> None:
    transport = IdentityTransport()
    _service, repo, store = install(monkeypatch, transport=transport)
    add_account(repo, role="employee")
    transport.claims = claims_for(NONCE)
    store.add(
        SsoState(state="st-1", nonce=NONCE, code_verifier="v", redirect_uri=REDIRECT_URI, created_at=datetime.now(UTC))
    )

    response = client.post("/api/v1/auth/sso/callback", json={"code": "c", "state": "st-1"})

    assert response.status_code == 200
    body = response.json()
    assert body["scope"] == "full"
    assert body["expires_in"] == 900
    assert body.get("requires_totp") is None


def test_callback_unknown_state_returns_401(monkeypatch) -> None:
    install(monkeypatch, transport=IdentityTransport())

    response = client.post("/api/v1/auth/sso/callback", json={"code": "c", "state": "missing"})

    assert response.status_code == 401
    assert response.json()["detail"] == "登录会话已失效，请重新发起 SSO 登录"


def test_verification_rejects_full_scope_token(monkeypatch) -> None:
    _service, repo, _store = install(monkeypatch, transport=IdentityTransport())
    account = add_account(repo, role="employee")
    token = create_access_token(
        UserContext("t-1", account.account_id, "employee", scope="full"), SECRET, ttl_seconds=900
    )

    response = client.post(
        "/api/v1/auth/sso/verification", headers=bearer(token), json={"totp_code": "123456"}
    )

    assert response.status_code == 403
