from __future__ import annotations

from typing import Any

from ..contracts import AgentPlan, RuntimeContext
from .common import ExternalAdapter


class AgentScopeAdapter(ExternalAdapter):
    def __init__(self, transport: Any, endpoint: str) -> None:
        super().__init__(transport, endpoint, "agentscope")

    def _payload(self, context: RuntimeContext, plan: AgentPlan) -> dict[str, Any]:
        payload = super()._payload(context, plan)
        payload["runtime_key"] = "agentscope"
        return payload
