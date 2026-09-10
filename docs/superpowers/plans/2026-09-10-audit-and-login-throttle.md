# 关键操作审计与登录限流 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立一套跨模块共用的安全审计设施（数据库审计表 + 结构化 stdout 日志），并让账号与计划模块的关键操作全部留痕；同时对登录按手机号实施失败计数与锁定。

**Architecture:** 新增 `app/audit/`（脱敏工具、审计模型、日志设施、仓储、服务）与 `app/accounts/rate_limit.py`（登录失败计数与锁定）；账号与计划服务通过**必填关键字参数**注入审计与限流依赖，避免生产漏注入导致静默失去审计或限流。审计仓储与限流仓储跟随既有 `WORKBENCH_STORAGE_BACKEND`（开发内存 / 生产 PostgreSQL）。

**Tech Stack:** Python 3.11+、FastAPI、Pydantic v2、标准库 `logging`/`hmac`/`hashlib`、pytest、PostgreSQL（psycopg3）。

**参考规格：** [`docs/superpowers/specs/2026-09-10-audit-and-login-throttle-design.md`](../specs/2026-09-10-audit-and-login-throttle-design.md)

---

## 文件结构

| 文件 | 职责 |
| --- | --- |
| `app/audit/__init__.py` | 包标记 |
| `app/audit/redaction.py` | 共享脱敏工具：敏感键判定、手机号脱敏（**单一来源**） |
| `app/audit/models.py` | `AuditAction`、`AuditRecord`、明细校验、领域异常 |
| `app/audit/logging.py` | 结构化 stdout 日志（单行 JSON）与格式化器安装 |
| `app/audit/store.py` | `AuditStore` 协议 + 内存实现 + PostgreSQL 实现 |
| `app/audit/service.py` | `AuditService`：先写仓储再写日志 |
| `app/accounts/rate_limit.py` | `LoginAttemptState`、仓储协议、内存与 PostgreSQL 实现、`LoginRateLimiter` |
| `app/settings.py`（修改） | 三项限流配置 |
| `app/bootstrap.py`（修改） | 装配审计与限流 |
| `app/accounts/service.py`（修改） | 注入审计与限流，登录加锁定判定 |
| `app/planner/service.py`（修改） | 注入审计并记录四类计划动作 |
| `app/planner/models.py`（修改） | 改用共享脱敏工具，删除私有重复实现 |
| `app/main.py`（修改） | 登录 `429`；手机号脱敏改用共享工具；装配审计 |
| `migrations/010_audit_log.sql`（新增） | 审计表 |
| `migrations/011_login_attempts.sql`（新增） | 登录尝试表 |
| `tests/test_audit_redaction.py`、`tests/test_audit_models.py`、`tests/test_audit_logging.py`、`tests/test_audit_store.py`、`tests/test_login_rate_limit.py`、`tests/test_audit_bootstrap.py`、`tests/test_audit_postgres.py` | 新增测试 |
| `tests/test_account_service.py`、`tests/test_account_api.py`、`tests/test_planner_service.py`、`tests/test_planner_api.py`（修改） | 适配新构造签名并补审计断言 |

**约定：** 本仓库测试命令用 `py -m pytest`（该机器 `python` 不在 PATH）。当前全量基线 **380 项通过**。迁移现有 `001`–`009`，本功能新增 `010`、`011`。

**计数约定：** 全量测试步骤只写「全部通过（基线 380 + 本任务新增）」，不写累计绝对值——累计数会随实现微调漂移，逐任务核对「本任务 focused 用例数」即可。

---

### Task 1: 共享脱敏工具与审计模型

**Files:**
- Create: `app/audit/__init__.py`
- Create: `app/audit/redaction.py`
- Create: `app/audit/models.py`
- Modify: `app/planner/models.py`
- Modify: `app/main.py`
- Test: `tests/test_audit_redaction.py`
- Test: `tests/test_audit_models.py`

- [ ] **Step 1: 写失败测试**

`tests/test_audit_redaction.py`：

```python
from app.audit.redaction import has_sensitive_key, key_tokens, mask_phone


def test_key_tokens_splits_underscore_hyphen_and_camel_case() -> None:
    assert key_tokens("api_key") == {"api", "key"}
    assert key_tokens("x-api-key") == {"x", "api", "key"}
    assert key_tokens("apiKey") == {"api", "key"}
    assert key_tokens("API_KEY") == {"api", "key"}
    assert key_tokens("keyword") == {"keyword"}


def test_has_sensitive_key_blocks_compound_nested_and_camel_case() -> None:
    for value in (
        {"client_secret": "x"},
        {"x-api-key": "x"},
        {"apiKey": "x"},
        {"accessToken": "x"},
        {"Authorization": "x"},
        {"credential": "x"},
        {"headers": {"Authorization": "x"}},
        {"items": [{"clientSecret": "x"}]},
    ):
        assert has_sensitive_key(value) is True


def test_has_sensitive_key_allows_benign_keys() -> None:
    assert has_sensitive_key({"keyword": "a", "topicName": "b", "goal": "c"}) is False
    assert has_sensitive_key({}) is False
    assert has_sensitive_key("text") is False


def test_mask_phone_masks_short_and_full_numbers() -> None:
    assert mask_phone("13800000001") == "138****0001"
    assert mask_phone("1234567") == "*******"
    assert mask_phone("") == ""
```

`tests/test_audit_models.py`：

```python
import pytest

from app.audit.models import AuditAction, AuditDetailNotAllowed, AuditRecord, build_record


def test_build_record_defaults_and_identity() -> None:
    record = build_record(
        AuditAction.ACCOUNT_LOGIN_SUCCEEDED,
        tenant_id="t-1",
        actor_id="acct-1",
        target_type="account",
        target_id="acct-1",
        phone_masked="138****0001",
    )

    assert record.record_id.startswith("audit-")
    assert record.occurred_at.tzinfo is not None
    assert record.detail == {}
    assert record.action is AuditAction.ACCOUNT_LOGIN_SUCCEEDED


def test_action_values_are_stable_strings() -> None:
    assert AuditAction.ACCOUNT_LOGIN_LOCKED.value == "account.login.locked"
    assert AuditAction.PLAN_RUN_STARTED.value == "plan.run_started"
    assert len(set(AuditAction)) == 12


def test_build_record_rejects_undeclared_detail_keys() -> None:
    for bad in (
        {"password": "x"},
        {"apiKey": "x"},
        {"unknown": "x"},
        {"nested": {"accessToken": "x"}},
    ):
        with pytest.raises(AuditDetailNotAllowed):
            build_record(AuditAction.PLAN_PROPOSED, tenant_id="t-1", detail=bad)


def test_build_record_allows_every_declared_detail_key() -> None:
    from app.audit.models import ALLOWED_DETAIL_KEYS

    record = build_record(
        AuditAction.PLAN_RUN_STARTED,
        tenant_id="t-1",
        detail={key: "v" for key in ALLOWED_DETAIL_KEYS},
    )

    assert set(record.detail) == set(ALLOWED_DETAIL_KEYS)


def test_build_record_accepts_bounded_structured_detail() -> None:
    record = build_record(
        AuditAction.PLAN_RUN_STARTED,
        tenant_id="t-1",
        detail={"runtime_key": "mock", "step_count": 3},
    )

    assert record.detail == {"runtime_key": "mock", "step_count": 3}
```

- [ ] **Step 2: 运行测试确认失败**

Run: `py -m pytest tests/test_audit_redaction.py tests/test_audit_models.py -q`
Expected: FAIL，`ModuleNotFoundError: No module named 'app.audit'`

- [ ] **Step 3: 实现**

`app/audit/__init__.py`：

```python
"""关键操作审计与脱敏。"""
```

`app/audit/redaction.py`：

```python
from __future__ import annotations

import re

SENSITIVE_KEY_TOKENS = frozenset(
    {
        "password",
        "passwd",
        "pwd",
        "token",
        "secret",
        "key",
        "cookie",
        "authorization",
        "credential",
        "session",
        "bearer",
    }
)
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def key_tokens(key: object) -> set[str]:
    """把键名归一切词：camelCase 边界拆开、- 与 _ 视为分隔，再小写比对词元。"""
    text = _CAMEL_BOUNDARY.sub("_", str(key))
    return {part for part in text.lower().replace("-", "_").split("_") if part}


def has_sensitive_key(value: object) -> bool:
    """递归检查是否出现敏感键名；按词元比对，避免误伤 keyword 之类。"""
    if isinstance(value, dict):
        for key, item in value.items():
            if key_tokens(key) & SENSITIVE_KEY_TOKENS or has_sensitive_key(item):
                return True
        return False
    if isinstance(value, list):
        return any(has_sensitive_key(item) for item in value)
    return False


def mask_phone(phone: str) -> str:
    """手机号脱敏；非 11 位一律全量遮蔽，避免短号泄露。"""
    if len(phone) < 11:
        return "*" * len(phone)
    return f"{phone[:3]}{'*' * (len(phone) - 7)}{phone[-4:]}"
```

`app/audit/models.py`：

```python
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4


class AuditAction(StrEnum):
    ACCOUNT_REGISTRATION_REQUESTED = "account.registration.requested"
    ACCOUNT_REGISTRATION_APPROVED = "account.registration.approved"
    ACCOUNT_REGISTRATION_REJECTED = "account.registration.rejected"
    ACCOUNT_LOGIN_SUCCEEDED = "account.login.succeeded"
    ACCOUNT_LOGIN_FAILED = "account.login.failed"
    ACCOUNT_LOGIN_LOCKED = "account.login.locked"
    ACCOUNT_PASSWORD_CHANGED = "account.password.changed"
    ACCOUNT_PASSWORD_RESET = "account.password.reset"
    PLAN_PROPOSED = "plan.proposed"
    PLAN_APPROVED = "plan.approved"
    PLAN_REJECTED = "plan.rejected"
    PLAN_RUN_STARTED = "plan.run_started"


class AuditDetailNotAllowed(ValueError):
    """审计明细包含未声明的字段，已拒绝写入。"""


ALLOWED_DETAIL_KEYS = frozenset(
    {
        "reason",
        "role",
        "step_count",
        "generator",
        "runtime_key",
        "failure_count",
        "bootstrap",
        "tenant_assigned_at_approval",
    }
)


@dataclass(frozen=True)
class AuditRecord:
    action: AuditAction
    tenant_id: str | None = None
    actor_id: str | None = None
    target_type: str | None = None
    target_id: str | None = None
    phone_masked: str | None = None
    detail: dict[str, object] = field(default_factory=dict)
    record_id: str = field(default_factory=lambda: f"audit-{uuid4().hex[:12]}")
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))


def build_record(
    action: AuditAction,
    *,
    tenant_id: str | None = None,
    actor_id: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    phone_masked: str | None = None,
    detail: dict[str, object] | None = None,
) -> AuditRecord:
    """构造审计记录；明细采用白名单，只允许服务端声明的字段，未知字段一律拒绝。"""
    payload = dict(detail or {})
    undeclared = {str(key) for key in payload if key not in ALLOWED_DETAIL_KEYS}
    if undeclared:
        raise AuditDetailNotAllowed("审计明细包含未声明的字段")
    return AuditRecord(
        action=action,
        tenant_id=tenant_id,
        actor_id=actor_id,
        target_type=target_type,
        target_id=target_id,
        phone_masked=phone_masked,
        detail=payload,
    )
```

- [ ] **Step 4: 删除 `app/planner/models.py` 里的重复实现并改为共享工具**

删除该文件中的 `SENSITIVE_KEY_TOKENS`、`_CAMEL_BOUNDARY`、`_key_tokens`、`_has_sensitive_key` 四段定义；若 `import re` 因此不再被使用则一并删除。在文件顶部 import 区加入：

```python
from app.audit.redaction import has_sensitive_key
```

把 `normalize_steps` 中的

```python
        if _has_sensitive_key(args):
            raise PlanGenerationError("步骤参数包含敏感字段")
```

改为

```python
        if has_sensitive_key(args):
            raise PlanGenerationError("步骤参数包含敏感字段")
```

- [ ] **Step 5: `app/main.py` 改用共享的手机号脱敏**

删除 `app/main.py` 中的 `_mask_phone` 函数定义，在 import 区加入：

```python
from .audit.redaction import mask_phone
```

把 `_account_view` 中的 `"phone": _mask_phone(account.phone),` 改为 `"phone": mask_phone(account.phone),`。

- [ ] **Step 6: 运行测试**

Run: `py -m pytest tests/test_audit_redaction.py tests/test_audit_models.py -q`
Expected: PASS（4 + 5 = 9 passed）

Run: `py -m pytest -o addopts=""`
Expected: 全部通过（基线 380 + 本任务新增）——**特别注意 `tests/test_planner_models.py` 与 `tests/test_account_api.py` 必须仍然全绿**，它们守护本次去重是否改变了既有行为。

- [ ] **Step 7: 提交**

```bash
git add app/audit/__init__.py app/audit/redaction.py app/audit/models.py app/planner/models.py app/main.py tests/test_audit_redaction.py tests/test_audit_models.py
git commit -m "feat: 增加共享脱敏工具与审计模型"
```

---

### Task 2: 审计日志设施

**Files:**
- Create: `app/audit/logging.py`
- Test: `tests/test_audit_logging.py`

- [ ] **Step 1: 写失败测试**

```python
import json
import logging

from app.audit.logging import AUDIT_LOGGER_NAME, configure_audit_logging, emit_audit_line
from app.audit.models import AuditAction, build_record


def capture(caplog):
    return caplog.records


def test_emit_writes_single_json_line_with_expected_fields(caplog) -> None:
    caplog.set_level(logging.INFO, logger=AUDIT_LOGGER_NAME)
    record = build_record(
        AuditAction.ACCOUNT_LOGIN_FAILED,
        tenant_id="t-1",
        actor_id=None,
        target_type="account",
        target_id=None,
        phone_masked="138****0001",
        detail={"reason": "invalid_credentials"},
    )

    emit_audit_line(record)

    message = caplog.records[-1].getMessage()
    assert "\n" not in message
    payload = json.loads(message)
    assert payload["event"] == "audit"
    assert payload["action"] == "account.login.failed"
    assert payload["tenant_id"] == "t-1"
    assert payload["phone_masked"] == "138****0001"
    assert payload["detail"] == {"reason": "invalid_credentials"}
    assert payload["occurred_at"]
    assert "actor_id" in payload


def test_configure_audit_logging_is_idempotent() -> None:
    import app.audit.logging as module

    module._configured = False
    logger = logging.getLogger(AUDIT_LOGGER_NAME)
    before = len(logger.handlers)
    try:
        configure_audit_logging("INFO")
        after_first = len(logger.handlers)
        configure_audit_logging("INFO")
        after_second = len(logger.handlers)
    finally:
        for handler in list(logger.handlers)[before:]:
            logger.removeHandler(handler)
        module._configured = False

    assert after_first == before + 1
    assert after_second == after_first


def test_configure_audit_logging_sets_level() -> None:
    import app.audit.logging as module

    module._configured = False
    logger = logging.getLogger(AUDIT_LOGGER_NAME)
    before = len(logger.handlers)
    try:
        configure_audit_logging("WARNING")
        assert logging.getLogger(AUDIT_LOGGER_NAME).level == logging.WARNING
    finally:
        for handler in list(logger.handlers)[before:]:
            logger.removeHandler(handler)
        module._configured = False


def test_configure_audit_logging_rejects_invalid_level() -> None:
    import app.audit.logging as module

    module._configured = False
    try:
        configure_audit_logging("NOT-A-LEVEL")
    finally:
        module._configured = False
    # 非法级别不抛异常，回退到 INFO
    assert logging.getLogger(AUDIT_LOGGER_NAME).level == logging.INFO
```

- [ ] **Step 2: 运行测试确认失败**

Run: `py -m pytest tests/test_audit_logging.py -q`
Expected: FAIL，`ModuleNotFoundError: No module named 'app.audit.logging'`

- [ ] **Step 3: 实现**

```python
from __future__ import annotations

import json
import logging

from .models import AuditRecord


AUDIT_LOGGER_NAME = "company_workbench.audit"
_configured = False


def configure_audit_logging(level: str) -> None:
    """安装单行 JSON 输出；幂等，重复调用不叠加 handler。"""
    global _configured
    logger = logging.getLogger(AUDIT_LOGGER_NAME)
    resolved = logging.getLevelName(str(level).upper())
    logger.setLevel(resolved if isinstance(resolved, int) else logging.INFO)
    if _configured:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.propagate = False
    _configured = True


def emit_audit_line(record: AuditRecord) -> None:
    """把审计记录写成一行 JSON；字段固定，不写入任何未声明内容。"""
    payload = {
        "event": "audit",
        "action": record.action.value,
        "actor_id": record.actor_id,
        "tenant_id": record.tenant_id,
        "target_type": record.target_type,
        "target_id": record.target_id,
        "phone_masked": record.phone_masked,
        "detail": record.detail,
        "record_id": record.record_id,
        "occurred_at": record.occurred_at.isoformat(),
    }
    logging.getLogger(AUDIT_LOGGER_NAME).info(json.dumps(payload, ensure_ascii=False, sort_keys=True))
```

- [ ] **Step 4: 运行测试确认通过**

Run: `py -m pytest tests/test_audit_logging.py -q`
Expected: PASS（4 passed）

> **必须遵守（执行中发现的真实缺陷）**：`configure_audit_logging` 会把该 logger 的 `propagate` 设为 `False`，而 `caplog` 的捕获 handler 挂在 root logger 上。如果测试只移除 handler 与复原 `_configured`，`propagate=False` 会**泄漏到全局**，让同一次运行里后续任何依赖 `caplog` 的测试失败（实测会导致 Task 3 的 `test_service_writes_to_store_and_emits_log` 报 `IndexError: list index out of range`）。
>
> 因此该测试文件必须包含一个 autouse fixture，对 logger 的 `handlers`、`level`、`propagate` 与模块级 `_configured` 做**完整快照与复原**，并且各测试内不再自行 `try/finally` 收尾：
>
> ```python
> @pytest.fixture(autouse=True)
> def _restore_audit_logger():
>     import app.audit.logging as module
>
>     logger = logging.getLogger(AUDIT_LOGGER_NAME)
>     snapshot = (list(logger.handlers), logger.level, logger.propagate, module._configured)
>     try:
>         yield
>     finally:
>         for handler in list(logger.handlers):
>             logger.removeHandler(handler)
>         for handler in snapshot[0]:
>             logger.addHandler(handler)
>         logger.setLevel(snapshot[1])
>         logger.propagate = snapshot[2]
>         module._configured = snapshot[3]
> ```
>
> 验收方式：`py -m pytest tests/test_audit_logging.py tests/test_audit_store.py -q` 与反序运行都必须全绿。

- [ ] **Step 5: 提交**

```bash
git add app/audit/logging.py tests/test_audit_logging.py
git commit -m "feat: 增加审计结构化日志设施"
```

---

### Task 3: 审计仓储与 AuditService

**Files:**
- Create: `app/audit/store.py`
- Create: `app/audit/service.py`
- Test: `tests/test_audit_store.py`

- [ ] **Step 1: 写失败测试**

```python
import pytest

from app.audit.models import AuditAction, build_record
from app.audit.service import AuditService
from app.audit.store import InMemoryAuditStore


def record(tenant_id: str = "t-1", action: AuditAction = AuditAction.ACCOUNT_LOGIN_SUCCEEDED):
    return build_record(action, tenant_id=tenant_id, actor_id="u-1", target_type="account", target_id="u-1")


def test_store_append_and_list_recent_is_tenant_scoped() -> None:
    store = InMemoryAuditStore()

    first = store.append(record())
    store.append(record("t-other"))

    assert store.list_recent("t-1", limit=10) == [first]
    assert store.list_recent("t-other", limit=10)[0].tenant_id == "t-other"
    assert store.list_recent("t-missing", limit=10) == []


def test_store_list_recent_respects_limit_and_orders_newest_last() -> None:
    store = InMemoryAuditStore()
    for _index in range(5):
        store.append(record())

    recent = store.list_recent("t-1", limit=3)

    assert len(recent) == 3
    assert [item.record_id for item in recent] == [
        item.record_id for item in store.list_recent("t-1", limit=5)[-3:]
    ]


def test_service_writes_to_store_and_emits_log(caplog) -> None:
    import logging

    from app.audit.logging import AUDIT_LOGGER_NAME

    caplog.set_level(logging.INFO, logger=AUDIT_LOGGER_NAME)
    store = InMemoryAuditStore()
    service = AuditService(store)

    saved = service.record(
        AuditAction.PLAN_PROPOSED,
        tenant_id="t-1",
        actor_id="u-1",
        target_type="task",
        target_id="task-1",
        detail={"step_count": 2},
    )

    assert store.list_recent("t-1", limit=10) == [saved]
    assert saved.action is AuditAction.PLAN_PROPOSED
    assert caplog.records[-1].getMessage().find('"action": "plan.proposed"') >= 0


def test_service_rejects_sensitive_detail() -> None:
    from app.audit.models import AuditDetailNotAllowed

    service = AuditService(InMemoryAuditStore())

    with pytest.raises(AuditDetailNotAllowed):
        service.record(AuditAction.PLAN_PROPOSED, tenant_id="t-1", detail={"apiKey": "x"})


def test_service_propagates_store_failure_and_does_not_swallow(caplog) -> None:
    import logging

    from app.audit.logging import AUDIT_LOGGER_NAME

    caplog.set_level(logging.INFO, logger=AUDIT_LOGGER_NAME)

    class ExplodingStore:
        def append(self, item):
            raise RuntimeError("db down")

        def list_recent(self, tenant_id, limit):
            return []

    service = AuditService(ExplodingStore())

    with pytest.raises(RuntimeError, match="db down"):
        service.record(AuditAction.PLAN_PROPOSED, tenant_id="t-1")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `py -m pytest tests/test_audit_store.py -q`
Expected: FAIL，`ModuleNotFoundError: No module named 'app.audit.store'`

- [ ] **Step 3: 实现**

`app/audit/store.py`：

```python
from __future__ import annotations

from threading import RLock
from typing import Protocol

from .models import AuditRecord


class AuditStore(Protocol):
    def append(self, record: AuditRecord) -> AuditRecord: ...
    def list_recent(self, tenant_id: str | None = None, *, limit: int = 100) -> list[AuditRecord]: ...


class InMemoryAuditStore:
    """开发期内存审计仓储；仅保留最近若干条。"""

    def __init__(self, *, max_items: int = 1_000) -> None:
        self._items: list[AuditRecord] = []
        self._max_items = max_items
        self._lock = RLock()

    def append(self, record: AuditRecord) -> AuditRecord:
        with self._lock:
            self._items.append(record)
            if len(self._items) > self._max_items:
                self._items = self._items[-self._max_items :]
            return record

    def list_recent(self, tenant_id: str | None = None, *, limit: int = 100) -> list[AuditRecord]:
        """按租户过滤；`tenant_id` 为 None 时返回全部（供测试与后续管理端排查使用）。"""
        with self._lock:
            matched = [
                item for item in self._items if tenant_id is None or item.tenant_id == tenant_id
            ]
            return matched[-limit:]
```

`app/audit/service.py`：

```python
from __future__ import annotations

from .logging import emit_audit_line
from .models import AuditAction, AuditRecord, build_record
from .store import AuditStore


class AuditService:
    """审计入口：先落库再写结构化日志，两条通道都不静默吞掉异常。"""

    def __init__(self, store: AuditStore) -> None:
        self.store = store

    def record(
        self,
        action: AuditAction,
        *,
        tenant_id: str | None = None,
        actor_id: str | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
        phone_masked: str | None = None,
        detail: dict[str, object] | None = None,
    ) -> AuditRecord:
        record = build_record(
            action,
            tenant_id=tenant_id,
            actor_id=actor_id,
            target_type=target_type,
            target_id=target_id,
            phone_masked=phone_masked,
            detail=detail,
        )
        saved = self.store.append(record)
        emit_audit_line(saved)
        return saved
```

- [ ] **Step 4: 运行测试确认通过**

Run: `py -m pytest tests/test_audit_store.py -q`
Expected: PASS（5 passed）

- [ ] **Step 5: 提交**

```bash
git add app/audit/store.py app/audit/service.py tests/test_audit_store.py
git commit -m "feat: 增加审计仓储与审计服务"
```

---

### Task 4: 登录失败计数与锁定

**Files:**
- Create: `app/accounts/rate_limit.py`
- Test: `tests/test_login_rate_limit.py`

- [ ] **Step 1: 写失败测试**

```python
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest

from app.accounts.rate_limit import (
    InMemoryLoginAttemptStore,
    LoginRateLimited,
    LoginRateLimiter,
)

SECRET = "s" * 40
NOW = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)


def limiter(store=None, *, failures=5, window=300, lock=900) -> LoginRateLimiter:
    return LoginRateLimiter(
        store or InMemoryLoginAttemptStore(),
        secret=SECRET,
        max_failures=failures,
        window_seconds=window,
        lock_seconds=lock,
    )


def test_phone_is_never_stored_in_plain_text() -> None:
    store = InMemoryLoginAttemptStore()
    instance = limiter(store)

    instance.register_failure("13800000001", now=NOW)

    assert "13800000001" not in store.dump_keys()
    assert instance.phone_hash("13800000001") in store.dump_keys()


def test_failures_below_threshold_do_not_lock() -> None:
    instance = limiter(failures=5)

    for _index in range(4):
        state = instance.register_failure("13800000001", now=NOW)

    assert state.failure_count == 4
    assert state.locked_until is None
    assert instance.is_locked("13800000001", now=NOW) is False


def test_reaching_threshold_locks_for_configured_duration() -> None:
    instance = limiter(failures=5, lock=900)

    for _index in range(5):
        state = instance.register_failure("13800000001", now=NOW)

    assert state.failure_count == 5
    assert state.locked_until == NOW + timedelta(seconds=900)
    assert instance.is_locked("13800000001", now=NOW) is True
    assert instance.is_locked("13800000001", now=NOW + timedelta(seconds=899)) is True
    assert instance.is_locked("13800000001", now=NOW + timedelta(seconds=901)) is False


def test_window_expiry_resets_counter() -> None:
    instance = limiter(failures=5, window=300)

    for _index in range(3):
        instance.register_failure("13800000001", now=NOW)
    later = NOW + timedelta(seconds=301)
    state = instance.register_failure("13800000001", now=later)

    assert state.failure_count == 1
    assert state.window_started_at == later


def test_success_clears_counter_and_lock() -> None:
    instance = limiter(failures=2)

    instance.register_failure("13800000001", now=NOW)
    instance.register_failure("13800000001", now=NOW)
    assert instance.is_locked("13800000001", now=NOW) is True

    instance.register_success("13800000001")

    assert instance.is_locked("13800000001", now=NOW) is False
    assert instance.register_failure("13800000001", now=NOW).failure_count == 1


def test_require_unlocked_raises_when_locked() -> None:
    instance = limiter(failures=1, lock=900)
    instance.register_failure("13800000001", now=NOW)

    with pytest.raises(LoginRateLimited):
        instance.require_unlocked("13800000001", now=NOW)

    instance.require_unlocked("13800000001", now=NOW + timedelta(seconds=901))


def test_different_phones_are_counted_independently() -> None:
    instance = limiter(failures=2)

    instance.register_failure("13800000001", now=NOW)
    state = instance.register_failure("13800000002", now=NOW)

    assert state.failure_count == 1
    assert instance.is_locked("13800000001", now=NOW) is False


def test_concurrent_failures_do_not_lose_counts() -> None:
    store = InMemoryLoginAttemptStore()
    instance = limiter(store, failures=1_000, window=10_000)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _index: instance.register_failure("13800000001", now=NOW), range(20)))

    state = store.load(instance.phone_hash("13800000001"))
    assert state is not None
    assert state.failure_count == 20


def test_unknown_phone_reports_unlocked() -> None:
    instance = limiter()

    assert instance.is_locked("13900000009", now=NOW) is False
    assert instance.register_failure("13900000009", now=NOW).failure_count == 1
```

- [ ] **Step 2: 运行测试确认失败**

Run: `py -m pytest tests/test_login_rate_limit.py -q`
Expected: FAIL，`ModuleNotFoundError: No module named 'app.accounts.rate_limit'`

- [ ] **Step 3: 实现**

`app/accounts/rate_limit.py`：

```python
from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from threading import RLock
from typing import Protocol


class LoginRateLimited(ValueError):
    """账号已被登录失败锁定。"""


@dataclass(frozen=True)
class LoginAttemptState:
    phone_hash: str
    failure_count: int
    window_started_at: datetime
    locked_until: datetime | None = None


class LoginAttemptStore(Protocol):
    def load(self, phone_hash: str) -> LoginAttemptState | None: ...
    def record_failure(
        self,
        phone_hash: str,
        *,
        now: datetime,
        window_seconds: int,
        max_failures: int,
        lock_seconds: int,
    ) -> LoginAttemptState: ...
    def clear(self, phone_hash: str) -> None: ...


class InMemoryLoginAttemptStore:
    """开发期内存实现；计数与窗口推进在同一把锁内原子完成。"""

    def __init__(self) -> None:
        self._items: dict[str, LoginAttemptState] = {}
        self._lock = RLock()

    def dump_keys(self) -> set[str]:
        with self._lock:
            return set(self._items)

    def load(self, phone_hash: str) -> LoginAttemptState | None:
        with self._lock:
            return self._items.get(phone_hash)

    def record_failure(
        self,
        phone_hash: str,
        *,
        now: datetime,
        window_seconds: int,
        max_failures: int,
        lock_seconds: int,
    ) -> LoginAttemptState:
        with self._lock:
            current = self._items.get(phone_hash)
            if current is None or now - current.window_started_at >= timedelta(seconds=window_seconds):
                state = LoginAttemptState(phone_hash=phone_hash, failure_count=1, window_started_at=now)
            else:
                state = replace(current, failure_count=current.failure_count + 1)
            if state.failure_count >= max_failures:
                state = replace(state, locked_until=now + timedelta(seconds=lock_seconds))
            self._items[phone_hash] = state
            return state

    def clear(self, phone_hash: str) -> None:
        with self._lock:
            self._items.pop(phone_hash, None)


class LoginRateLimiter:
    """按手机号的失败计数与锁定；手机号只以 HMAC 哈希形式接触仓储。"""

    def __init__(
        self,
        store: LoginAttemptStore,
        *,
        secret: str,
        max_failures: int,
        window_seconds: int,
        lock_seconds: int,
    ) -> None:
        self.store = store
        self.secret = secret
        self.max_failures = max_failures
        self.window_seconds = window_seconds
        self.lock_seconds = lock_seconds

    def phone_hash(self, phone: str) -> str:
        return hmac.new(self.secret.encode(), phone.encode(), hashlib.sha256).hexdigest()

    def is_locked(self, phone: str, *, now: datetime | None = None) -> bool:
        state = self.store.load(self.phone_hash(phone))
        if state is None or state.locked_until is None:
            return False
        return (now or datetime.now(UTC)) < state.locked_until

    def require_unlocked(self, phone: str, *, now: datetime | None = None) -> None:
        if self.is_locked(phone, now=now):
            raise LoginRateLimited("登录尝试过于频繁，请稍后再试")

    def register_failure(self, phone: str, *, now: datetime | None = None) -> LoginAttemptState:
        return self.store.record_failure(
            self.phone_hash(phone),
            now=now or datetime.now(UTC),
            window_seconds=self.window_seconds,
            max_failures=self.max_failures,
            lock_seconds=self.lock_seconds,
        )

    def register_success(self, phone: str) -> None:
        self.store.clear(self.phone_hash(phone))
```

> 关键：计数与窗口推进必须由**仓储的单个原子操作**完成（内存实现持锁、PostgreSQL 实现用单条 upsert 语句）。若在服务层用「先 `load` 再 `save`」，并发下会丢计数，`test_concurrent_failures_do_not_lose_counts` 会失败。

- [ ] **Step 4: 运行测试确认通过**

Run: `py -m pytest tests/test_login_rate_limit.py -q`
Expected: PASS（9 passed）

- [ ] **Step 5: 提交**

```bash
git add app/accounts/rate_limit.py tests/test_login_rate_limit.py
git commit -m "feat: 增加登录失败计数与锁定"
```

---

### Task 5: 配置与装配

**Files:**
- Modify: `app/settings.py`
- Modify: `app/bootstrap.py`
- Test: `tests/test_audit_bootstrap.py`

- [ ] **Step 1: 写失败测试**

```python
import pytest
from pydantic import ValidationError

from app.audit.service import AuditService
from app.audit.store import InMemoryAuditStore
from app.accounts.rate_limit import InMemoryLoginAttemptStore, LoginRateLimiter
from app.bootstrap import build_audit_service, build_login_rate_limiter
from app.settings import Settings


def memory_settings(**overrides) -> Settings:
    base = {
        "env": "development",
        "storage_backend": "memory",
        "login_max_failures": 5,
        "login_window_seconds": 300,
        "login_lock_seconds": 900,
    }
    base.update(overrides)
    return Settings(**base)


def test_memory_backend_builds_audit_and_limiter() -> None:
    settings = memory_settings(auth_secret="s" * 40)

    audit = build_audit_service(settings)
    limiter = build_login_rate_limiter(settings)

    assert isinstance(audit, AuditService)
    assert isinstance(audit.store, InMemoryAuditStore)
    assert isinstance(limiter, LoginRateLimiter)
    assert isinstance(limiter.store, InMemoryLoginAttemptStore)
    assert limiter.max_failures == 5
    assert limiter.window_seconds == 300
    assert limiter.lock_seconds == 900
    assert limiter.secret == "s" * 40


def test_login_throttle_defaults() -> None:
    settings = Settings()

    assert settings.login_max_failures == 5
    assert settings.login_window_seconds == 300
    assert settings.login_lock_seconds == 900


def test_login_throttle_bounds_are_enforced() -> None:
    for overrides in (
        {"login_max_failures": 0},
        {"login_max_failures": 21},
        {"login_window_seconds": 10},
        {"login_window_seconds": 3601},
        {"login_lock_seconds": 10},
        {"login_lock_seconds": 86_401},
    ):
        with pytest.raises(ValidationError):
            Settings(**overrides)


def test_unsupported_storage_backend_is_rejected() -> None:
    with pytest.raises(ValueError):
        build_audit_service(memory_settings(storage_backend="sqlite"))

    with pytest.raises(ValueError):
        build_login_rate_limiter(memory_settings(storage_backend="sqlite"))
```

- [ ] **Step 2: 运行测试确认失败**

Run: `py -m pytest tests/test_audit_bootstrap.py -q`
Expected: FAIL，`ImportError: cannot import name 'build_audit_service'`

- [ ] **Step 3: 新增配置项**

在 `app/settings.py` 的 `Settings` 类中、`planner_model_timeout_seconds` 之后追加：

```python
    login_max_failures: int = Field(
        default=5,
        ge=1,
        le=20,
        validation_alias=AliasChoices("LOGIN_MAX_FAILURES", "WORKBENCH_LOGIN_MAX_FAILURES"),
    )
    login_window_seconds: int = Field(
        default=300,
        ge=30,
        le=3600,
        validation_alias=AliasChoices("LOGIN_WINDOW_SECONDS", "WORKBENCH_LOGIN_WINDOW_SECONDS"),
    )
    login_lock_seconds: int = Field(
        default=900,
        ge=30,
        le=86400,
        validation_alias=AliasChoices("LOGIN_LOCK_SECONDS", "WORKBENCH_LOGIN_LOCK_SECONDS"),
    )
```

- [ ] **Step 4: 实现装配函数**

在 `app/bootstrap.py` 顶部 import 区加入：

```python
from .accounts.rate_limit import InMemoryLoginAttemptStore, LoginRateLimiter
from .audit.service import AuditService
from .audit.store import InMemoryAuditStore
```

在文件末尾追加：

```python
def build_audit_service(settings: Settings, *, connection=None, migrate: bool = True) -> AuditService:
    """按存储模式装配审计仓储。"""
    validate_runtime_settings(settings)
    if settings.storage_backend == "memory":
        if settings.env != "development":
            raise ValueError("生产环境禁止使用内存审计仓储")
        return AuditService(InMemoryAuditStore())
    if settings.storage_backend == "postgres":
        from .audit.store import PostgresAuditStore

        if connection is None:
            from psycopg_pool import ConnectionPool

            database_url = settings.database_url.replace("postgresql+psycopg://", "postgresql://", 1)
            connection = ConnectionPool(database_url, min_size=1, max_size=10, open=True)
        if migrate:
            apply_migrations(connection, Path(__file__).resolve().parents[1] / "migrations")
        return AuditService(PostgresAuditStore(connection))
    raise ValueError("不支持的审计存储类型")


def build_login_rate_limiter(settings: Settings, *, connection=None, migrate: bool = True) -> LoginRateLimiter:
    """按存储模式装配登录限流。"""
    validate_runtime_settings(settings)
    if settings.storage_backend == "memory":
        if settings.env != "development":
            raise ValueError("生产环境禁止使用内存登录限流仓储")
        store = InMemoryLoginAttemptStore()
    elif settings.storage_backend == "postgres":
        from .accounts.rate_limit import PostgresLoginAttemptStore

        if connection is None:
            from psycopg_pool import ConnectionPool

            database_url = settings.database_url.replace("postgresql+psycopg://", "postgresql://", 1)
            connection = ConnectionPool(database_url, min_size=1, max_size=10, open=True)
        if migrate:
            apply_migrations(connection, Path(__file__).resolve().parents[1] / "migrations")
        store = PostgresLoginAttemptStore(connection)
    else:
        raise ValueError("不支持的登录限流存储类型")
    return LoginRateLimiter(
        store,
        secret=settings.auth_secret,
        max_failures=settings.login_max_failures,
        window_seconds=settings.login_window_seconds,
        lock_seconds=settings.login_lock_seconds,
    )
```

> `PostgresAuditStore` 与 `PostgresLoginAttemptStore` 在 Task 8 创建，因此这里用**函数内惰性导入**；本任务**不要**创建这两个类。

- [ ] **Step 5: 运行测试确认通过**

Run: `py -m pytest tests/test_audit_bootstrap.py -q`
Expected: PASS（4 passed）

- [ ] **Step 6: 跑全量测试**

Run: `py -m pytest -o addopts=""`
Expected: 全部通过（基线 380 + 本任务新增）

- [ ] **Step 7: 提交**

```bash
git add app/settings.py app/bootstrap.py tests/test_audit_bootstrap.py
git commit -m "feat: 增加审计与登录限流的配置与装配"
```

---

### Task 6: 账号模块接入审计与限流

**Files:**
- Modify: `app/accounts/service.py`
- Modify: `app/main.py`
- Modify: `tests/test_account_service.py`
- Modify: `tests/test_account_api.py`
- Test: `tests/test_account_audit.py`

- [ ] **Step 1: 先改测试辅助函数（否则后续全是导入错误）**

`tests/test_account_service.py`：把 `service()` 辅助函数改为

```python
def service(*, bootstrap_token: str = BOOTSTRAP) -> AccountService:
    return AccountService(
        InMemoryAccountRepository(),
        bootstrap_token=bootstrap_token,
        audit=AuditService(InMemoryAuditStore()),
        login_limiter=LoginRateLimiter(
            InMemoryLoginAttemptStore(),
            secret="s" * 40,
            max_failures=5,
            window_seconds=300,
            lock_seconds=900,
        ),
    )
```

并在该文件 import 区加入：

```python
from app.accounts.rate_limit import InMemoryLoginAttemptStore, LoginRateLimiter
from app.audit.service import AuditService
from app.audit.store import InMemoryAuditStore
```

`tests/test_account_api.py`：把 `accounts` fixture 改为

```python
@pytest.fixture
def accounts(monkeypatch) -> AccountService:
    service = AccountService(
        InMemoryAccountRepository(),
        bootstrap_token=BOOTSTRAP,
        audit=AuditService(InMemoryAuditStore()),
        login_limiter=LoginRateLimiter(
            InMemoryLoginAttemptStore(),
            secret="s" * 40,
            max_failures=5,
            window_seconds=300,
            lock_seconds=900,
        ),
    )
    monkeypatch.setattr(main, "account_service", service)
    monkeypatch.setattr(main.settings, "auth_secret", SECRET)
    monkeypatch.setattr(main.settings, "session_ttl_seconds", 900)
    return service
```

并在该文件 import 区加入：

```python
from app.accounts.rate_limit import InMemoryLoginAttemptStore, LoginRateLimiter
from app.audit.service import AuditService
from app.audit.store import InMemoryAuditStore
```

- [ ] **Step 2: 写新增行为测试**

新建 `tests/test_account_audit.py`：

```python
import pytest

from app.accounts.models import AccountStatus, RegistrationRequest
from app.accounts.rate_limit import InMemoryLoginAttemptStore, LoginRateLimiter, LoginRateLimited
from app.accounts.repository import InMemoryAccountRepository
from app.accounts.service import AccountService
from app.audit.models import AuditAction
from app.audit.service import AuditService
from app.audit.store import InMemoryAuditStore
from app.domain import PolicyError, UserContext

BOOTSTRAP = "bootstrap-secret-value"
PASSWORD = "correct-horse-battery"


class Harness:
    def __init__(self, *, max_failures: int = 5) -> None:
        self.audits = InMemoryAuditStore()
        self.audit = AuditService(self.audits)
        self.limiter = LoginRateLimiter(
            InMemoryLoginAttemptStore(),
            secret="s" * 40,
            max_failures=max_failures,
            window_seconds=300,
            lock_seconds=900,
        )
        self.service = AccountService(
            InMemoryAccountRepository(),
            bootstrap_token=BOOTSTRAP,
            audit=self.audit,
            login_limiter=self.limiter,
        )

    def actions(self) -> list[str]:
        # 普通注册申请在审批前没有租户归属，审计记录的 tenant_id 为空；
        # 因此这里用「不过滤租户」读取，才能看到全部动作。
        return [item.action.value for item in self.audits.list_recent(None, limit=100)]


def bootstrap_admin(harness: Harness):
    return harness.service.request_registration(
        RegistrationRequest(
            phone="13800000001",
            password=PASSWORD,
            position="内容运营",
            full_name="张三",
            tenant_id="t-1",
            bootstrap_token=BOOTSTRAP,
        )
    )


def test_first_admin_registration_audits_requested_and_approved() -> None:
    harness = Harness()

    bootstrap_admin(harness)

    assert AuditAction.ACCOUNT_REGISTRATION_REQUESTED.value in harness.actions()
    assert AuditAction.ACCOUNT_REGISTRATION_APPROVED.value in harness.actions()


def test_pending_registration_audits_requested_only() -> None:
    harness = Harness()
    bootstrap_admin(harness)

    harness.service.request_registration(
        RegistrationRequest(phone="13800000002", password=PASSWORD, position="运营", full_name="李四")
    )

    actions = harness.actions()
    assert actions.count(AuditAction.ACCOUNT_REGISTRATION_REQUESTED.value) == 2
    assert actions.count(AuditAction.ACCOUNT_REGISTRATION_APPROVED.value) == 1


def test_approval_and_rejection_are_audited() -> None:
    harness = Harness()
    admin = bootstrap_admin(harness)
    actor = UserContext("t-1", admin.account_id, "super_admin")
    first = harness.service.request_registration(
        RegistrationRequest(phone="13800000002", password=PASSWORD, position="运营", full_name="李四")
    )
    second = harness.service.request_registration(
        RegistrationRequest(phone="13800000003", password=PASSWORD, position="运营", full_name="王五")
    )

    harness.service.approve(actor, first.account_id, role="employee", tenant_id="t-1")
    harness.service.reject(actor, second.account_id, reason="资料不完整")

    actions = harness.actions()
    assert AuditAction.ACCOUNT_REGISTRATION_APPROVED.value in actions
    assert AuditAction.ACCOUNT_REGISTRATION_REJECTED.value in actions


def test_login_success_and_failure_are_audited() -> None:
    harness = Harness()
    bootstrap_admin(harness)

    with pytest.raises(Exception):
        harness.service.login("13800000001", "wrong-horse-battery")
    harness.service.login("13800000001", PASSWORD)

    actions = harness.actions()
    assert AuditAction.ACCOUNT_LOGIN_FAILED.value in actions
    assert AuditAction.ACCOUNT_LOGIN_SUCCEEDED.value in actions


def test_lockout_audits_locked_and_blocks_further_attempts() -> None:
    harness = Harness(max_failures=3)
    bootstrap_admin(harness)

    for _index in range(3):
        with pytest.raises(Exception):
            harness.service.login("13800000001", "wrong-horse-battery")

    with pytest.raises(LoginRateLimited, match="稍后再试"):
        harness.service.login("13800000001", PASSWORD)

    assert AuditAction.ACCOUNT_LOGIN_LOCKED.value in harness.actions()


def test_lockout_does_not_reveal_account_existence() -> None:
    harness = Harness(max_failures=2)

    for _index in range(2):
        with pytest.raises(Exception):
            harness.service.login("13900000009", "wrong-horse-battery")

    with pytest.raises(LoginRateLimited):
        harness.service.login("13900000009", "wrong-horse-battery")


def test_successful_login_clears_counter() -> None:
    harness = Harness(max_failures=5)
    bootstrap_admin(harness)
    for _index in range(4):
        with pytest.raises(Exception):
            harness.service.login("13800000001", "wrong-horse-battery")

    harness.service.login("13800000001", PASSWORD)

    for _index in range(4):
        with pytest.raises(Exception):
            harness.service.login("13800000001", "wrong-horse-battery")


def test_password_change_and_reset_are_audited() -> None:
    harness = Harness()
    admin = bootstrap_admin(harness)
    actor = UserContext("t-1", admin.account_id, "super_admin")

    harness.service.change_password(actor, old_password=PASSWORD, new_password="brand-new-passphrase")
    harness.service.reset_password(actor, admin.account_id, new_password="admin-reset-passphrase")

    actions = harness.actions()
    assert AuditAction.ACCOUNT_PASSWORD_CHANGED.value in actions
    assert AuditAction.ACCOUNT_PASSWORD_RESET.value in actions


def test_audit_records_never_contain_credentials() -> None:
    harness = Harness()
    bootstrap_admin(harness)
    with pytest.raises(Exception):
        harness.service.login("13800000001", "wrong-horse-battery")

    rendered = str([item.detail for item in harness.audits.list_recent(None, limit=100)])
    for leaked in ("password", "password_hash", "scrypt$", PASSWORD, "wrong-horse-battery"):
        assert leaked not in rendered


def test_audit_records_carry_masked_phone_only() -> None:
    harness = Harness()
    bootstrap_admin(harness)

    rendered = str(
        [(item.phone_masked, item.detail) for item in harness.audits.list_recent(None, limit=100)]
    )

    assert "13800000001" not in rendered
    assert "138****0001" in rendered
```

- [ ] **Step 3: 运行测试确认失败**

Run: `py -m pytest tests/test_account_audit.py -q`
Expected: FAIL，`TypeError: AccountService.__init__() got an unexpected keyword argument 'audit'`

- [ ] **Step 4: 实现服务改造**

修改 `app/accounts/service.py`：

**(a)** import 区加入：

```python
from app.audit.models import AuditAction
from app.audit.redaction import mask_phone
from app.audit.service import AuditService

from .rate_limit import LoginRateLimiter
```

**(b)** 构造函数改为：

```python
    def __init__(
        self,
        repository: AccountRepository,
        *,
        bootstrap_token: str = "",
        audit: AuditService,
        login_limiter: LoginRateLimiter,
    ) -> None:
        self.repository = repository
        self.bootstrap_token = bootstrap_token
        self.audit = audit
        self.login_limiter = login_limiter
```

**(c)** 在 `request_registration` 的两条分支里，把落库结果先接住、再写审计。普通申请分支当前的结尾是

```python
        return self.repository.add(
            Account(
                phone=phone,
                password_hash=hash_password(request.password),
                position=position,
                full_name=full_name,
                email=request.email,
            )
        )
```

改为

```python
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
```

> `request_registration` 是**匿名入口**，签名保持 `(self, request: RegistrationRequest) -> Account` 不变。普通申请在审批前还没有租户归属，因此审计记录的 `tenant_id` 为 `None`，并在明细中标注 `tenant_assigned_at_approval`；待管理员审批时会再写一条带真实租户的 `account.registration.approved`。**不要**为此放宽审计表的租户约束。

首管理员分支改为：

```python
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
```

**(d)** `approve` 与 `reject` 在返回前写审计：

```python
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
```

**(e)** `login` 改为（含锁定判定与三类审计）。先在类中新增一个私有辅助方法，再重写 `login`：

```python
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
                phone_masked=mask_phone(phone),
                detail={"failure_count": state.failure_count},
            )
        return LoginFailed("手机号或密码不正确")

    def login(self, phone: str, password: str) -> UserContext:
        normalized_phone = phone.strip() if isinstance(phone, str) else ""
        self.login_limiter.require_unlocked(normalized_phone)
        account = self.repository.find_by_phone(normalized_phone)
        # 登录是匿名入口：账号不存在或尚未分配租户时，审计记录不写租户，但必须写脱敏手机号。
        audit_tenant = str(account.tenant_id) if account is not None and account.tenant_id else None
        if account is None or account.status is not AccountStatus.APPROVED:
            raise self._fail_login(normalized_phone, audit_tenant)
        if not verify_password(password, account.password_hash):
            raise self._fail_login(normalized_phone, audit_tenant)
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
            tenant_id=str(account.tenant_id), user_id=account.account_id, role=str(account.role)
        )
```

> 三种失败（手机号不存在、状态非 `approved`、口令错误）都走 `_fail_login`，因此**文案完全一致**，既有测试 `test_login_failure_does_not_distinguish_unknown_phone_from_wrong_password` 仍会通过。

**(f)** `change_password` / `reset_password` 在成功后写审计：

```python
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
```

- [ ] **Step 5: 接口层加 429 并装配依赖**

修改 `app/main.py`：

**(a)** import 区加入：

```python
from .accounts.rate_limit import LoginRateLimited
from .audit.logging import configure_audit_logging
from .bootstrap import build_audit_service, build_login_rate_limiter
```

**(b)** 在 `planner_service, planner_store = build_planner_service(...)` 之后加入：

```python
configure_audit_logging(settings.log_level)
audit_service = build_audit_service(settings)
login_rate_limiter = build_login_rate_limiter(settings)
```

**(c)** 把 `account_service, _ = build_account_service(settings)` 改为传入依赖：

```python
account_service, _ = build_account_service(
    settings, audit=audit_service, login_limiter=login_rate_limiter
)
```

**(d)** `create_session` 的错误映射加入 `429`：

```python
    try:
        context = account_service.login(payload.phone, payload.password)
    except LoginRateLimited as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except LoginFailed as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
```

- [ ] **Step 6: 调整装配函数签名**

修改 `app/bootstrap.py` 的 `build_account_service`，让它接收并转发审计与限流依赖：

```python
def build_account_service(
    settings: Settings,
    *,
    audit: AuditService,
    login_limiter: LoginRateLimiter,
    connection=None,
    migrate: bool = True,
):
```

并在末尾的 `AccountService(...)` 调用中传入 `audit=audit, login_limiter=login_limiter`。

同时更新 `tests/test_account_bootstrap.py`：把两处 `build_account_service(...)` 调用补上 `audit=AuditService(InMemoryAuditStore())` 与 `login_limiter=LoginRateLimiter(InMemoryLoginAttemptStore(), secret="s"*40, max_failures=5, window_seconds=300, lock_seconds=900)`，并补相应 import。

- [ ] **Step 7: 运行测试**

Run: `py -m pytest tests/test_account_audit.py tests/test_account_service.py tests/test_account_api.py tests/test_account_bootstrap.py -q`
Expected: PASS

Run: `py -m pytest -o addopts=""`
Expected: 全部通过（基线 380 + 本任务新增）

- [ ] **Step 8: 提交**

```bash
git add app/accounts/service.py app/main.py app/bootstrap.py tests/test_account_audit.py tests/test_account_service.py tests/test_account_api.py tests/test_account_bootstrap.py
git commit -m "feat: 账号模块接入审计与登录限流"
```

---

### Task 7: 计划模块接入审计

**Files:**
- Modify: `app/planner/service.py`
- Modify: `app/main.py`
- Modify: `tests/test_planner_service.py`
- Modify: `tests/test_planner_api.py`
- Test: `tests/test_planner_audit.py`

- [ ] **Step 1: 先改测试辅助函数**

`tests/test_planner_service.py`：`service()` 辅助函数补上审计依赖

```python
def service(task_store, runtime=None, *, tools: ToolCatalog | None = None) -> PlannerService:
    return PlannerService(
        task_store=task_store,
        store=InMemoryPlanProposalStore(),
        generator=MockPlanGenerator(),
        catalog=tools if tools is not None else catalog(),
        runtime_service=runtime or RecordingRuntimeService(),
        max_steps=5,
        audit=AuditService(InMemoryAuditStore()),
    )
```

并在 import 区加入：

```python
from app.audit.service import AuditService
from app.audit.store import InMemoryAuditStore
```

同一文件里直接构造 `PlannerService(...)` 的那个测试（`test_generation_failure_does_not_persist_a_proposal`）也要补 `audit=AuditService(InMemoryAuditStore())`。

`tests/test_planner_api.py`：`planner` fixture 与 `test_planner_api.py` 内直接构造 `PlannerService` 的地方同样补 `audit=AuditService(InMemoryAuditStore())`，并补 import。

- [ ] **Step 2: 写新增行为测试**

新建 `tests/test_planner_audit.py`：

```python
import pytest

from app.audit.models import AuditAction
from app.audit.service import AuditService
from app.audit.store import InMemoryAuditStore
from app.domain import RiskLevel, Task, TaskStatus, UserContext
from app.planner.generator import MockPlanGenerator
from app.planner.models import Tool, ToolCatalog
from app.planner.service import PlannerService
from app.planner.store import InMemoryPlanProposalStore


class RecordingRuntimeService:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def start(self, actor, task_id, runtime_key, steps, mode):
        self.calls.append((task_id, runtime_key, steps, mode))
        return "run-1", runtime_key, "policy-1"


def harness():
    audits = InMemoryAuditStore()
    runtime = RecordingRuntimeService()
    service = PlannerService(
        task_store=TaskStoreFixture.store,
        store=InMemoryPlanProposalStore(),
        generator=MockPlanGenerator(),
        catalog=ToolCatalog((Tool(name="knowledge.search", kind="read"),)),
        runtime_service=runtime,
        max_steps=5,
        audit=AuditService(audits),
    )
    return service, audits, runtime


class TaskStoreFixture:
    store = None


def bootstrap():
    from app.domain import TaskStore

    TaskStoreFixture.store = TaskStore()
    task = Task(
        tenant_id="t-1",
        project_id=None,
        created_by="u-1",
        employee_key="content-operator",
        title="整理选题",
        risk_level=RiskLevel.LOW,
        budget=1,
        idempotency_key="plan-audit-1",
        request_fingerprint="fp",
        status=TaskStatus.QUEUED,
    )
    TaskStoreFixture.store.create(UserContext("t-1", "u-1", "employee"), task)
    return task


def actions(audits: InMemoryAuditStore) -> list[str]:
    return [item.action.value for item in audits.list_recent("t-1", limit=100)]


def test_propose_approve_run_are_audited() -> None:
    task = bootstrap()
    service, audits, _runtime = harness()

    proposal = service.propose(UserContext("t-1", "u-1", "employee"), task.id, "整理选题", "key-1")
    service.approve(UserContext("t-1", "ceo-1", "ceo"), proposal.proposal_id)
    service.start_run(UserContext("t-1", "u-1", "employee"), proposal.proposal_id, "mock", "product_manager")

    recorded = actions(audits)
    assert AuditAction.PLAN_PROPOSED.value in recorded
    assert AuditAction.PLAN_APPROVED.value in recorded
    assert AuditAction.PLAN_RUN_STARTED.value in recorded


def test_reject_is_audited() -> None:
    task = bootstrap()
    service, audits, _runtime = harness()
    proposal = service.propose(UserContext("t-1", "u-1", "employee"), task.id, "整理选题", "key-1")

    service.reject(UserContext("t-1", "ceo-1", "ceo"), proposal.proposal_id, "步骤不完整")

    assert AuditAction.PLAN_REJECTED.value in actions(audits)


def test_propose_audit_detail_has_step_count_not_goal_text() -> None:
    task = bootstrap()
    service, audits, _runtime = harness()

    service.propose(UserContext("t-1", "u-1", "employee"), task.id, "机密目标文本", "key-1")

    details = [item.detail for item in audits.list_recent("t-1", limit=100)]
    assert any(item.get("step_count") == 1 for item in details)
    assert "机密目标文本" not in str(details)


def test_run_audit_detail_contains_runtime_key() -> None:
    task = bootstrap()
    service, audits, _runtime = harness()
    proposal = service.propose(UserContext("t-1", "u-1", "employee"), task.id, "整理选题", "key-1")
    service.approve(UserContext("t-1", "ceo-1", "ceo"), proposal.proposal_id)

    service.start_run(UserContext("t-1", "u-1", "employee"), proposal.proposal_id, "mock", "product_manager")

    details = [item.detail for item in audits.list_recent("t-1", limit=100)]
    assert {"runtime_key": "mock"} in details


def test_rejected_proposal_is_not_audited_as_approved() -> None:
    task = bootstrap()
    service, audits, _runtime = harness()
    proposal = service.propose(UserContext("t-1", "u-1", "employee"), task.id, "整理选题", "key-1")

    service.reject(UserContext("t-1", "ceo-1", "ceo"), proposal.proposal_id, "不通过")

    recorded = actions(audits)
    assert AuditAction.PLAN_APPROVED.value not in recorded
```

- [ ] **Step 3: 运行测试确认失败**

Run: `py -m pytest tests/test_planner_audit.py -q`
Expected: FAIL，`TypeError: PlannerService.__init__() got an unexpected keyword argument 'audit'`

- [ ] **Step 4: 实现服务改造**

修改 `app/planner/service.py`：import 区加入

```python
from app.audit.models import AuditAction
from app.audit.service import AuditService
```

构造函数增加必填参数 `audit: AuditService` 并保存为 `self.audit`；然后在四个方法返回前写审计：

`propose`（落库之后）：

```python
        saved = self.store.add(proposal)
        self.audit.record(
            AuditAction.PLAN_PROPOSED,
            tenant_id=actor.tenant_id,
            actor_id=actor.user_id,
            target_type="plan_proposal",
            target_id=saved.proposal_id,
            detail={"step_count": len(saved.steps), "generator": saved.generator_key},
        )
        return saved
```

`approve`：

```python
        approved = self.store.mark_approved(proposal_id, reviewer=actor.user_id)
        self.audit.record(
            AuditAction.PLAN_APPROVED,
            tenant_id=actor.tenant_id,
            actor_id=actor.user_id,
            target_type="plan_proposal",
            target_id=approved.proposal_id,
            detail={"step_count": len(approved.steps)},
        )
        return approved
```

`reject`：

```python
        rejected = self.store.mark_rejected(proposal_id, reason=normalized_reason, reviewer=actor.user_id)
        self.audit.record(
            AuditAction.PLAN_REJECTED,
            tenant_id=actor.tenant_id,
            actor_id=actor.user_id,
            target_type="plan_proposal",
            target_id=rejected.proposal_id,
            detail={"reason": normalized_reason},
        )
        return rejected
```

`start_run`（成功之后、返回之前）：

```python
        run_id, runtime_key, policy_version = self.runtime_service.start(
            actor, proposal.task_id, runtime_key, steps, mode
        )
        self.audit.record(
            AuditAction.PLAN_RUN_STARTED,
            tenant_id=actor.tenant_id,
            actor_id=actor.user_id,
            target_type="plan_proposal",
            target_id=proposal.proposal_id,
            detail={"runtime_key": runtime_key},
        )
        return run_id, runtime_key, policy_version
```

- [ ] **Step 5: 装配传入审计**

修改 `app/main.py` 的 `build_planner_service(...)` 调用，补上审计：

```python
planner_service, planner_store = build_planner_service(
    settings, task_store=store, runtime_service=runtime_service, audit=audit_service
)
```

同时修改 `app/bootstrap.py` 的 `build_planner_service` 签名，接收 `audit: AuditService` 并传给 `PlannerService(audit=audit)`。

- [ ] **Step 6: 运行测试**

Run: `py -m pytest tests/test_planner_audit.py tests/test_planner_service.py tests/test_planner_api.py -q`
Expected: PASS

Run: `py -m pytest -o addopts=""`
Expected: 全部通过（基线 380 + 本任务新增）

- [ ] **Step 7: 提交**

```bash
git add app/planner/service.py app/bootstrap.py app/main.py tests/test_planner_audit.py tests/test_planner_service.py tests/test_planner_api.py
git commit -m "feat: 计划模块接入审计"
```

---

### Task 8: PostgreSQL 迁移与仓储

**Files:**
- Create: `migrations/010_audit_log.sql`
- Create: `migrations/011_login_attempts.sql`
- Modify: `app/audit/store.py`
- Modify: `app/accounts/rate_limit.py`
- Test: `tests/test_audit_postgres.py`

- [ ] **Step 1: 写失败测试**

```python
from datetime import UTC, datetime

import pytest

from app.accounts.rate_limit import LoginAttemptState, PostgresLoginAttemptStore
from app.audit.models import AuditAction, build_record
from app.audit.store import PostgresAuditStore


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


def audit_row() -> tuple:
    return (
        1,
        "account.login.succeeded",
        "u-1",
        "t-1",
        "account",
        "u-1",
        "138****0001",
        '{"step_count": 2}',
        datetime(2026, 9, 10, tzinfo=UTC),
    )


def test_audit_append_uses_transaction_and_parses_detail() -> None:
    connection = RecordingConnection([audit_row()])
    store = PostgresAuditStore(connection)

    saved = store.append(
        build_record(AuditAction.ACCOUNT_LOGIN_SUCCEEDED, tenant_id="t-1", actor_id="u-1")
    )

    assert saved.action is AuditAction.ACCOUNT_LOGIN_SUCCEEDED
    assert saved.detail == {"step_count": 2}
    assert saved.phone_masked == "138****0001"
    assert connection.transaction_count == 1
    assert "INSERT INTO workbench_audit_log" in connection.cursor_instance.statements[0][0]


def test_audit_append_passes_columns_in_order() -> None:
    connection = RecordingConnection([audit_row()])
    store = PostgresAuditStore(connection)
    draft = build_record(AuditAction.PLAN_PROPOSED, tenant_id="t-1", actor_id="u-1", detail={"step_count": 2})

    store.append(draft)

    _statement, params = connection.cursor_instance.statements[0]
    assert len(params) == 9
    assert params[1] == draft.action.value
    assert params[2] == "u-1"
    assert params[3] == "t-1"


def test_audit_list_recent_is_tenant_scoped() -> None:
    connection = RecordingConnection([[audit_row()]])
    store = PostgresAuditStore(connection)

    items = store.list_recent("t-1", limit=10)

    assert len(items) == 1
    statement, params = connection.cursor_instance.statements[0]
    assert "tenant_id = %s" in statement
    assert params == ("t-1", 10)


def test_rate_limit_store_round_trip() -> None:
    connection = RecordingConnection(
        [("hash-1", 3, datetime(2026, 9, 10, tzinfo=UTC), None)]
    )
    store = PostgresLoginAttemptStore(connection)

    state = store.load("hash-1")

    assert state is not None
    assert state.failure_count == 3
    assert state.locked_until is None


def test_rate_limit_store_returns_none_when_absent() -> None:
    connection = RecordingConnection([None])
    store = PostgresLoginAttemptStore(connection)

    assert store.load("hash-missing") is None


def test_rate_limit_store_record_failure_uses_single_statement() -> None:
    connection = RecordingConnection(
        [("hash-1", 3, datetime(2026, 9, 10, tzinfo=UTC), None)]
    )
    store = PostgresLoginAttemptStore(connection)

    state = store.record_failure(
        "hash-1",
        now=datetime(2026, 9, 10, tzinfo=UTC),
        window_seconds=300,
        max_failures=5,
        lock_seconds=900,
    )

    assert state.failure_count == 3
    assert connection.transaction_count == 1
    statement = connection.cursor_instance.statements[0][0]
    assert "INSERT INTO workbench_login_attempts" in statement
    assert "ON CONFLICT (phone_hash) DO UPDATE" in statement


def test_rate_limit_store_clear_deletes() -> None:
    connection = RecordingConnection([])
    store = PostgresLoginAttemptStore(connection)

    store.clear("hash-1")

    statement, params = connection.cursor_instance.statements[0]
    assert "DELETE FROM workbench_login_attempts" in statement
    assert params == ("hash-1",)


def test_migrations_010_and_011_define_expected_constraints() -> None:
    from pathlib import Path

    audit_sql = Path("migrations/010_audit_log.sql").read_text(encoding="utf-8")
    throttle_sql = Path("migrations/011_login_attempts.sql").read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS workbench_audit_log" in audit_sql
    assert "detail JSONB NOT NULL DEFAULT '{}'::jsonb" in audit_sql
    assert "occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()" in audit_sql

    assert "CREATE TABLE IF NOT EXISTS workbench_login_attempts" in throttle_sql
    assert "phone_hash TEXT PRIMARY KEY" in throttle_sql
    assert "failure_count INTEGER NOT NULL DEFAULT 0" in throttle_sql
```

- [ ] **Step 2: 运行测试确认失败**

Run: `py -m pytest tests/test_audit_postgres.py -q`
Expected: FAIL，`ImportError: cannot import name 'PostgresAuditStore'` 与 `FileNotFoundError`

- [ ] **Step 3: 写迁移文件**

`migrations/010_audit_log.sql`：

```sql
CREATE TABLE IF NOT EXISTS workbench_audit_log (
    id BIGSERIAL PRIMARY KEY,
    action TEXT NOT NULL,
    actor_id TEXT,
    tenant_id TEXT,
    target_type TEXT,
    target_id TEXT,
    phone_masked TEXT,
    detail JSONB NOT NULL DEFAULT '{}'::jsonb,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_workbench_audit_log_tenant_time
    ON workbench_audit_log (tenant_id, occurred_at DESC);

CREATE INDEX IF NOT EXISTS idx_workbench_audit_log_action_time
    ON workbench_audit_log (action, occurred_at DESC);

CREATE INDEX IF NOT EXISTS idx_workbench_audit_log_target
    ON workbench_audit_log (target_id);
```

`migrations/011_login_attempts.sql`：

```sql
CREATE TABLE IF NOT EXISTS workbench_login_attempts (
    phone_hash TEXT PRIMARY KEY,
    failure_count INTEGER NOT NULL DEFAULT 0,
    window_started_at TIMESTAMPTZ NOT NULL,
    locked_until TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_workbench_login_attempts_locked
    ON workbench_login_attempts (locked_until);
```

- [ ] **Step 4: 实现 PostgreSQL 仓储**

`app/audit/store.py`：import 区补充

```python
import json
from contextlib import contextmanager, nullcontext
from datetime import UTC, datetime
```

文件末尾追加：

```python
class PostgresAuditStore:
    """审计持久化；写入在事务内完成，失败向上抛出。"""

    _COLUMNS = "id, action, actor_id, tenant_id, target_type, target_id, phone_masked, detail, occurred_at"

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
    def _hydrate(row: tuple) -> AuditRecord:
        raw_detail = row[7]
        if isinstance(raw_detail, str):
            raw_detail = json.loads(raw_detail)
        return AuditRecord(
            action=AuditAction(str(row[1])),
            actor_id=row[2],
            tenant_id=str(row[3]),
            target_type=row[4],
            target_id=row[5],
            phone_masked=row[6],
            detail=dict(raw_detail or {}),
            record_id=str(row[0]),
            occurred_at=row[8] if isinstance(row[8], datetime) else datetime.now(UTC),
        )

    def append(self, record: AuditRecord) -> AuditRecord:
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""
                        INSERT INTO workbench_audit_log ({self._COLUMNS})
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)
                        RETURNING {self._COLUMNS}
                        """,
                        (
                            record.record_id,
                            record.action.value,
                            record.actor_id,
                            record.tenant_id,
                            record.target_type,
                            record.target_id,
                            record.phone_masked,
                            json.dumps(record.detail, ensure_ascii=False),
                            record.occurred_at,
                        ),
                    )
                    row = cursor.fetchone()
        if row is None:
            raise RuntimeError("审计写入失败")
        return self._hydrate(row)

    def list_recent(self, tenant_id: str | None = None, *, limit: int = 100) -> list[AuditRecord]:
        """按租户过滤；`tenant_id` 为 None 时返回全部（供测试与后续管理端排查使用）。"""
        with self._connection() as connection:
            with connection.cursor() as cursor:
                if tenant_id is None:
                    cursor.execute(
                        f"""
                        SELECT {self._COLUMNS} FROM workbench_audit_log
                        ORDER BY id DESC LIMIT %s
                        """,
                        (limit,),
                    )
                else:
                    cursor.execute(
                        f"""
                        SELECT {self._COLUMNS} FROM workbench_audit_log
                        WHERE tenant_id = %s ORDER BY id DESC LIMIT %s
                        """,
                        (tenant_id, limit),
                    )
                rows = cursor.fetchall()
        return [self._hydrate(row) for row in reversed(rows)]
```

注意：`id` 是 `BIGSERIAL`，因此 `AuditRecord.record_id` 用插入值（`RETURNING` 的第一列）；`_hydrate` 中按 `str(row[0])` 还原。

`app/accounts/rate_limit.py`：import 区补充

```python
from contextlib import contextmanager, nullcontext
```

文件末尾追加：

```python
class PostgresLoginAttemptStore:
    """登录尝试持久化；save 使用 upsert 原子写入。"""

    _COLUMNS = "phone_hash, failure_count, window_started_at, locked_until"

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
    def _hydrate(row: tuple) -> LoginAttemptState:
        return LoginAttemptState(
            phone_hash=str(row[0]),
            failure_count=int(row[1]),
            window_started_at=row[2],
            locked_until=row[3],
        )

    def load(self, phone_hash: str) -> LoginAttemptState | None:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT {self._COLUMNS} FROM workbench_login_attempts WHERE phone_hash = %s",
                    (phone_hash,),
                )
                row = cursor.fetchone()
        return self._hydrate(row) if row is not None else None

    def record_failure(
        self,
        phone_hash: str,
        *,
        now: datetime,
        window_seconds: int,
        max_failures: int,
        lock_seconds: int,
    ) -> LoginAttemptState:
        window_cutoff = now - timedelta(seconds=window_seconds)
        lock_until = now + timedelta(seconds=lock_seconds)
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""
                        INSERT INTO workbench_login_attempts
                            (phone_hash, failure_count, window_started_at, locked_until, updated_at)
                        VALUES (%s, 1, %s, NULL, now())
                        ON CONFLICT (phone_hash) DO UPDATE SET
                            failure_count = CASE
                                WHEN workbench_login_attempts.window_started_at <= %s THEN 1
                                ELSE workbench_login_attempts.failure_count + 1 END,
                            window_started_at = CASE
                                WHEN workbench_login_attempts.window_started_at <= %s THEN %s
                                ELSE workbench_login_attempts.window_started_at END,
                            locked_until = CASE
                                WHEN (CASE
                                        WHEN workbench_login_attempts.window_started_at <= %s THEN 1
                                        ELSE workbench_login_attempts.failure_count + 1 END) >= %s
                                    THEN %s
                                ELSE NULL END,
                            updated_at = now()
                        RETURNING {self._COLUMNS}
                        """,
                        (
                            phone_hash,
                            now,
                            window_cutoff,
                            window_cutoff,
                            now,
                            window_cutoff,
                            max_failures,
                            lock_until,
                        ),
                    )
                    row = cursor.fetchone()
        if row is None:
            raise RuntimeError("登录尝试写入失败")
        return self._hydrate(row)

    def clear(self, phone_hash: str) -> None:
        with self._connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        "DELETE FROM workbench_login_attempts WHERE phone_hash = %s", (phone_hash,)
                    )
```

> 注意：`PostgresLoginAttemptStore.record_failure` 用**单条 upsert 语句**在同一事务内完成「窗口判断 + 计数 + 锁定」，因此内存与 PostgreSQL 两种实现都满足原子性要求，无需在服务层再加锁。`_COLUMNS` 必须与 `_hydrate` 的取值顺序、`RETURNING` 的列顺序一致。

- [ ] **Step 5: 运行测试确认通过**

Run: `py -m pytest tests/test_audit_postgres.py -q`
Expected: PASS（8 passed）

- [ ] **Step 6: 跑全量测试与编译检查**

Run: `py -m pytest -o addopts=""`
Expected: 全部通过（基线 380 + 本任务新增）

Run: `py -m compileall -q app tests extract_pdf.py scripts`
Expected: 退出码 0

- [ ] **Step 7: 提交**

```bash
git add migrations/010_audit_log.sql migrations/011_login_attempts.sql app/audit/store.py app/accounts/rate_limit.py tests/test_audit_postgres.py
git commit -m "feat: 增加审计与登录限流的 PostgreSQL 迁移与仓储"
```

---

### Task 9: 文档同步

**Files:**
- Modify: `docs/api-contract.md`
- Modify: `.env.example`
- Modify: `.env.staging.example`
- Modify: `docs/private-deployment-runbook.md`
- Modify: `docs/delivery-gates.md`

- [ ] **Step 1: 更新接口契约**

在 `docs/api-contract.md` 的「## 账号注册与登录」小节内，把 `POST /api/v1/auth/sessions` 一段改为（补 `429`）：

```markdown
`POST /api/v1/auth/sessions`

用 `phone` 与 `password` 换取会话令牌。手机号不存在、口令错误或账号未通过审批一律返回 `401` 且不区分原因。**同一手机号在 5 分钟窗口内失败达到阈值（默认 5 次）后锁定 15 分钟，锁定期间一律返回 `429`**；由于计数按手机号统一执行，已存在与不存在的手机号达到阈值后表现一致，不泄露账号是否存在。成功返回 `access_token`、`token_type`、`expires_in`、`tenant_id`、`user_id` 和 `role`。会话密钥未配置时返回 `503`。
```

在该小节末尾追加：

```markdown
### 关键操作审计

账号与计划模块的关键操作会写入通用安全审计表 `workbench_audit_log`，并同时输出单行 JSON 结构化日志（logger 名 `company_workbench.audit`）。

覆盖动作：`account.registration.requested`、`account.registration.approved`、`account.registration.rejected`、`account.login.succeeded`、`account.login.failed`、`account.login.locked`、`account.password.changed`、`account.password.reset`、`plan.proposed`、`plan.approved`、`plan.rejected`、`plan.run_started`。

审计记录包含动作、操作者、租户、目标、脱敏手机号与结构化明细；**不包含**口令、口令哈希、令牌、Cookie、密钥或模型原始响应。本轮不提供读取审计的接口。
```

- [ ] **Step 2: 更新环境示例**

在 `.env.example` 末尾追加：

```dotenv
# 登录限流：5 分钟窗口内失败达阈值即锁定
WORKBENCH_LOGIN_MAX_FAILURES=5
WORKBENCH_LOGIN_WINDOW_SECONDS=300
WORKBENCH_LOGIN_LOCK_SECONDS=900
```

- [ ] **Step 3: 同步迁移清单**

把 `.env.staging.example` 的 `WORKBENCH_APPLIED_MIGRATIONS` 行末尾追加 `,010_audit_log,011_login_attempts`：

```dotenv
WORKBENCH_APPLIED_MIGRATIONS=001_initial,002_event_outbox,003_dead_letters,004_knowledge_access_bindings,005_knowledge_access_audit,006_commercial_g0,007_commercial_retention,008_accounts,009_plan_proposals,010_audit_log,011_login_attempts
```

把 `docs/private-deployment-runbook.md` 中迁移范围 `001` 至 `009` 更新为 `001` 至 `011`。

- [ ] **Step 4: 更新交付门禁**

在 `docs/delivery-gates.md` 中，把这三行

```markdown
- [ ] 账号登录限流与失败锁定（宪法第一道防线要求）
- [ ] 账号关键操作结构化审计日志（注册、审批、登录、改密、重置）
- [ ] 计划模块的生成、审批与执行纳入审计（与上一项一并落地）
```

替换为

```markdown
- [x] 账号登录限流与失败锁定（开发期接口验证）
- [x] 账号与计划模块关键操作审计（审计表 + 结构化日志，开发期接口验证）
```

- [ ] **Step 5: 验证**

Run: `py -m pytest -o addopts=""`
Expected: 全部通过

Run: `py -m compileall -q app tests extract_pdf.py scripts`
Expected: 退出码 0

Run: `py -c "from pathlib import Path; from scripts.commercial_g0_preflight import run_preflight; expected=sorted(p.stem for p in Path('migrations').glob('*.sql')); v={'environment':'staging','storage_backend':'postgres','database_url':'postgresql://u:p@h/db','auth_secret':'a'*32,'backup_key':'b'*32,'applied_migrations':expected,'expected_migrations':expected,'retention_policy':{'tasks':180},'runtime_versions':{'mock':'0.1.0'}}; print([(c.name,c.status) for c in run_preflight(v).checks if '迁移' in c.name])"`
Expected: `[('迁移状态', 'pass')]`

Run: `git diff --check`
Expected: 无空白错误

- [ ] **Step 6: 提交**

```bash
git add docs/api-contract.md .env.example .env.staging.example docs/private-deployment-runbook.md docs/delivery-gates.md
git commit -m "docs: 同步审计与登录限流契约及配置"
```

---

## 验收对照

| 规格要求 | 对应任务 |
| --- | --- |
| 共享脱敏工具（敏感键、手机号），消除重复实现 | Task 1 |
| `AuditAction` 12 类动作与明细校验 | Task 1 |
| 单行 JSON 结构化日志、幂等安装格式化器 | Task 2 |
| 审计仓储协议 + 内存实现 + `AuditService` | Task 3 |
| 手机号 HMAC 键、窗口/阈值/锁定、成功清零、并发不丢计数 | Task 4 |
| 三项配置与越界拒绝启动、两种装配路径 | Task 5 |
| 账号 8 类动作审计 + 登录锁定 + `429` | Task 6 |
| 计划 4 类动作审计 | Task 7 |
| PostgreSQL 迁移 `010`/`011` 与两种仓储 | Task 8 |
| 接口契约、环境示例、迁移清单、交付门禁 | Task 9 |

## 明确不做

不做读取审计的接口、不做按 IP 限流、不做账号解锁接口、不改造全项目日志设施、不引入第三方日志或限流库。生产并发下的限流原子性与网关层限流仍需单独验收；真实 staging 联调不在本计划范围内。
