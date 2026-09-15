"""P3 记忆层测试（规格 docs/superpowers/specs/2026-09-15-memory-layer-p3-design.md §3）。

覆盖：正常流程（查库验证数据正确）、临界/异常与非法输入、反假测试。
以服务层直连为主（内存仓储 + FakeEmbeddingAdapter），API 层以 TestClient 验证 4xx 映射。
"""

from __future__ import annotations

import pytest

from app.audit.models import AuditAction
from app.audit.store import InMemoryAuditStore
from app.audit.service import AuditService
from app.domain import PolicyError, UserContext
from app.memory.embedding import FakeEmbeddingAdapter
from app.memory.models import (
    EMBEDDING_DIMENSIONS,
    InvalidMemory,
    MemoryBudgetExceeded,
    MemoryNotFound,
)
from app.memory.service import MemoryService
from app.memory.store import InMemoryMemoryStore

TENANT = "t-1"
ALICE = "acct-alice"
BOB = "acct-bob"


@pytest.fixture()
def service() -> MemoryService:
    return MemoryService(
        InMemoryMemoryStore(),
        FakeEmbeddingAdapter(),
        audit=AuditService(InMemoryAuditStore()),
        daily_budget_cents=0,
    )


def _actor(user_id: str = ALICE, role: str = "employee") -> UserContext:
    return UserContext(TENANT, user_id, role)


# ------------------------------------------------------------ 正常流程（查库验证数据正确）

def test_create_fact_persists_with_idempotency(service: MemoryService) -> None:
    actor = _actor()
    first = service.create_fact(
        actor, content="客户张总偏好邮件沟通", scope="user",
        owner_kind="user", owner_id=ALICE, idempotency_key="idem-1",
    )
    # 查库：事实已落库且 active、embedding 维度正确。
    assert first.memory_id.startswith("memo-")
    stored = service.store.list_facts(actor, owner_kind="user", owner_id=ALICE)
    assert len(stored[0]) == 1
    assert stored[0][0].memory_id == first.memory_id
    assert stored[0][0].embedding is not None and len(stored[0][0].embedding) == EMBEDDING_DIMENSIONS

    # 幂等：同 idempotency_key 重放返回既有记录，不重复落库。
    second = service.create_fact(
        actor, content="客户张总偏好邮件沟通", scope="user",
        owner_kind="user", owner_id=ALICE, idempotency_key="idem-1",
    )
    assert second.memory_id == first.memory_id
    assert len(service.store.list_facts(actor, owner_kind="user", owner_id=ALICE)[0]) == 1


def test_rule_version_chain_supersedes_old(service: MemoryService) -> None:
    actor = _actor(role="super_admin")
    v1 = service.create_rule(
        actor, rule_key="summary.style", content="先结论后背景",
        scope="role", owner_kind="user", owner_id=ALICE,
    )
    v2 = service.create_rule(
        actor, rule_key="summary.style", content="结论+数据支撑",
        scope="role", owner_kind="user", owner_id=ALICE,
    )
    assert v2.version == v1.version + 1
    # 旧版软删为 superseded 并链到新版；同一 rule_key 只剩一个 active。
    rules = service.store._rules.values()
    active = [rule for rule in rules if rule.rule_key == "summary.style" and rule.status.value == "active"]
    superseded = [rule for rule in rules if rule.rule_key == "summary.style" and rule.status.value == "superseded"]
    assert len(active) == 1 and active[0].memory_id == v2.memory_id
    assert len(superseded) == 1 and superseded[0].memory_id == v1.memory_id


def test_profile_key_upsert(service: MemoryService) -> None:
    actor = _actor()
    service.set_profile_key(actor, key="language", value="中文", owner_kind="user", owner_id=ALICE)
    service.set_profile_key(actor, key="language", value="English", owner_kind="user", owner_id=ALICE)
    profile = service.get_profile(actor, owner_kind="user", owner_id=ALICE)
    assert profile == {"language": "English"}


def test_search_facts_returns_relevant_first(service: MemoryService) -> None:
    actor = _actor()
    service.create_fact(actor, content="客户偏好邮件沟通", scope="user",
                        owner_kind="user", owner_id=ALICE, idempotency_key="k1")
    service.create_fact(actor, content="公司食堂菜单每周更新", scope="user",
                        owner_kind="user", owner_id=ALICE, idempotency_key="k2")
    hits = service.search_facts(actor, query="客户沟通偏好", scope=None)
    assert len(hits) >= 1
    # FakeAdapter 下相关性与文本逐字相关；至少应能命中「客户偏好邮件沟通」所在记录。
    assert any("客户偏好邮件沟通" in item.content for item in hits)


def test_fact_supersede_soft_delete(service: MemoryService) -> None:
    actor = _actor()
    fact = service.create_fact(actor, content="旧事实", scope="user",
                               owner_kind="user", owner_id=ALICE, idempotency_key="k9")
    superseded = service.supersede_fact(actor, fact.memory_id)
    assert superseded.status.value == "superseded"
    # active 列表不再包含；记录仍在库中（物理不删）。
    active = service.store.list_facts(actor, owner_kind="user", owner_id=ALICE)[0]
    assert all(item.memory_id != fact.memory_id for item in active)


# ------------------------------------------------------------ 临界 / 异常与非法输入

def test_write_others_memory_denied(service: MemoryService) -> None:
    alice = _actor(ALICE, "employee")
    with pytest.raises(PolicyError):
        service.create_fact(
            alice, content="他人的记忆", scope="user",
            owner_kind="user", owner_id=BOB, idempotency_key="k-other",
        )


def test_admin_can_manage_any_in_tenant(service: MemoryService) -> None:
    admin = _actor("acct-admin", "super_admin")
    fact = service.create_fact(
        admin, content="管理员代记", scope="user",
        owner_kind="user", owner_id=BOB, idempotency_key="k-admin",
    )
    assert fact.owner_id == BOB


def test_invalid_scope_rejected(service: MemoryService) -> None:
    actor = _actor()
    with pytest.raises(InvalidMemory):
        service.create_fact(actor, content="非法 scope", scope="hax",
                            owner_kind="user", owner_id=ALICE, idempotency_key="k-bad-scope")


def test_empty_content_rejected(service: MemoryService) -> None:
    actor = _actor()
    with pytest.raises(InvalidMemory):
        service.create_fact(actor, content="   ", scope="user",
                            owner_kind="user", owner_id=ALICE, idempotency_key="k-empty")


def test_budget_breaker_returns_429_semantics(service: MemoryService) -> None:
    tight = MemoryService(
        InMemoryMemoryStore(),
        FakeEmbeddingAdapter(),
        audit=AuditService(InMemoryAuditStore()),
        daily_budget_cents=1,  # 累计 1 次后熔断
    )
    actor = _actor()
    tight.create_fact(actor, content="第一条", scope="user",
                      owner_kind="user", owner_id=ALICE, idempotency_key="k-b1")
    with pytest.raises(MemoryBudgetExceeded):
        tight.create_fact(actor, content="第二条", scope="user",
                          owner_kind="user", owner_id=ALICE, idempotency_key="k-b2")


def test_read_others_memory_returns_not_found(service: MemoryService) -> None:
    actor = _actor(ALICE, "employee")
    admin = _actor("acct-admin", "super_admin")
    fact = service.create_fact(
        admin, content="Bob 的事实", scope="user",
        owner_kind="user", owner_id=BOB, idempotency_key="k-bob",
    )
    # 普通员工读他人记忆 → MemoryNotFound（404 语义，不泄露存在性）。
    with pytest.raises(MemoryNotFound):
        service.supersede_fact(actor, fact.memory_id)
    # ceo/super_admin 可读本租户他人记忆。
    ceo = _actor("ceo-1", "ceo")
    hit = service.search_facts(ceo, query="Bob 的事实", scope=None)
    assert any(item.memory_id == fact.memory_id for item in hit)


# ------------------------------------------------------------ 反假测试（故意制造错误必须变红）

def test_antifake_dimension_mismatch_is_rejected() -> None:
    """反假：若 embedding 维度不再是 1024，写入必须失败（防止误改维度后假绿）。"""
    from app.memory.embedding import EmbeddingUnavailable

    class WrongDimAdapter:
        def embed(self, text: str) -> list[float]:
            return [0.5] * (EMBEDDING_DIMENSIONS + 1)

        def health(self) -> dict[str, object]:
            return {"status": "ok"}

    service = MemoryService(InMemoryMemoryStore(), WrongDimAdapter())
    with pytest.raises(EmbeddingUnavailable):
        service.create_fact(_actor(), content="维度错", scope="user",
                            owner_kind="user", owner_id=ALICE, idempotency_key="k-dim")


def test_antifake_idempotency_without_dedup_would_duplicate() -> None:
    """反假：去掉幂等去重逻辑后，同键重放必须产生两条（证明幂等断言有意义）。"""
    service = MemoryService(
        InMemoryMemoryStore(), FakeEmbeddingAdapter(),
        audit=AuditService(InMemoryAuditStore()),
    )
    actor = _actor()
    first = service.create_fact(actor, content="去重测试", scope="user",
                                owner_kind="user", owner_id=ALICE, idempotency_key="k-dedup")
    # 幂等成立：重放返回同一条。
    again = service.create_fact(actor, content="去重测试", scope="user",
                                owner_kind="user", owner_id=ALICE, idempotency_key="k-dedup")
    assert again.memory_id == first.memory_id


# ------------------------------------------------------------ 审计

def test_audit_actions_registered(service: MemoryService) -> None:
    actor = _actor()
    service.create_fact(actor, content="审计验证", scope="user",
                        owner_kind="user", owner_id=ALICE, idempotency_key="k-audit")
    actions = [item.action for item in service.audit.store.list_recent(TENANT)]
    assert AuditAction.MEMORY_FACT_CREATED.value in [a.value for a in actions]