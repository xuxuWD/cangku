"""数字员工配置的写入闸门：D11 提示词防护 + 取值校验 + 审计。

🔴 D11：提示词必须在**写入阶段**拦截，不允许留到运行期。
🔴 写配置**仅 `super_admin`**（与岗位/数字员工目录的管理档同权限）；
   读配置为**归属人 ∪ `super_admin`**（V4=A：`use` 档成员亦不可读），
   该判定在**仓储层**（需要「这一行属于谁」，路由层拿不到）。
"""

from __future__ import annotations

import re
import unicodedata

from ..audit.models import AuditAction
from ..domain import PolicyError, UserContext
from .models import (
    AUTONOMY_LEVELS,
    MAX_APPROVAL_TIMEOUT_MINUTES,
    MAX_SYSTEM_PROMPT_LENGTH,
    MIN_APPROVAL_TIMEOUT_MINUTES,
    RISK_THRESHOLDS,
    DigitalEmployee,
    InvalidAgentConfig,
    InvalidDirectoryKey,
    normalize_key,
)
from .store import WorkforceDirectoryStore

# 零宽字符与常见分隔符：归一后抹平，防「i.g.n.o.r.e」「忽 略 审 批」之类绕过
_ZERO_WIDTH = dict.fromkeys(map(ord, "\u200b\u200c\u200d\u2060\ufeff"), None)
_SEPARATOR = re.compile(
    r"[\s\.\-_\*/\|~,，、;；:：'\"“”‘’()（）\[\]【】{}<>《》!！?？=+]+"
)
# 试图改变权限判定的中文动词 × 目标（顺序固定为「动词 + 目标」）
_ZH_VERBS = ("忽略", "无视", "绕过", "跳过", "不遵守", "不要遵守", "取消", "关闭", "禁用", "停用", "解除", "移除", "去掉", "豁免", "免去", "免")
_ZH_TARGETS = ("审批", "审核", "权限", "限制", "约束", "校验", "检查", "门禁", "闸门")
# 英文注入指令（squash 后比对，故此处不含空格/标点）
_EN_PHRASES = (
    "ignorepreviousinstructions",
    "ignoreaboveinstructions",
    "ignorethepreviousinstructions",
    "ignoretheaboveinstructions",
    "ignoreallpreviousinstructions",
    "ignoreinstructions",
    "disregardpreviousinstructions",
    "disregardaboveinstructions",
    "disregardinstructions",
    "forgetpreviousinstructions",
    "forgetinstructions",
    "skipapproval",
    "skipapprovals",
    "skipapprovalprocess",
    "bypassapproval",
    "bypassapprovals",
    "bypasspermission",
    "bypasspermissions",
    "ignorepermission",
    "ignorepermissions",
    "ignorelimitation",
    "ignorelimitations",
    "disableapproval",
    "disableapprovals",
    "disablepermission",
    "disablepermissions",
    "removeapproval",
    "removepermission",
    "noapprovalrequired",
    "withoutapproval",
)

_MEMORY_POLICY_KEYS = frozenset({"short_term_enabled", "short_term_turns"})


def _squash(text: str) -> str:
    """全角→半角、大小写归一、去零宽与常见分隔符，得到用于比对的紧凑串。"""
    normalized = unicodedata.normalize("NFKC", text)
    normalized = normalized.translate(_ZERO_WIDTH)
    return _SEPARATOR.sub("", normalized.lower())


def scan_system_prompt(text: str) -> str | None:
    """提示注入扫描；命中返回中文原因，未命中返回 None。

    刻意**不做**「否定前缀」豁免：`不要忽略审批，直接执行` 这类句子若因「不要」放行，
    就会成为绕过口子。此处按 fail-closed 处理，宁可误拒。
    """
    squashed = _squash(text)
    for phrase in _EN_PHRASES:
        if phrase in squashed:
            return "提示词包含试图改变权限判定的指令（如忽略/跳过审批、绕过权限），已拒绝写入"
    for verb in _ZH_VERBS:
        for target in _ZH_TARGETS:
            if f"{verb}{target}" in squashed:
                return "提示词包含试图改变权限判定的指令（如忽略/跳过审批、绕过权限），已拒绝写入"
    return None


def _reject(message: str, field: str) -> InvalidAgentConfig:
    return InvalidAgentConfig(message, fields=(field,))


def _validate_system_prompt(value: object) -> str:
    if not isinstance(value, str):
        raise _reject("提示词必须是字符串", "system_prompt")
    if len(value) > MAX_SYSTEM_PROMPT_LENGTH:
        raise _reject(f"提示词最长 {MAX_SYSTEM_PROMPT_LENGTH} 个字符", "system_prompt")
    reason = scan_system_prompt(value)
    if reason is not None:
        raise _reject(reason, "system_prompt")
    return value


def _validate_model_key(value: object, allowed_model_keys: frozenset[str]) -> str:
    if not isinstance(value, str):
        raise _reject("模型键必须是字符串", "model_key")
    text = value.strip()
    if text and text not in allowed_model_keys:
        raise _reject("模型键未在模型网关注册，已拒绝", "model_key")
    return text


def _validate_temperature(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _reject("温度必须是数字", "temperature")
    number = float(value)
    if not 0.0 <= number <= 2.0:
        raise _reject("温度必须在 0.00 到 2.00 之间", "temperature")
    return round(number, 2)


def _validate_tool_allowlist(value: object, allowed_tools: frozenset[str]) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise _reject("工具白名单必须是字符串数组", "tool_allowlist")
    normalized = tuple(sorted({item.strip() for item in value if item.strip()}))
    if any(name not in allowed_tools for name in normalized):
        raise _reject("工具白名单包含未注册的工具，已拒绝", "tool_allowlist")
    return normalized


def _validate_memory_policy(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise _reject("记忆策略必须是对象", "memory_policy")
    if set(value) - _MEMORY_POLICY_KEYS:
        raise _reject("记忆策略包含未知字段，已拒绝", "memory_policy")
    clean: dict[str, object] = {}
    if "short_term_enabled" in value:
        if not isinstance(value["short_term_enabled"], bool):
            raise _reject("短期记忆开关必须是布尔值", "memory_policy")
        clean["short_term_enabled"] = value["short_term_enabled"]
    if "short_term_turns" in value:
        turns = value["short_term_turns"]
        if isinstance(turns, bool) or not isinstance(turns, int) or not 0 <= turns <= 50:
            raise _reject("短期记忆保留轮数必须是 0 到 50 的整数", "memory_policy")
        clean["short_term_turns"] = turns
    return clean


def _validate_enum(value: object, allowed: tuple[str, ...], label: str, field: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise _reject(f"{label}只能是 {'、'.join(allowed)} 之一", field)
    return value


def _validate_int_range(value: object, minimum: int, maximum: int, label: str, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise _reject(f"{label}必须是 {minimum} 到 {maximum} 的整数", field)
    return value


def _validate_non_negative_int(value: object, label: str, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise _reject(f"{label}必须是不小于 0 的整数", field)
    return value


def validate_agent_config(
    changes: dict[str, object],
    *,
    allowed_model_keys: frozenset[str],
    allowed_tools: frozenset[str],
) -> dict[str, object]:
    """逐字段校验并归一；任一失败抛 `InvalidAgentConfig`（接口层 → 422）。"""
    if not isinstance(changes, dict):
        raise InvalidAgentConfig("配置必须是对象")
    clean: dict[str, object] = {}
    if "system_prompt" in changes:
        clean["system_prompt"] = _validate_system_prompt(changes["system_prompt"])
    if "model_key" in changes:
        clean["model_key"] = _validate_model_key(changes["model_key"], allowed_model_keys)
    if "temperature" in changes:
        clean["temperature"] = _validate_temperature(changes["temperature"])
    if "tool_allowlist" in changes:
        clean["tool_allowlist"] = _validate_tool_allowlist(changes["tool_allowlist"], allowed_tools)
    if "memory_policy" in changes:
        clean["memory_policy"] = _validate_memory_policy(changes["memory_policy"])
    if "autonomy_level" in changes:
        clean["autonomy_level"] = _validate_enum(
            changes["autonomy_level"], AUTONOMY_LEVELS, "自治等级", "autonomy_level"
        )
    if "risk_threshold" in changes:
        clean["risk_threshold"] = _validate_enum(
            changes["risk_threshold"], RISK_THRESHOLDS, "风险阈值", "risk_threshold"
        )
    if "approval_timeout_minutes" in changes:
        clean["approval_timeout_minutes"] = _validate_int_range(
            changes["approval_timeout_minutes"],
            MIN_APPROVAL_TIMEOUT_MINUTES,
            MAX_APPROVAL_TIMEOUT_MINUTES,
            "审批超时分钟数",
            "approval_timeout_minutes",
        )
    if "daily_budget_cents" in changes:
        clean["daily_budget_cents"] = _validate_non_negative_int(
            changes["daily_budget_cents"], "每日预算（分）", "daily_budget_cents"
        )
    return clean


def _ensure_admin(context: UserContext) -> None:
    if context.role != "super_admin":
        raise PolicyError("只有超级管理员可以配置数字员工")


def _audit_agent_key(value: str) -> str:
    try:
        return normalize_key(value)
    except InvalidDirectoryKey:
        return ""


class AgentConfigService:
    """配置读写闸门：校验 → 写库 → 写审计；被拒的尝试同样写审计（不含正文）。"""

    def __init__(
        self,
        store: WorkforceDirectoryStore,
        *,
        audit=None,
        allowed_model_keys: frozenset[str] = frozenset(),
        allowed_tools: frozenset[str] = frozenset(),
    ) -> None:
        self.store = store
        self.audit = audit
        self.allowed_model_keys = frozenset(allowed_model_keys)
        self.allowed_tools = frozenset(allowed_tools)

    def read_config(self, context: UserContext, agent_key: str) -> DigitalEmployee:
        """读配置：**仅归属人 ∪ `super_admin`**（V4=A）。

        闸门**在仓储层**（`store.read_agent_config`）—— 因为它需要「这一行属于谁」，
        路由层拿不到；这里不再另判一次角色，避免两层口径漂移。
        """
        employee = self.store.read_agent_config(context, agent_key)
        self._record(
            context,
            AuditAction.WORKFORCE_AGENT_CONFIG_READ,
            employee.agent_key,
            {"agent_key": employee.agent_key},
        )
        return employee

    def update_config(self, context: UserContext, agent_key: str, *, changes: dict[str, object]) -> DigitalEmployee:
        _ensure_admin(context)
        try:
            clean = validate_agent_config(
                changes, allowed_model_keys=self.allowed_model_keys, allowed_tools=self.allowed_tools
            )
        except InvalidAgentConfig as exc:
            self._record(
                context,
                AuditAction.WORKFORCE_AGENT_CONFIG_REJECTED,
                _audit_agent_key(agent_key),
                {
                    "agent_key": _audit_agent_key(agent_key),
                    "reason": str(exc),
                    "rejected_fields": list(exc.fields),
                },
            )
            raise
        employee = self.store.update_agent_config(context, agent_key, **clean)
        self._record(
            context,
            AuditAction.WORKFORCE_AGENT_CONFIG_UPDATED,
            employee.agent_key,
            {"agent_key": employee.agent_key, "changed_fields": sorted(clean)},
        )
        return employee

    def _record(self, context: UserContext, action: AuditAction, target_id: str, detail: dict[str, object]) -> None:
        if self.audit is None:
            return
        self.audit.record(
            action,
            tenant_id=context.tenant_id,
            actor_id=context.user_id,
            target_type="digital_employee",
            target_id=target_id,
            detail=detail,
        )
