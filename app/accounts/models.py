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


class TotpRequired(ValueError):
    """账号已绑定动态口令，本次登录必须提供验证码。"""


class TotpInvalid(ValueError):
    """动态口令验证码错误，或命中了已使用过的步号（重放）。"""


class TotpNotEnrolled(ValueError):
    """目标账号尚未绑定动态口令。"""


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
    # 动态口令（TOTP）：密钥为 base32 文本；confirmed_at 非空表示已启用；
    # last_step 记录最近一次成功校验的步号，用于拒绝同一窗口内的重放。
    totp_secret: str | None = None
    totp_confirmed_at: datetime | None = None
    totp_last_step: int | None = None
    # SSO 单点登录身份绑定：provider 为 IdP 标识，subject 为 IdP 侧稳定用户标识。
    sso_provider: str | None = None
    sso_subject: str | None = None
