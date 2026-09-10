from __future__ import annotations

from datetime import UTC, datetime
from threading import RLock
from typing import Protocol

from .models import (
    SUPER_ADMIN_ROLE,
    Account,
    AccountConflict,
    AccountNotFound,
    AccountStateConflict,
    AccountStatus,
)


class AccountRepository(Protocol):
    def add(self, account: Account) -> Account: ...
    def find_by_phone(self, phone: str) -> Account | None: ...
    def get(self, account_id: str) -> Account: ...
    def list_by_status(self, status: AccountStatus) -> list[Account]: ...
    def mark_approved(self, account_id: str, *, role: str, tenant_id: str, reviewed_by: str) -> Account: ...
    def mark_rejected(self, account_id: str, *, reason: str, reviewed_by: str) -> Account: ...
    def update_password(self, account_id: str, password_hash: str) -> Account: ...
    def has_approved_admin(self) -> bool: ...


class InMemoryAccountRepository:
    """开发期内存仓储；审批与改密在锁内原子完成。"""

    def __init__(self) -> None:
        self._accounts: dict[str, Account] = {}
        self._by_phone: dict[str, str] = {}
        self._lock = RLock()

    def add(self, account: Account) -> Account:
        with self._lock:
            if account.phone in self._by_phone:
                raise AccountConflict("该手机号已提交申请或已注册")
            self._accounts[account.account_id] = account
            self._by_phone[account.phone] = account.account_id
            return account

    def find_by_phone(self, phone: str) -> Account | None:
        with self._lock:
            account_id = self._by_phone.get(phone)
            return self._accounts.get(account_id) if account_id else None

    def get(self, account_id: str) -> Account:
        with self._lock:
            account = self._accounts.get(account_id)
            if account is None:
                raise AccountNotFound(account_id)
            return account

    def list_by_status(self, status: AccountStatus) -> list[Account]:
        with self._lock:
            return [item for item in self._accounts.values() if item.status is status]

    def mark_approved(self, account_id: str, *, role: str, tenant_id: str, reviewed_by: str) -> Account:
        with self._lock:
            account = self._require(account_id)
            if account.status is not AccountStatus.PENDING:
                raise AccountStateConflict("该申请当前状态不允许审批")
            account.status = AccountStatus.APPROVED
            account.role = role
            account.tenant_id = tenant_id
            account.reviewed_at = datetime.now(UTC)
            account.reviewed_by = reviewed_by
            account.rejection_reason = None
            return account

    def mark_rejected(self, account_id: str, *, reason: str, reviewed_by: str) -> Account:
        with self._lock:
            account = self._require(account_id)
            if account.status is not AccountStatus.PENDING:
                raise AccountStateConflict("该申请当前状态不允许审批")
            account.status = AccountStatus.REJECTED
            account.reviewed_at = datetime.now(UTC)
            account.reviewed_by = reviewed_by
            account.rejection_reason = reason
            return account

    def update_password(self, account_id: str, password_hash: str) -> Account:
        with self._lock:
            account = self._require(account_id)
            account.password_hash = password_hash
            return account

    def has_approved_admin(self) -> bool:
        with self._lock:
            return any(
                item.status is AccountStatus.APPROVED and item.role == SUPER_ADMIN_ROLE
                for item in self._accounts.values()
            )

    def _require(self, account_id: str) -> Account:
        account = self._accounts.get(account_id)
        if account is None:
            raise AccountNotFound(account_id)
        return account
