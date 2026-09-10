import pytest

from app.accounts.models import (
    Account,
    AccountNotFound,
    AccountStatus,
    TotpInvalid,
    TotpNotEnrolled,
)
from app.accounts.repository import InMemoryAccountRepository


def make_account(phone: str = "13800000001") -> Account:
    return Account(
        phone=phone,
        password_hash="scrypt$1$2$3$salt$hash",
        position="内容运营",
        full_name="张三",
        status=AccountStatus.APPROVED,
    )


def enrolled_repository(phone: str = "13800000001") -> tuple[InMemoryAccountRepository, Account]:
    repository = InMemoryAccountRepository()
    account = repository.add(make_account(phone))
    return repository, account


def test_set_totp_writes_secret_and_resets_confirmation() -> None:
    repository, account = enrolled_repository()

    updated = repository.set_totp(account.account_id, "JBSWY3DPEHPK3PXP")

    assert updated.totp_secret == "JBSWY3DPEHPK3PXP"
    assert updated.totp_confirmed_at is None
    assert updated.totp_last_step is None


def test_set_totp_resets_previously_confirmed_account() -> None:
    repository, account = enrolled_repository()
    repository.set_totp(account.account_id, "JBSWY3DPEHPK3PXP")
    repository.confirm_totp(account.account_id, step=42)

    updated = repository.set_totp(account.account_id, "GEZDGNBVGY3TQOJQ")

    assert updated.totp_secret == "GEZDGNBVGY3TQOJQ"
    assert updated.totp_confirmed_at is None
    assert updated.totp_last_step is None


def test_set_totp_raises_for_missing_account() -> None:
    repository = InMemoryAccountRepository()

    with pytest.raises(AccountNotFound):
        repository.set_totp("acct-missing", "JBSWY3DPEHPK3PXP")


def test_confirm_totp_requires_enrolled_secret() -> None:
    repository, account = enrolled_repository()

    with pytest.raises(TotpNotEnrolled):
        repository.confirm_totp(account.account_id, step=42)


def test_confirm_totp_raises_for_missing_account() -> None:
    repository = InMemoryAccountRepository()

    with pytest.raises(AccountNotFound):
        repository.confirm_totp("acct-missing", step=42)


def test_confirm_totp_records_confirmation_and_step() -> None:
    repository, account = enrolled_repository()
    repository.set_totp(account.account_id, "JBSWY3DPEHPK3PXP")

    updated = repository.confirm_totp(account.account_id, step=42)

    assert updated.totp_confirmed_at is not None
    assert updated.totp_last_step == 42


def test_clear_totp_empties_all_three_columns() -> None:
    repository, account = enrolled_repository()
    repository.set_totp(account.account_id, "JBSWY3DPEHPK3PXP")
    repository.confirm_totp(account.account_id, step=42)

    updated = repository.clear_totp(account.account_id)

    assert updated.totp_secret is None
    assert updated.totp_confirmed_at is None
    assert updated.totp_last_step is None


def test_clear_totp_raises_for_missing_account() -> None:
    repository = InMemoryAccountRepository()

    with pytest.raises(AccountNotFound):
        repository.clear_totp("acct-missing")


def test_record_totp_step_first_use_succeeds() -> None:
    repository, account = enrolled_repository()

    updated = repository.record_totp_step(account.account_id, 100)

    assert updated.totp_last_step == 100


def test_record_totp_step_rejects_same_step_replay() -> None:
    repository, account = enrolled_repository()
    repository.record_totp_step(account.account_id, 100)

    with pytest.raises(TotpInvalid):
        repository.record_totp_step(account.account_id, 100)


def test_record_totp_step_rejects_smaller_step_replay() -> None:
    repository, account = enrolled_repository()
    repository.record_totp_step(account.account_id, 100)

    with pytest.raises(TotpInvalid):
        repository.record_totp_step(account.account_id, 99)


def test_record_totp_step_advances_with_larger_step() -> None:
    repository, account = enrolled_repository()
    repository.record_totp_step(account.account_id, 100)

    updated = repository.record_totp_step(account.account_id, 101)

    assert updated.totp_last_step == 101


def test_record_totp_step_raises_for_missing_account() -> None:
    repository = InMemoryAccountRepository()

    with pytest.raises(AccountNotFound):
        repository.record_totp_step("acct-missing", 100)
