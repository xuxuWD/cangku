"""B1 会话层租户清场：组合顺序、面名上报、内存实现语义（真库语义见 `..._postgres.py`）。

背景（`docs/superpowers/specs/2026-09-19-tenant-purge-expansion-design.md` §3 B1）：会话层不是一张表，
而是**六张表 / 四个仓储**，且删除顺序被**真库外键**锁死（幂等行同时引用会话行与消息行、流帧/流态/消息
均引用会话行，且这些外键无级联）。本文件把三件事钉住：
  1. `CONVERSATION_LAYER_ORDER` 与实际调用顺序**逐字一致**（两种实现都要一致）；
  2. 内存组合实现**整层清空**本租户、**不碰他租户**、可重复调用（幂等）；
  3. 生命周期服务**只在注入时**上报该面（未注入必须如实不列 —— 不假装清过）。
"""

from __future__ import annotations

from app.audit.models import AuditAction
from app.audit.service import AuditService
from app.audit.store import InMemoryAuditStore
from app.commercial.lifecycle import CommercialLifecycleService
from app.commercial.repository import InMemoryCommercialRepository
from app.conversation.idempotency import ExecutionIdempotencyRecord, InMemoryExecutionIdempotencyStore
from app.conversation.members import InMemoryConversationMemberStore
from app.conversation.purge import (
    CONVERSATION_LAYER_ORDER,
    InMemoryConversationLayerPurgeStore,
    PostgresConversationLayerPurgeStore,
)
from app.conversation.stream import InMemoryStreamStore
from app.conversation.store import InMemoryConversationStore
from app.commercial.tenant import Actor
from app.domain import UserContext

TENANT = "tenant-b1"
OTHER = "tenant-b1-other"
# 每租户种子行数：幂等 1 + 帧 1 + 流态 1 + 成员 1 + 消息 1 + 会话 1 = 6。
ROWS_PER_TENANT = 6


class _Recorder:
    """记录调用次序的组合替身（只实现 `delete_all_for_tenant`）。"""

    def __init__(self, name: str, calls: list[str]) -> None:
        self.name = name
        self.calls = calls

    def delete_all_for_tenant(self, tenant_id: str) -> int:
        self.calls.append(self.name)
        return 1


def _seed_one_tenant(conversations, members, stream, idempotency, tenant: str) -> None:
    context = UserContext(tenant, f"user-{tenant}", "employee")
    conversation = conversations.create_conversation(context, title="清场样本")
    conversations.append_message(context, conversation.conversation_id, role="user", content="你好")
    members.upsert(
        tenant_id=tenant,
        conversation_id=conversation.conversation_id,
        member_id="user-2",
        permission="read",
        added_by=context.user_id,
    )
    stream.append_frame(
        tenant, conversation.conversation_id, f"run-{tenant}", kind="step.started", payload={"step": 1}
    )
    idempotency.insert(
        ExecutionIdempotencyRecord(
            tenant_id=tenant,
            actor_id=context.user_id,
            conversation_id=conversation.conversation_id,
            idempotency_key=f"idem-{tenant}",
            outcome="pending_approval",
            http_status=202,
        )
    )


def _in_memory_face():
    conversations = InMemoryConversationStore()
    members = InMemoryConversationMemberStore()
    stream = InMemoryStreamStore()
    idempotency = InMemoryExecutionIdempotencyStore()
    face = InMemoryConversationLayerPurgeStore(
        conversations=conversations, members=members, stream=stream, idempotency=idempotency
    )
    return face, conversations, members, stream, idempotency


def test_layer_order_matches_the_fk_safe_sequence() -> None:
    names = [name for name, _label in CONVERSATION_LAYER_ORDER]

    # 判据：幂等行必须最先（它同时引用会话行与消息行，无级联）；消息必须在会话之前。
    assert names == ["execution_idempotency", "stream", "members", "conversations"]


def test_postgres_composite_calls_the_four_stores_in_the_fixed_order() -> None:
    calls: list[str] = []
    face = PostgresConversationLayerPurgeStore(
        None,  # 四个仓储全部显式传入 ⇒ 不需要连接（也不该去建连接）
        conversations=_Recorder("conversations", calls),
        members=_Recorder("members", calls),
        stream=_Recorder("stream", calls),
        idempotency=_Recorder("execution_idempotency", calls),
    )

    assert face.delete_all_for_tenant(TENANT) == 4

    assert calls == [name for name, _label in CONVERSATION_LAYER_ORDER]


def test_in_memory_composite_calls_the_four_stores_in_the_fixed_order() -> None:
    calls: list[str] = []
    face = InMemoryConversationLayerPurgeStore(
        conversations=_Recorder("conversations", calls),
        members=_Recorder("members", calls),
        stream=_Recorder("stream", calls),
        idempotency=_Recorder("execution_idempotency", calls),
    )

    face.delete_all_for_tenant(TENANT)

    assert calls == [name for name, _label in CONVERSATION_LAYER_ORDER]


def test_in_memory_purge_clears_whole_layer_and_spares_other_tenants() -> None:
    face, conversations, members, stream, idempotency = _in_memory_face()
    for tenant in (TENANT, OTHER):
        _seed_one_tenant(conversations, members, stream, idempotency, tenant)

    deleted = face.delete_all_for_tenant(TENANT)

    assert deleted == ROWS_PER_TENANT
    assert [key for key in conversations._conversations if key[0] == TENANT] == []
    assert [key for key in conversations._messages if key[0] == TENANT] == []
    assert [key for key in members._items if key[0] == TENANT] == []
    assert [key for key in stream._frames if key[0] == TENANT] == []
    assert [key for key in stream._states if key[0] == TENANT] == []
    assert [key for key in idempotency._items if key[0] == TENANT] == []

    # 他租户零影响：整层仍完好（再清一次能取到完整行数即证）。
    assert face.delete_all_for_tenant(OTHER) == ROWS_PER_TENANT
    # 幂等：重复清已空的租户返回 0，不报错。
    assert face.delete_all_for_tenant(TENANT) == 0


def _seeded_service(*, with_face: bool) -> tuple[CommercialLifecycleService, str, AuditService]:
    repository = InMemoryCommercialRepository()
    tenant = repository.create_tenant("客户B1", owner_id="admin-1")
    repository.add_customer_admin(tenant.id, "admin-1")
    audit = AuditService(InMemoryAuditStore())
    face, conversations, members, stream, idempotency = _in_memory_face()
    _seed_one_tenant(conversations, members, stream, idempotency, tenant.id)
    service = CommercialLifecycleService(
        repository,
        cooldown_days=7,
        audit=audit,
        conversation_store=face if with_face else None,
    )
    return service, tenant.id, audit


def test_delete_reports_the_conversation_face_only_when_wired() -> None:
    for with_face, expected in ((True, ["conversations"]), (False, [])):
        service, tenant_id, audit = _seeded_service(with_face=with_face)
        actor = Actor("admin-1", "customer_admin")
        job = service.request_delete(actor, tenant_id)
        service.mark_final_exported(job.id)
        service.confirm_deletion(actor, tenant_id)

        service.execute_delete(tenant_id, now=job.execute_after)

        executed = [
            record
            for record in audit.store.list_recent(tenant_id)
            if record.action == AuditAction.COMMERCIAL_DELETION_EXECUTED
        ]
        assert len(executed) == 1
        # 未注入 ⇒ **如实不列**（不假装清过）；注入 ⇒ 面名出现。
        assert executed[0].detail["cleared_categories"] == expected


def test_delete_actually_empties_the_layer_when_wired() -> None:
    service, tenant_id, _audit = _seeded_service(with_face=True)
    face = service.conversation_store
    actor = Actor("admin-1", "customer_admin")
    job = service.request_delete(actor, tenant_id)
    service.mark_final_exported(job.id)
    service.confirm_deletion(actor, tenant_id)

    service.execute_delete(tenant_id, now=job.execute_after)

    assert [key for key in face.conversations._conversations if key[0] == tenant_id] == []
    assert [key for key in face.idempotency._items if key[0] == tenant_id] == []
    # 删除作业到点且执行成功（回读状态，避免「只看审计」的弱判据）。
    assert service.get_job(job.id).status == "completed"
    assert service.tenant_status(tenant_id).value == "deleted"