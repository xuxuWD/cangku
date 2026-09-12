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
from dataclasses import dataclass
from datetime import datetime

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
