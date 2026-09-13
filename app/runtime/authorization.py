"""执行授权位：**谁**在**何时**批准了**哪个计划**。

口径见段一规格 §2.3。三条要点：

* 授权位是针对**某一个具体计划**的凭证：批准时记下计划摘要，执行前重新计算并比对，
  不一致即视为「授权已失效」——不依赖任何人记得发撤销事件；
* 授权来源必须由服务端判定且在白名单内；**数字员工（`agent`）不得授权自己**；
* 三列**全有或全无**（数据库有 `CHECK` 兜底），任一为空即「未授权」。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, fields
from datetime import datetime
from typing import Any

from .contracts import AgentPlan

# 允许的授权来源。`agent` 刻意不在其中：数字员工不能批准自己要执行的动作。
AUTHORIZATION_SOURCES = ("user", "system", "api", "ui", "automation")


class ExecutionNotAuthorized(ValueError):
    """推进执行时未持有与当前计划一致的授权（接口层按 409 处理）。"""


class InvalidAuthorizationSource(ValueError):
    """授权来源不在白名单内（含被显式拒绝的 `agent`）。"""


@dataclass(frozen=True)
class ExecutionAuthorization:
    """一次授权的完整凭证；三个字段同生同灭，不存在「只填了一半」的合法状态。"""

    authorized_by: str
    plan_digest: str
    authorized_at: datetime


# 8 字段只读投影的字段清单（顺序即 §5 用例 29③ 的逐个非空断言顺序）。
AUTHORIZATION_ACTION_FIELDS = (
    "action_id",
    "approval_id",
    "step_id",
    "tool_key",
    "args_digest",
    "plan_digest",
    "risk_level",
    "requires_approval",
)


@dataclass(frozen=True)
class AuthorizationAction:
    """⑦ 需要的**待判动作只读投影**——8 个字段与 §4.1.1 表「与判定相关列」一一对应。

    **命名说明（🔴 命名冲突的显式处置）**：规格 §4.1.7-5 把这条投影也称为 `ToolAction`；
    但本仓库 `app/tool_execution/store.py` 已有**同名的 21 字段整行** `ToolAction`（迁移 `027`
    的一行）。为遵守「不得 shadow、不得复用同一个类」，此处改名为 `AuthorizationAction`，
    **待规格同步**（已在 §8 U18 收口汇报中点名）。

    * **不含参数原文，也不含 `args_json`**——判定只需摘要投影；
    * `args_digest` 由 §4.1.4 算法产出；
    * **8 个字段均须非空**（§5 用例 29③）；任一为空即 fail-closed。
    """

    action_id: str
    approval_id: str
    step_id: str
    tool_key: str
    args_digest: str
    plan_digest: str
    risk_level: str
    requires_approval: bool

    @classmethod
    def from_row(cls, row: Any) -> "AuthorizationAction":
        """从 `store.py` 的整行 `ToolAction` 投影出只读视图（duck-typed，避免层级耦合）。"""
        risk = getattr(row, "risk_level", None)
        return cls(
            action_id=str(getattr(row, "action_id", "") or ""),
            approval_id=str(getattr(row, "approval_id", "") or ""),
            step_id=str(getattr(row, "step_id", "") or ""),
            tool_key=str(getattr(row, "tool_key", "") or ""),
            args_digest=str(getattr(row, "args_digest", "") or ""),
            plan_digest=str(getattr(row, "plan_digest", "") or ""),
            risk_level=str(getattr(risk, "value", risk)) if risk is not None else "",
            requires_approval=bool(getattr(row, "requires_approval", False)),
        )

    def missing_fields(self) -> tuple[str, ...]:
        """返回为空（含 `False`）的字段名；供 §5 用例 29③ 的逐个非空断言复用。"""
        return tuple(name for name in AUTHORIZATION_ACTION_FIELDS if not getattr(self, name))


def validate_authorization_action(action: AuthorizationAction) -> None:
    """8 字段逐个非空；任一为空即 fail-closed（`ExecutionNotAuthorized`）。"""
    missing = action.missing_fields()
    if missing:
        raise ExecutionNotAuthorized("待判动作投影字段不完整：" + "、".join(missing))


def authorization_action_field_names() -> tuple[str, ...]:
    """投影的字段名集合（不含 `args_json` 与任何参数原文列）。"""
    return tuple(field.name for field in fields(AuthorizationAction))


def ensure_source_allowed(source: str) -> str:
    """校验授权来源；不在白名单内一律拒绝（含 `agent`）。"""
    if source not in AUTHORIZATION_SOURCES:
        raise InvalidAuthorizationSource("授权来源不在允许清单内")
    return source


def plan_digest(plan: AgentPlan) -> str:
    """计划的规范化摘要：只取**影响执行**的字段，顺序稳定。

    与既有 `request_fingerprint` 同口径（`sort_keys=True` + 紧凑分隔符）后取 SHA-256。
    摘要不含自由文本，因此可以安全地写进运行记录与日志。
    """
    payload = [
        {
            "step_id": step.step_id,
            "kind": step.kind,
            "tool": step.tool,
            "requires_approval": step.requires_approval,
        }
        for step in plan.steps
    ]
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
