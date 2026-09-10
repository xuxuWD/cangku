# 账号注册审批与登录 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让工作台具备自建账号体系：手机号提交注册申请、超级管理员审批并指定角色与租户、审批通过后登录换取带过期的会话令牌，并支持本人改密与管理员重置密码。

**Architecture:** 新增独立的 `app/accounts` 领域包（模型、密码、仓储、服务），与现有控制平面解耦；仓储提供内存实现与 PostgreSQL 实现，由 `bootstrap.py` 按 `WORKBENCH_STORAGE_BACKEND` 装配。会话令牌扩展现有 `app/auth.py` 的 HMAC 方案，增加 `exp`/`iat`/`jti`，不引入签名库。接口层只做校验、身份解析和错误映射。

**Tech Stack:** Python 3.11+、FastAPI、Pydantic v2、标准库 `hashlib.scrypt`、pytest、PostgreSQL（psycopg3）。

**参考规格：** [`docs/superpowers/specs/2026-09-10-account-registration-design.md`](../specs/2026-09-10-account-registration-design.md)

---

## 文件结构

| 文件 | 职责 |
| --- | --- |
| `app/accounts/__init__.py` | 包标记 |
| `app/accounts/models.py` | 账号模型、状态、注册请求、领域异常 |
| `app/accounts/passwords.py` | scrypt 口令哈希与恒定时间校验 |
| `app/accounts/repository.py` | 仓储协议 + 内存实现 + PostgreSQL 实现 |
| `app/accounts/service.py` | 注册、审批、登录、改密、重置的业务规则 |
| `app/auth.py`（修改） | 会话令牌增加过期、签发时间、唯一号 |
| `app/settings.py`（修改） | 新增 `bootstrap_token` 与 `session_ttl_seconds` |
| `app/bootstrap.py`（修改） | 装配账号服务与仓储 |
| `app/main.py`（修改） | 7 个账号接口与身份解析 |
| `migrations/008_accounts.sql`（新增） | `workbench_accounts` 表 |
| `tests/test_account_passwords.py` | 口令测试 |
| `tests/test_account_repository.py` | 内存仓储测试 |
| `tests/test_account_service.py` | 服务测试 |
| `tests/test_account_auth.py` | 令牌与配置测试 |
| `tests/test_account_api.py` | 接口测试 |
| `tests/test_account_postgres.py` | PostgreSQL 仓储契约测试 |

**约定：** 本仓库测试命令用 `py -m pytest`（该机器 `python` 不在 PATH）。禁止提交 `.env`、密钥、口令或口令哈希。

---

### Task 1: 口令哈希模块

**Files:**
- Create: `app/accounts/__init__.py`
- Create: `app/accounts/passwords.py`
- Test: `tests/test_account_passwords.py`

- [ ] **Step 1: 写失败测试**

```python
import pytest

from app.accounts.passwords import (
    MAX_PASSWORD_LENGTH,
    MIN_PASSWORD_LENGTH,
    PasswordPolicyError,
    hash_password,
    verify_password,
)


def test_hash_then_verify_succeeds() -> None:
    encoded = hash_password("correct-horse-battery")

    assert verify_password("correct-horse-battery", encoded) is True


def test_wrong_password_is_rejected() -> None:
    encoded = hash_password("correct-horse-battery")

    assert verify_password("wrong-horse-battery", encoded) is False


def test_same_password_hashes_differently_because_of_salt() -> None:
    assert hash_password("correct-horse-battery") != hash_password("correct-horse-battery")


def test_password_length_policy_is_enforced() -> None:
    with pytest.raises(PasswordPolicyError, match="口令长度"):
        hash_password("short")
    with pytest.raises(PasswordPolicyError, match="口令长度"):
        hash_password("x" * (MAX_PASSWORD_LENGTH + 1))
    with pytest.raises(PasswordPolicyError, match="控制字符"):
        hash_password("line\nbreak-passwords")


def test_verify_returns_false_for_damaged_encoding() -> None:
    assert verify_password("correct-horse-battery", "not-a-valid-encoding") is False
    assert verify_password("correct-horse-battery", "") is False


def test_minimum_length_constant_matches_policy() -> None:
    with pytest.raises(PasswordPolicyError):
        hash_password("x" * (MIN_PASSWORD_LENGTH - 1))
```

- [ ] **Step 2: 运行测试确认失败**

Run: `py -m pytest tests/test_account_passwords.py -q`
Expected: FAIL，`ModuleNotFoundError: No module named 'app.accounts'`

- [ ] **Step 3: 创建包标记与实现**

`app/accounts/__init__.py`：

```python
"""账号注册、审批与登录领域。"""
```

`app/accounts/passwords.py`：

```python
from __future__ import annotations

import base64
import hashlib
import hmac
import os

MIN_PASSWORD_LENGTH = 10
MAX_PASSWORD_LENGTH = 128
_SCRYPT_N = 16384
_SCRYPT_R = 8
_SCRYPT_P = 1
_SALT_BYTES = 16
_DERIVED_BYTES = 32


class PasswordPolicyError(ValueError):
    """口令不满足最小安全策略。"""


def _validate(password: object) -> None:
    if not isinstance(password, str):
        raise PasswordPolicyError("口令必须是文本")
    if len(password) < MIN_PASSWORD_LENGTH or len(password) > MAX_PASSWORD_LENGTH:
        raise PasswordPolicyError(f"口令长度必须在 {MIN_PASSWORD_LENGTH} 到 {MAX_PASSWORD_LENGTH} 之间")
    if any(ord(char) < 32 or ord(char) == 127 for char in password):
        raise PasswordPolicyError("口令不能包含控制字符")


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def hash_password(password: str) -> str:
    """使用 scrypt 加随机盐哈希口令，输出自描述字符串。"""
    _validate(password)
    salt = os.urandom(_SALT_BYTES)
    derived = hashlib.scrypt(
        password.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=_DERIVED_BYTES
    )
    return "$".join(
        ["scrypt", str(_SCRYPT_N), str(_SCRYPT_R), str(_SCRYPT_P), _b64encode(salt), _b64encode(derived)]
    )


def verify_password(password: str, encoded: str) -> bool:
    """恒定时间校验口令；任何解析失败都返回 False，不抛异常。"""
    try:
        scheme, n, r, p, salt_b64, hash_b64 = encoded.split("$")
        if scheme != "scrypt":
            return False
        salt = _b64decode(salt_b64)
        expected = _b64decode(hash_b64)
        derived = hashlib.scrypt(
            password.encode(), salt=salt, n=int(n), r=int(r), p=int(p), dklen=len(expected)
        )
        return hmac.compare_digest(derived, expected)
    except (AttributeError, TypeError, ValueError):
        return False
```

- [ ] **Step 4: 运行测试确认通过**

Run: `py -m pytest tests/test_account_passwords.py -q`
Expected: PASS（6 passed）

- [ ] **Step 5: 提交**

```bash
git add app/accounts/__init__.py app/accounts/passwords.py tests/test_account_passwords.py
git commit -m "feat: 增加账号口令哈希模块"
```

---

### Task 2: 账号模型与内存仓储

**Files:**
- Create: `app/accounts/models.py`
- Create: `app/accounts/repository.py`
- Test: `tests/test_account_repository.py`

- [ ] **Step 1: 写失败测试**

```python
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `py -m pytest tests/test_account_repository.py -q`
Expected: FAIL，`ModuleNotFoundError: No module named 'app.accounts.models'`

- [ ] **Step 3: 实现模型与仓储**

`app/accounts/models.py`：

```python
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
```

`app/accounts/repository.py`：

```python
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
```

- [ ] **Step 4: 运行测试确认通过**

Run: `py -m pytest tests/test_account_repository.py -q`
Expected: PASS（9 passed）

- [ ] **Step 5: 提交**

```bash
git add app/accounts/models.py app/accounts/repository.py tests/test_account_repository.py
git commit -m "feat: 增加账号模型与内存仓储"
```

---

### Task 3: 账号注册审批服务

**Files:**
- Create: `app/accounts/service.py`
- Test: `tests/test_account_service.py`

- [ ] **Step 1: 写失败测试**

```python
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
from app.accounts.repository import InMemoryAccountRepository
from app.accounts.service import AccountService
from app.domain import PolicyError, UserContext

BOOTSTRAP = "bootstrap-secret-value"
PASSWORD = "correct-horse-battery"


def service(*, bootstrap_token: str = BOOTSTRAP) -> AccountService:
    return AccountService(InMemoryAccountRepository(), bootstrap_token=bootstrap_token)


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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `py -m pytest tests/test_account_service.py -q`
Expected: FAIL，`ModuleNotFoundError: No module named 'app.accounts.service'`

- [ ] **Step 3: 实现服务**

`app/accounts/service.py`：

```python
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


class AccountService:
    def __init__(self, repository: AccountRepository, *, bootstrap_token: str = "") -> None:
        self.repository = repository
        self.bootstrap_token = bootstrap_token

    def request_registration(self, request: RegistrationRequest) -> Account:
        phone = _normalized_phone(request.phone)
        if self.repository.find_by_phone(phone) is not None:
            raise AccountConflict("该手机号已提交申请或已注册")
        password_hash = hash_password(request.password)

        if not self.repository.has_approved_admin():
            if (
                not self.bootstrap_token
                or not request.bootstrap_token
                or not hmac.compare_digest(request.bootstrap_token, self.bootstrap_token)
            ):
                raise BootstrapDenied("首个管理员需要正确的初始化口令")
            tenant_id = _normalized_tenant(request.tenant_id) if request.tenant_id else None
            if tenant_id is None:
                raise BootstrapDenied("首个管理员申请必须声明有效租户")
            now = datetime.now(UTC)
            return self.repository.add(
                Account(
                    phone=phone,
                    password_hash=password_hash,
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

        return self.repository.add(
            Account(
                phone=phone,
                password_hash=password_hash,
                position=request.position.strip(),
                full_name=request.full_name.strip(),
                email=request.email,
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
        if account is None or account.status is not AccountStatus.APPROVED:
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
```

- [ ] **Step 4: 运行测试确认通过**

Run: `py -m pytest tests/test_account_service.py -q`
Expected: PASS（14 passed）

- [ ] **Step 5: 提交**

```bash
git add app/accounts/service.py tests/test_account_service.py
git commit -m "feat: 增加账号注册审批服务"
```

---

### Task 4: 会话令牌过期与账号配置

**Files:**
- Modify: `app/auth.py`
- Modify: `app/settings.py`
- Modify: `tests/test_control_plane.py:202`
- Test: `tests/test_account_auth.py`

- [ ] **Step 1: 写失败测试**

```python
import base64
import hashlib
import hmac
import json

import pytest
from pydantic import ValidationError

from app.auth import create_access_token, verify_access_token
from app.domain import UserContext
from app.settings import Settings

SECRET = "s" * 40


def raw_token(payload: dict[str, object], secret: str = SECRET) -> str:
    encoded = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode()
    ).rstrip(b"=")
    signature = hmac.new(secret.encode(), encoded, hashlib.sha256).digest()
    return encoded.decode() + "." + base64.urlsafe_b64encode(signature).rstrip(b"=").decode()


def test_session_token_round_trips_identity() -> None:
    token = create_access_token(UserContext("t-1", "acct-1", "employee"), SECRET, ttl_seconds=900)

    context = verify_access_token(token, SECRET)

    assert (context.tenant_id, context.user_id, context.role) == ("t-1", "acct-1", "employee")


def test_expired_token_is_rejected() -> None:
    token = create_access_token(UserContext("t-1", "acct-1", "employee"), SECRET, ttl_seconds=-1)

    with pytest.raises(ValueError, match="登录凭证无效"):
        verify_access_token(token, SECRET)


def test_token_without_expiry_is_rejected() -> None:
    token = raw_token({"tenant_id": "t-1", "user_id": "acct-1", "role": "employee"})

    with pytest.raises(ValueError, match="登录凭证无效"):
        verify_access_token(token, SECRET)


def test_tampered_token_is_rejected() -> None:
    token = create_access_token(UserContext("t-1", "acct-1", "employee"), SECRET, ttl_seconds=900)

    with pytest.raises(ValueError, match="登录凭证无效"):
        verify_access_token(token + "tampered", SECRET)
    with pytest.raises(ValueError, match="登录凭证无效"):
        verify_access_token(token, "other-secret-value")


def test_session_ttl_default_and_bounds() -> None:
    assert Settings().session_ttl_seconds == 900

    with pytest.raises(ValidationError):
        Settings(session_ttl_seconds=10)
    with pytest.raises(ValidationError):
        Settings(session_ttl_seconds=99999)


def test_bootstrap_token_defaults_to_empty() -> None:
    assert Settings().bootstrap_token == ""
```

- [ ] **Step 2: 运行测试确认失败**

Run: `py -m pytest tests/test_account_auth.py -q`
Expected: FAIL，`TypeError: create_access_token() got an unexpected keyword argument 'ttl_seconds'`

- [ ] **Step 3: 修改会话令牌与配置**

`app/auth.py` 全量替换：

```python
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from .domain import UserContext


def create_access_token(context: UserContext, secret: str, *, ttl_seconds: int) -> str:
    """签发带过期时间的会话令牌；TTL 由调用方传入，本模块不读取配置。"""
    if not secret:
        raise ValueError("认证密钥不能为空")
    issued_at = datetime.now(UTC)
    payload = json.dumps(
        {
            "tenant_id": context.tenant_id,
            "user_id": context.user_id,
            "role": context.role,
            "iat": int(issued_at.timestamp()),
            "exp": int((issued_at + timedelta(seconds=ttl_seconds)).timestamp()),
            "jti": uuid4().hex,
        },
        separators=(",", ":"),
    ).encode()
    encoded = base64.urlsafe_b64encode(payload).rstrip(b"=")
    signature = hmac.new(secret.encode(), encoded, hashlib.sha256).digest()
    return encoded.decode() + "." + base64.urlsafe_b64encode(signature).rstrip(b"=").decode()


def verify_access_token(token: str, secret: str) -> UserContext:
    try:
        encoded, supplied_signature = token.split(".", 1)
        expected = hmac.new(secret.encode(), encoded.encode(), hashlib.sha256).digest()
        actual = base64.urlsafe_b64decode(supplied_signature + "=" * (-len(supplied_signature) % 4))
        if not hmac.compare_digest(expected, actual):
            raise ValueError("签名无效")
        payload = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        data = json.loads(payload)
        expires_at = data["exp"]
        if not isinstance(expires_at, int) or isinstance(expires_at, bool):
            raise ValueError("缺少过期时间")
        if datetime.now(UTC).timestamp() >= expires_at:
            raise ValueError("登录凭证已过期")
        return UserContext(
            tenant_id=str(data["tenant_id"]),
            user_id=str(data["user_id"]),
            role=str(data["role"]),
        )
    except (KeyError, ValueError, TypeError, binascii.Error, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("登录凭证无效") from exc
```

`app/settings.py` 在 `Settings` 内、`content_model_max_retries` 之后追加两个字段：

```python
    bootstrap_token: str = Field(
        default="",
        validation_alias=AliasChoices("BOOTSTRAP_TOKEN", "WORKBENCH_BOOTSTRAP_TOKEN"),
    )
    session_ttl_seconds: int = Field(
        default=900,
        ge=60,
        le=3600,
        validation_alias=AliasChoices("SESSION_TTL_SECONDS", "WORKBENCH_SESSION_TTL_SECONDS"),
    )
```

`tests/test_control_plane.py` 第 202 行改为：

```python
        token = create_access_token(
            UserContext("t-signed", "u-signed", "employee"), "test-secret", ttl_seconds=900
        )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `py -m pytest tests/test_account_auth.py tests/test_control_plane.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add app/auth.py app/settings.py tests/test_account_auth.py tests/test_control_plane.py
git commit -m "feat: 会话令牌增加过期与账号配置"
```

---

### Task 5: 装配账号服务

**Files:**
- Modify: `app/bootstrap.py`
- Test: `tests/test_account_postgres.py`（本任务只加装配用例，PostgreSQL 用例在 Task 7 补全）

- [ ] **Step 1: 写失败测试**

```python
import pytest

from app.accounts.repository import InMemoryAccountRepository
from app.bootstrap import build_account_service
from app.settings import Settings


def postgres_settings() -> Settings:
    return Settings(
        env="production",
        storage_backend="postgres",
        database_url="postgresql://workbench:pw@pg.internal:5432/workbench",
        auth_secret="a" * 32,
        backup_encryption_key="b" * 32,
    )


def test_memory_backend_returns_in_memory_repository() -> None:
    settings = Settings(env="development", storage_backend="memory", bootstrap_token="boot-secret")

    service, repository = build_account_service(settings)

    assert isinstance(repository, InMemoryAccountRepository)
    assert service.bootstrap_token == "boot-secret"


def test_production_requires_postgres_backend() -> None:
    settings = Settings(env="development", storage_backend="sqlite")

    with pytest.raises(ValueError, match="账号存储类型"):
        build_account_service(settings)


def test_postgres_backend_uses_injected_connection() -> None:
    service, repository = build_account_service(postgres_settings(), connection=object(), migrate=False)

    assert not isinstance(repository, InMemoryAccountRepository)
    assert service.repository is repository


def test_postgres_backend_exposes_account_repository_contract() -> None:
    _service, repository = build_account_service(postgres_settings(), connection=object(), migrate=False)

    for name in (
        "add",
        "find_by_phone",
        "get",
        "list_by_status",
        "mark_approved",
        "mark_rejected",
        "update_password",
        "has_approved_admin",
    ):
        assert callable(getattr(repository, name))
```

> 说明：`PostgresAccountRepository` 类在 Task 7 创建，因此本任务只用鸭子类型断言；Task 7 会把它升级为 `isinstance` 断言。

- [ ] **Step 2: 运行测试确认失败**

Run: `py -m pytest tests/test_account_postgres.py -q`
Expected: FAIL，`ImportError: cannot import name 'build_account_service'` 与 `ModuleNotFoundError: No module named 'app.accounts.repository'`

- [ ] **Step 3: 实现装配函数**

在 `app/bootstrap.py` 顶部 import 区加入：

```python
from .accounts.repository import InMemoryAccountRepository
from .accounts.service import AccountService
```

在文件末尾追加：

```python
def build_account_service(settings: Settings, *, connection=None, migrate: bool = True) -> tuple[AccountService, object]:
    """按存储模式装配账号仓储与服务。"""
    validate_runtime_settings(settings)
    if settings.storage_backend == "memory":
        if settings.env != "development":
            raise ValueError("生产环境禁止使用内存账号仓储")
        repository = InMemoryAccountRepository()
    elif settings.storage_backend == "postgres":
        from .accounts.repository import PostgresAccountRepository

        if connection is None:
            from psycopg_pool import ConnectionPool

            database_url = settings.database_url.replace("postgresql+psycopg://", "postgresql://", 1)
            connection = ConnectionPool(database_url, min_size=1, max_size=10, open=True)
        if migrate:
            apply_migrations(connection, Path(__file__).resolve().parents[1] / "migrations")
        repository = PostgresAccountRepository(connection)
    else:
        raise ValueError("不支持的账号存储类型")
    return AccountService(repository, bootstrap_token=settings.bootstrap_token), repository
```

- [ ] **Step 4: 运行测试确认通过**

Run: `py -m pytest tests/test_account_postgres.py -q`
Expected: PASS（4 passed）

- [ ] **Step 5: 提交**

```bash
git add app/bootstrap.py tests/test_account_postgres.py
git commit -m "feat: 装配账号服务与仓储"
```

---

### Task 6: 账号注册登录接口

**Files:**
- Modify: `app/main.py`
- Test: `tests/test_account_api.py`

- [ ] **Step 1: 写失败测试**

```python
import pytest
from fastapi.testclient import TestClient

from app import main
from app.accounts.models import SUPER_ADMIN_ROLE
from app.accounts.repository import InMemoryAccountRepository
from app.accounts.service import AccountService
from app.main import app

client = TestClient(app)

BOOTSTRAP = "bootstrap-secret-value"
PASSWORD = "correct-horse-battery"
SECRET = "s" * 40


@pytest.fixture
def accounts(monkeypatch) -> AccountService:
    service = AccountService(InMemoryAccountRepository(), bootstrap_token=BOOTSTRAP)
    monkeypatch.setattr(main, "account_service", service)
    monkeypatch.setattr(main.settings, "auth_secret", SECRET)
    monkeypatch.setattr(main.settings, "session_ttl_seconds", 900)
    return service


def registration_body(phone: str = "13800000001", **overrides) -> dict[str, object]:
    body = {
        "phone": phone,
        "password": PASSWORD,
        "position": "内容运营",
        "full_name": "张三",
    }
    body.update(overrides)
    return body


def register_admin(accounts: AccountService) -> dict[str, object]:
    response = client.post(
        "/api/v1/auth/registrations",
        json=registration_body(tenant_id="t-1", bootstrap_token=BOOTSTRAP),
    )
    assert response.status_code == 201
    return response.json()


def login(phone: str, password: str = PASSWORD) -> dict[str, object]:
    return client.post("/api/v1/auth/sessions", json={"phone": phone, "password": password})


def test_first_registration_without_bootstrap_token_is_forbidden(accounts: AccountService) -> None:
    response = client.post("/api/v1/auth/registrations", json=registration_body(tenant_id="t-1"))

    assert response.status_code == 403


def test_first_registration_creates_approved_admin(accounts: AccountService) -> None:
    body = register_admin(accounts)

    assert body["status"] == "approved"
    assert body["role"] == SUPER_ADMIN_ROLE
    assert body["tenant_id"] == "t-1"
    assert "password" not in body
    assert "password_hash" not in body
    assert BOOTSTRAP not in str(body)


def test_registration_response_masks_phone(accounts: AccountService) -> None:
    body = register_admin(accounts)

    assert body["phone"] == "138****0001"


def test_duplicate_phone_returns_conflict(accounts: AccountService) -> None:
    register_admin(accounts)

    response = client.post(
        "/api/v1/auth/registrations", json=registration_body(tenant_id="t-1", bootstrap_token=BOOTSTRAP)
    )

    assert response.status_code == 409


def test_short_password_is_rejected_by_schema(accounts: AccountService) -> None:
    response = client.post("/api/v1/auth/registrations", json=registration_body(password="short"))

    assert response.status_code == 422


def test_pending_account_cannot_login_then_can_after_approval(accounts: AccountService) -> None:
    admin = register_admin(accounts)
    pending = client.post("/api/v1/auth/registrations", json=registration_body("13800000002")).json()

    assert login("13800000002").status_code == 401

    admin_headers = {
        "X-Tenant-Id": "t-1",
        "X-User-Id": admin["account_id"],
        "X-User-Role": SUPER_ADMIN_ROLE,
    }
    listed = client.get("/api/v1/auth/registrations", headers=admin_headers)
    assert listed.status_code == 200
    assert [item["account_id"] for item in listed.json()] == [pending["account_id"]]

    approved = client.post(
        f"/api/v1/auth/registrations/{pending['account_id']}/approval",
        headers=admin_headers,
        json={"role": "employee", "tenant_id": "t-1"},
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"

    session = login("13800000002")
    assert session.status_code == 200
    assert session.json()["role"] == "employee"
    assert session.json()["tenant_id"] == "t-1"
    assert session.json()["expires_in"] == 900


def test_rejection_keeps_account_locked(accounts: AccountService) -> None:
    admin = register_admin(accounts)
    pending = client.post("/api/v1/auth/registrations", json=registration_body("13800000002")).json()
    admin_headers = {
        "X-Tenant-Id": "t-1",
        "X-User-Id": admin["account_id"],
        "X-User-Role": SUPER_ADMIN_ROLE,
    }

    rejected = client.post(
        f"/api/v1/auth/registrations/{pending['account_id']}/rejection",
        headers=admin_headers,
        json={"reason": "资料不完整"},
    )

    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    assert login("13800000002").status_code == 401


def test_non_admin_cannot_read_registrations(accounts: AccountService) -> None:
    register_admin(accounts)

    response = client.get(
        "/api/v1/auth/registrations",
        headers={"X-Tenant-Id": "t-1", "X-User-Id": "acct-x", "X-User-Role": "employee"},
    )

    assert response.status_code == 403


def test_session_token_authorizes_requests_and_overrides_forged_headers(accounts: AccountService) -> None:
    admin = register_admin(accounts)
    token = login(admin["phone"], PASSWORD).json()["access_token"]

    response = client.get(
        "/api/v1/auth/registrations",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Tenant-Id": "forged-tenant",
            "X-User-Id": "forged-user",
            "X-User-Role": "employee",
        },
    )

    assert response.status_code == 200


def test_login_with_wrong_password_is_unauthorized(accounts: AccountService) -> None:
    admin = register_admin(accounts)

    assert login(admin["phone"], "wrong-horse-battery").status_code == 401


def test_change_own_password_requires_current_password(accounts: AccountService) -> None:
    admin = register_admin(accounts)
    headers = {"X-Tenant-Id": "t-1", "X-User-Id": admin["account_id"], "X-User-Role": SUPER_ADMIN_ROLE}

    wrong = client.put(
        "/api/v1/auth/me/password",
        headers=headers,
        json={"old_password": "wrong-horse-battery", "new_password": "brand-new-passphrase"},
    )
    assert wrong.status_code == 401

    updated = client.put(
        "/api/v1/auth/me/password",
        headers=headers,
        json={"old_password": PASSWORD, "new_password": "brand-new-passphrase"},
    )
    assert updated.status_code == 200
    assert login(admin["phone"], "brand-new-passphrase").status_code == 200
    assert login(admin["phone"], PASSWORD).status_code == 401


def test_admin_can_reset_password_and_employee_cannot(accounts: AccountService) -> None:
    admin = register_admin(accounts)
    other = client.post("/api/v1/auth/registrations", json=registration_body("13800000002")).json()
    admin_headers = {
        "X-Tenant-Id": "t-1",
        "X-User-Id": admin["account_id"],
        "X-User-Role": SUPER_ADMIN_ROLE,
    }
    client.post(
        f"/api/v1/auth/registrations/{other['account_id']}/approval",
        headers=admin_headers,
        json={"role": "employee", "tenant_id": "t-1"},
    )

    forbidden = client.post(
        f"/api/v1/auth/accounts/{other['account_id']}/password",
        headers={"X-Tenant-Id": "t-1", "X-User-Id": other["account_id"], "X-User-Role": "employee"},
        json={"new_password": "another-passphrase"},
    )
    assert forbidden.status_code == 403

    reset = client.post(
        f"/api/v1/auth/accounts/{other['account_id']}/password",
        headers=admin_headers,
        json={"new_password": "another-passphrase"},
    )
    assert reset.status_code == 200
    assert login("13800000002", "another-passphrase").status_code == 200


def test_reset_unknown_account_returns_not_found(accounts: AccountService) -> None:
    admin = register_admin(accounts)

    response = client.post(
        "/api/v1/auth/accounts/acct-missing/password",
        headers={"X-Tenant-Id": "t-1", "X-User-Id": admin["account_id"], "X-User-Role": SUPER_ADMIN_ROLE},
        json={"new_password": "another-passphrase"},
    )

    assert response.status_code == 404


def test_session_endpoint_requires_configured_secret(monkeypatch, accounts: AccountService) -> None:
    admin = register_admin(accounts)
    monkeypatch.setattr(main.settings, "auth_secret", "")

    assert login(admin["phone"]).status_code == 503
```

- [ ] **Step 2: 运行测试确认失败**

Run: `py -m pytest tests/test_account_api.py -q`
Expected: FAIL，`404 Not Found`（接口尚未注册）

- [ ] **Step 3: 实现接口**

在 `app/main.py` 的 import 区加入：

```python
from .accounts.models import (
    AccountConflict,
    AccountNotFound,
    AccountStateConflict,
    AccountStatus,
    BootstrapDenied,
    LoginFailed,
    RegistrationRequest,
)
from .accounts.passwords import PasswordPolicyError
```

把现有的 `from .auth import verify_access_token` 一行改为：

```python
from .auth import create_access_token, verify_access_token
```

把 `from .bootstrap import build_commercial_components, ...` 一行补上 `build_account_service`，并在 `commercial_repository, commercial_usage, commercial_lifecycle = build_commercial_components(settings)` 之后加入：

```python
account_service, account_repository = build_account_service(settings)
```

在 `current_user` 内，把开发分支改为同时接受会话令牌：

```python
    if authorization and authorization.startswith("Bearer ") and settings.auth_secret:
        try:
            return verify_access_token(authorization.removeprefix("Bearer "), settings.auth_secret)
        except ValueError as exc:
            raise HTTPException(status_code=401, detail="登录凭证无效") from exc
    if not tenant_id or not user_id or not role:
        raise HTTPException(status_code=401, detail="缺少登录身份信息")
    return UserContext(tenant_id=tenant_id, user_id=user_id, role=role)
```

在 `TaskView` 相关视图函数之后追加请求模型、视图辅助与 7 个接口：

```python
class RegistrationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phone: str = Field(min_length=1, max_length=20)
    password: str = Field(min_length=10, max_length=128)
    position: str = Field(min_length=1, max_length=100)
    full_name: str = Field(min_length=1, max_length=100)
    email: str | None = Field(default=None, max_length=200)
    tenant_id: str | None = Field(default=None, max_length=64)
    bootstrap_token: str | None = Field(default=None, max_length=200)


class RegistrationApproval(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str = Field(min_length=1, max_length=40)
    tenant_id: str = Field(min_length=1, max_length=64)


class RegistrationRejection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=500)


class SessionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phone: str = Field(min_length=1, max_length=20)
    password: str = Field(min_length=1, max_length=128)


class PasswordChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    old_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=10, max_length=128)


class PasswordReset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    new_password: str = Field(min_length=10, max_length=128)


def _mask_phone(phone: str) -> str:
    if len(phone) < 7:
        return "*" * len(phone)
    return f"{phone[:3]}{'*' * (len(phone) - 7)}{phone[-4:]}"


def _account_view(account) -> dict[str, object]:
    return {
        "account_id": account.account_id,
        "phone": _mask_phone(account.phone),
        "position": account.position,
        "full_name": account.full_name,
        "email": account.email,
        "role": account.role,
        "tenant_id": account.tenant_id,
        "status": account.status.value,
        "requested_at": account.requested_at,
        "reviewed_at": account.reviewed_at,
    }


@app.post("/api/v1/auth/registrations", status_code=status.HTTP_201_CREATED)
def submit_registration(payload: RegistrationCreate) -> dict[str, object]:
    try:
        account = account_service.request_registration(
            RegistrationRequest(
                phone=payload.phone,
                password=payload.password,
                position=payload.position,
                full_name=payload.full_name,
                email=payload.email,
                tenant_id=payload.tenant_id,
                bootstrap_token=payload.bootstrap_token,
            )
        )
    except AccountConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except BootstrapDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except PasswordPolicyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _account_view(account)


@app.get("/api/v1/auth/registrations")
def list_registrations(
    status_filter: str = Query(default="pending", alias="status"),
    context: UserContext = Depends(current_user),
) -> list[dict[str, object]]:
    try:
        requested_status = AccountStatus(status_filter)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="不支持的账号状态") from exc
    try:
        items = account_service.list_requests(context, requested_status)
    except PolicyError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return [_account_view(item) for item in items]


@app.post("/api/v1/auth/registrations/{account_id}/approval")
def approve_registration(
    account_id: str, payload: RegistrationApproval, context: UserContext = Depends(current_user)
) -> dict[str, object]:
    try:
        account = account_service.approve(
            context, account_id, role=payload.role, tenant_id=payload.tenant_id
        )
    except PolicyError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except AccountStateConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except AccountNotFound as exc:
        raise HTTPException(status_code=404, detail="账号申请不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _account_view(account)


@app.post("/api/v1/auth/registrations/{account_id}/rejection")
def reject_registration(
    account_id: str, payload: RegistrationRejection, context: UserContext = Depends(current_user)
) -> dict[str, object]:
    try:
        account = account_service.reject(context, account_id, reason=payload.reason)
    except PolicyError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except AccountStateConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except AccountNotFound as exc:
        raise HTTPException(status_code=404, detail="账号申请不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _account_view(account)


@app.post("/api/v1/auth/sessions")
def create_session(payload: SessionCreate) -> dict[str, object]:
    if not settings.auth_secret:
        raise HTTPException(status_code=503, detail="会话密钥未配置，请先设置 WORKBENCH_AUTH_SECRET")
    try:
        context = account_service.login(payload.phone, payload.password)
    except LoginFailed as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    token = create_access_token(context, settings.auth_secret, ttl_seconds=settings.session_ttl_seconds)
    return {
        "access_token": token,
        "token_type": "Bearer",
        "expires_in": settings.session_ttl_seconds,
        "tenant_id": context.tenant_id,
        "user_id": context.user_id,
        "role": context.role,
    }


@app.put("/api/v1/auth/me/password")
def change_own_password(payload: PasswordChange, context: UserContext = Depends(current_user)) -> dict[str, str]:
    try:
        account_service.change_password(
            context, old_password=payload.old_password, new_password=payload.new_password
        )
    except LoginFailed as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except PasswordPolicyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"status": "updated"}


@app.post("/api/v1/auth/accounts/{account_id}/password")
def reset_account_password(
    account_id: str, payload: PasswordReset, context: UserContext = Depends(current_user)
) -> dict[str, str]:
    try:
        account_service.reset_password(context, account_id, new_password=payload.new_password)
    except PolicyError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except AccountNotFound as exc:
        raise HTTPException(status_code=404, detail="账号不存在") from exc
    except PasswordPolicyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"status": "reset"}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `py -m pytest tests/test_account_api.py -q`
Expected: PASS（13 passed）

- [ ] **Step 5: 跑全量测试确认无回归**

Run: `py -m pytest -q`
Expected: PASS（全部通过）

- [ ] **Step 6: 提交**

```bash
git add app/main.py tests/test_account_api.py
git commit -m "feat: 增加账号注册登录接口"
```

---

### Task 7: PostgreSQL 迁移与仓储

**Files:**
- Create: `migrations/008_accounts.sql`
- Modify: `app/accounts/repository.py`
- Test: `tests/test_account_postgres.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_account_postgres.py` 末尾追加下列假连接与用例。同时在文件顶部补充 import，最终形态如下（Task 5 已写入的 `import pytest`、`build_account_service`、`Settings`、`InMemoryAccountRepository` 保留）：

```python
from datetime import UTC, datetime

import pytest

from app.accounts.models import (
    Account,
    AccountConflict,
    AccountNotFound,
    AccountStateConflict,
    AccountStatus,
)
from app.accounts.repository import InMemoryAccountRepository, PostgresAccountRepository
from app.bootstrap import build_account_service
from app.settings import Settings
```

追加的假连接与用例：

```python
class RecordingCursor:
    def __init__(self, rows: list[object]) -> None:
        self.rows = rows
        self.statements: list[tuple[str, tuple]] = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, statement: str, params: tuple = ()) -> None:
        self.statements.append((statement, params))

    def fetchone(self):
        return self.rows.pop(0)

    def fetchall(self):
        return self.rows.pop(0)


class RecordingTransaction:
    def __init__(self, connection) -> None:
        self.connection = connection

    def __enter__(self):
        self.connection.transaction_count += 1
        return self

    def __exit__(self, *_args):
        return False


class RecordingConnection:
    def __init__(self, rows: list[object]) -> None:
        self.cursor_instance = RecordingCursor(rows)
        self.transaction_count = 0

    def transaction(self):
        return RecordingTransaction(self)

    def cursor(self):
        return self.cursor_instance


def account_row(status: str = "pending") -> tuple:
    return (
        "acct-1", "13800000001", "scrypt$hash", "内容运营", "张三", None,
        None, None, status, datetime(2026, 9, 10, tzinfo=UTC), None, None, None,
    )


def test_postgres_add_uses_on_conflict_and_transaction() -> None:
    connection = RecordingConnection([account_row()])
    repository = PostgresAccountRepository(connection)

    account = repository.add(
        Account(phone="13800000001", password_hash="scrypt$hash", position="内容运营", full_name="张三")
    )

    assert account.account_id == "acct-1"
    assert connection.transaction_count == 1
    statement = connection.cursor_instance.statements[0][0]
    assert "INSERT INTO workbench_accounts" in statement
    assert "ON CONFLICT (phone) DO NOTHING" in statement


def test_postgres_add_conflict_raises_when_no_row_returned() -> None:
    connection = RecordingConnection([None])
    repository = PostgresAccountRepository(connection)

    with pytest.raises(AccountConflict, match="手机号"):
        repository.add(
            Account(phone="13800000001", password_hash="scrypt$hash", position="内容运营", full_name="张三")
        )


def test_postgres_mark_approved_uses_pending_guard() -> None:
    connection = RecordingConnection([account_row("approved")])
    repository = PostgresAccountRepository(connection)

    account = repository.mark_approved(
        "acct-1", role="employee", tenant_id="t-1", reviewed_by="acct-admin"
    )

    assert account.status is AccountStatus.APPROVED
    statement = connection.cursor_instance.statements[0][0]
    assert "WHERE account_id = %s AND status = 'pending'" in statement


def test_postgres_mark_approved_conflicts_when_row_missing() -> None:
    connection = RecordingConnection([None, ("acct-1",)])
    repository = PostgresAccountRepository(connection)

    with pytest.raises(AccountStateConflict):
        repository.mark_approved("acct-1", role="employee", tenant_id="t-1", reviewed_by="acct-admin")


def test_postgres_mark_approved_raises_not_found_when_account_missing() -> None:
    connection = RecordingConnection([None, None])
    repository = PostgresAccountRepository(connection)

    with pytest.raises(AccountNotFound):
        repository.mark_approved("acct-1", role="employee", tenant_id="t-1", reviewed_by="acct-admin")


def test_postgres_has_approved_admin_queries_super_admin() -> None:
    connection = RecordingConnection([(1,)])
    repository = PostgresAccountRepository(connection)

    assert repository.has_approved_admin() is True
    assert "role = 'super_admin'" in connection.cursor_instance.statements[0][0]


def test_postgres_find_by_phone_returns_none_when_absent() -> None:
    connection = RecordingConnection([None])
    repository = PostgresAccountRepository(connection)

    assert repository.find_by_phone("13800000001") is None


def test_migration_008_defines_unique_phone_and_status_check() -> None:
    from pathlib import Path

    migration = Path("migrations/008_accounts.sql").read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS workbench_accounts" in migration
    assert "phone TEXT NOT NULL UNIQUE" in migration
    assert "CHECK (status IN ('pending', 'approved', 'rejected'))" in migration
```

另外把 Task 5 留下的鸭子类型断言升级为真实类型断言，在 `test_postgres_backend_uses_injected_connection` 中改为：

```python
def test_postgres_backend_uses_injected_connection() -> None:
    service, repository = build_account_service(postgres_settings(), connection=object(), migrate=False)

    assert isinstance(repository, PostgresAccountRepository)
    assert service.repository is repository
```

- [ ] **Step 2: 运行测试确认失败**

Run: `py -m pytest tests/test_account_postgres.py -q`
Expected: FAIL，`ImportError: cannot import name 'PostgresAccountRepository'`（类尚未实现）与 `FileNotFoundError`（迁移文件不存在）

- [ ] **Step 3: 写迁移文件**

`migrations/008_accounts.sql`：

```sql
CREATE TABLE IF NOT EXISTS workbench_accounts (
    account_id TEXT PRIMARY KEY,
    phone TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    position TEXT NOT NULL,
    full_name TEXT NOT NULL,
    email TEXT,
    role TEXT,
    tenant_id TEXT,
    status TEXT NOT NULL CHECK (status IN ('pending', 'approved', 'rejected')),
    requested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    reviewed_at TIMESTAMPTZ,
    reviewed_by TEXT,
    rejection_reason TEXT
);

CREATE INDEX IF NOT EXISTS idx_workbench_accounts_status
    ON workbench_accounts (status, requested_at DESC);
```

- [ ] **Step 4: 实现 PostgreSQL 仓储**

在 `app/accounts/repository.py` 的 import 区补充：

```python
from contextlib import contextmanager, nullcontext
```

并在文件末尾追加：

```python
class PostgresAccountRepository:
    """账号持久化适配器；审批使用条件更新保证并发安全。"""

    _COLUMNS = (
        "account_id, phone, password_hash, position, full_name, email, role, tenant_id, "
        "status, requested_at, reviewed_at, reviewed_by, rejection_reason"
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
        )

    def add(self, account: Account) -> Account:
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""
                        INSERT INTO workbench_accounts ({self._COLUMNS})
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (phone) DO NOTHING
                        RETURNING {self._COLUMNS}
                        """,
                        (
                            account.account_id, account.phone, account.password_hash, account.position,
                            account.full_name, account.email, account.role, account.tenant_id,
                            account.status.value, account.requested_at, account.reviewed_at,
                            account.reviewed_by, account.rejection_reason,
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
```

- [ ] **Step 5: 运行测试确认通过**

Run: `py -m pytest tests/test_account_postgres.py -q`
Expected: PASS

- [ ] **Step 6: 跑全量测试与编译检查**

Run: `py -m pytest -q; py -m compileall -q app tests extract_pdf.py scripts`
Expected: 全部通过，compileall 退出码 0

- [ ] **Step 7: 提交**

```bash
git add migrations/008_accounts.sql app/accounts/repository.py tests/test_account_postgres.py
git commit -m "feat: 增加账号 PostgreSQL 迁移与仓储"
```

---

### Task 8: 文档同步

**Files:**
- Modify: `docs/api-contract.md`
- Modify: `README.md`
- Modify: `docs/delivery-gates.md`
- Modify: `.env.example`

- [ ] **Step 1: 更新接口契约**

在 `docs/api-contract.md` 的“健康检查”小节之后插入：

```markdown
## 账号注册与登录

账号由工作台自建：员工提交注册申请，超级管理员审批并指定角色与归属租户，审批通过后才能登录。首个管理员凭部署注入的 `WORKBENCH_BOOTSTRAP_TOKEN` 自助申请，角色固定为超级管理员，租户由申请自行声明；普通申请的 `tenant_id` 与 `role` 一律忽略。

登录标识为手机号，在部署内全局唯一。口令只保存 scrypt 哈希，任何响应、事件和日志都不包含口令或口令哈希。

`POST /api/v1/auth/registrations`

提交注册申请。请求体包含 `phone`、`password`、`position`、`full_name`，可选 `email`、`tenant_id`、`bootstrap_token`。首个管理员申请缺少正确初始化口令时返回 `403`；手机号已存在返回 `409`；口令不满足策略返回 `422`；成功返回 `201` 与账号视图，视图中的手机号已脱敏。

`GET /api/v1/auth/registrations?status=pending`

仅超级管理员可调用，按状态查询申请列表，默认 `pending`。其他角色返回 `403`，非法状态返回 `400`。

`POST /api/v1/auth/registrations/{account_id}/approval`

仅超级管理员可调用。请求体为 `{ "role": "...", "tenant_id": "..." }`，只允许审批 `pending` 状态；重复审批返回 `409`，账号不存在返回 `404`。

`POST /api/v1/auth/registrations/{account_id}/rejection`

仅超级管理员可调用。请求体为 `{ "reason": "..." }`，只允许驳回 `pending` 状态。

`POST /api/v1/auth/sessions`

用 `phone` 与 `password` 换取会话令牌。手机号不存在、口令错误或账号未通过审批一律返回 `401` 且不区分原因。成功返回 `access_token`、`token_type`、`expires_in`、`tenant_id`、`user_id` 和 `role`。会话密钥未配置时返回 `503`。

`PUT /api/v1/auth/me/password`

已登录用户修改本人密码。请求体为 `{ "old_password": "...", "new_password": "..." }`；原密码错误返回 `401`，新口令不满足策略返回 `422`。

`POST /api/v1/auth/accounts/{account_id}/password`

仅超级管理员可调用，用于忘记密码后的重置。请求体为 `{ "new_password": "..." }`；账号不存在返回 `404`，其他角色返回 `403`。

会话令牌使用 HMAC-SHA256 签名，载荷包含租户、用户、角色、签发时间、过期时间和唯一号；过期或签名错误一律返回 `401`。有效期由 `WORKBENCH_SESSION_TTL_SECONDS` 控制，默认 900 秒，范围 60–3600。本轮不提供服务端会话撤销，登出由客户端丢弃令牌并由短期有效期兜底。
```

- [ ] **Step 2: 更新 README 安全边界与配置说明**

在 `README.md` 的“安全边界”小节，把第一条改为：

```markdown
- 不保存或上传第三方系统的密码、Cookie、验证码、会话快照、原始 API 密钥；自建账号只保存本地口令的 scrypt 哈希，不保存明文口令。
```

在“第一阶段 API 行为”小节末尾追加：

```markdown
自建账号流程：员工通过 `POST /api/v1/auth/registrations` 提交申请，超级管理员审批并指定角色与租户后，用 `POST /api/v1/auth/sessions` 登录换取短期会话令牌。首个管理员凭部署注入的 `WORKBENCH_BOOTSTRAP_TOKEN` 自助申请。会话有效期由 `WORKBENCH_SESSION_TTL_SECONDS` 控制（默认 900 秒）。
```

- [ ] **Step 3: 更新交付门禁**

在 `docs/delivery-gates.md` 的当前阶段列表中，替换这一行：

```markdown
- [ ] 统一登录、设备绑定和生产密钥管理
```

为：

```markdown
- [x] 自建账号注册审批、登录会话与管理员重置密码（开发期接口验证）
- [ ] 设备绑定、生产密钥轮换和真实统一登录验收
```

- [ ] **Step 4: 更新环境示例**

在 `.env.example` 末尾追加：

```dotenv
WORKBENCH_BOOTSTRAP_TOKEN=
WORKBENCH_SESSION_TTL_SECONDS=900
```

- [ ] **Step 5: 验证并与代码一致性检查**

Run: `py -m pytest -q; py -m compileall -q app tests extract_pdf.py scripts; git diff --check`
Expected: 测试全绿、compileall 退出码 0、无空白错误

- [ ] **Step 6: 提交**

```bash
git add docs/api-contract.md README.md docs/delivery-gates.md .env.example
git commit -m "docs: 同步账号接口契约与安全边界"
```

---

## 验收对照

| 规格要求 | 对应任务 |
| --- | --- |
| 只存 scrypt 哈希，不存明文 | Task 1、Task 4（配置）、Task 8（README） |
| 手机号全局唯一、重复有提示 | Task 2、Task 3、Task 6 |
| 首管理员凭 bootstrap 口令自助申请 | Task 3、Task 4、Task 6 |
| 普通申请需审批后登录 | Task 3、Task 6 |
| 角色与租户由管理员审批指定 | Task 3、Task 6 |
| 职位仅展示，不参与鉴权 | Task 2、Task 6（视图） |
| 本人改密需验原密码 | Task 3、Task 6 |
| 忘记密码由管理员重置 | Task 3、Task 6 |
| 会话令牌带过期，过期/篡改 401 | Task 4、Task 6 |
| 开发态保留请求头，生产态只用令牌 | Task 6 |
| 新接口同步接口契约 | Task 8 |
| PostgreSQL 持久化与迁移清单 | Task 7 |
| 不泄漏口令、哈希、bootstrap 口令 | Task 1、Task 6（视图与断言）、Task 8 |

## 明确不做

设备绑定、OIDC/SSO、服务端会话撤销表、账号禁用/吊销、短信验证码、邮箱验证、找回密码自助流程。真实 staging 联调与生产密钥轮换仍需单独验收，不得据此宣称已上线。
