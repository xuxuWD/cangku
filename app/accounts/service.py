from __future__ import annotations

import hmac
import re
from datetime import UTC, datetime

from app.domain import PolicyError, UserContext

from .models import (
    SUPER_ADMIN_ROLE,
    Account,
    AccountConflict,
    AccountNotFound,
    AccountStatus,
    BootstrapDenied,
    LoginFailed,
    RegistrationRequest,
)
from .passwords import hash_password, verify_password
from .repository import AccountRepository


_PHONE_PATTERN = re.compile(r"^1[3-9]\d{9}$")
_TENANT_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{1,63}$")
_SUPPORTED_ROLES = {"employee", "department_lead", "ceo", "super_admin", "customer_admin"}


def _normalized_phone(phone: object) -> str:
    value = phone.strip() if isinstance(phone, str) else ""
    if not _PHONE_PATTERN.match(value):
        raise ValueError("手机号格式不正确")
    return value


def _normalized_tenant(tenant_id: object) -> str:
    value = tenant_id.strip() if isinstance(tenant_id, str) else ""
    if not _TENANT_PATTERN.match(value):
        raise ValueError("租户标识无效")
    return value


def _constant_time_equal(left: object, right: object) -> bool:
    """恒定时间比较两个口令字符串；非字符串或非 ASCII 都不会抛异常。"""
    if not isinstance(left, str) or not isinstance(right, str):
        return False
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


class AccountService:
    def __init__(self, repository: AccountRepository, *, bootstrap_token: str = "") -> None:
        self.repository = repository
        self.bootstrap_token = bootstrap_token

    def request_registration(self, request: RegistrationRequest) -> Account:
        phone = _normalized_phone(request.phone)
        if self.repository.find_by_phone(phone) is not None:
            raise AccountConflict("该手机号已提交申请或已注册")

        if self.repository.has_approved_admin():
            return self.repository.add(
                Account(
                    phone=phone,
                    password_hash=hash_password(request.password),
                    position=request.position.strip(),
                    full_name=request.full_name.strip(),
                    email=request.email,
                )
            )

        if not self.bootstrap_token or not _constant_time_equal(request.bootstrap_token, self.bootstrap_token):
            raise BootstrapDenied("首个管理员需要正确的初始化口令")
        if not isinstance(request.tenant_id, str) or not request.tenant_id.strip():
            raise BootstrapDenied("首个管理员申请必须声明有效租户")
        try:
            tenant_id = _normalized_tenant(request.tenant_id)
        except ValueError as exc:
            raise BootstrapDenied("首个管理员申请必须声明有效租户") from exc
        now = datetime.now(UTC)
        return self.repository.add(
            Account(
                phone=phone,
                password_hash=hash_password(request.password),
                position=request.position.strip(),
                full_name=request.full_name.strip(),
                email=request.email,
                role=SUPER_ADMIN_ROLE,
                tenant_id=tenant_id,
                status=AccountStatus.APPROVED,
                reviewed_at=now,
                reviewed_by="bootstrap",
            )
        )

    def list_requests(self, actor: UserContext, status: AccountStatus = AccountStatus.PENDING) -> list[Account]:
        self._ensure_super_admin(actor)
        return self.repository.list_by_status(status)

    def approve(self, actor: UserContext, account_id: str, *, role: str, tenant_id: str) -> Account:
        self._ensure_super_admin(actor)
        if role not in _SUPPORTED_ROLES:
            raise ValueError("不支持的角色")
        normalized_tenant = _normalized_tenant(tenant_id)
        return self.repository.mark_approved(
            account_id, role=role, tenant_id=normalized_tenant, reviewed_by=actor.user_id
        )

    def reject(self, actor: UserContext, account_id: str, *, reason: str) -> Account:
        self._ensure_super_admin(actor)
        normalized_reason = reason.strip() if isinstance(reason, str) else ""
        if not normalized_reason:
            raise ValueError("驳回原因不能为空")
        return self.repository.mark_rejected(
            account_id, reason=normalized_reason, reviewed_by=actor.user_id
        )

    def login(self, phone: str, password: str) -> UserContext:
        account = self.repository.find_by_phone(phone.strip() if isinstance(phone, str) else "")
        if account is None or account.status != AccountStatus.APPROVED:
            raise LoginFailed("手机号或密码不正确")
        if not verify_password(password, account.password_hash):
            raise LoginFailed("手机号或密码不正确")
        return UserContext(
            tenant_id=str(account.tenant_id), user_id=account.account_id, role=str(account.role)
        )

    def change_password(self, actor: UserContext, *, old_password: str, new_password: str) -> None:
        try:
            account = self.repository.get(actor.user_id)
        except AccountNotFound as exc:
            raise LoginFailed("账号不可用") from exc
        if not verify_password(old_password, account.password_hash):
            raise LoginFailed("原密码不正确")
        self.repository.update_password(account.account_id, hash_password(new_password))

    def reset_password(self, actor: UserContext, account_id: str, *, new_password: str) -> None:
        self._ensure_super_admin(actor)
        self.repository.update_password(account_id, hash_password(new_password))

    @staticmethod
    def _ensure_super_admin(actor: UserContext) -> None:
        if actor.role != SUPER_ADMIN_ROLE:
            raise PolicyError("只有超级管理员可以管理账号申请")
