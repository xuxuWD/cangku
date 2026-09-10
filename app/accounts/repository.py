from __future__ import annotations

from contextlib import contextmanager, nullcontext
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
    TotpInvalid,
    TotpNotEnrolled,
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
    def set_totp(self, account_id: str, secret: str) -> Account: ...
    def confirm_totp(self, account_id: str, *, step: int) -> Account: ...
    def clear_totp(self, account_id: str) -> Account: ...
    def record_totp_step(self, account_id: str, step: int) -> Account: ...


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
            return [item for item in self._accounts.values() if item.status == status]

    def mark_approved(self, account_id: str, *, role: str, tenant_id: str, reviewed_by: str) -> Account:
        with self._lock:
            account = self._require(account_id)
            if account.status != AccountStatus.PENDING:
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
            if account.status != AccountStatus.PENDING:
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
                item.status == AccountStatus.APPROVED and item.role == SUPER_ADMIN_ROLE
                for item in self._accounts.values()
            )

    def set_totp(self, account_id: str, secret: str) -> Account:
        with self._lock:
            account = self._require(account_id)
            account.totp_secret = secret
            account.totp_confirmed_at = None
            account.totp_last_step = None
            return account

    def confirm_totp(self, account_id: str, *, step: int) -> Account:
        with self._lock:
            account = self._require(account_id)
            if not account.totp_secret:
                raise TotpNotEnrolled(account_id)
            account.totp_confirmed_at = datetime.now(UTC)
            account.totp_last_step = step
            return account

    def clear_totp(self, account_id: str) -> Account:
        with self._lock:
            account = self._require(account_id)
            account.totp_secret = None
            account.totp_confirmed_at = None
            account.totp_last_step = None
            return account

    def record_totp_step(self, account_id: str, step: int) -> Account:
        with self._lock:
            account = self._require(account_id)
            if account.totp_last_step is not None and account.totp_last_step >= step:
                raise TotpInvalid("动态口令步号未推进")
            account.totp_last_step = step
            return account

    def _require(self, account_id: str) -> Account:
        account = self._accounts.get(account_id)
        if account is None:
            raise AccountNotFound(account_id)
        return account


class PostgresAccountRepository:
    """账号持久化适配器；审批使用条件更新保证并发安全。"""

    _COLUMNS = (
        "account_id, phone, password_hash, position, full_name, email, role, tenant_id, "
        "status, requested_at, reviewed_at, reviewed_by, rejection_reason, "
        "totp_secret, totp_confirmed_at, totp_last_step"
    )

    def __init__(self, connection_or_pool) -> None:
        self.connection = connection_or_pool

    @contextmanager
    def _connection(self):
        if hasattr(self.connection, "connection") and callable(self.connection.connection):
            with self.connection.connection() as connection:
                yield connection
        else:
            with nullcontext(self.connection) as connection:
                yield connection

    @staticmethod
    def _hydrate(row: tuple) -> Account:
        return Account(
            account_id=str(row[0]),
            phone=str(row[1]),
            password_hash=str(row[2]),
            position=str(row[3]),
            full_name=str(row[4]),
            email=row[5],
            role=row[6],
            tenant_id=row[7],
            status=AccountStatus(str(row[8])),
            requested_at=row[9] if isinstance(row[9], datetime) else datetime.now(UTC),
            reviewed_at=row[10],
            reviewed_by=row[11],
            rejection_reason=row[12],
            totp_secret=row[13],
            totp_confirmed_at=row[14],
            totp_last_step=row[15],
        )

    def add(self, account: Account) -> Account:
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""
                        INSERT INTO workbench_accounts ({self._COLUMNS})
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (phone) DO NOTHING
                        RETURNING {self._COLUMNS}
                        """,
                        (
                            account.account_id, account.phone, account.password_hash, account.position,
                            account.full_name, account.email, account.role, account.tenant_id,
                            account.status.value, account.requested_at, account.reviewed_at,
                            account.reviewed_by, account.rejection_reason,
                            account.totp_secret, account.totp_confirmed_at, account.totp_last_step,
                        ),
                    )
                    row = cursor.fetchone()
        if row is None:
            raise AccountConflict("该手机号已提交申请或已注册")
        return self._hydrate(row)

    def find_by_phone(self, phone: str) -> Account | None:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT {self._COLUMNS} FROM workbench_accounts WHERE phone = %s", (phone,)
                )
                row = cursor.fetchone()
        return self._hydrate(row) if row is not None else None

    def get(self, account_id: str) -> Account:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT {self._COLUMNS} FROM workbench_accounts WHERE account_id = %s",
                    (account_id,),
                )
                row = cursor.fetchone()
        if row is None:
            raise AccountNotFound(account_id)
        return self._hydrate(row)

    def list_by_status(self, status: AccountStatus) -> list[Account]:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT {self._COLUMNS} FROM workbench_accounts
                    WHERE status = %s ORDER BY requested_at
                    """,
                    (status.value,),
                )
                rows = cursor.fetchall()
        return [self._hydrate(row) for row in rows]

    def mark_approved(self, account_id: str, *, role: str, tenant_id: str, reviewed_by: str) -> Account:
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""
                        UPDATE workbench_accounts
                        SET status = 'approved', role = %s, tenant_id = %s,
                            reviewed_at = now(), reviewed_by = %s, rejection_reason = NULL
                        WHERE account_id = %s AND status = 'pending'
                        RETURNING {self._COLUMNS}
                        """,
                        (role, tenant_id, reviewed_by, account_id),
                    )
                    row = cursor.fetchone()
                    if row is None:
                        cursor.execute(
                            "SELECT account_id FROM workbench_accounts WHERE account_id = %s",
                            (account_id,),
                        )
                        if cursor.fetchone() is None:
                            raise AccountNotFound(account_id)
                        raise AccountStateConflict("该申请当前状态不允许审批")
        return self._hydrate(row)

    def mark_rejected(self, account_id: str, *, reason: str, reviewed_by: str) -> Account:
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""
                        UPDATE workbench_accounts
                        SET status = 'rejected', reviewed_at = now(), reviewed_by = %s,
                            rejection_reason = %s
                        WHERE account_id = %s AND status = 'pending'
                        RETURNING {self._COLUMNS}
                        """,
                        (reviewed_by, reason, account_id),
                    )
                    row = cursor.fetchone()
                    if row is None:
                        cursor.execute(
                            "SELECT account_id FROM workbench_accounts WHERE account_id = %s",
                            (account_id,),
                        )
                        if cursor.fetchone() is None:
                            raise AccountNotFound(account_id)
                        raise AccountStateConflict("该申请当前状态不允许审批")
        return self._hydrate(row)

    def update_password(self, account_id: str, password_hash: str) -> Account:
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""
                        UPDATE workbench_accounts SET password_hash = %s
                        WHERE account_id = %s RETURNING {self._COLUMNS}
                        """,
                        (password_hash, account_id),
                    )
                    row = cursor.fetchone()
        if row is None:
            raise AccountNotFound(account_id)
        return self._hydrate(row)

    def set_totp(self, account_id: str, secret: str) -> Account:
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""
                        UPDATE workbench_accounts
                        SET totp_secret = %s, totp_confirmed_at = NULL, totp_last_step = NULL
                        WHERE account_id = %s
                        RETURNING {self._COLUMNS}
                        """,
                        (secret, account_id),
                    )
                    row = cursor.fetchone()
        if row is None:
            raise AccountNotFound(account_id)
        return self._hydrate(row)

    def confirm_totp(self, account_id: str, *, step: int) -> Account:
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""
                        UPDATE workbench_accounts
                        SET totp_confirmed_at = now(), totp_last_step = %s
                        WHERE account_id = %s AND totp_secret IS NOT NULL
                        RETURNING {self._COLUMNS}
                        """,
                        (step, account_id),
                    )
                    row = cursor.fetchone()
                    if row is None:
                        cursor.execute(
                            "SELECT account_id FROM workbench_accounts WHERE account_id = %s",
                            (account_id,),
                        )
                        if cursor.fetchone() is None:
                            raise AccountNotFound(account_id)
                        raise TotpNotEnrolled(account_id)
        return self._hydrate(row)

    def clear_totp(self, account_id: str) -> Account:
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""
                        UPDATE workbench_accounts
                        SET totp_secret = NULL, totp_confirmed_at = NULL, totp_last_step = NULL
                        WHERE account_id = %s
                        RETURNING {self._COLUMNS}
                        """,
                        (account_id,),
                    )
                    row = cursor.fetchone()
        if row is None:
            raise AccountNotFound(account_id)
        return self._hydrate(row)

    def record_totp_step(self, account_id: str, step: int) -> Account:
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""
                        UPDATE workbench_accounts
                        SET totp_last_step = %s
                        WHERE account_id = %s AND (totp_last_step IS NULL OR totp_last_step < %s)
                        RETURNING {self._COLUMNS}
                        """,
                        (step, account_id, step),
                    )
                    row = cursor.fetchone()
                    if row is None:
                        cursor.execute(
                            "SELECT account_id FROM workbench_accounts WHERE account_id = %s",
                            (account_id,),
                        )
                        if cursor.fetchone() is None:
                            raise AccountNotFound(account_id)
                        raise TotpInvalid("动态口令步号未推进")
        return self._hydrate(row)

    def has_approved_admin(self) -> bool:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT 1 FROM workbench_accounts
                    WHERE status = 'approved' AND role = 'super_admin' LIMIT 1
                    """
                )
                return cursor.fetchone() is not None
