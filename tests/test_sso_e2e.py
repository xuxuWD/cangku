"""SSO 真实全链路端到端测试：真实 HTTP 语义（进程内 WSGI）+ 真实 RS256 验签。

与 `tests/test_sso_login.py`（桩传输层 + HS256）互补：本文件用 `OidcTestIdp`
（标准库 WSGI + cryptography）跑通「发起授权 → IdP 校验 PKCE/nonce → 回调换取并校验
RS256 id_token → 应用内 TOTP → 完整会话」的真实链路，并覆盖六类负向。

全程不开 socket：`OidcTestIdp.as_transport()` 基于 `httpx.WSGITransport`，测试夹具应用为
纯函数式 WSGI 应用；`test_full_flow_never_touches_socket` 进一步在禁用 socket 的前提下跑通全链路。
"""

from __future__ import annotations

import json
import socket
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient

from app import main
from app.accounts.models import Account, AccountStatus
from app.accounts.passwords import hash_password
from app.accounts.rate_limit import InMemoryLoginAttemptStore, LoginRateLimiter
from app.accounts.repository import InMemoryAccountRepository
from app.accounts.service import AccountService
from app.accounts.sso import SsoError, SsoTokenError, exchange_code
from app.accounts.sso_store import InMemorySsoStateStore
from app.accounts.totp import current_step, hotp
from app.audit.models import AuditAction
from app.audit.service import AuditService
from app.audit.store import InMemoryAuditStore
from app.auth import SSO_PENDING_SCOPE, verify_access_token
from app.main import app

from tests.oidc_test_idp import OidcTestIdp

client = TestClient(app)

SECRET = "s" * 40
PASSWORD = "correct-horse-battery"
EMAIL = "user@example.com"


# --- 装配 ---------------------------------------------------------------------


def build_service(*, idp: OidcTestIdp, trust: bool = False, require_admin_totp: bool = True):
    repository = InMemoryAccountRepository()
    audit = AuditService(InMemoryAuditStore())
    limiter = LoginRateLimiter(
        InMemoryLoginAttemptStore(), secret=SECRET, max_failures=5, window_seconds=300, lock_seconds=900
    )
    state_store = InMemorySsoStateStore()
    service = AccountService(
        repository,
        bootstrap_token="bootstrap-secret-value",
        audit=audit,
        login_limiter=limiter,
        require_admin_totp=require_admin_totp,
        sso_config=idp.config(),
        sso_state_store=state_store,
        sso_provider="generic_oidc",
        sso_trust_idp_mfa=trust,
        sso_state_ttl_seconds=300,
        sso_transport=idp.as_transport(),
    )
    return service, repository, state_store


def add_account(
    repository: InMemoryAccountRepository,
    *,
    phone: str = "13800000001",
    email: str = EMAIL,
    role: str = "employee",
    totp_secret: str | None = None,
    totp_confirmed: bool = False,
) -> Account:
    account = repository.add(
        Account(
            phone=phone,
            password_hash=hash_password(PASSWORD),
            position="内容运营",
            full_name="张三",
            email=email,
            role=role,
            tenant_id="t-1",
            status=AccountStatus.APPROVED,
        )
    )
    if totp_secret is not None:
        repository.set_totp(account.account_id, totp_secret)
        if totp_confirmed:
            repository.confirm_totp(account.account_id, step=current_step(datetime.now(UTC)) - 5)
    return account


def begin_and_authorize(service: AccountService, idp: OidcTestIdp, *, challenge: str | None = None) -> tuple[str, str]:
    """走「发起授权 → IdP 校验并下发 code」，返回 (code, state)。"""
    url, state = service.begin_sso_login()
    query = parse_qs(urlsplit(url).query)
    nonce = query["nonce"][0]
    code_challenge = challenge if challenge is not None else query["code_challenge"][0]
    code = idp.authorize(state=state, nonce=nonce, code_challenge=code_challenge)
    return code, state


def run_flow(service: AccountService, idp: OidcTestIdp):
    code, state = begin_and_authorize(service, idp)
    return service.complete_sso_login(code=code, state=state)


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# --- 服务层端到端 -------------------------------------------------------------


def test_service_end_to_end_binds_subject_with_real_rs256() -> None:
    idp = OidcTestIdp()
    service, repository, _ = build_service(idp=idp)
    account = add_account(repository, email=idp.email, role="employee")

    result, requires_totp = run_flow(service, idp)

    assert result.account_id == account.account_id
    assert requires_totp is False
    bound = repository.get(account.account_id)
    assert bound.sso_subject == idp.subject
    assert bound.sso_provider == "generic_oidc"
    actions = {record.action for record in service.audit.store.list_recent(None, limit=50)}
    assert AuditAction.ACCOUNT_SSO_IDENTITY_BOUND in actions
    assert AuditAction.ACCOUNT_SSO_LOGIN_SUCCEEDED in actions
    # 邮箱只用于匹配，不落审计。
    serialized = json.dumps(
        [(r.detail, r.phone_masked, r.target_id) for r in service.audit.store.list_recent(None, limit=50)]
    )
    assert "example.com" not in serialized


def test_service_end_to_end_admin_requires_totp() -> None:
    idp = OidcTestIdp()
    service, repository, _ = build_service(idp=idp, trust=False)
    add_account(
        repository,
        email=idp.email,
        role="super_admin",
        totp_secret="JBSWY3DPEHPK3PXP",
        totp_confirmed=True,
    )

    _account, requires_totp = run_flow(service, idp)

    assert requires_totp is True
    actions = {record.action for record in service.audit.store.list_recent(None, limit=50)}
    assert AuditAction.ACCOUNT_SSO_MFA_REQUIRED in actions


def test_service_end_to_end_trust_idp_mfa_skips_totp() -> None:
    idp = OidcTestIdp()
    service, repository, _ = build_service(idp=idp, trust=True)
    add_account(
        repository,
        email=idp.email,
        role="super_admin",
        totp_secret="JBSWY3DPEHPK3PXP",
        totp_confirmed=True,
    )

    _account, requires_totp = run_flow(service, idp)

    assert requires_totp is False


def test_tampered_code_challenge_is_rejected_by_token_endpoint() -> None:
    """证明授权地址里的 code_challenge 确实被 IdP 校验：篡改后 token 端点拒绝。"""
    idp = OidcTestIdp()
    service, repository, _ = build_service(idp=idp)
    add_account(repository, email=idp.email)

    code, state = begin_and_authorize(service, idp, challenge="tampered-challenge-not-matching-verifier")

    with pytest.raises(SsoError) as excinfo:
        service.complete_sso_login(code=code, state=state)
    assert not isinstance(excinfo.value, SsoTokenError)
    assert str(excinfo.value) == "SSO 令牌交换失败"
    assert "invalid_grant" not in str(excinfo.value)


# --- 负向用例 -----------------------------------------------------------------


def test_code_verifier_mismatch_is_rejected_without_leaking_idp_response() -> None:
    idp = OidcTestIdp()
    service, repository, _ = build_service(idp=idp)
    add_account(repository, email=idp.email)

    code, state = begin_and_authorize(service, idp, challenge="another-serviceable-challenge")

    with pytest.raises(SsoError) as excinfo:
        service.complete_sso_login(code=code, state=state)
    assert not isinstance(excinfo.value, SsoTokenError)
    assert str(excinfo.value) == "SSO 令牌交换失败"


def test_id_token_signed_with_unpublished_key_is_rejected() -> None:
    idp = OidcTestIdp(sign_with_unknown_key=True)
    service, repository, _ = build_service(idp=idp)
    add_account(repository, email=idp.email)

    with pytest.raises(SsoTokenError) as excinfo:
        run_flow(service, idp)
    assert "签名" in str(excinfo.value)


def test_nonce_mismatch_is_rejected() -> None:
    idp = OidcTestIdp(nonce_override="nonce-from-another-flow")
    service, repository, _ = build_service(idp=idp)
    add_account(repository, email=idp.email)

    with pytest.raises(SsoTokenError) as excinfo:
        run_flow(service, idp)
    assert "随机数" in str(excinfo.value)


def test_unverified_email_is_rejected() -> None:
    idp = OidcTestIdp(email_verified=False)
    service, repository, _ = build_service(idp=idp)
    add_account(repository, email=idp.email)

    with pytest.raises(SsoTokenError) as excinfo:
        run_flow(service, idp)
    assert "未验证邮箱" in str(excinfo.value)


def test_unknown_kid_is_rejected() -> None:
    idp = OidcTestIdp(kid_override="kid-not-published")
    service, repository, _ = build_service(idp=idp)
    add_account(repository, email=idp.email)

    with pytest.raises(SsoTokenError) as excinfo:
        run_flow(service, idp)
    assert "公钥" in str(excinfo.value)


def test_authorization_code_is_single_use() -> None:
    idp = OidcTestIdp()
    service, repository, store = build_service(idp=idp)
    add_account(repository, email=idp.email)

    url, state = service.begin_sso_login()
    query = parse_qs(urlsplit(url).query)
    verifier = store.consume(state, ttl_seconds=300).code_verifier
    code = idp.authorize(state=state, nonce=query["nonce"][0], code_challenge=query["code_challenge"][0])
    config = idp.config()
    transport = idp.as_transport()

    first = exchange_code(config, code=code, code_verifier=verifier, transport=transport)
    assert first["id_token"]

    with pytest.raises(SsoError) as excinfo:
        exchange_code(config, code=code, code_verifier=verifier, transport=transport)
    assert str(excinfo.value) == "SSO 令牌交换失败"

    # 同一 state 二次回调同样失败（state 一次性消费）。
    url2, state2 = service.begin_sso_login()
    query2 = parse_qs(urlsplit(url2).query)
    code2 = idp.authorize(
        state=state2, nonce=query2["nonce"][0], code_challenge=query2["code_challenge"][0]
    )
    service.complete_sso_login(code=code2, state=state2)
    with pytest.raises(SsoError):
        service.complete_sso_login(code=code2, state=state2)


# --- 无 socket 证明 -----------------------------------------------------------


def test_full_flow_never_touches_socket(monkeypatch) -> None:
    """在禁用 socket 的前提下跑通全链路，证明传输层为进程内 WSGI。"""

    def _forbidden(*_args, **_kwargs):
        raise AssertionError("全链路不应创建 socket")

    monkeypatch.setattr(socket, "socket", _forbidden)
    monkeypatch.setattr(socket, "create_connection", _forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", _forbidden)

    idp = OidcTestIdp()
    assert isinstance(idp.wsgi_transport, httpx.WSGITransport)
    assert isinstance(idp.as_transport(), type(idp.as_transport()))

    service, repository, _ = build_service(idp=idp)
    add_account(repository, email=idp.email)

    account, requires_totp = run_flow(service, idp)

    assert account.sso_subject == idp.subject
    assert requires_totp is False


# --- 接口层端到端 -------------------------------------------------------------


def install(monkeypatch, idp: OidcTestIdp, *, trust: bool = False):
    service, repository, state_store = build_service(idp=idp, trust=trust)
    monkeypatch.setattr(main, "account_service", service)
    monkeypatch.setattr(main.settings, "auth_secret", SECRET)
    monkeypatch.setattr(main.settings, "session_ttl_seconds", 900)
    monkeypatch.setattr(main.settings, "sso_state_ttl_seconds", 300)
    return service, repository, state_store


def authorize_via_api(idp: OidcTestIdp) -> tuple[str, str]:
    response = client.get("/api/v1/auth/sso/authorize")
    assert response.status_code == 200
    body = response.json()
    query = parse_qs(urlsplit(body["authorization_url"]).query)
    code = idp.authorize(
        state=body["state"], nonce=query["nonce"][0], code_challenge=query["code_challenge"][0]
    )
    return code, body["state"]


def test_interface_end_to_end_full_session_and_protected_route(monkeypatch) -> None:
    idp = OidcTestIdp()
    _service, repository, _ = install(monkeypatch, idp)
    add_account(repository, email=idp.email, role="employee")

    code, state = authorize_via_api(idp)
    response = client.post("/api/v1/auth/sso/callback", json={"code": code, "state": state})

    assert response.status_code == 200
    body = response.json()
    assert body["scope"] == "full"
    assert body["expires_in"] == 900
    assert verify_access_token(body["access_token"], SECRET).scope == "full"
    protected = client.get("/api/v1/approvals/pending", headers=bearer(body["access_token"]))
    assert protected.status_code == 200


def test_interface_end_to_end_totp_then_full_session(monkeypatch) -> None:
    idp = OidcTestIdp()
    _service, repository, _ = install(monkeypatch, idp, trust=False)
    totp_secret = "JBSWY3DPEHPK3PXP"
    add_account(
        repository,
        email=idp.email,
        role="super_admin",
        totp_secret=totp_secret,
        totp_confirmed=True,
    )

    code, state = authorize_via_api(idp)
    response = client.post("/api/v1/auth/sso/callback", json={"code": code, "state": state})

    assert response.status_code == 200
    pending = response.json()
    assert pending["scope"] == SSO_PENDING_SCOPE
    assert pending["requires_totp"] is True
    token = pending["access_token"]
    assert verify_access_token(token, SECRET).scope == SSO_PENDING_SCOPE
    # 受限令牌访问受保护接口必须被拒。
    assert client.get("/api/v1/approvals/pending", headers=bearer(token)).status_code == 403

    verified = client.post(
        "/api/v1/auth/sso/verification",
        headers=bearer(token),
        json={"totp_code": hotp(totp_secret, current_step(datetime.now(UTC)))},
    )
    assert verified.status_code == 200
    assert verified.json()["scope"] == "full"
    protected = client.get("/api/v1/approvals/pending", headers=bearer(verified.json()["access_token"]))
    assert protected.status_code == 200
