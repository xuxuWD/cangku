from __future__ import annotations

import hmac
import re
import secrets
from datetime import UTC, datetime

from app.audit.models import AuditAction
from app.audit.redaction import mask_phone
from app.audit.service import AuditService
from app.auth import FULL_SCOPE, TOTP_ENROLLMENT_SCOPE
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
    TotpInvalid,
    TotpNotEnrolled,
    TotpRequired,
)
from .passwords import hash_password, verify_password
from .rate_limit import LoginRateLimited, LoginRateLimiter
from .repository import AccountRepository
from .sso import (
    SsoConfig,
    SsoError,
    SsoNotConfigured,
    SsoTransport,
    build_authorization_url,
    complete_authorization,
    generate_pkce_pair,
)
from .sso_store import SsoState, SsoStateNotFound, SsoStateStore
from .totp import generate_secret, normalize_code, provisioning_uri, verify_code


_PHONE_PATTERN = re.compile(r"^1[3-9]\d{9}$")
_TENANT_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{1,63}$")
_SUPPORTED_ROLES = {"employee", "department_lead", "ceo", "super_admin", "customer_admin"}
# 与密码登录一致：强制绑定动态口令的管理员角色集合。
_MFA_ROLES = {"super_admin", "ceo"}


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


def _normalized_identity(position: object, full_name: object) -> tuple[str, str]:
    position_text = position.strip() if isinstance(position, str) else ""
    full_name_text = full_name.strip() if isinstance(full_name, str) else ""
    if not position_text or not full_name_text:
        raise ValueError("职位和姓名不能为空")
    return position_text, full_name_text


def _constant_time_equal(left: object, right: object) -> bool:
    """恒定时间比较两个口令字符串；非字符串或非 ASCII 都不会抛异常。"""
    if not isinstance(left, str) or not isinstance(right, str):
        return False
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


class AccountService:
    def __init__(
        self,
        repository: AccountRepository,
        *,
        bootstrap_token: str = "",
        audit: AuditService,
        login_limiter: LoginRateLimiter,
        require_admin_totp: bool,
        sso_config: SsoConfig | None = None,
        sso_state_store: SsoStateStore | None = None,
        sso_provider: str = "generic_oidc",
        sso_trust_idp_mfa: bool = False,
        sso_state_ttl_seconds: int = 300,
        sso_transport: SsoTransport | None = None,
    ) -> None:
        self.repository = repository
        self.bootstrap_token = bootstrap_token
        self.audit = audit
        self.login_limiter = login_limiter
        self.require_admin_totp = require_admin_totp
        self.sso_config = sso_config
        self.sso_state_store = sso_state_store
        self.sso_provider = sso_provider
        self.sso_trust_idp_mfa = sso_trust_idp_mfa
        self.sso_state_ttl_seconds = sso_state_ttl_seconds
        self.sso_transport = sso_transport

    def request_registration(self, request: RegistrationRequest) -> Account:
        phone = _normalized_phone(request.phone)
        position, full_name = _normalized_identity(request.position, request.full_name)
        if self.repository.find_by_phone(phone) is not None:
            raise AccountConflict("该手机号已提交申请或已注册")

        if self.repository.has_approved_admin():
            created = self.repository.add(
                Account(
                    phone=phone,
                    password_hash=hash_password(request.password),
                    position=position,
                    full_name=full_name,
                    email=request.email,
                )
            )
            self.audit.record(
                AuditAction.ACCOUNT_REGISTRATION_REQUESTED,
                tenant_id=None,
                target_type="account",
                target_id=created.account_id,
                phone_masked=mask_phone(phone),
                detail={"tenant_assigned_at_approval": True},
            )
            return created

        if not self.bootstrap_token or not _constant_time_equal(request.bootstrap_token, self.bootstrap_token):
            raise BootstrapDenied("首个管理员需要正确的初始化口令")
        if not isinstance(request.tenant_id, str) or not request.tenant_id.strip():
            raise BootstrapDenied("首个管理员申请必须声明有效租户")
        try:
            tenant_id = _normalized_tenant(request.tenant_id)
        except ValueError as exc:
            raise BootstrapDenied("首个管理员申请必须声明有效租户") from exc
        now = datetime.now(UTC)
        created = self.repository.add(
            Account(
                phone=phone,
                password_hash=hash_password(request.password),
                position=position,
                full_name=full_name,
                email=request.email,
                role=SUPER_ADMIN_ROLE,
                tenant_id=tenant_id,
                status=AccountStatus.APPROVED,
                reviewed_at=now,
                reviewed_by="bootstrap",
            )
        )
        self.audit.record(
            AuditAction.ACCOUNT_REGISTRATION_REQUESTED,
            tenant_id=tenant_id,
            target_type="account",
            target_id=created.account_id,
            phone_masked=mask_phone(phone),
        )
        self.audit.record(
            AuditAction.ACCOUNT_REGISTRATION_APPROVED,
            tenant_id=tenant_id,
            actor_id=None,
            target_type="account",
            target_id=created.account_id,
            phone_masked=mask_phone(phone),
            detail={"bootstrap": True},
        )
        return created

    def list_requests(self, actor: UserContext, status: AccountStatus = AccountStatus.PENDING) -> list[Account]:
        self._ensure_super_admin(actor)
        return self.repository.list_by_status(status)

    def approve(self, actor: UserContext, account_id: str, *, role: str, tenant_id: str) -> Account:
        self._ensure_super_admin(actor)
        if role not in _SUPPORTED_ROLES:
            raise ValueError("不支持的角色")
        normalized_tenant = _normalized_tenant(tenant_id)
        account = self.repository.mark_approved(
            account_id, role=role, tenant_id=normalized_tenant, reviewed_by=actor.user_id
        )
        self.audit.record(
            AuditAction.ACCOUNT_REGISTRATION_APPROVED,
            tenant_id=normalized_tenant,
            actor_id=actor.user_id,
            target_type="account",
            target_id=account.account_id,
            phone_masked=mask_phone(account.phone),
            detail={"role": role},
        )
        return account

    def reject(self, actor: UserContext, account_id: str, *, reason: str) -> Account:
        self._ensure_super_admin(actor)
        normalized_reason = reason.strip() if isinstance(reason, str) else ""
        if not normalized_reason:
            raise ValueError("驳回原因不能为空")
        account = self.repository.mark_rejected(
            account_id, reason=normalized_reason, reviewed_by=actor.user_id
        )
        self.audit.record(
            AuditAction.ACCOUNT_REGISTRATION_REJECTED,
            tenant_id=actor.tenant_id,
            actor_id=actor.user_id,
            target_type="account",
            target_id=account.account_id,
            phone_masked=mask_phone(account.phone),
            detail={"reason": normalized_reason},
        )
        return account

    def _fail_login(self, phone: str, audit_tenant: str | None) -> LoginFailed:
        """统一的登录失败处理：计数、审计、必要时追加锁定审计，并返回同一文案的异常。"""
        state = self.login_limiter.register_failure(phone)
        self.audit.record(
            AuditAction.ACCOUNT_LOGIN_FAILED,
            tenant_id=audit_tenant,
            target_type="account",
            phone_masked=mask_phone(phone),
        )
        if state.locked_until is not None:
            self.audit.record(
                AuditAction.ACCOUNT_LOGIN_LOCKED,
                tenant_id=audit_tenant,
                target_type="account",
                phone_masked=mask_phone(phone),
                detail={"failure_count": state.failure_count},
            )
        return LoginFailed("手机号或密码不正确")

    def login(
        self, phone: str, password: str, *, totp_code: object = None, now=None
    ) -> UserContext:
        normalized_phone = phone.strip() if isinstance(phone, str) else ""
        moment = now or datetime.now(UTC)
        account = self.repository.find_by_phone(normalized_phone)
        # 登录是匿名入口：账号不存在或尚未分配租户时，审计记录不写租户，但必须写脱敏手机号。
        audit_tenant = str(account.tenant_id) if account is not None and account.tenant_id else None
        try:
            self.login_limiter.require_unlocked(normalized_phone)
        except LoginRateLimited:
            self.audit.record(
                AuditAction.ACCOUNT_LOGIN_LOCKED,
                tenant_id=audit_tenant,
                target_type="account",
                phone_masked=mask_phone(normalized_phone),
            )
            raise
        if account is None or account.status is not AccountStatus.APPROVED:
            raise self._fail_login(normalized_phone, audit_tenant)
        if not verify_password(password, account.password_hash):
            raise self._fail_login(normalized_phone, audit_tenant)
        if account.totp_confirmed_at is not None:
            if normalize_code(totp_code) is None:
                # 用户还没开始猜码，只提示需要验证码，不计入登录限流。
                self.audit.record(
                    AuditAction.ACCOUNT_LOGIN_FAILED,
                    tenant_id=audit_tenant,
                    target_type="account",
                    phone_masked=mask_phone(normalized_phone),
                    detail={"reason": "totp_required"},
                )
                raise TotpRequired("请输入动态验证码")
            step = verify_code(account.totp_secret, totp_code, at=moment)
            if step is None:
                # 先按统一失败处理计数与审计（否则 6 位码可暴力破解），
                # 再抛出可区分的验证码错误，供接口层返回固定文案。
                self._fail_login(normalized_phone, audit_tenant)
                raise TotpInvalid("动态验证码不正确")
            try:
                self.repository.record_totp_step(account.account_id, step)
            except TotpInvalid:
                raise self._fail_login(normalized_phone, audit_tenant)
        elif self.require_admin_totp and account.role in {"super_admin", "ceo"}:
            self.audit.record(
                AuditAction.ACCOUNT_TOTP_ENROLLMENT_REQUIRED,
                tenant_id=audit_tenant,
                actor_id=account.account_id,
                target_type="account",
                target_id=account.account_id,
                phone_masked=mask_phone(normalized_phone),
                detail={"role": account.role},
            )
            return UserContext(
                tenant_id=str(account.tenant_id),
                user_id=account.account_id,
                role=str(account.role),
                scope=TOTP_ENROLLMENT_SCOPE,
            )
        self.login_limiter.register_success(normalized_phone)
        self.audit.record(
            AuditAction.ACCOUNT_LOGIN_SUCCEEDED,
            tenant_id=audit_tenant,
            actor_id=account.account_id,
            target_type="account",
            target_id=account.account_id,
            phone_masked=mask_phone(normalized_phone),
        )
        return UserContext(
            tenant_id=str(account.tenant_id),
            user_id=account.account_id,
            role=str(account.role),
            scope=FULL_SCOPE,
        )

    def _require_sso(self) -> tuple[SsoConfig, SsoStateStore]:
        """SSO 未配置一律 fail-closed。"""
        if self.sso_config is None or self.sso_state_store is None:
            raise SsoNotConfigured("SSO 未启用")
        return self.sso_config, self.sso_state_store

    def _record_sso_rejected(self, reason: str, *, tenant_id: str | None = None) -> None:
        """登录被拒审计：只写固定安全文案，绝不写邮箱、令牌或 IdP 原始响应。"""
        self.audit.record(
            AuditAction.ACCOUNT_SSO_LOGIN_REJECTED,
            tenant_id=tenant_id,
            target_type="account",
            detail={"provider": self.sso_provider, "reason": reason},
        )

    def _account_needs_second_factor(self, account: Account) -> bool:
        """与密码登录一致的二次验证判定：已绑定动态口令的账号需验证码，
        管理员在强制绑定策略下同样需要（未绑定时由后续校验统一拒绝，fail-closed）。"""
        if account.totp_confirmed_at is not None:
            return True
        return self.require_admin_totp and account.role in _MFA_ROLES

    def begin_sso_login(self, *, now=None) -> tuple[str, str]:
        """发起 SSO 登录：生成 state/nonce/PKCE，state 入仓储并返回 (授权地址, state)。"""
        config, state_store = self._require_sso()
        moment = now or datetime.now(UTC)
        state = secrets.token_urlsafe(32)
        verifier, challenge = generate_pkce_pair()
        nonce = secrets.token_urlsafe(16)
        state_store.add(
            SsoState(
                state=state,
                nonce=nonce,
                code_verifier=verifier,
                redirect_uri=config.redirect_uri,
                created_at=moment,
            )
        )
        url = build_authorization_url(config, state=state, nonce=nonce, code_challenge=challenge)
        return url, state

    def complete_sso_login(self, *, code: str, state: str, now=None) -> tuple[Account, bool]:
        """完成 SSO 授权回调：换取并校验身份、按已验证邮箱匹配已审批账号、绑定 sub。

        返回 (账号, 是否需要应用内 TOTP)。**绝不自动建号**；邮箱只用于匹配，不落审计。
        """
        config, state_store = self._require_sso()
        moment = now or datetime.now(UTC)
        try:
            stored = state_store.consume(state, now=moment, ttl_seconds=self.sso_state_ttl_seconds)
        except SsoStateNotFound as exc:
            self._record_sso_rejected("state_invalid")
            raise SsoError("登录会话已失效，请重新发起 SSO 登录") from exc
        try:
            identity = complete_authorization(
                config,
                code=code,
                code_verifier=stored.code_verifier,
                nonce=stored.nonce,
                transport=self.sso_transport,
                now=moment,
            )
        except SsoError as exc:
            self._record_sso_rejected("identity_verification_failed")
            raise
        account = self.repository.find_by_email(identity.email)
        if account is None:
            self._record_sso_rejected("unknown_account")
            raise SsoError("该邮箱没有已审批的账号")
        if account.status is not AccountStatus.APPROVED:
            self._record_sso_rejected("account_not_approved", tenant_id=str(account.tenant_id) if account.tenant_id else None)
            raise SsoError("账号尚未通过审批")
        audit_tenant = str(account.tenant_id) if account.tenant_id else None
        if not account.sso_subject:
            self.repository.set_sso_identity(
                account.account_id, provider=self.sso_provider, subject=identity.subject
            )
            self.audit.record(
                AuditAction.ACCOUNT_SSO_IDENTITY_BOUND,
                tenant_id=audit_tenant,
                actor_id=account.account_id,
                target_type="account",
                target_id=account.account_id,
                phone_masked=mask_phone(account.phone),
                detail={"provider": self.sso_provider},
            )
        elif account.sso_subject != identity.subject:
            self._record_sso_rejected("subject_mismatch", tenant_id=audit_tenant)
            raise SsoError("该账号已绑定其他 SSO 身份")
        requires_totp = (not self.sso_trust_idp_mfa) and self._account_needs_second_factor(account)
        if requires_totp and account.totp_confirmed_at is None:
            # 管理员在强制绑定策略下尚未绑定动态口令：SSO 无法代其完成绑定，
            # 明确要求改走密码登录的绑定流程，且**不发放待验证令牌**（fail-closed）。
            self._record_sso_rejected("totp_enrollment_required", tenant_id=audit_tenant)
            raise SsoError("该账号尚未绑定动态口令，请先用密码登录完成绑定")
        if requires_totp:
            self.audit.record(
                AuditAction.ACCOUNT_SSO_MFA_REQUIRED,
                tenant_id=audit_tenant,
                actor_id=account.account_id,
                target_type="account",
                target_id=account.account_id,
                phone_masked=mask_phone(account.phone),
                detail={"provider": self.sso_provider},
            )
        else:
            self.audit.record(
                AuditAction.ACCOUNT_SSO_LOGIN_SUCCEEDED,
                tenant_id=audit_tenant,
                actor_id=account.account_id,
                target_type="account",
                target_id=account.account_id,
                phone_masked=mask_phone(account.phone),
                detail={"provider": self.sso_provider},
            )
        return account, requires_totp

    def verify_sso_totp(self, account: Account, totp_code: object, *, now=None) -> Account:
        """校验 SSO 后续的应用内 TOTP：复用密码登录的校验与重放防护及失败语义。"""
        moment = now or datetime.now(UTC)
        audit_tenant = str(account.tenant_id) if account.tenant_id else None
        if not account.totp_secret:
            self._fail_login(account.phone, audit_tenant)
            raise TotpInvalid("动态验证码不正确")
        if normalize_code(totp_code) is None:
            self.audit.record(
                AuditAction.ACCOUNT_LOGIN_FAILED,
                tenant_id=audit_tenant,
                target_type="account",
                phone_masked=mask_phone(account.phone),
                detail={"reason": "totp_required"},
            )
            raise TotpRequired("请输入动态验证码")
        step = verify_code(account.totp_secret, totp_code, at=moment)
        if step is None:
            self._fail_login(account.phone, audit_tenant)
            raise TotpInvalid("动态验证码不正确")
        try:
            self.repository.record_totp_step(account.account_id, step)
        except TotpInvalid:
            raise self._fail_login(account.phone, audit_tenant)
        self.login_limiter.register_success(account.phone)
        self.audit.record(
            AuditAction.ACCOUNT_SSO_LOGIN_SUCCEEDED,
            tenant_id=audit_tenant,
            actor_id=account.account_id,
            target_type="account",
            target_id=account.account_id,
            phone_masked=mask_phone(account.phone),
            detail={"provider": self.sso_provider},
        )
        return account

    def change_password(self, actor: UserContext, *, old_password: str, new_password: str) -> None:
        try:
            account = self.repository.get(actor.user_id)
        except AccountNotFound as exc:
            raise LoginFailed("账号不可用") from exc
        if not verify_password(old_password, account.password_hash):
            raise LoginFailed("原密码不正确")
        self.repository.update_password(account.account_id, hash_password(new_password))
        self.audit.record(
            AuditAction.ACCOUNT_PASSWORD_CHANGED,
            tenant_id=actor.tenant_id,
            actor_id=actor.user_id,
            target_type="account",
            target_id=account.account_id,
            phone_masked=mask_phone(account.phone),
        )

    def reset_password(self, actor: UserContext, account_id: str, *, new_password: str) -> None:
        self._ensure_super_admin(actor)
        account = self.repository.update_password(account_id, hash_password(new_password))
        self.audit.record(
            AuditAction.ACCOUNT_PASSWORD_RESET,
            tenant_id=actor.tenant_id,
            actor_id=actor.user_id,
            target_type="account",
            target_id=account.account_id,
            phone_masked=mask_phone(account.phone),
        )

    def start_totp_enrollment(self, actor: UserContext) -> tuple[str, str]:
        """生成本人的新种子并返回 (secret, otpauth_uri)。此时尚未确认启用。"""
        account = self.repository.get(actor.user_id)
        secret = generate_secret()
        uri = provisioning_uri(secret, account_name=mask_phone(account.phone))
        self.repository.set_totp(account.account_id, secret)
        self.audit.record(
            AuditAction.ACCOUNT_TOTP_ENROLLED,
            tenant_id=actor.tenant_id,
            actor_id=actor.user_id,
            target_type="account",
            target_id=account.account_id,
            phone_masked=mask_phone(account.phone),
        )
        return secret, uri

    def confirm_totp_enrollment(self, actor: UserContext, code: object, *, now=None) -> None:
        account = self.repository.get(actor.user_id)
        if not account.totp_secret:
            raise TotpNotEnrolled("尚未开始绑定动态口令")
        step = verify_code(account.totp_secret, code, at=now or datetime.now(UTC))
        if step is None:
            raise TotpInvalid("动态验证码不正确")
        self.repository.confirm_totp(account.account_id, step=step)
        self.audit.record(
            AuditAction.ACCOUNT_TOTP_CONFIRMED,
            tenant_id=actor.tenant_id,
            actor_id=actor.user_id,
            target_type="account",
            target_id=account.account_id,
            phone_masked=mask_phone(account.phone),
        )

    def reset_totp(self, actor: UserContext, account_id: str) -> None:
        self._ensure_super_admin(actor)
        account = self.repository.clear_totp(account_id)
        self.audit.record(
            AuditAction.ACCOUNT_TOTP_RESET,
            tenant_id=actor.tenant_id,
            actor_id=actor.user_id,
            target_type="account",
            target_id=account.account_id,
            phone_masked=mask_phone(account.phone),
        )

    @staticmethod
    def _ensure_super_admin(actor: UserContext) -> None:
        if actor.role != SUPER_ADMIN_ROLE:
            raise PolicyError("只有超级管理员可以管理账号申请")
