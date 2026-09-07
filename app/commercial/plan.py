from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping


class QuotaError(ValueError):
    pass


@dataclass(frozen=True)
class QuotaDecision:
    action: str
    reason: str


@dataclass(frozen=True)
class PlanVersion:
    key: str
    limits: Mapping[str, int]
    version: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(self, "limits", MappingProxyType(dict(self.limits)))


class QuotaService:
    def __init__(self, plan: PlanVersion) -> None:
        self.plan = plan
        self._consumed: dict[str, int] = {}
        self._policies: dict[str, str] = {}

    def consume(self, metric: str, amount: int) -> None:
        if amount < 0:
            raise QuotaError("用量不能小于 0")
        decision = self.check(metric, amount)
        if decision.action == "block":
            raise QuotaError(decision.reason)
        self._consumed[metric] = self._consumed.get(metric, 0) + amount

    def set_overage_policy(self, metric: str, policy: str) -> None:
        if policy not in {"block", "degrade", "approval"}:
            raise QuotaError("不支持的超额策略")
        self._policies[metric] = policy

    def check(self, metric: str, amount: int) -> QuotaDecision:
        if amount < 0:
            raise QuotaError("用量不能小于 0")
        limit = self.plan.limits.get(metric)
        if limit is None or self._consumed.get(metric, 0) + amount <= limit:
            return QuotaDecision("allow", "未超过套餐额度")
        policy = self._policies.get(metric, "block")
        return QuotaDecision(policy, "本次用量将超过套餐额度")
