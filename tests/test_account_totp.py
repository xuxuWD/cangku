"""动态口令（TOTP）服务层测试：登录、绑定、确认、重置与审计。"""

from datetime import UTC, datetime, timedelta

import pytest

from app.accounts.models import (
    Account,
    LoginFailed,
    RegistrationRequest,
    TotpInvalid,
    TotpNotEnrolled,
    TotpRequired,
)
from app.accounts.rate_limit import InMemoryLoginAttemptStore, LoginRateLimited, LoginRateLimiter
from app.accounts.repository import InMemoryAccountRepository
from app.accounts.service import AccountService
from app.accounts.totp import current_step, hotp, verify_code
from app.audit.models import AuditAction
from app.audit.service import AuditService
from app.audit.store import InMemoryAuditStore
from app.domain import PolicyError, UserContext

BOOTSTRAP = "bootstrap-secret-value"
PASSWORD = "correct-horse-battery"
NOW = datetime(2026, 9, 10, 12, 0, 0, tzinfo=UTC)
LATER = NOW + timedelta(seconds=60)


class Harness:
    def __init__(self, *, require_admin_totp: bool = True, max_failures: int = 5) -> None:
        self.audits = InMemoryAuditStore()
        self.service = AccountService(
            InMemoryAccountRepository(),
            bootstrap_token=BOOTSTRAP,
            audit=AuditService(self.audits),
            login_limiter=LoginRateLimiter(
                InMemoryLoginAttemptStore(),
                secret="s" * 40,
                max_failures=max_failures,
                window_seconds=300,
                lock_seconds=900,
            ),
            require_admin_totp=require_admin_totp,
        )

    def actions(self) -> list[str]:
        return [item.action.value for item in self.audits.list_recent(None, limit=100)]

    def bootstrap_admin(self) -> Account:
        return self.service.request_registration(
            RegistrationRequest(
                phone="13800000001",
                password=PASSWORD,
                position="内容运营",
                full_name="张三",
                tenant_id="t-1",
                bootstrap_token=BOOTSTRAP,
            )
        )


def actor_for(account: Account) -> UserContext:
    return UserContext(str(account.tenant_id), account.account_id, str(account.role))


def wrong_code(secret: str, moment: datetime) -> str:
    """窗口外五步的码，用于稳定构造「错误验证码」。"""
    return hotp(secret, current_step(moment) + 5)


def enroll(harness: Harness, actor: UserContext, *, at: datetime = NOW) -> str:
    secret, _uri = harness.service.start_totp_enrollment(actor)
    harness.service.confirm_totp_enrollment(actor, hotp(secret, current_step(at)), now=at)
    return secret


def test_missing_code_is_required_but_not_counted() -> None:
    harness = Harness(max_failures=3)
    admin = harness.bootstrap_admin()
    actor = actor_for(admin)
    secret = enroll(harness, actor)

    for _index in range(5):
        with pytest.raises(TotpRequired):
            harness.service.login(admin.phone, PASSWORD, now=LATER)

    context = harness.service.login(
        admin.phone, PASSWORD, totp_code=hotp(secret, current_step(LATER)), now=LATER
    )

    assert context.scope == "full"
    assert harness.actions().count(AuditAction.ACCOUNT_LOGIN_FAILED.value) == 5


def test_valid_code_login_returns_full_scope() -> None:
    harness = Harness()
    admin = harness.bootstrap_admin()
    secret = enroll(harness, actor_for(admin))

    context = harness.service.login(
        admin.phone, PASSWORD, totp_code=hotp(secret, current_step(LATER)), now=LATER
    )

    assert context.user_id == admin.account_id
    assert context.scope == "full"
    assert AuditAction.ACCOUNT_LOGIN_SUCCEEDED.value in harness.actions()


def test_wrong_code_reaches_login_throttle() -> None:
    harness = Harness(max_failures=3)
    admin = harness.bootstrap_admin()
    secret = enroll(harness, actor_for(admin))

    for _index in range(3):
        with pytest.raises(TotpInvalid):
            harness.service.login(
                admin.phone, PASSWORD, totp_code=wrong_code(secret, LATER), now=LATER
            )

    with pytest.raises(LoginRateLimited):
        harness.service.login(
            admin.phone, PASSWORD, totp_code=hotp(secret, current_step(LATER)), now=LATER
        )


def test_replayed_code_is_rejected_and_counted() -> None:
    harness = Harness(max_failures=5)
    admin = harness.bootstrap_admin()
    secret = enroll(harness, actor_for(admin))
    code = hotp(secret, current_step(LATER))

    assert harness.service.login(
        admin.phone, PASSWORD, totp_code=code, now=LATER
    ).scope == "full"

    with pytest.raises(LoginFailed):
        harness.service.login(admin.phone, PASSWORD, totp_code=code, now=LATER)

    assert AuditAction.ACCOUNT_LOGIN_FAILED.value in harness.actions()


def test_unenrolled_admin_gets_enrollment_scope_when_required() -> None:
    harness = Harness(require_admin_totp=True)
    admin = harness.bootstrap_admin()

    context = harness.service.login(admin.phone, PASSWORD, now=NOW)

    assert context.scope == "totp_enrollment"
    assert AuditAction.ACCOUNT_TOTP_ENROLLMENT_REQUIRED.value in harness.actions()


def test_unenrolled_admin_gets_full_scope_when_not_required() -> None:
    harness = Harness(require_admin_totp=False)
    admin = harness.bootstrap_admin()

    assert harness.service.login(admin.phone, PASSWORD, now=NOW).scope == "full"


def test_start_enrollment_generates_verifiable_secret_and_rotates() -> None:
    harness = Harness()
    admin = harness.bootstrap_admin()
    actor = actor_for(admin)

    secret, uri = harness.service.start_totp_enrollment(actor)

    assert uri.startswith("otpauth://totp/")
    assert "138****0001" in uri
    assert verify_code(secret, hotp(secret, current_step(NOW)), at=NOW) is not None

    harness.service.confirm_totp_enrollment(actor, hotp(secret, current_step(NOW)), now=NOW)
    confirmed = harness.service.repository.get(admin.account_id)
    assert confirmed.totp_confirmed_at is not None

    rotated, _uri = harness.service.start_totp_enrollment(actor)
    restarted = harness.service.repository.get(admin.account_id)

    assert rotated != secret
    assert restarted.totp_secret == rotated
    assert restarted.totp_confirmed_at is None
    assert restarted.totp_last_step is None


def test_confirm_requires_enrollment_and_valid_code() -> None:
    harness = Harness()
    admin = harness.bootstrap_admin()
    actor = actor_for(admin)

    with pytest.raises(TotpNotEnrolled):
        harness.service.confirm_totp_enrollment(actor, "123456", now=NOW)

    secret, _uri = harness.service.start_totp_enrollment(actor)

    with pytest.raises(TotpInvalid):
        harness.service.confirm_totp_enrollment(actor, wrong_code(secret, NOW), now=NOW)


def test_reset_requires_super_admin_and_clears_requirement() -> None:
    harness = Harness(require_admin_totp=False)
    admin = harness.bootstrap_admin()
    actor = actor_for(admin)
    enroll(harness, actor)

    with pytest.raises(TotpRequired):
        harness.service.login(admin.phone, PASSWORD, now=LATER)

    with pytest.raises(PolicyError):
        harness.service.reset_totp(UserContext("t-1", "acct-x", "employee"), admin.account_id)

    harness.service.reset_totp(actor, admin.account_id)

    cleared = harness.service.repository.get(admin.account_id)
    assert cleared.totp_secret is None

    context = harness.service.login(admin.phone, PASSWORD, now=LATER)
    assert context.scope == "full"


def test_totp_lifecycle_actions_are_audited_without_secret() -> None:
    harness = Harness(require_admin_totp=True)
    admin = harness.bootstrap_admin()
    actor = actor_for(admin)

    harness.service.login(admin.phone, PASSWORD, now=NOW)
    secret, _uri = harness.service.start_totp_enrollment(actor)
    harness.service.confirm_totp_enrollment(actor, hotp(secret, current_step(NOW)), now=NOW)
    harness.service.reset_totp(actor, admin.account_id)

    actions = harness.actions()
    for action in (
        AuditAction.ACCOUNT_TOTP_ENROLLMENT_REQUIRED,
        AuditAction.ACCOUNT_TOTP_ENROLLED,
        AuditAction.ACCOUNT_TOTP_CONFIRMED,
        AuditAction.ACCOUNT_TOTP_RESET,
    ):
        assert action.value in actions

    rendered = str([item.detail for item in harness.audits.list_recent(None, limit=100)])
    assert secret not in rendered
