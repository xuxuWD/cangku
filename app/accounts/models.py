from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4


SUPER_ADMIN_ROLE = "super_admin"


class AccountStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class AccountConflict(ValueError):
    """手机号已被申请或注册。"""


class AccountNotFound(LookupError):
    pass


class AccountStateConflict(ValueError):
    pass


class BootstrapDenied(ValueError):
    """首个管理员申请缺少正确的初始化口令或租户。"""


class LoginFailed(ValueError):
    """登录或口令校验失败，详情不对外区分。"""


@dataclass(frozen=True)
class RegistrationRequest:
    phone: str
    password: str
    position: str
    full_name: str
    email: str | None = None
    tenant_id: str | None = None
    bootstrap_token: str | None = None


@dataclass
class Account:
    phone: str
    password_hash: str
    position: str
    full_name: str
    email: str | None = None
    account_id: str = field(default_factory=lambda: f"acct-{uuid4().hex[:12]}")
    role: str | None = None
    tenant_id: str | None = None
    status: AccountStatus = AccountStatus.PENDING
    requested_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    reviewed_at: datetime | None = None
    reviewed_by: str | None = None
    rejection_reason: str | None = None
