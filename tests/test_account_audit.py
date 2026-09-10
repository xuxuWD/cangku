import pytest

from app.accounts.models import RegistrationRequest
from app.accounts.rate_limit import InMemoryLoginAttemptStore, LoginRateLimiter, LoginRateLimited
from app.accounts.repository import InMemoryAccountRepository
from app.accounts.service import AccountService
from app.audit.models import AuditAction
from app.audit.service import AuditService
from app.audit.store import InMemoryAuditStore
from app.domain import UserContext

BOOTSTRAP = "bootstrap-secret-value"
PASSWORD = "correct-horse-battery"


class Harness:
    def __init__(self, *, max_failures: int = 5) -> None:
        self.audits = InMemoryAuditStore()
        self.audit = AuditService(self.audits)
        self.limiter = LoginRateLimiter(
            InMemoryLoginAttemptStore(),
            secret="s" * 40,
            max_failures=max_failures,
            window_seconds=300,
            lock_seconds=900,
        )
        self.service = AccountService(
            InMemoryAccountRepository(),
            bootstrap_token=BOOTSTRAP,
            audit=self.audit,
            login_limiter=self.limiter,
        )

    def actions(self) -> list[str]:
        # 普通注册申请在审批前没有租户归属，审计记录的 tenant_id 为空；
        # 因此这里用「不过滤租户」读取，才能看到全部动作。
        return [item.action.value for item in self.audits.list_recent(None, limit=100)]


def bootstrap_admin(harness: Harness):
    return harness.service.request_registration(
        RegistrationRequest(
            phone="13800000001",
            password=PASSWORD,
            position="内容运营",
            full_name="张三",
            tenant_id="t-1",
            bootstrap_token=BOOTSTRAP,
        )
    )


def test_first_admin_registration_audits_requested_and_approved() -> None:
    harness = Harness()

    bootstrap_admin(harness)

    assert AuditAction.ACCOUNT_REGISTRATION_REQUESTED.value in harness.actions()
    assert AuditAction.ACCOUNT_REGISTRATION_APPROVED.value in harness.actions()


def test_pending_registration_audits_requested_only() -> None:
    harness = Harness()
    bootstrap_admin(harness)

    harness.service.request_registration(
        RegistrationRequest(phone="13800000002", password=PASSWORD, position="运营", full_name="李四")
    )

    actions = harness.actions()
    assert actions.count(AuditAction.ACCOUNT_REGISTRATION_REQUESTED.value) == 2
    assert actions.count(AuditAction.ACCOUNT_REGISTRATION_APPROVED.value) == 1


def test_approval_and_rejection_are_audited() -> None:
    harness = Harness()
    admin = bootstrap_admin(harness)
    actor = UserContext("t-1", admin.account_id, "super_admin")
    first = harness.service.request_registration(
        RegistrationRequest(phone="13800000002", password=PASSWORD, position="运营", full_name="李四")
    )
    second = harness.service.request_registration(
        RegistrationRequest(phone="13800000003", password=PASSWORD, position="运营", full_name="王五")
    )

    harness.service.approve(actor, first.account_id, role="employee", tenant_id="t-1")
    harness.service.reject(actor, second.account_id, reason="资料不完整")

    actions = harness.actions()
    assert AuditAction.ACCOUNT_REGISTRATION_APPROVED.value in actions
    assert AuditAction.ACCOUNT_REGISTRATION_REJECTED.value in actions


def test_login_success_and_failure_are_audited() -> None:
    harness = Harness()
    bootstrap_admin(harness)

    with pytest.raises(Exception):
        harness.service.login("13800000001", "wrong-horse-battery")
    harness.service.login("13800000001", PASSWORD)

    actions = harness.actions()
    assert AuditAction.ACCOUNT_LOGIN_FAILED.value in actions
    assert AuditAction.ACCOUNT_LOGIN_SUCCEEDED.value in actions


def test_lockout_audits_locked_and_blocks_further_attempts() -> None:
    harness = Harness(max_failures=3)
    bootstrap_admin(harness)

    for _index in range(3):
        with pytest.raises(Exception):
            harness.service.login("13800000001", "wrong-horse-battery")

    with pytest.raises(LoginRateLimited, match="稍后再试"):
        harness.service.login("13800000001", PASSWORD)

    assert AuditAction.ACCOUNT_LOGIN_LOCKED.value in harness.actions()


def test_lockout_does_not_reveal_account_existence() -> None:
    harness = Harness(max_failures=2)

    for _index in range(2):
        with pytest.raises(Exception):
            harness.service.login("13900000009", "wrong-horse-battery")

    with pytest.raises(LoginRateLimited):
        harness.service.login("13900000009", "wrong-horse-battery")


def test_successful_login_clears_counter() -> None:
    harness = Harness(max_failures=5)
    bootstrap_admin(harness)
    for _index in range(4):
        with pytest.raises(Exception):
            harness.service.login("13800000001", "wrong-horse-battery")

    harness.service.login("13800000001", PASSWORD)

    for _index in range(4):
        with pytest.raises(Exception):
            harness.service.login("13800000001", "wrong-horse-battery")


def test_password_change_and_reset_are_audited() -> None:
    harness = Harness()
    admin = bootstrap_admin(harness)
    actor = UserContext("t-1", admin.account_id, "super_admin")

    harness.service.change_password(actor, old_password=PASSWORD, new_password="brand-new-passphrase")
    harness.service.reset_password(actor, admin.account_id, new_password="admin-reset-passphrase")

    actions = harness.actions()
    assert AuditAction.ACCOUNT_PASSWORD_CHANGED.value in actions
    assert AuditAction.ACCOUNT_PASSWORD_RESET.value in actions


def test_audit_records_never_contain_credentials() -> None:
    harness = Harness()
    bootstrap_admin(harness)
    with pytest.raises(Exception):
        harness.service.login("13800000001", "wrong-horse-battery")

    rendered = str([item.detail for item in harness.audits.list_recent(None, limit=100)])
    for leaked in ("password", "password_hash", "scrypt$", PASSWORD, "wrong-horse-battery"):
        assert leaked not in rendered


def test_audit_records_carry_masked_phone_only() -> None:
    harness = Harness()
    bootstrap_admin(harness)

    rendered = str(
        [(item.phone_masked, item.detail) for item in harness.audits.list_recent(None, limit=100)]
    )

    assert "13800000001" not in rendered
    assert "138****0001" in rendered


def test_hitting_an_existing_lock_is_audited() -> None:
    harness = Harness(max_failures=3)
    bootstrap_admin(harness)
    for _index in range(3):
        with pytest.raises(Exception):
            harness.service.login("13800000001", "wrong-horse-battery")
    locked_before = harness.actions().count(AuditAction.ACCOUNT_LOGIN_LOCKED.value)

    with pytest.raises(LoginRateLimited):
        harness.service.login("13800000001", PASSWORD)

    this_time = harness.actions()
    assert this_time.count(AuditAction.ACCOUNT_LOGIN_LOCKED.value) == locked_before + 1
    assert AuditAction.ACCOUNT_LOGIN_FAILED.value not in this_time[-1:]
