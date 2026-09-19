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


# ---------------------------------------------------------------------------
# B-2b（2026-09-19）：账号按租户列出（导出包 `users` 类别的读取通道）
# 口径：按租户过滤 + 稳定排序（`requested_at, account_id`）+ 总数与分页；
# **待审批（tenant_id 为空）不属于任何租户** ⇒ 不出现在任何租户的导出里。
# ---------------------------------------------------------------------------


def test_list_for_tenant_scopes_orders_and_counts() -> None:
    repository = InMemoryAccountRepository()
    pending = repository.add(make_account("13800000009"))  # 未审批：无租户
    first = repository.add(make_account("13800000001"))
    repository.mark_approved(first.account_id, role="employee", tenant_id="t-1", reviewed_by="admin-1")
    second = repository.add(make_account("13800000002"))
    repository.mark_approved(second.account_id, role="ceo", tenant_id="t-1", reviewed_by="admin-1")
    foreign = repository.add(make_account("13800000003"))
    repository.mark_approved(foreign.account_id, role="employee", tenant_id="t-2", reviewed_by="admin-2")

    rows, total = repository.list_for_tenant("t-1", limit=10, offset=0)

    assert total == 2  # 他租户与未审批账号都不计入
    assert {row.account_id for row in rows} == {first.account_id, second.account_id}
    assert all(row.tenant_id == "t-1" for row in rows)

    page, same_total = repository.list_for_tenant("t-1", limit=1, offset=1)

    assert same_total == 2
    assert len(page) == 1
    assert pending.account_id not in {row.account_id for row in page}


def test_concurrent_approval_only_succeeds_once() -> None:
    from concurrent.futures import ThreadPoolExecutor

    repository = InMemoryAccountRepository()
    account = repository.add(make_account())
    reviewer = "acct-admin"

    def attempt(index: int) -> str:
        try:
            repository.mark_approved(
                account.account_id, role="employee", tenant_id="t-1", reviewed_by=f"{reviewer}-{index}"
            )
            return "approved"
        except AccountStateConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(attempt, range(20)))

    assert results.count("approved") == 1
    assert results.count("conflict") == 19
    assert repository.get(account.account_id).status == AccountStatus.APPROVED


def test_approved_account_cannot_be_rejected() -> None:
    repository = InMemoryAccountRepository()
    account = repository.add(make_account())
    repository.mark_approved(account.account_id, role="employee", tenant_id="t-1", reviewed_by="acct-admin")

    with pytest.raises(AccountStateConflict):
        repository.mark_rejected(account.account_id, reason="反悔", reviewed_by="acct-admin")

    assert repository.get(account.account_id).status == AccountStatus.APPROVED
