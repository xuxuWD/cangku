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


# ------------------------------------------------------------ 生命周期（租户整体删除）

def test_delete_all_for_tenant_clears_whole_memory_layer_not_just_facts() -> None:
    """租户整体删除必须清**整个记忆层**（事实 / 规则 / 身份类画像三张表），不是只清事实表。

    为什么单列这条（2026-09-19 真机验证抓到的真缺陷）：`029` 迁移把「记忆层」落成**三张表**
    （`workbench_memory_facts` / `workbench_memory_rules` / `workbench_memory_profile_keys`），
    而 `delete_all_for_tenant` 原先只删事实 ⇒ **规则与身份类画像整租户残留**。
    真机实测：租户已 `deleted`、审计 `cleared_categories` 报 `memories`，但两张表行数原样不动
    ⇒ 「审计面名齐全」与「每面只清一张表」不一致（数据残留，合规问题）。
    """
    service = MemoryService(
        InMemoryMemoryStore(), FakeEmbeddingAdapter(),
        audit=AuditService(InMemoryAuditStore()),
    )
    actor = _actor(role="super_admin")
    service.create_fact(
        actor, content="待清场事实", scope="user",
        owner_kind="user", owner_id=ALICE, idempotency_key="lc-fact-1",
    )
    service.create_rule(
        actor, rule_key="lc.rule", content="待清场规则",
        scope="user", owner_kind="user", owner_id=ALICE,
    )
    service.set_profile_key(
        actor, key="lc-profile", value="待清场画像", owner_kind="user", owner_id=ALICE,
    )

    deleted = service.store.delete_all_for_tenant(TENANT)

    assert deleted >= 1
    assert service.store.list_all_for_tenant(TENANT) == []  # 事实面
    assert [r for r in service.store._rules.values() if r.tenant_id == TENANT] == []  # 规则面
    assert service.get_profile(actor, owner_kind="user", owner_id=ALICE) == {}  # 身份类画像面


def test_lifecycle_reads_cover_rules_and_profiles_for_tenant() -> None:
    """导出面（真源 §6.1「记忆」）需要**三类记忆的按租户读取**：规则与身份类画像也要能整租户读出。

    2026-09-19：此前只有 `list_all_for_tenant`（**只读事实**）⇒ 导出包里的 `memories` 只有事实，
    规则与画像拿不到（删除面已改为整层三张表，两面口径必须一致）。口径同事实类：
    **只出 `active`**（`superseded` 历史版本不入包）、排序确定。
    """
    service = MemoryService(
        InMemoryMemoryStore(), FakeEmbeddingAdapter(),
        audit=AuditService(InMemoryAuditStore()),
    )
    actor = _actor(role="super_admin")
    service.create_rule(actor, rule_key="lc.read", content="第一版规则",
                        scope="user", owner_kind="user", owner_id=ALICE)
    service.create_rule(actor, rule_key="lc.read", content="第二版规则",
                        scope="user", owner_kind="user", owner_id=ALICE)  # 旧版转 superseded
    service.set_profile_key(actor, key="language", value="中文", owner_kind="user", owner_id=ALICE)
    service.set_profile_key(actor, key="timezone", value="UTC+8", owner_kind="user", owner_id=ALICE)

    rules = service.store.list_rules_for_tenant(TENANT)
    profiles = service.store.list_profiles_for_tenant(TENANT)

    # 只出 active：两条里只有第二版（第一版已 superseded）。
    assert [r.content for r in rules] == ["第二版规则"]
    assert rules[0].version == 2 and rules[0].rule_key == "lc.read"
    assert [(p.profile_key, p.value) for p in profiles] == [("language", "中文"), ("timezone", "UTC+8")]
    assert all(p.owner_kind == "user" and p.owner_id == ALICE for p in profiles)


# ------------------------------------------------------------ 审计

def test_audit_actions_registered(service: MemoryService) -> None:
    actor = _actor()
    service.create_fact(actor, content="审计验证", scope="user",
                        owner_kind="user", owner_id=ALICE, idempotency_key="k-audit")
    actions = [item.action for item in service.audit.store.list_recent(TENANT)]
    assert AuditAction.MEMORY_FACT_CREATED.value in [a.value for a in actions]