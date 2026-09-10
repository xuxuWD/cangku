import pytest

from app.accounts.models import (
    Account,
    AccountConflict,
    AccountNotFound,
    AccountStateConflict,
    AccountStatus,
    SUPER_ADMIN_ROLE,
)
from app.accounts.repository import InMemoryAccountRepository


def make_account(phone: str = "13800000001", *, status: AccountStatus = AccountStatus.PENDING) -> Account:
    return Account(
        phone=phone,
        password_hash="scrypt$1$2$3$salt$hash",
        position="内容运营",
        full_name="张三",
        status=status,
    )


def test_add_and_find_account_by_phone() -> None:
    repository = InMemoryAccountRepository()
    account = repository.add(make_account())

    assert repository.find_by_phone("13800000001") is account
    assert repository.get(account.account_id) is account


def test_duplicate_phone_is_rejected() -> None:
    repository = InMemoryAccountRepository()
    repository.add(make_account())

    with pytest.raises(AccountConflict):
        repository.add(make_account())


def test_missing_account_raises_not_found() -> None:
    repository = InMemoryAccountRepository()

    with pytest.raises(AccountNotFound):
        repository.get("acct-missing")


def test_pending_account_can_be_approved_only_once() -> None:
    repository = InMemoryAccountRepository()
    account = repository.add(make_account())

    approved = repository.mark_approved(
        account.account_id, role="employee", tenant_id="t-1", reviewed_by="acct-admin"
    )

    assert approved.status is AccountStatus.APPROVED
    assert approved.role == "employee"
    assert approved.tenant_id == "t-1"
    with pytest.raises(AccountStateConflict):
        repository.mark_approved(
            account.account_id, role="ceo", tenant_id="t-1", reviewed_by="acct-admin"
        )


def test_rejection_records_reason_and_blocks_login_state() -> None:
    repository = InMemoryAccountRepository()
    account = repository.add(make_account())

    rejected = repository.mark_rejected(account.account_id, reason="信息不完整", reviewed_by="acct-admin")

    assert rejected.status is AccountStatus.REJECTED
    assert rejected.rejection_reason == "信息不完整"


def test_update_password_replaces_hash() -> None:
    repository = InMemoryAccountRepository()
    account = repository.add(make_account())

    updated = repository.update_password(account.account_id, "scrypt$new")

    assert updated.password_hash == "scrypt$new"


def test_has_approved_admin_only_counts_approved_super_admin() -> None:
    repository = InMemoryAccountRepository()

    assert repository.has_approved_admin() is False
    repository.add(make_account(status=AccountStatus.PENDING))
    assert repository.has_approved_admin() is False
    repository.add(
        Account(
            phone="13800000002",
            password_hash="scrypt$1$2$3$salt$hash",
            position="负责人",
            full_name="李四",
            role=SUPER_ADMIN_ROLE,
            tenant_id="t-1",
            status=AccountStatus.APPROVED,
        )
    )
    assert repository.has_approved_admin() is True


def test_list_by_status_filters() -> None:
    repository = InMemoryAccountRepository()
    repository.add(make_account("13800000001"))
    repository.add(make_account("13800000002", status=AccountStatus.REJECTED))

    assert [item.phone for item in repository.list_by_status(AccountStatus.PENDING)] == ["13800000001"]
