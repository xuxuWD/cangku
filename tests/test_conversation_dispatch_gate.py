"""会话派活路径的授权闸门（O3 · 派生授权）—— **TDD 失败测试（先红后绿）**。

口径（真源，**先于实现落定**）：
    - `docs/api-contract.md`「会话协作：分享与多端协同（P2c-6）」
      ・「**使用权的传递上限（O3 · 派生授权 —— 2026-09-24 用户裁决）**」
    - `docs/api-contract.md`「数字员工归属与共享（B2）」C4 节末
      ・「**派活权两面同口径**」与「**超管代建流程的变化**」
    - 裁决留痕：`docs/contracts/decision-log.md` **D-062**

判定式（**执行期每次重判**，以下两条**同时成立**才放行）：
    ① **会话发起人当前**对 `conversation.agent_key` 享有 `owner ∪ use`（**或**发起人是 `super_admin`）；
    ② **发言者**是该会话本人或 `write` 成员（＝既有发言写权限，本闸门**不放松**它）。
    不成立 ⇒ **`403` 且零落库**（不建承载任务 / 运行 / 消息 / 幂等行，不调工具）。

⚠️ **闸门次序（硬约束）**：本闸门**必须排在**「`agent_key` 存在且启用 ⇒ `422`」校验**之后**
（用例 G 钉住：否则「员工已停用」会从 `422` 变成 `403`）。

⚠️ **与既有 P2c-6 行为的关系**：本闸门**不推翻**「`write` 成员可触发执行」——
它只把「这条会话能**用哪个**数字员工」的上限收敛到**发起人当前权限**。
`tests/test_conversation_members_api.py` 的「write 成员按本人身份执行」用例属**真语义**，
**不得改断言**（其夹具若因本闸门变红，须按下方「夹具判定规程」处置）。

覆盖：A–I（逐条见各用例）。**当前全部（除反假说明外）应为红** —— 这正是 TDD 要的。
"""

from __future__ import annotations

import json

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
from app.workforce.store import InMemoryWorkforceDirectoryStore

client = TestClient(app)

TENANT = "t-1"
OWNER = "u-1"        # 归属人：亲手创建了 AGENT（owner_user_id = u-1）
WRITER = "u-2"       # 被点名的 `write` 成员
STRANGER = "u-9"     # 与 AGENT 无任何授权关系的陌生人
ADMIN = "admin-1"    # super_admin（管理视角）
AGENT = "content-writer"

# 与既有会话用例同一工具调用口径（`fs.list` 风险低 ⇒ 正常 201）。
TOOL_CALL = json.dumps({"tool_key": "fs.list", "params": {"path": "/workspace"}})


class FakeToolExecution:
    """打桩执行入口：只记调用次数与请求（`requested_by` 即「以谁的身份执行」的判据）。"""

    def __init__(self) -> None:
        self.calls = 0
        self.requests = []

    def execute(self, request, *, actor=None, plan=None):
        self.calls += 1
        self.requests.append(request)
        return ToolExecutionResult(outcome="executed", code=201)


def _account(index: int, account_id: str, *, role: str = "employee") -> Account:
    return Account(
        phone=f"1390001{index:04d}",
        password_hash="hash",
        position="岗位",
        full_name=f"姓名-{account_id}",
        account_id=account_id,
        role=role,
        tenant_id=TENANT,
        status=AccountStatus.APPROVED,
    )


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    """与生产同口径的装配：账号 / 成员 / 会话 / 运行时 / 目录（owner = `u-1`）。"""
    accounts = InMemoryAccountRepository()
    for index, (account_id, kwargs) in enumerate(
        [(OWNER, {}), (WRITER, {}), (STRANGER, {}), (ADMIN, {"role": "super_admin"})]
    ):
        accounts.add(_account(index, account_id, **kwargs))

    member_store = InMemoryConversationMemberStore()
    conv_store = InMemoryConversationStore(members=member_store)
    audit = AuditService(InMemoryAuditStore())
    # `accounts` 是发起人角色（超管判定）的解析来源 —— 与 `app/main.py` 的装配一致。
    conversations = ConversationService(conv_store, audit=audit, members=member_store, accounts=accounts)
    stream_store = InMemoryStreamStore()
    idempotency = InMemoryExecutionIdempotencyStore()
    task_store = TaskStore()
    metrics = RunMetricsService(InMemoryRunRecordStore())
    runtime = RuntimeService(task_store, run_metrics=metrics, member_run_reader=main._member_can_read_run)

    directory = InMemoryWorkforceDirectoryStore()
    admin = UserContext(TENANT, ADMIN, "super_admin")
    directory.create_role(admin, role_key="writer", name="内容岗")
    # ⚠️ 关键：AGENT **由归属人本人创建**（非管理员 ⇒ `owner_user_id` = 调用者本人 = `u-1`）。
    directory.create_employee(
        UserContext(TENANT, OWNER, "employee"), agent_key=AGENT, name="内容员工", role_key="writer"
    )

    execution = ConversationExecutionService(
        conversations=conversations,
        conversation_store=conv_store,
        task_store=task_store,
        runtime_service=runtime,
        tool_execution=None,
        idempotency=idempotency,
        catalog=build_tool_spec_catalog(),
        audit=audit,
        directory_store=directory,
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
        "stream": stream_store,
        "idempotency": idempotency,
        "audit": audit,
        "directory": directory,
        "tasks": task_store,
    }


def wire_execution(monkeypatch, tool_execution) -> None:
    """接上打桩执行器（带键路径 ⇒ 真实执行分支）；目录沿用夹具里已建好的那一份。"""
    monkeypatch.setattr(
        main,
        "conversation_execution_service",
        ConversationExecutionService(
            conversations=main.conversation_service,
            conversation_store=main.conversation_store,
            task_store=main.store,
            runtime_service=main.runtime_service,
            tool_execution=tool_execution,
            idempotency=main.execution_idempotency_store,
            catalog=build_tool_spec_catalog(),
            audit=main.audit_service,
            directory_store=main.conversation_execution_service.directory_store,
        ),
    )


def headers(user_id: str = OWNER, role: str = "employee", tenant_id: str = TENANT) -> dict[str, str]:
    return {"X-Tenant-Id": tenant_id, "X-User-Id": user_id, "X-User-Role": role}


def create_conversation(*, who: str = OWNER, role: str = "employee") -> dict:
    response = client.post(
        "/api/v1/conversations", headers=headers(who, role), json={"agent_key": AGENT}
    )
    assert response.status_code == 201, response.text
    return response.json()


def add_member(conversation_id: str, member_id: str, *, permission: str | None = None,
               who: str = OWNER, role: str = "employee"):
    payload: dict[str, object] = {"member_id": member_id}
    if permission is not None:
        payload["permission"] = permission
    return client.post(
        f"/api/v1/conversations/{conversation_id}/members",
        headers=headers(who, role),
        json=payload,
    )


def send(conversation_id: str, content: str, *, key: str, who: str = OWNER, role: str = "employee"):
    return client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers={**headers(who, role), "Idempotency-Key": key},
        json={"content": content},
    )


def send_stream(conversation_id: str, content: str, *, key: str, who: str = OWNER, role: str = "employee"):
    return client.post(
        f"/api/v1/conversations/{conversation_id}/messages:stream",
        headers={**headers(who, role), "Idempotency-Key": key},
        json={"content": content},
    )


def owner_context() -> UserContext:
    return UserContext(TENANT, OWNER, "employee")


def assert_nothing_persisted(conversation_id: str, *, who: str = STRANGER, key: str) -> None:
    """零落库：任务 / 运行 / 幂等行 / 消息 全为 0。"""
    assert main.store.count_by_employee(TENANT) == {}
    assert main.run_metrics_service.store.list_recent(TENANT, limit=50) == []
    assert main.execution_idempotency_store.get(TENANT, who, conversation_id, key) is None
    detail = client.get(
        f"/api/v1/conversations/{conversation_id}", headers=headers(who)
    ).json()
    assert detail["messages_total"] == 0


# ------------------------------------------------------------ A · 陌生人


def test_A_stranger_cannot_dispatch_others_agent(monkeypatch) -> None:
    """A：`u-9` 自建会话绑 `u-1` 的 `agent_key` ⇒ 触发执行 **403 且零落库**。"""
    fake = FakeToolExecution()
    wire_execution(monkeypatch, fake)
    conversation_id = create_conversation(who=STRANGER)["conversation_id"]

    blocked = send(conversation_id, TOOL_CALL, key="k-stranger", who=STRANGER)

    assert blocked.status_code == 403, blocked.text
    assert fake.calls == 0
    assert_nothing_persisted(conversation_id, who=STRANGER, key="k-stranger")


# ------------------------------------------------------------ H · 两个入口同一判定


def test_H_stream_endpoint_enforces_the_same_gate(monkeypatch) -> None:
    """H：`/messages:stream` 与 `/messages` 同一判定（不得只在旧入口装闸门）。"""
    fake = FakeToolExecution()
    wire_execution(monkeypatch, fake)
    conversation_id = create_conversation(who=STRANGER)["conversation_id"]

    blocked = send_stream(conversation_id, TOOL_CALL, key="k-stranger-stream", who=STRANGER)

    assert blocked.status_code == 403, blocked.text
    assert blocked.headers.get("X-Stream-Run-Id") is None
    assert fake.calls == 0
    assert_nothing_persisted(conversation_id, who=STRANGER, key="k-stranger-stream")


# ------------------------------------------------------------ B · P2c-6 保住


def test_B_write_member_dispatch_is_preserved_when_initiator_has_owner(monkeypatch) -> None:
    """B（P2c-6 保住）：归属人建会话 + `u-2` 是 `write` 成员 ⇒ 执行 **201**。

    这条刻意对齐 `tests/test_conversation_members_api.py` 的「write 成员按本人身份执行」用例：
    派生授权**不得**把已交付的成员协作行为打红。
    """
    fake = FakeToolExecution()
    wire_execution(monkeypatch, fake)
    conversation_id = create_conversation(who=OWNER)["conversation_id"]
    assert add_member(conversation_id, WRITER, permission="write", who=OWNER).status_code == 201

    ok = send(conversation_id, TOOL_CALL, key="k-writer", who=WRITER)

    assert ok.status_code == 201, ok.text
    assert fake.calls == 1
    assert fake.requests[0].requested_by == WRITER  # 仍以**发言者本人**身份执行
    assert main.store.count_by_employee(TENANT) == {AGENT: 1}


# ------------------------------------------------------------ C · 成员身份绕过不了发起人权限


def test_C_write_member_cannot_dispatch_when_initiator_lacks_use(monkeypatch) -> None:
    """C：会话由 `u-9`（无 `use`）建并绑他人 agent，`u-2` 是 `write` 成员 ⇒ **403 且零落库**。"""
    fake = FakeToolExecution()
    wire_execution(monkeypatch, fake)
    conversation_id = create_conversation(who=STRANGER)["conversation_id"]
    assert add_member(conversation_id, WRITER, permission="write", who=STRANGER).status_code == 201

    blocked = send(conversation_id, TOOL_CALL, key="k-writer-blocked", who=WRITER)

    assert blocked.status_code == 403, blocked.text
    assert fake.calls == 0
    assert_nothing_persisted(conversation_id, who=WRITER, key="k-writer-blocked")


# ------------------------------------------------------------ C2 · `read` 档不能派活


def test_C2_read_tier_share_cannot_dispatch(monkeypatch) -> None:
    """C2（安全轴）：发起人只拿到 `read` 档共享 ⇒ 触发执行 **403 且零落库**。

    与 D / D2 的 `use` 档（`201`）形成对照，钉住「**只认 `use`**」这条判定：
    把闸门档位判定放宽为「任何档位都放行」时本条必红。
    （此前全仓**无任何**用例给**会话发起人**授过 `permission="read"` 的 agent 共享 ——
     这正是该变异体存活的根因；本条即为其死结。）
    """
    fake = FakeToolExecution()
    wire_execution(monkeypatch, fake)
    directory = main.conversation_execution_service.directory_store
    directory.add_share(owner_context(), AGENT, grantee_user_id=STRANGER, permission="read")

    conversation_id = create_conversation(who=STRANGER)["conversation_id"]
    blocked = send(conversation_id, TOOL_CALL, key="k-read-tier", who=STRANGER)

    assert blocked.status_code == 403, blocked.text
    assert fake.calls == 0
    assert_nothing_persisted(conversation_id, who=STRANGER, key="k-read-tier")


# ------------------------------------------------------------ D · 撤销后立即失效


def test_D_revoking_use_share_immediately_removes_derived_authority(monkeypatch) -> None:
    """D：先共享 `use` 再撤销 ⇒（本人路径）下一次执行 **403**（执行期重判，非建会话时一次性）。"""
    fake = FakeToolExecution()
    wire_execution(monkeypatch, fake)
    directory = main.conversation_execution_service.directory_store
    directory.add_share(owner_context(), AGENT, grantee_user_id=STRANGER, permission="use")

    conversation_id = create_conversation(who=STRANGER)["conversation_id"]
    first = send(conversation_id, TOOL_CALL, key="k-derived-1", who=STRANGER)
    assert first.status_code == 201, first.text
    assert main.store.count_by_employee(TENANT) == {AGENT: 1}

    assert directory.remove_share(owner_context(), AGENT, STRANGER) is True

    second = send(conversation_id, TOOL_CALL, key="k-derived-2", who=STRANGER)
    assert second.status_code == 403, second.text
    # 只 **1** 条任务 —— 撤销后的那次不得落库（不是 2）。
    assert main.store.count_by_employee(TENANT) == {AGENT: 1}
    assert main.execution_idempotency_store.get(TENANT, STRANGER, conversation_id, "k-derived-2") is None


def test_D2_revoking_use_drops_the_member_transfer_too(monkeypatch) -> None:
    """D 的第二面：撤销后，被点名的 `write` 成员**立即**失去传递权（同一会话、下一次请求）。"""
    fake = FakeToolExecution()
    wire_execution(monkeypatch, fake)
    directory = main.conversation_execution_service.directory_store
    directory.add_share(owner_context(), AGENT, grantee_user_id=STRANGER, permission="use")

    conversation_id = create_conversation(who=STRANGER)["conversation_id"]
    assert add_member(conversation_id, WRITER, permission="write", who=STRANGER).status_code == 201

    first = send(conversation_id, TOOL_CALL, key="k-transfer-1", who=WRITER)
    assert first.status_code == 201, first.text

    assert directory.remove_share(owner_context(), AGENT, STRANGER) is True

    second = send(conversation_id, TOOL_CALL, key="k-transfer-2", who=WRITER)
    assert second.status_code == 403, second.text
    assert main.store.count_by_employee(TENANT) == {AGENT: 1}


# ------------------------------------------------------------ E / F · 正向基线


def test_E_owner_can_dispatch_in_own_conversation(monkeypatch) -> None:
    """E：归属人自建会话 ⇒ **201**（正向基线）。"""
    fake = FakeToolExecution()
    wire_execution(monkeypatch, fake)
    conversation_id = create_conversation(who=OWNER)["conversation_id"]

    ok = send(conversation_id, TOOL_CALL, key="k-owner", who=OWNER)

    assert ok.status_code == 201, ok.text
    assert main.store.count_by_employee(TENANT) == {AGENT: 1}


def test_F_super_admin_can_dispatch_an_agent_owned_by_someone_else(monkeypatch) -> None:
    """F：`super_admin` 管理视角 —— 会话发起人 / 发言人均为超管，agent 归属他人 ⇒ **201**。

    （本用例要求实现能解析**发起人**的角色：夹具已把 `accounts` 注入 `ConversationService`，
     与 `app/main.py` 装配同口径。）
    """
    fake = FakeToolExecution()
    wire_execution(monkeypatch, fake)
    conversation_id = create_conversation(who=ADMIN, role="super_admin")["conversation_id"]

    ok = send(conversation_id, TOOL_CALL, key="k-admin", who=ADMIN, role="super_admin")

    assert ok.status_code == 201, ok.text
    assert fake.calls == 1


# ------------------------------------------------------------ G · 闸门次序


def test_G_disabled_agent_still_returns_422_not_403(monkeypatch) -> None:
    """G：员工已停用 ⇒ 仍是契约规定的 **422**，**不是 403**（闸门须排在「存在且启用」之后）。

    用**陌生人**做判据：若派生闸门抢先执行，陌生人会先拿到 `403`；
    只有「存在且启用 ⇒ 422」排在前面，才会得到 `422`。
    """
    fake = FakeToolExecution()
    wire_execution(monkeypatch, fake)
    directory = main.conversation_execution_service.directory_store
    directory.update_employee(UserContext(TENANT, ADMIN, "super_admin"), AGENT, status="disabled")

    stranger_conversation = create_conversation(who=STRANGER)["conversation_id"]
    blocked = send(stranger_conversation, TOOL_CALL, key="k-disabled", who=STRANGER)
    assert blocked.status_code == 422, blocked.text

    # 归属人同样 422（停用与身份无关；两行合起来说明「422 先于派生闸门」不是陌生人错觉）。
    owner_conversation = create_conversation(who=OWNER)["conversation_id"]
    also_blocked = send(owner_conversation, TOOL_CALL, key="k-disabled-owner", who=OWNER)
    assert also_blocked.status_code == 422, also_blocked.text

    assert fake.calls == 0
    assert main.store.count_by_employee(TENANT) == {}


# ============================================================ I · 反假怎么跑
#
# 目标：证明「A / C / D 的 403」**确实由派生判定产生**，而不是别的什么恰好拦住了它们
#       —— 即「把派生判定做成恒真 ⇒ A / C / D 必红」。
#
# 做法（实现落地后手动执行一次，记录到报告；**不要**把结果留成跳过的用例）：
#
#   1. 找出实现里承载「派生判定」的那个函数（本轮实现轮确定其名字/位置；候选落点：
#      ・`app/conversation/execution.py::ConversationExecutionService._execute` 内新增的私有判定；
#      ・`app/workforce/service.py::WorkforceDirectoryService` 上新增/扩展的派活闸门（若复用
#        `ensure_can_dispatch`，则该函数即落点）。
#   2. 把它**临时改坏**为恒真（例：在判定函数首行 `return`；或把「无权限」分支直接删掉）。
#   3. 只跑本文件：`./.venv/Scripts/python.exe -m pytest tests/test_conversation_dispatch_gate.py -q`
#      ⇒ 期望 **A / C / D（含 D2）全红**（它们拿到 201 而非 403，「零落库」断言随之失败）。
#      **若仍全绿 ⇒ 本文件的用例无效，不是实现正确。**
#   4. **还原**改动，重跑本文件 + `tests/test_conversation_members_api.py` ⇒ 全绿。
#
# 另：下列两处**未纳入本轮反假范围**，如实标注：
#   ・入口 ② 的 `messages:stream` 与 ① 共用 `handle_message` ⇒ 同一处改坏会同时红；
#     若要单独证明 H 有效，可只把 `stream=True` 分支的判定短路。
#   ・`app/content/service.py` 那条落库路径**不在本闸门范围**（调用者不可选目标），
#     故本文件不覆盖、也不应据此声称该路径已受保护。
