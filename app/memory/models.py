"""记忆层（记忆 / 画像）的领域模型、错误类型与访问权限判定。

口径见 `docs/superpowers/specs/2026-09-15-memory-layer-p3-design.md` §2。

三张表对应三类记忆：事实（`workbench_memory_facts`）、规则（`workbench_memory_rules`）、
身份画像（`workbench_memory_profile_keys`）。权限判定刻意放在本模块，供仓储层、服务层与
接口层共用同一份实现（沿用对话层 §8 约束 3 的手法）：
读他人记忆 / 跨租户一律映射为「未找到」（404），写他人记忆映射为「无权限」（403 PolicyError），
避免探测存在性。

作用域（scope）是域内枚举，**由服务端解析**，客户端不得直接指定（§2.3）；
规则写强制人工在环 + 版本快照，事实/画像可手工写入。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from ..domain import PolicyError, UserContext

# 事实内容 / 画像值的长度上限（§2.4：写入前服务端二次校验）。
MAX_MEMORY_CONTENT_LENGTH = 8000
MAX_PROFILE_VALUE_LENGTH = 4000
MAX_PROFILE_KEYS_PER_OWNER = 64
# 向量维度固定 1024（Qwen3-Embedding-0.6B 一锤定音，D12 一次性建列）。
EMBEDDING_DIMENSIONS = 1024

# 规则类 rule_key 的稳定标识格式（沿用对话层数字员工标识 normalize_key 风格：小写、可含 . _ -）。
_RULE_KEY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")

# 可查看 / 管理本租户内他人记忆的岗位（§2.7：读沿用对话层 VIEW_ANY_ROLES 口径——治理者可见）。
VIEW_ANY_ROLES = frozenset({"ceo", "super_admin"})


class MemoryScope(StrEnum):
    """作用域域内枚举；由服务端从解析规则推导，客户端不得直接指定（§2.3）。"""

    USER = "user"
    ROLE = "role"
    PROJECT = "project"
    ORGANIZATION = "organization"


class MemoryOwnerKind(StrEnum):
    """记忆归属方类别：账号用户或数字员工。"""

    USER = "user"
    AGENT = "agent"


class MemoryStatus(StrEnum):
    """软删口径：活跃 / 已被后继条目作废（supersede 链，§2.2）。"""

    ACTIVE = "active"
    SUPERSEDED = "superseded"


class MemoryError(ValueError):
    """记忆操作失败的基类；接口层按子类映射到 4xx。"""


class InvalidMemory(MemoryError):
    """输入不合法（scope / content / rule_key / owner 等）→ 422。"""


class MemoryStateConflict(MemoryError):
    """状态冲突（例如作废一条已作废的记忆）→ 409。"""


class MemoryBudgetExceeded(MemoryError):
    """记忆写入成本超过每日预算（§2.8 熔断之一）→ 429。"""


class MemoryNotFound(LookupError):
    """记忆不存在、跨租户，或不属于当前操作者 → 404。

    刻意**不**继承 `MemoryError`/`PolicyError`：否则会被 403/422 分支截走，
    把「看不到（避免探测存在性）」误报成「无权限」或「参数错误」（沿用对话层口径）。
    """


def now() -> datetime:
    return datetime.now(UTC)


def new_memory_id() -> str:
    return f"memo-{uuid4().hex[:12]}"


@dataclass(frozen=True)
class MemoryFact:
    """事实类记忆：短句 + 向量，可累积 / 可 supersede（§2.1）。"""

    tenant_id: str
    memory_id: str
    owner_kind: MemoryOwnerKind
    owner_id: str
    scope: MemoryScope
    content: str
    embedding: tuple[float, ...] | None
    idempotency_key: str
    status: MemoryStatus = MemoryStatus.ACTIVE
    superseded_by: str | None = None
    created_by: str | None = None
    created_at: datetime | None = field(default_factory=now)


@dataclass(frozen=True)
class MemoryRule:
    """规则类记忆：整段准则文本，强制人工在环 + 版本快照可回滚（§2.1 / §2.4）。"""

    tenant_id: str
    memory_id: str
    owner_kind: MemoryOwnerKind
    owner_id: str
    scope: MemoryScope
    content: str
    rule_key: str
    version: int  # 第几版；再次写入同 rule_key 时 supersede 旧版并 version+1。
    status: MemoryStatus = MemoryStatus.ACTIVE
    superseded_by: str | None = None
    created_by: str | None = None
    created_at: datetime | None = field(default_factory=now)


@dataclass(frozen=True)
class MemoryProfileKey:
    """身份类画像 KV 项：同键覆盖（UPSERT），不进向量检索（§2.1）。"""

    tenant_id: str
    owner_kind: MemoryOwnerKind
    owner_id: str
    profile_key: str
    value: str
    created_by: str | None = None
    updated_at: datetime | None = field(default_factory=now)


# ------------------------------------------------------------ 访问权限（跨层共用）


def can_manage_any(context: UserContext) -> bool:
    """是否可管理本租户内他人记忆（写：CEO / 超级管理员）。"""
    return context.role in VIEW_ANY_ROLES


def can_view_any(context: UserContext) -> bool:
    """是否可查看本租户内他人记忆（读：CEO / 超级管理员）。"""
    return context.role in VIEW_ANY_ROLES


def ensure_can_manage(context: UserContext, owner_kind: MemoryOwnerKind | str, owner_id: str) -> None:
    """写入记忆归属校验：本人可写自己的；CEO / 超级管理员可写本租户内任何 owner；否则 403。

    读路径的「未找到」口径在 `ensure_can_view`，二者刻意分开映射不同 4xx。
    """
    owner_kind = MemoryOwnerKind(owner_kind)
    if owner_kind is MemoryOwnerKind.USER and owner_id == context.user_id:
        return
    if can_manage_any(context):
        return
    raise PolicyError("只能管理自己的记忆")


def ensure_can_view(context: UserContext, owner_kind: MemoryOwnerKind | str, owner_id: str) -> None:
    """读取记忆归属校验：本人可读；CEO / 超级管理员可读本租户内他人记忆；其余按「未找到」处理。"""
    owner_kind = MemoryOwnerKind(owner_kind)
    if owner_kind is MemoryOwnerKind.USER and owner_id == context.user_id:
        return
    if can_view_any(context):
        return
    raise MemoryNotFound(owner_id)


# ------------------------------------------------------------ 输入归一化


def normalize_scope(value: str | MemoryScope) -> MemoryScope:
    """归一作用域白名单枚举；非法值抛 422（服务端解析后传入，客户端直传也会在此被兜底拦截）。"""
    try:
        return MemoryScope(value)
    except ValueError as exc:
        raise InvalidMemory("scope 只能是 user / role / project / organization") from exc


def normalize_owner_kind(value: str | MemoryOwnerKind) -> MemoryOwnerKind:
    """归一归属方类别；非法值抛 422。"""
    try:
        return MemoryOwnerKind(value)
    except ValueError as exc:
        raise InvalidMemory("owner_kind 只能是 user / agent") from exc


def normalize_content(value: str) -> str:
    """归一记忆内容：非空、去首尾空白、≤ 上限；非法抛 422。"""
    if not isinstance(value, str):
        raise InvalidMemory("记忆内容必须是字符串")
    if not value.strip():
        raise InvalidMemory("记忆内容不能为空")
    if len(value) > MAX_MEMORY_CONTENT_LENGTH:
        raise InvalidMemory(f"记忆内容最长 {MAX_MEMORY_CONTENT_LENGTH} 个字符")
    return value.strip()


def normalize_rule_key(value: str) -> str:
    """归一规则类记忆的 rule_key（稳定锚 -> superse 链幂等键）。

    沿用对话层数字员工标识 normalize_key 风格：小写、字母或数字开头、可含 . _ -，最长 64。
    """
    if not isinstance(value, str):
        raise InvalidMemory("rule_key 必须是字符串")
    normalized = value.strip().lower()
    if not normalized:
        raise InvalidMemory("rule_key 不能为空")
    if not _RULE_KEY_PATTERN.match(normalized):
        raise InvalidMemory(
            "rule_key 只能包含小写字母、数字、点、下划线与短横线，且必须以字母或数字开头（最长 64 个字符）"
        )
    return normalized


def normalize_profile_key(value: str) -> str:
    """归一画像键：服务端声明值，非自由文本；沿用 rule_key 的稳定标识风格。"""
    return normalize_rule_key(value)


def normalize_profile_value(value: str) -> str:
    """归一画像值：非空、去首尾空白、≤ 上限；非法抛 422。"""
    if not isinstance(value, str):
        raise InvalidMemory("画像值必须是字符串")
    if not value.strip():
        raise InvalidMemory("画像值不能为空")
    if len(value) > MAX_PROFILE_VALUE_LENGTH:
        raise InvalidMemory(f"画像值最长 {MAX_PROFILE_VALUE_LENGTH} 个字符")
    return value.strip()