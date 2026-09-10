import pytest

from app.accounts.models import (
    SUPER_ADMIN_ROLE,
    AccountConflict,
    AccountNotFound,
    AccountStateConflict,
    AccountStatus,
    BootstrapDenied,
    LoginFailed,
    RegistrationRequest,
)
from app.accounts.rate_limit import InMemoryLoginAttemptStore, LoginRateLimiter
from app.accounts.repository import InMemoryAccountRepository
from app.accounts.service import AccountService
from app.audit.service import AuditService
from app.audit.store import InMemoryAuditStore
from app.domain import PolicyError, UserContext

BOOTSTRAP = "bootstrap-secret-value"
PASSWORD = "correct-horse-battery"


def service(*, bootstrap_token: str = BOOTSTRAP) -> AccountService:
    return AccountService(
        InMemoryAccountRepository(),
        bootstrap_token=bootstrap_token,
        audit=AuditService(InMemoryAuditStore()),
        login_limiter=LoginRateLimiter(
            InMemoryLoginAttemptStore(),
            secret="s" * 40,
            max_failures=5,
            window_seconds=300,
            lock_seconds=900,
        ),
        require_admin_totp=False,
    )


def valid_request(**overrides) -> RegistrationRequest:
    payload = {
        "phone": "13800000001",
        "password": PASSWORD,
        "position": "内容运营",
        "full_name": "张三",
    }
    payload.update(overrides)
    return RegistrationRequest(**payload)


def bootstrap_admin(service_instance: AccountService):
    return service_instance.request_registration(
        valid_request(tenant_id="t-1", bootstrap_token=BOOTSTRAP)
    )


def test_first_registration_requires_bootstrap_token() -> None:
    instance = service()

    with pytest.raises(BootstrapDenied, match="初始化口令"):
        instance.request_registration(valid_request(tenant_id="t-1"))


def test_first_registration_with_wrong_bootstrap_token_is_denied() -> None:
    instance = service()

    with pytest.raises(BootstrapDenied, match="初始化口令"):
        instance.request_registration(
            valid_request(tenant_id="t-1", bootstrap_token="wrong-secret-value")
        )


def test_first_registration_requires_tenant_and_becomes_approved_super_admin() -> None:
    instance = service()

    with pytest.raises(BootstrapDenied, match="租户"):
        instance.request_registration(valid_request(bootstrap_token=BOOTSTRAP))

    account = bootstrap_admin(instance)

    assert account.status is AccountStatus.APPROVED
    assert account.role == SUPER_ADMIN_ROLE
    assert account.tenant_id == "t-1"
    assert account.reviewed_by == "bootstrap"


def test_later_registration_is_pending_and_ignores_role_and_tenant() -> None:
    instance = service()
    bootstrap_admin(instance)

    account = instance.request_registration(
        valid_request(phone="13800000002", tenant_id="t-hijack", bootstrap_token=BOOTSTRAP)
    )

    assert account.status is AccountStatus.PENDING
    assert account.role is None
    assert account.tenant_id is None


def test_duplicate_phone_is_rejected() -> None:
    instance = service()
    instance.request_registration(valid_request(tenant_id="t-1", bootstrap_token=BOOTSTRAP))

    with pytest.raises(AccountConflict):
        instance.request_registration(valid_request())


def test_invalid_phone_format_is_rejected() -> None:
    instance = service()

    with pytest.raises(ValueError, match="手机号格式"):
        instance.request_registration(valid_request(phone="12345"))


def test_pending_account_cannot_login_until_approved() -> None:
    instance = service()
    bootstrap_admin(instance)
    pending = instance.request_registration(valid_request(phone="13800000002"))

    with pytest.raises(LoginFailed):
        instance.login("13800000002", PASSWORD)

    instance.approve(
        UserContext("t-1", "acct-admin", SUPER_ADMIN_ROLE),
        pending.account_id,
        role="employee",
        tenant_id="t-1",
    )
    context = instance.login("13800000002", PASSWORD)

    assert context.tenant_id == "t-1"
    assert context.user_id == pending.account_id
    assert context.role == "employee"


def test_login_failure_does_not_distinguish_unknown_phone_from_wrong_password() -> None:
    instance = service()
    account = bootstrap_admin(instance)

    with pytest.raises(LoginFailed) as unknown:
        instance.login("13900000009", PASSWORD)
    with pytest.raises(LoginFailed) as wrong:
        instance.login(account.phone, "wrong-horse-battery")

    assert str(unknown.value) == str(wrong.value)


def test_only_super_admin_can_list_approve_and_reject() -> None:
    instance = service()
    bootstrap_admin(instance)
    pending = instance.request_registration(valid_request(phone="13800000002"))
    employee = UserContext("t-1", "acct-employee", "employee")

    with pytest.raises(PolicyError):
        instance.list_requests(employee)
    with pytest.raises(PolicyError):
        instance.approve(employee, pending.account_id, role="employee", tenant_id="t-1")
    with pytest.raises(PolicyError):
        instance.reject(employee, pending.account_id, reason="不符合要求")


def test_approval_requires_supported_role_and_tenant() -> None:
    instance = service()
    admin = bootstrap_admin(instance)
    actor = UserContext("t-1", admin.account_id, SUPER_ADMIN_ROLE)
    pending = instance.request_registration(valid_request(phone="13800000002"))

    with pytest.raises(ValueError, match="角色"):
        instance.approve(actor, pending.account_id, role="owner", tenant_id="t-1")
    with pytest.raises(ValueError, match="租户"):
        instance.approve(actor, pending.account_id, role="employee", tenant_id="  ")


def test_repeat_approval_conflicts() -> None:
    instance = service()
    admin = bootstrap_admin(instance)
    actor = UserContext("t-1", admin.account_id, SUPER_ADMIN_ROLE)
    pending = instance.request_registration(valid_request(phone="13800000002"))
    instance.approve(actor, pending.account_id, role="employee", tenant_id="t-1")

    with pytest.raises(AccountStateConflict):
        instance.approve(actor, pending.account_id, role="employee", tenant_id="t-1")


def test_rejected_account_cannot_login() -> None:
    instance = service()
    admin = bootstrap_admin(instance)
    actor = UserContext("t-1", admin.account_id, SUPER_ADMIN_ROLE)
    pending = instance.request_registration(valid_request(phone="13800000002"))
    instance.reject(actor, pending.account_id, reason="资料不完整")

    with pytest.raises(LoginFailed):
        instance.login("13800000002", PASSWORD)


def test_change_password_requires_current_password() -> None:
    instance = service()
    account = bootstrap_admin(instance)
    actor = UserContext("t-1", account.account_id, SUPER_ADMIN_ROLE)

    with pytest.raises(LoginFailed, match="原密码"):
        instance.change_password(actor, old_password="wrong-horse-battery", new_password="brand-new-passphrase")

    instance.change_password(actor, old_password=PASSWORD, new_password="brand-new-passphrase")

    with pytest.raises(LoginFailed):
        instance.login(account.phone, PASSWORD)
    assert instance.login(account.phone, "brand-new-passphrase").user_id == account.account_id


def test_admin_reset_password_requires_super_admin_and_known_account() -> None:
    instance = service()
    admin = bootstrap_admin(instance)
    actor = UserContext("t-1", admin.account_id, SUPER_ADMIN_ROLE)

    instance.reset_password(actor, admin.account_id, new_password="admin-reset-passphrase")
    assert instance.login(admin.phone, "admin-reset-passphrase").user_id == admin.account_id

    with pytest.raises(PolicyError):
        instance.reset_password(
            UserContext("t-1", admin.account_id, "employee"),
            admin.account_id,
            new_password="another-passphrase",
        )
    with pytest.raises(AccountNotFound):
        instance.reset_password(actor, "acct-missing", new_password="another-passphrase")


def test_first_registration_with_blank_or_invalid_tenant_is_denied() -> None:
    instance = service()

    for bad_tenant in ("   ", "bad!", "t"):
        with pytest.raises(BootstrapDenied, match="租户"):
            instance.request_registration(
                valid_request(tenant_id=bad_tenant, bootstrap_token=BOOTSTRAP)
            )


def test_first_registration_is_denied_when_server_has_no_bootstrap_token() -> None:
    instance = service(bootstrap_token="")

    with pytest.raises(BootstrapDenied, match="初始化口令"):
        instance.request_registration(valid_request(tenant_id="t-1", bootstrap_token="anything"))


def test_non_ascii_bootstrap_token_is_rejected_without_server_error() -> None:
    instance = service()

    with pytest.raises(BootstrapDenied, match="初始化口令"):
        instance.request_registration(valid_request(tenant_id="t-1", bootstrap_token="口令不正确"))


def test_bootstrap_denial_does_not_hash_password(monkeypatch) -> None:
    instance = service()
    calls = {"count": 0}

    def exploding_hash(password: str) -> str:
        calls["count"] += 1
        raise AssertionError("不应在验证初始化口令之前哈希口令")

    monkeypatch.setattr("app.accounts.service.hash_password", exploding_hash)

    with pytest.raises(BootstrapDenied):
        instance.request_registration(
            valid_request(tenant_id="t-1", bootstrap_token="wrong-secret-value")
        )

    assert calls["count"] == 0


def test_blank_position_or_full_name_is_rejected() -> None:
    instance = service()

    with pytest.raises(ValueError, match="职位和姓名"):
        instance.request_registration(valid_request(position="   "))
    with pytest.raises(ValueError, match="职位和姓名"):
        instance.request_registration(valid_request(full_name=" "))
