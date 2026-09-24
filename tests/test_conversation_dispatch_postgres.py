"""O3「派生授权」闸门 —— **真库**回归（`PostgresWorkforceDirectoryStore`）。

**为什么需要本文件**：O3 闸门（commit `ef74f6f`）的判定完全落在目录仓储的两个方法上
——`read_agent_owner` / `share_permission`（见 `app/conversation/execution.py`
的 `_ensure_can_dispatch_derived`）。而 `tests/test_conversation_dispatch_gate.py`
（A–I 全量用例）装配的是 **`InMemoryWorkforceDirectoryStore`**；
`tests/test_dsh_execution_postgres.py` 名字虽叫 postgres，其目录仓储**同样是内存实现**
（该文件 :50 / :433）。⇒ **O3 闸门从未在真 PostgreSQL 的共享层上跑过**：SQL 能否跑通、
`workbench_employee_shares` 的租户过滤是否真的生效、撤销共享后回读是否为 `None`，
这些都只有真库能证。本文件即补这一段。

口径（沿用 `tests/test_skills_postgres.py` / `tests/test_workforce_directory_gate_split_postgres.py` 先例）：
  - DSN 从 **`WORKBENCH_TEST_DATABASE_URL`** 读；**未设置即整体 skip**；
  - 目标库须**已完成全部迁移（含 045）**；本文件**不建表、不迁移**；
  - 只操作 `TENANT` / `OTHER_TENANT` 两个测试租户的数据，用例前后自清
    （**先子表后主表**：`workbench_employee_shares` 有指向 `workbench_digital_employees` 的外键）。

真源：`docs/api-contract.md`「会话协作：分享与多端协同（P2c-6）」§「使用权的传递上限
（O3 · 派生授权）」（约 1296 行起）；裁决留痕 `docs/contracts/decision-log.md` D-062。
"""

from __future__ import annotations

import json
import os

import pytest
from fastapi.testclient import TestClient

from app import main
from app.accounts.models import Account, AccountStatus
from app.accounts.repository import InMemoryAccountRepository
from app.audit.service import AuditService
from app.audit.store import InMemoryAuditStore
from app.conversation.execution import ConversationExecutionService
from app.conversation.idempotency import InMemoryExecutionIdempotencyStore
from app.conversation.members import InMemoryConversationMemberStore
from app.conversation.service import ConversationService
from app.conversation.store import InMemoryConversationStore
from app.conversation.stream import InMemoryStreamStore
from app.domain import TaskStore, UserContext
from app.main import app
from app.runtime.records import InMemoryRunRecordStore
from app.runtime.run_metrics import RunMetricsService
from app.runtime.service import RuntimeService
from app.tool_execution.catalog import build_tool_spec_catalog
from app.tool_execution.service import ToolExecutionResult
from app.workforce.store import PostgresWorkforceDirectoryStore

DSN = os.environ.get("WORKBENCH_TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not DSN,
    reason="未设置 WORKBENCH_TEST_DATABASE_URL，跳过真库集成测试（见本文件 docstring）",
)

client = TestClient(app)

TENANT = "test-o3-pg"
OTHER_TENANT = "test-o3-pg-other"

OWNER = "acct-o3-pg-owner"       # 归属人（亲手创建 AGENT ⇒ owner_user_id = 本人）
MATE = "acct-o3-pg-mate"         # 被共享人（use / read 档）
WRITER = "acct-o3-pg-writer"     # 被点名的 `write` 成员（传递链的末端）
STRANGER = "acct-o3-pg-stranger"  # 与 AGENT 无任何授权关系的陌生人
ADMIN = "acct-o3-pg-admin"       # super_admin（建岗位 / 停用员工用）
OTHER_OWNER = "acct-o3-pg-other-owner"  # 别的租户里的同名员工归属人

ROLE_KEY = "o3-pg-role"
AGENT = "o3-pg-agent"

TOOL_CALL = json.dumps({"tool_key": "fs.list", "params": {"path": "/workspace"}})


# ============================================================ 夹具


class FakeToolExecution:
    """打桩执行入口：只记调用次数（`0` = 从未真实执行，是「零落库」的旁证）。"""

    def __init__(self) -> None:
        self.calls = 0

    def execute(self, request, *, actor=None, plan=None):
        self.calls += 1
        return ToolExecutionResult(outcome="executed", code=201)


def _account(index: int, account_id: str, *, role: str = "employee") -> Account:
    return Account(
        phone=f"1390002{index:04d}",
        password_hash="hash",
        position="岗位",
        full_name=f"姓名-{account_id}",
        account_id=account_id,
        role=role,
        tenant_id=TENANT,
        status=AccountStatus.APPROVED,
    )


def _purge(connection) -> None:
    """自清：**先子表后主表**（shares 有指向 employees 的外键）。"""
    with connection.cursor() as cursor:
        for tenant in (TENANT, OTHER_TENANT):
            cursor.execute("DELETE FROM workbench_employee_shares WHERE tenant_id = %s", (tenant,))
            cursor.execute("DELETE FROM workbench_digital_employees WHERE tenant_id = %s", (tenant,))
            cursor.execute("DELETE FROM workbench_job_roles WHERE tenant_id = %s", (tenant,))


@pytest.fixture()
def directory():
    """**真连接**的目录仓储：`PostgresWorkforceDirectoryStore`（本文件的全部意义所在）。"""
    psycopg = pytest.importorskip("psycopg")
    # ⚠️ `connect_timeout` 必须给：不给时 DSN 指向**不可达**的主机 / 端口，
    # psycopg 会一直等（实测 >120s 未返回）⇒ 在 CI 上表现为 job 级超时，
    # 报错信息极难解读。给了以后立刻得到 ConnectionTimeout，判因清楚。
    connection = psycopg.connect(DSN, autocommit=True, connect_timeout=5)
    _purge(connection)
    store = PostgresWorkforceDirectoryStore(connection)
    # 两个租户各建一个岗位（跨租户用例要在 OTHER_TENANT 也能建员工）。
    for tenant in (TENANT, OTHER_TENANT):
        store.create_role(UserContext(tenant, ADMIN, "super_admin"), role_key=ROLE_KEY, name="O3 真库岗")
    try:
        yield store
    finally:
        _purge(connection)
        connection.close()


@pytest.fixture()
def harness(monkeypatch, directory):
    """会话 / 运行时 / 目录的装配：**除目录仓储走真库外**，与生产同口径。

    ⚠️ 与 `tests/test_conversation_dispatch_gate.py` 的唯一关键差异：
    `directory_store` 传的是上面 `directory`（真 `PostgresWorkforceDirectoryStore(conn)`），
    **不是** `InMemoryWorkforceDirectoryStore`。会话 / 幂等 / 运行等仍用内存实现 ——
    它们不是本文件要验的对象，且 O3 的判定不读它们。
    """
    accounts = InMemoryAccountRepository()
    for index, (account_id, role) in enumerate(
        [
            (OWNER, "employee"),
            (MATE, "employee"),
            (WRITER, "employee"),
            (STRANGER, "employee"),
            (ADMIN, "super_admin"),
        ]
    ):
        accounts.add(_account(index, account_id, role=role))

    member_store = InMemoryConversationMemberStore()
    conv_store = InMemoryConversationStore(members=member_store)
    audit = AuditService(InMemoryAuditStore())
    conversations = ConversationService(
        conv_store, audit=audit, members=member_store, accounts=accounts
    )
    stream_store = InMemoryStreamStore()
    idempotency = InMemoryExecutionIdempotencyStore()
    task_store = TaskStore()
    metrics = RunMetricsService(InMemoryRunRecordStore())
    runtime = RuntimeService(task_store, run_metrics=metrics, member_run_reader=main._member_can_read_run)

    execution = ConversationExecutionService(
        conversations=conversations,
        conversation_store=conv_store,
        task_store=task_store,
        runtime_service=runtime,
        tool_execution=None,
        idempotency=idempotency,
        catalog=build_tool_spec_catalog(),
        audit=audit,
        # ★ 真连接（不是 InMemory）—— 本文件的全部意义。
        directory_store=directory,
        accounts=accounts,
    )

    monkeypatch.setattr(main, "store", task_store)
    monkeypatch.setattr(main, "run_metrics_service", metrics)
    monkeypatch.setattr(main, "runtime_service", runtime)
    monkeypatch.setattr(main, "conversation_store", conv_store)
    monkeypatch.setattr(main, "conversation_member_store", member_store)
    monkeypatch.setattr(main, "conversation_service", conversations)
    monkeypatch.setattr(main, "conversation_execution_service", execution)
    monkeypatch.setattr(main, "conversation_stream_store", stream_store)
    monkeypatch.setattr(main, "execution_idempotency_store", idempotency)
    monkeypatch.setattr(main, "audit_service", audit)

    return {
        "accounts": accounts,
        "members": member_store,
        "conv_store": conv_store,
        "service": conversations,
        "execution": execution,
        "idempotency": idempotency,
        "directory": directory,
        "connection": directory.connection,
        "tasks": task_store,
        "metrics": metrics,
    }


def _wire(monkeypatch, harness) -> FakeToolExecution:
    """接上打桩执行器（带键路径 ⇒ 真实执行分支）；目录沿用夹具里那份真库仓储。"""
    fake = FakeToolExecution()
    monkeypatch.setattr(
        main,
        "conversation_execution_service",
        ConversationExecutionService(
            conversations=main.conversation_service,
            conversation_store=main.conversation_store,
            task_store=main.store,
            runtime_service=main.runtime_service,
            tool_execution=fake,
            idempotency=main.execution_idempotency_store,
            catalog=build_tool_spec_catalog(),
            audit=main.audit_service,
            directory_store=harness["directory"],          # ★ 仍是真库
            accounts=harness["accounts"],
        ),
    )
    return fake


# ============================================================ 请求辅助


def headers(user_id: str = OWNER, role: str = "employee", tenant_id: str = TENANT) -> dict[str, str]:
    return {"X-Tenant-Id": tenant_id, "X-User-Id": user_id, "X-User-Role": role}


def create_conversation(*, who: str = OWNER, role: str = "employee") -> dict:
    response = client.post(
        "/api/v1/conversations", headers=headers(who, role), json={"agent_key": AGENT}
    )
    assert response.status_code == 201, response.text
    return response.json()


def add_member(conversation_id: str, member_id: str, *, permission: str, who: str):
    return client.post(
        f"/api/v1/conversations/{conversation_id}/members",
        headers=headers(who),
        json={"member_id": member_id, "permission": permission},
    )


def send(conversation_id: str, content: str, *, key: str, who: str, role: str = "employee"):
    return client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers={**headers(who, role), "Idempotency-Key": key},
        json={"content": content},
    )


def _ctx(user_id: str, *, tenant_id: str = TENANT, role: str = "employee") -> UserContext:
    return UserContext(tenant_id, user_id, role)


def _employee_owned_by_owner(directory) -> None:
    """AGENT 由**归属人本人**创建 ⇒ 真库 `owner_user_id` = `OWNER`（非管理员，不可冒名）。"""
    directory.create_employee(_ctx(OWNER), agent_key=AGENT, name="O3 员工", role_key=ROLE_KEY)


def _assert_nothing_persisted(harness, conversation_id: str, *, who: str, key: str) -> None:
    """零落库：任务 / 运行 / 幂等行 / 消息 全为 0。"""
    assert harness["tasks"].count_by_employee(TENANT) == {}
    assert harness["metrics"].store.list_recent(TENANT, limit=50) == []
    assert harness["idempotency"].get(TENANT, who, conversation_id, key) is None
    detail = client.get(f"/api/v1/conversations/{conversation_id}", headers=headers(who)).json()
    assert detail["messages_total"] == 0


# ============================================================ 0 · 装配自证（不是假连接）


def test_harness_uses_postgres_store_not_memory(harness, monkeypatch) -> None:
    """本文件的「全部意义」自证：判定用的目录仓储是**真 PG 实现**，且写入真的落库。

    若有人把 `directory_store=directory` 改回 `InMemoryWorkforceDirectoryStore`，
    本用例即红（`isinstance` + 裸 SQL 回读双重钉住）。
    """
    from app.workforce.store import InMemoryWorkforceDirectoryStore

    _wire(monkeypatch, harness)
    execution = main.conversation_execution_service
    assert isinstance(execution.directory_store, PostgresWorkforceDirectoryStore)
    assert not isinstance(execution.directory_store, InMemoryWorkforceDirectoryStore)

    _employee_owned_by_owner(harness["directory"])
    with harness["connection"].cursor() as cursor:
        cursor.execute(
            "SELECT owner_user_id FROM workbench_digital_employees "
            "WHERE tenant_id = %s AND agent_key = %s",
            (TENANT, AGENT),
        )
        row = cursor.fetchone()
    assert row is not None, "员工必须真的写进了 workbench_digital_employees"
    assert row[0] == OWNER


# ============================================================ 1 · 陌生人（越权堵点）


def test_stranger_initiator_blocked_and_nothing_persisted_on_real_db(harness, monkeypatch) -> None:
    """陌生人自建会话绑他人员工 ⇒ 执行 **403 且零落库**（真库 `read_agent_owner`/`share_permission` 判否）。"""
    fake = _wire(monkeypatch, harness)
    _employee_owned_by_owner(harness["directory"])
    conversation_id = create_conversation(who=STRANGER)["conversation_id"]

    blocked = send(conversation_id, TOOL_CALL, key="o3-pg-stranger", who=STRANGER)

    assert blocked.status_code == 403, blocked.text
    assert fake.calls == 0
    _assert_nothing_persisted(harness, conversation_id, who=STRANGER, key="o3-pg-stranger")


# ============================================================ 2 · 归属人（正向基线）


def test_owner_initiator_dispatches_on_real_db(harness, monkeypatch) -> None:
    """归属人自建会话 ⇒ **201**（真库 `read_agent_owner` 返回本人）。"""
    fake = _wire(monkeypatch, harness)
    _employee_owned_by_owner(harness["directory"])
    conversation_id = create_conversation(who=OWNER)["conversation_id"]

    ok = send(conversation_id, TOOL_CALL, key="o3-pg-owner", who=OWNER)

    assert ok.status_code == 201, ok.text
    assert fake.calls == 1
    assert harness["tasks"].count_by_employee(TENANT) == {AGENT: 1}


# ============================================================ 3 · `use` 档共享 ⇒ 201


def test_use_share_grantee_initiator_dispatches_on_real_db(harness, monkeypatch) -> None:
    """被 `use` 档共享者自建会话 ⇒ **201**（真库 `share_permission` 读回 `use`）。"""
    fake = _wire(monkeypatch, harness)
    directory = harness["directory"]
    _employee_owned_by_owner(directory)
    directory.add_share(_ctx(OWNER), AGENT, grantee_user_id=MATE, permission="use")
    assert directory.share_permission(_ctx(MATE), AGENT, MATE) == "use"  # 真库回读

    conversation_id = create_conversation(who=MATE)["conversation_id"]
    ok = send(conversation_id, TOOL_CALL, key="o3-pg-use", who=MATE)

    assert ok.status_code == 201, ok.text
    assert fake.calls == 1
    assert harness["tasks"].count_by_employee(TENANT) == {AGENT: 1}


# ============================================================ 4 · `read` 档 ⇒ 403（只认 use）


def test_read_share_grantee_initiator_blocked_on_real_db(harness, monkeypatch) -> None:
    """被 `read` 档共享者自建会话 ⇒ **403 且零落库**（只认 `use`；真库档位读回 `read` 不放行）。"""
    fake = _wire(monkeypatch, harness)
    directory = harness["directory"]
    _employee_owned_by_owner(directory)
    directory.add_share(_ctx(OWNER), AGENT, grantee_user_id=MATE, permission="read")
    assert directory.share_permission(_ctx(MATE), AGENT, MATE) == "read"

    conversation_id = create_conversation(who=MATE)["conversation_id"]
    blocked = send(conversation_id, TOOL_CALL, key="o3-pg-read", who=MATE)

    assert blocked.status_code == 403, blocked.text
    assert fake.calls == 0
    _assert_nothing_persisted(harness, conversation_id, who=MATE, key="o3-pg-read")


# ============================================================ 5 · 撤销 `use` 后立即失效


def test_revoking_use_share_immediately_blocks_on_real_db(harness, monkeypatch) -> None:
    """先共享 `use` 再**真库撤销** ⇒ 下一次（新幂等键）执行 **403**，且不新增任务。

    钉住「执行期每次重判」：撤销是**真 DELETE**（`remove_share` 走 SQL），
    下一次判定读回 `None` ⇒ 403。若 `share_permission` 的租户/键过滤写错、或撤销没删干净，本条必红。
    """
    fake = _wire(monkeypatch, harness)
    directory = harness["directory"]
    _employee_owned_by_owner(directory)
    directory.add_share(_ctx(OWNER), AGENT, grantee_user_id=MATE, permission="use")

    conversation_id = create_conversation(who=MATE)["conversation_id"]
    first = send(conversation_id, TOOL_CALL, key="o3-pg-revoke-1", who=MATE)
    assert first.status_code == 201, first.text
    assert harness["tasks"].count_by_employee(TENANT) == {AGENT: 1}

    assert directory.remove_share(_ctx(OWNER), AGENT, MATE) is True
    assert directory.share_permission(_ctx(MATE), AGENT, MATE) is None  # 真库确已删除

    second = send(conversation_id, TOOL_CALL, key="o3-pg-revoke-2", who=MATE)
    assert second.status_code == 403, second.text
    # 只 **1** 条任务 —— 撤销后的那次不得落库（不是 2）。
    assert harness["tasks"].count_by_employee(TENANT) == {AGENT: 1}
    assert harness["idempotency"].get(TENANT, MATE, conversation_id, "o3-pg-revoke-2") is None


# ============================================================ 6 · 传递上限：`write` 成员随发起人失效


def test_write_member_transfer_follows_initiator_on_real_db(harness, monkeypatch) -> None:
    """`use` 档派活权经会话传给 `write` 成员，但**上限 = 发起人此刻权限**（真库版 D2）。

    发起人 `MATE` 有 `use` ⇒ 其会话里的 `write` 成员 `WRITER` 触发执行 **201**（以 WRITER 本人身份）；
    撤销 `MATE` 的 `use` ⇒ WRITER 下一次请求**立即 403**。
    """
    fake = _wire(monkeypatch, harness)
    directory = harness["directory"]
    _employee_owned_by_owner(directory)
    directory.add_share(_ctx(OWNER), AGENT, grantee_user_id=MATE, permission="use")

    conversation_id = create_conversation(who=MATE)["conversation_id"]
    assert add_member(conversation_id, WRITER, permission="write", who=MATE).status_code == 201

    first = send(conversation_id, TOOL_CALL, key="o3-pg-transfer-1", who=WRITER)
    assert first.status_code == 201, first.text
    assert harness["tasks"].count_by_employee(TENANT) == {AGENT: 1}

    assert directory.remove_share(_ctx(OWNER), AGENT, MATE) is True

    second = send(conversation_id, TOOL_CALL, key="o3-pg-transfer-2", who=WRITER)
    assert second.status_code == 403, second.text
    assert harness["tasks"].count_by_employee(TENANT) == {AGENT: 1}


# ============================================================ 7 · 跨租户


def test_cross_tenant_share_does_not_leak_on_real_db(harness, monkeypatch) -> None:
    """跨租户：**别的租户里同 `agent_key` 的 `use` 共享不得泄漏到本租户** ⇒ **403**。

    构造：同一个 `agent_key` 在 `TENANT`（归 `OWNER`）与 `OTHER_TENANT`（归 `OTHER_OWNER`）
    各有一行；`OTHER_TENANT` 给 `MATE` 授了 `use`，但 `TENANT` **没有**。
    若 `share_permission` 的 SQL 漏掉 `tenant_id` 过滤（把别的租户的共享读进来），本条必红
    —— 这正是「假连接文本断言」证不了的：只有真 SQL 才能证明租户过滤真的生效。
    """
    fake = _wire(monkeypatch, harness)
    directory = harness["directory"]
    _employee_owned_by_owner(directory)
    directory.create_employee(_ctx(OTHER_OWNER, tenant_id=OTHER_TENANT), agent_key=AGENT, name="别租户员工", role_key=ROLE_KEY)
    directory.add_share(
        _ctx(OTHER_OWNER, tenant_id=OTHER_TENANT), AGENT, grantee_user_id=MATE, permission="use"
    )
    # 同一 `agent_key` / 同一被授权人，两个租户的档位互不相干：
    assert directory.share_permission(_ctx(MATE, tenant_id=OTHER_TENANT), AGENT, MATE) == "use"
    assert directory.share_permission(_ctx(MATE), AGENT, MATE) is None

    conversation_id = create_conversation(who=MATE)["conversation_id"]
    blocked = send(conversation_id, TOOL_CALL, key="o3-pg-cross-tenant", who=MATE)

    assert blocked.status_code == 403, blocked.text
    assert fake.calls == 0
    _assert_nothing_persisted(harness, conversation_id, who=MATE, key="o3-pg-cross-tenant")


def test_agent_only_in_other_tenant_treated_as_missing_on_real_db(harness, monkeypatch) -> None:
    """跨租户：`agent_key` **只**存在于别的租户 ⇒ 本租户按**不存在**处理 ⇒ **422**。

    为何是 `422` 而非 `403`：契约「闸门次序（硬约束）」规定「`agent_key` 存在且启用 ⇒ `422`」
    **排在** O3 派生闸门**之前**。本租户查不到该员工 ⇒ `read_agent_governance` 返回 `None`
    ⇒ 命中「不存在」分支 → `422`。这是**如实**的现状（不是本文件的期望值被迁就）。
    """
    fake = _wire(monkeypatch, harness)
    directory = harness["directory"]
    directory.create_employee(_ctx(OTHER_OWNER, tenant_id=OTHER_TENANT), agent_key=AGENT, name="别租户员工", role_key=ROLE_KEY)

    conversation_id = create_conversation(who=STRANGER)["conversation_id"]
    blocked = send(conversation_id, TOOL_CALL, key="o3-pg-other-only", who=STRANGER)

    assert blocked.status_code == 422, blocked.text
    assert fake.calls == 0
    _assert_nothing_persisted(harness, conversation_id, who=STRANGER, key="o3-pg-other-only")


# ============================================================ 8 · 闸门次序（停用仍 422）


def test_disabled_employee_still_422_not_403_on_real_db(harness, monkeypatch) -> None:
    """真库停用员工后仍是契约规定的 **422**（派生闸门须排在「存在且启用」之后）。

    用**陌生人**做判据：若派生闸门抢先执行，陌生人会先拿 `403`；
    只有「存在且启用 ⇒ 422」在前，才得到 `422`。真库 `update_employee(status=disabled)`
    后 `read_agent_governance`（JOIN 岗位、判 active）必须返回 `None`。
    """
    fake = _wire(monkeypatch, harness)
    directory = harness["directory"]
    _employee_owned_by_owner(directory)
    directory.update_employee(_ctx(ADMIN, role="super_admin"), AGENT, status="disabled")

    conversation_id = create_conversation(who=STRANGER)["conversation_id"]
    blocked = send(conversation_id, TOOL_CALL, key="o3-pg-disabled", who=STRANGER)

    assert blocked.status_code == 422, blocked.text
    assert fake.calls == 0
    _assert_nothing_persisted(harness, conversation_id, who=STRANGER, key="o3-pg-disabled")
