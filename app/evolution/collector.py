"""采集器（P6a 规格 V1）：**只读**真实运行轨迹 → 用例库**草稿**。

口径（如实登记，不得夸大）：
- 数据源 = 审计日志中「**被拦截**」的受控动作（`tool.blocked` / `knowledge.search.blocked`）——
  它们天然是负向回归线索，且审计明细受白名单约束，**不含正文**（快照只需受控字段）；
- 产出 = **草稿用例**（`source=run_trace`，期望留空）。系统按设计不落原文（工具参数只存摘要、
  消息正文不落审计），因此**自动提炼可回放期望在无原文前提下不可行**——草稿由专家补全期望后
  才能发布进入评测（发布闸门 fail-closed）；
- **幂等**：同一条记录重复采集不产生第二条用例（服务层按快照指纹去重）。
"""

from __future__ import annotations

from ..audit.models import AuditAction
from .models import CaseSpec, EvalCaseSource

# 可采集动作 → 目标套件（负向回归线索）。
COLLECT_ACTIONS: dict[AuditAction, str] = {
    AuditAction.TOOL_BLOCKED: "gate-blocked",
    AuditAction.KNOWLEDGE_SEARCH_BLOCKED: "knowledge-search-blocked",
}
# 允许进入快照的审计明细键（白名单子集；均为受控标识/枚举，无正文）。
SNAPSHOT_KEYS = ("tool_key", "risk_level", "reason", "role_key", "agent_key")
_MAX_VALUE_LENGTH = 200


def collect_blocked_case_specs(audit, tenant_id: str, *, limit: int = 50) -> list[CaseSpec]:
    """只读采集：按动作逐类查询审计（新 → 旧），生成草稿用例规格（不写库）。"""
    specs: list[CaseSpec] = []
    for action, suite_key in COLLECT_ACTIONS.items():
        records, _total = audit.query(tenant_id, actions=[action], limit=limit)
        for record in records:
            snapshot: dict = {
                "action": action.value,
                "recorded_at": record.occurred_at.isoformat(),
            }
            for key in SNAPSHOT_KEYS:
                value = record.detail.get(key)
                if isinstance(value, str) and value.strip():
                    snapshot[key] = value.strip()[:_MAX_VALUE_LENGTH]
            specs.append(
                CaseSpec(
                    suite_key=suite_key,
                    source=EvalCaseSource.RUN_TRACE,
                    input_snapshot=snapshot,
                    expectation=None,
                )
            )
    return specs