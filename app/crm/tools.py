"""CRM 受控工具面执行器（§2.8）：进程内分发 + 参数白名单 + 敏感字段剥离。

- 数字员工数据范围 = **会话操作者本人负责的对象**（固定 own 语义：`UserContext(..., "employee")`；
  扩大需评审——即使操作者是管理角色也不放大，§2.8）。
- 结果只落摘要；`masking.to_safe_dict` 保证任何输出无敏感字段（单测钉死）。
- **不提供外发 / 删除工具**；写工具仅 `crm.activity.log`（medium，走九级闸门审批）。
- 与既有执行链路的接口：`execute(..., requester=..., tenant_id=...)` 为**新增可选参数**
  （`ToolExecutionService._step_execute` 传入；既有容器执行器忽略之，向后兼容）。
"""

from __future__ import annotations

from typing import Any, Callable, Mapping

from ..domain import UserContext
from ..tool_execution.executor import ExecutionOutcome
from .models import (
    MAX_LIMIT,
    CrmNotFound,
    InvalidCrm,
)
from .service import CrmService

# 每个工具的参数白名单（**未知参数一律拒绝**；与 catalog 的 params_schema 对齐）。
ALLOWED_PARAMS: dict[str, frozenset[str]] = {
    "crm.account.search": frozenset({"query", "limit"}),
    "crm.account.get": frozenset({"account_id"}),
    "crm.opportunity.list": frozenset({"stage", "limit"}),
    "crm.progress.summary": frozenset({"scope"}),
    "crm.activity.log": frozenset(
        {"kind", "subject", "content", "account_id", "contact_id", "opportunity_id"}
    ),
}

MAX_QUERY_LENGTH = 100
DEFAULT_TOOL_LIMIT = 20
MAX_TOOL_LIMIT = min(50, MAX_LIMIT)
_OPPORTUNITY_STAGES = frozenset({"qualification", "proposal", "negotiation", "won", "lost"})


class CrmToolError(ValueError):
    """CRM 工具执行失败（参数不合法 / 缺少操作者上下文）→ 由执行链路映射为失败语义。"""


def _tool_limit(value: Any) -> int:
    if value is None:
        return DEFAULT_TOOL_LIMIT
    if isinstance(value, bool) or not isinstance(value, int):
        raise CrmToolError("limit 必须为整数")
    return max(1, min(value, MAX_TOOL_LIMIT))


class CrmToolExecutor:
    """CRM 工具执行器：`crm.*` 进程内执行；其余一律拒绝（由组合执行器分流）。"""

    def __init__(self, service_provider: Callable[[], CrmService]) -> None:
        self._service_provider = service_provider

    def execute(
        self,
        *,
        tool_key: str,
        params: Mapping[str, Any],
        workspace_path: str | None = None,
        spec: Any = None,
        environment: Mapping[str, str] | None = None,
        requester: str | None = None,
        tenant_id: str | None = None,
    ) -> ExecutionOutcome:
        del workspace_path, spec, environment  # 进程内执行不涉及容器 / 工作区
        handlers = {
            "crm.account.search": self._account_search,
            "crm.account.get": self._account_get,
            "crm.opportunity.list": self._opportunity_list,
            "crm.progress.summary": self._progress_summary,
            "crm.activity.log": self._activity_log,
        }
        handler = handlers.get(tool_key)
        if handler is None:
            raise CrmToolError(f"CRM 执行器不接受工具：{tool_key}")
        allowed = ALLOWED_PARAMS[tool_key]
        unknown = sorted(str(key) for key in params if key not in allowed)
        if unknown:
            raise CrmToolError(f"未知参数：{unknown}")
        if not tenant_id or not requester:
            raise CrmToolError("缺少操作者上下文（tenant_id / requester）")

        context = UserContext(tenant_id, requester, "employee")
        service = self._service_provider()
        try:
            summary = handler(service, context, dict(params))
        except (InvalidCrm, CrmNotFound) as exc:
            raise CrmToolError(str(exc)) from exc
        return ExecutionOutcome(ok=True, timed_out=False, summary=summary)

    # ------------------------------------------------------------ 读工具（low）

    def _account_search(self, service: CrmService, context: UserContext, params: dict) -> dict:
        query = params.get("query") or ""
        if not isinstance(query, str):
            raise CrmToolError("query 必须为字符串")
        query = query.strip()[:MAX_QUERY_LENGTH]
        limit = _tool_limit(params.get("limit"))
        items, total = service.list_accounts(context, limit=limit, offset=0)
        if query:
            items = [item for item in items if query in item.name or query in item.industry]
        return {
            "tool": "crm.account.search",
            "accounts": [
                {
                    "account_id": item.account_id,
                    "name": item.name,
                    "industry": item.industry,
                    "status": item.status,
                    "health_score": item.health_score,
                    "health_band": item.health_band,
                }
                for item in items
            ],
            "returned": len(items),
            "total": total,
        }

    def _account_get(self, service: CrmService, context: UserContext, params: dict) -> dict:
        account_id = params.get("account_id")
        if not isinstance(account_id, str) or not account_id:
            raise CrmToolError("account_id 必填")
        account = service.get_account(context, account_id)
        opportunities, _ = service.list_opportunities(context, account_id=account_id, limit=MAX_TOOL_LIMIT)
        activities, _ = service.list_activities(context, account_id=account_id, limit=10)
        return {
            "tool": "crm.account.get",
            "account": {
                "account_id": account.account_id,
                "name": account.name,
                "industry": account.industry,
                "status": account.status,
                "health_score": account.health_score,
                "health_band": account.health_band,
            },
            "opportunities": [
                {
                    "opportunity_id": item.opportunity_id,
                    "name": item.name,
                    "stage": item.stage,
                    "amount_cents": item.amount_cents,
                }
                for item in opportunities
            ],
            "recent_activities": [
                {"kind": item.kind, "subject": item.subject, "occurred_at": item.occurred_at.isoformat()}
                for item in activities
            ],
        }

    def _opportunity_list(self, service: CrmService, context: UserContext, params: dict) -> dict:
        stage = params.get("stage")
        if stage is not None:
            if stage not in _OPPORTUNITY_STAGES:
                raise CrmToolError("stage 取值不合法")
        limit = _tool_limit(params.get("limit"))
        items, total = service.list_opportunities(context, stage=stage, limit=limit, offset=0)
        return {
            "tool": "crm.opportunity.list",
            "opportunities": [
                {
                    "opportunity_id": item.opportunity_id,
                    "name": item.name,
                    "stage": item.stage,
                    "amount_cents": item.amount_cents,
                }
                for item in items
            ],
            "returned": len(items),
            "total": total,
        }

    def _progress_summary(self, service: CrmService, context: UserContext, params: dict) -> dict:
        scope = params.get("scope") or "me"
        # 数字员工只允许 me（操作者本人范围）；all 需人类管理角色从接口请求。
        if scope != "me":
            raise CrmToolError("scope 仅允许 me")
        summary = service.progress_summary(context, scope="me")
        return {"tool": "crm.progress.summary", "scope": "me", "metrics": summary}

    # ------------------------------------------------------------ 写工具（medium，走闸门审批）

    def _activity_log(self, service: CrmService, context: UserContext, params: dict) -> dict:
        kind = params.get("kind")
        if not isinstance(kind, str) or not kind:
            raise CrmToolError("kind 必填")
        activity = service.log_activity(
            context,
            kind=kind,
            subject=params.get("subject") or "",
            content=params.get("content") or "",
            account_id=params.get("account_id"),
            contact_id=params.get("contact_id"),
            opportunity_id=params.get("opportunity_id"),
            created_by_kind="agent",
        )
        return {
            "tool": "crm.activity.log",
            "activity_id": activity.activity_id,
            "kind": activity.kind,
            "account_id": activity.account_id,
        }


class CrmRoutingExecutor:
    """组合执行器：`crm.*` → `CrmToolExecutor`；其余 → 既有执行器（容器执行等）。"""

    def __init__(self, *, crm: CrmToolExecutor, inner: Any) -> None:
        self._crm = crm
        self._inner = inner

    def __getattr__(self, name: str) -> Any:
        """属性透传：组合执行器对外等同被包装的执行器（如 `token_revoker` / `managed_containers`）。

        仅在常规查找失败时触发；用 `object.__getattribute__` 读取 `_inner` 以避免递归。
        """
        return getattr(object.__getattribute__(self, "_inner"), name)

    def execute(
        self,
        *,
        tool_key: str,
        params: Mapping[str, Any],
        workspace_path: str | None = None,
        spec: Any = None,
        environment: Mapping[str, str] | None = None,
        requester: str | None = None,
        tenant_id: str | None = None,
    ) -> ExecutionOutcome:
        if tool_key.startswith("crm."):
            return self._crm.execute(
                tool_key=tool_key,
                params=params,
                workspace_path=workspace_path,
                spec=spec,
                environment=environment,
                requester=requester,
                tenant_id=tenant_id,
            )
        return self._inner.execute(
            tool_key=tool_key,
            params=params,
            workspace_path=workspace_path,
            spec=spec,
            environment=environment,
            requester=requester,
            tenant_id=tenant_id,
        )