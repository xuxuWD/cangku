from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from threading import RLock
from uuid import uuid4


class ModelNotAllowed(ValueError):
    """没有满足能力、启用状态和数据等级的模型。"""


class DataClassification(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    SENSITIVE = "sensitive"
    RESTRICTED = "restricted"


@dataclass(frozen=True)
class ProviderModel:
    model_key: str
    capabilities: frozenset[str]
    sensitive_data: bool
    enabled: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "capabilities", frozenset(self.capabilities))


@dataclass(frozen=True)
class ModelRoute:
    model_key: str
    reason: str


class ModelGateway:
    def __init__(self, models: list[ProviderModel]) -> None:
        self._models = {model.model_key: model for model in models}

    def choose(self, *, capability: str, data_classification: str, preferred: str | None = None) -> ModelRoute:
        try:
            classification = DataClassification(data_classification)
        except ValueError as exc:
            raise ModelNotAllowed("未知的数据等级，已拒绝模型调用") from exc
        candidates = [
            model
            for model in self._models.values()
            if model.enabled
            and capability in model.capabilities
            and (classification in {DataClassification.PUBLIC, DataClassification.INTERNAL} or model.sensitive_data)
        ]
        if preferred:
            selected = self._models.get(preferred)
            if selected and selected in candidates:
                return ModelRoute(selected.model_key, "manual_preference")
        if candidates:
            return ModelRoute(candidates[0].model_key, "capability_default")
        raise ModelNotAllowed("没有获准处理当前数据等级的模型")


class MemoryScope(StrEnum):
    USER = "user"
    ROLE = "role"
    PROJECT = "project"
    ORGANIZATION = "organization"


@dataclass
class Promotion:
    tenant_id: str
    agent_key: str
    content: str
    source: str
    id: str = field(default_factory=lambda: f"promotion-{uuid4().hex[:12]}")
    status: str = "pending_review"
    reviewer: str | None = None


class MemoryStore:
    def __init__(self) -> None:
        self._items: dict[tuple[str, str, MemoryScope, str], list[str]] = {}
        self._promotions: dict[str, Promotion] = {}
        self._lock = RLock()

    def remember(self, tenant_id: str, agent_key: str, scope: MemoryScope, owner_id: str, content: str) -> None:
        with self._lock:
            self._items.setdefault((tenant_id, agent_key, scope, owner_id), []).append(content)

    def list_for(self, tenant_id: str, agent_key: str, scope: MemoryScope, owner_id: str) -> list[str]:
        with self._lock:
            return list(self._items.get((tenant_id, agent_key, scope, owner_id), []))

    def propose_promotion(self, tenant_id: str, agent_key: str, content: str, *, source: str) -> Promotion:
        proposal = Promotion(tenant_id=tenant_id, agent_key=agent_key, content=content, source=source)
        with self._lock:
            self._promotions[proposal.id] = proposal
        return proposal

    def approve_promotion(self, promotion_id: str, *, tenant_id: str, reviewer: str) -> str:
        with self._lock:
            proposal = self._promotions.get(promotion_id)
            if proposal is None or proposal.tenant_id != tenant_id:
                raise ProposalNotFound(promotion_id)
            if proposal.status != "pending_review":
                raise InvalidProposalState(proposal.status)
            proposal.status = "approved"
            proposal.reviewer = reviewer
            return proposal.status


@dataclass
class GrowthProposal:
    agent_key: str
    kind: str
    summary: str
    diff: str
    id: str = field(default_factory=lambda: f"growth-{uuid4().hex[:12]}")
    status: str = "pending_review"
    reviewer: str | None = None


class ProposalNotFound(LookupError):
    pass


class InvalidProposalState(ValueError):
    pass


class GrowthProposalStore:
    def __init__(self) -> None:
        self._proposals: dict[str, GrowthProposal] = {}
        self._lock = RLock()

    def create(self, *, agent_key: str, kind: str, summary: str, diff: str) -> GrowthProposal:
        proposal = GrowthProposal(agent_key=agent_key, kind=kind, summary=summary, diff=diff)
        with self._lock:
            self._proposals[proposal.id] = proposal
        return proposal

    def review(self, proposal_id: str, *, reviewer: str, approved: bool) -> str:
        with self._lock:
            proposal = self._proposals.get(proposal_id)
            if proposal is None:
                raise ProposalNotFound(proposal_id)
            if proposal.status != "pending_review":
                raise InvalidProposalState(proposal.status)
            proposal.status = "approved" if approved else "rejected"
            proposal.reviewer = reviewer
            return proposal.status

    def activate(self, proposal_id: str) -> str:
        with self._lock:
            proposal = self._proposals.get(proposal_id)
            if proposal is None:
                raise ProposalNotFound(proposal_id)
            if proposal.status == "approved":
                proposal.status = "active"
            return proposal.status
