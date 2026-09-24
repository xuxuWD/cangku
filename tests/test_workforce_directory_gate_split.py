"""OP-01 岗位目录面 · 权限闸门拆分 —— 验收测试（**本文件先于实现存在**）。

口径源：`docs/contracts/gate-split-review-2026-09-24.md`（专项评审材料）。
宪法 4.1：权限模型属**地基级**变更 ⇒ 先写**失败测试**、再写实现；反假测试见 A9。

**本文件当前应为全红**（实现尚未开始）。逐条对应评审材料的验收项：

    A1 / A2  普通员工读目录不再 403，且只看到 owner 是自己 ∪ 被共享的
    A3       普通员工创建 ⇒ owner 是自己；**不可指定他人**
    A4       普通员工改 / 停用**别人的**员工 ⇒ 拒绝
    A5       普通员工读**别人的** config ⇒ 拒绝
    A6       `use` 档成员能派活、不能改配置 / 不能停用
    A7       **两层同口径**：同一角色在路由层与仓储层得到同一结论
    A8       本批**不放宽**的方法（建 / 改岗位、`known_keys` 等）权限逐字不变
    A10      读路径不落他人敏感明细

**⚠️ 本轮采纳的默认取值**（评审材料 §八之二，**可推翻**）：
    V1=C 岗位列表登录用户可读但只返回 active；V2=B 归属人不能改/停用；
    V3=A 本批只动目录面；V4=A `use` 档不可读 config。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import main
from app.audit.service import AuditService
from app.audit.store import InMemoryAuditStore
from app.domain import PolicyError, TaskStore, UserContext
from app.knowledge_policy import KnowledgeAccessRegistry
from app.main import app
from app.workforce.config import AgentConfigService
from app.workforce.service import WorkforceDirectoryService
from app.workforce.store import InMemoryWorkforceDirectoryStore

client = TestClient(app)

# 11 个用例在实现完成后即应全绿；`@NOT_IMPLEMENTED` 标记**已摘除**
# （strict=True 下 XPASS 即 FAIL，不允许"实现了但忘了摘标记"静默通过 —— 宪法 2.2）。

ADMIN = UserContext("t-1", "admin-1", "super_admin")
OWNER = UserContext("t-1", "u-owner", "employee")      # 员工甲：创建者 / 归属人
OTHER = UserContext("t-1", "u-other", "employee")      # 员工乙：无关同事
SHAREE = UserContext("t-1", "u-sharee", "employee")    # 员工丙：被共享者

DIRECTORY_ADMIN_MESSAGE = "只有超级管理员可以管理岗位与数字员工目录"


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    registry = KnowledgeAccessRegistry()
    directory_store = InMemoryWorkforceDirectoryStore()
    audit = AuditService(InMemoryAuditStore())
    service = WorkforceDirectoryService(
        directory_store,
        audit=audit,
        knowledge_registry=registry,
        task_store=TaskStore(),
    )
    monkeypatch.setattr(main, "store", TaskStore())
    monkeypatch.setattr(main, "knowledge_access_registry", registry)
    monkeypatch.setattr(main, "workforce_directory_store", directory_store)
    monkeypatch.setattr(main, "workforce_directory_service", service)
    # ⚠️ 必须**一并**换掉 `agent_config_service`：它在装配期就绑定了**旧**的目录仓储实例，
    # 只换 `workforce_directory_store` 会让 `{agent_key}/config` 打到空仓储（`404`）——
    # A10 的 PATCH 置提示词正是踩这个（测试隔离缺陷，非断言放宽）。
    monkeypatch.setattr(
        main, "agent_config_service", AgentConfigService(directory_store, audit=audit)
    )
    return directory_store


def headers(role: str = "employee", user_id: str = "u-owner", tenant_id: str = "t-1") -> dict[str, str]:
    return {"X-Tenant-Id": tenant_id, "X-User-Id": user_id, "X-User-Role": role}


def admin_headers() -> dict[str, str]:
    return headers(role="super_admin", user_id="admin-1")


def seed() -> None:
    """超管建一个岗位 + 一个归属 `u-owner` 的数字员工（走接口，保持黑盒）。"""
    assert client.post(
        "/api/v1/workforce/roles", headers=admin_headers(), json={"role_key": "writer", "name": "文案岗"}
    ).status_code == 201
    assert client.post(
        "/api/v1/workforce/agents",
        headers=admin_headers(),
        json={"agent_key": "a-owner", "name": "小写", "role_key": "writer", "owner_user_id": "u-owner"},
    ).status_code == 201


# --------------------------------------------------------------------------- A1 / A2


def test_employee_can_read_directory_without_403() -> None:
    """**A1**：普通员工读目录**不再** 403。（现状：403「只有超级管理员可以管理岗位与数字员工目录」）"""
    seed()

    response = client.get("/api/v1/workforce/agents", headers=headers(user_id="u-owner"))

    assert response.status_code == 200, "普通员工读目录应放开（B2 前置）；现状 403 即本用例为红"


def test_employee_sees_only_own_or_shared_agents() -> None:
    """**A2**：可见性 = owner 是自己 ∪ 被共享的 ∪ super_admin —— **不是前端隐藏，是服务端不返回**。"""
    seed()

    mine = client.get("/api/v1/workforce/agents", headers=headers(user_id="u-owner")).json()
    assert [i["agent_key"] for i in mine["items"]] == ["a-owner"]

    # 无关同事：看不到别人的员工
    theirs = client.get("/api/v1/workforce/agents", headers=headers(user_id="u-other")).json()
    assert theirs["items"] == [], "不得返回他人的数字员工"

    # 超管：管理视角，看得到
    assert len(client.get("/api/v1/workforce/agents", headers=admin_headers()).json()["items"]) == 1


def test_shares_extend_visibility() -> None:
    """**A2 续**：被共享者能看到该员工（两档 `read` / `use`）。"""
    seed()
    assert client.post(
        "/api/v1/workforce/agents/a-owner/shares",
        headers=headers(user_id="u-owner"),
        json={"grantee_user_id": "u-sharee", "permission": "read"},
    ).status_code == 201

    seen = client.get("/api/v1/workforce/agents", headers=headers(user_id="u-sharee")).json()
    assert [i["agent_key"] for i in seen["items"]] == ["a-owner"]


def test_roster_is_not_behind_the_admin_gate() -> None:
    """**A1 续 · 评审材料 §一 ④**：`GET /workforce/roster` 用的是**内联判定**，不在共享函数里。

    只拆 `_require_workforce_directory_admin` 而漏掉它就**一点不会变** —— 本用例专门钉住这点。
    """
    seed()

    response = client.get("/api/v1/workforce/roster", headers=headers(user_id="u-owner"))

    assert response.status_code == 200, "roster 走的是内联判定（app/main.py:1344），必须一并改"


# --------------------------------------------------------------------------- A3


def test_employee_creation_sets_self_as_owner() -> None:
    """**A3**：员工侧创建 ⇒ `owner_user_id` **由服务端置为调用者本人**。"""
    assert client.post(
        "/api/v1/workforce/roles", headers=admin_headers(), json={"role_key": "writer", "name": "文案岗"}
    ).status_code == 201

    created = client.post(
        "/api/v1/workforce/agents",
        headers=headers(user_id="u-owner"),
        json={"agent_key": "a-mine", "name": "我的员工", "role_key": "writer"},
    )

    assert created.status_code == 201, "员工侧创建应放开（B2 DE-01）"
    assert created.json()["owner_user_id"] == "u-owner"


def test_employee_cannot_forge_owner() -> None:
    """**A3 续**：**不可指定他人为 owner** —— 一切输入默认不可信。"""
    assert client.post(
        "/api/v1/workforce/roles", headers=admin_headers(), json={"role_key": "writer", "name": "文案岗"}
    ).status_code == 201

    forged = client.post(
        "/api/v1/workforce/agents",
        headers=headers(user_id="u-owner"),
        json={"agent_key": "a-evil", "name": "冒名", "role_key": "writer", "owner_user_id": "u-other"},
    )

    # 要么 422（未知字段白名单拒绝），要么 201 但 owner 仍被服务端改回自己 —— 两者都可接受，
    # **唯一不可接受的是 owner 真的变成 u-other**。
    if forged.status_code == 201:
        assert forged.json()["owner_user_id"] == "u-owner"
    else:
        assert forged.status_code == 422


# --------------------------------------------------------------------------- A4 / A5


def test_employee_cannot_modify_or_disable_others_agent() -> None:
    """**A4**（V2=B 默认）：归属人**也不能**改 / 停用 —— 改配置仍是管理动作。"""
    seed()

    patched = client.patch(
        "/api/v1/workforce/agents/a-owner", headers=headers(user_id="u-other"), json={"name": "改名"}
    )
    assert patched.status_code in (403, 404), "无关同事不得改他人员工"

    disabled = client.patch(
        "/api/v1/workforce/agents/a-owner", headers=headers(user_id="u-other"), json={"status": "disabled"}
    )
    assert disabled.status_code in (403, 404), "无关同事不得停用他人员工"


def test_employee_cannot_read_others_agent_config() -> None:
    """**A5**：`config` 含**提示词 / 模型 / 日预算 / 审批档** ⇒ 非归属人不可读。"""
    seed()

    response = client.get("/api/v1/workforce/agents/a-owner/config", headers=headers(user_id="u-other"))

    assert response.status_code in (403, 404), "他人 config 不得可读（含提示词与预算）"


# --------------------------------------------------------------------------- A6


def test_use_share_can_dispatch_but_not_configure() -> None:
    """**A6 / V4=A**：`use` 档能派活，**不能改配置、不能停用**，且**不可读 config**。"""
    seed()
    assert client.post(
        "/api/v1/workforce/agents/a-owner/shares",
        headers=headers(user_id="u-owner"),
        json={"grantee_user_id": "u-sharee", "permission": "use"},
    ).status_code == 201

    # 可读（`use` ⊃ `read` 的可见性）
    assert client.get("/api/v1/workforce/agents", headers=headers(user_id="u-sharee")).status_code == 200
    # 不可读 config（V4=A）
    assert client.get(
        "/api/v1/workforce/agents/a-owner/config", headers=headers(user_id="u-sharee")
    ).status_code in (403, 404)
    # 不可停用
    assert client.patch(
        "/api/v1/workforce/agents/a-owner", headers=headers(user_id="u-sharee"), json={"status": "disabled"}
    ).status_code in (403, 404)


def test_read_share_can_read_config_but_use_share_cannot() -> None:
    """**A5 / V4 真源对齐**（2026-09-24 修复）：`read` 档 = **能看配置**；`use` 档 = 不能读配置。

    B1 §3.3② 表与契约 C4 逐字写「`read`｜能看配置…；`use`｜能派活」。原实现两档都读不到配置
    ⇒ 与真源相反、且两档行为完全等价。反假：把 `_ensure_config_reader` 里的 `read` 分支删掉 ⇒ 本用例必红。
    """
    seed()
    assert client.post(
        "/api/v1/workforce/agents/a-owner/shares",
        headers=headers(user_id="u-owner"),
        json={"grantee_user_id": "u-read", "permission": "read"},
    ).status_code == 201
    assert client.post(
        "/api/v1/workforce/agents/a-owner/shares",
        headers=headers(user_id="u-owner"),
        json={"grantee_user_id": "u-use", "permission": "use"},
    ).status_code == 201

    readable = client.get("/api/v1/workforce/agents/a-owner/config", headers=headers(user_id="u-read"))
    assert readable.status_code == 200, "`read` 档应能看配置（真源 C4）"

    denied = client.get("/api/v1/workforce/agents/a-owner/config", headers=headers(user_id="u-use"))
    assert denied.status_code in (403, 404), "`use` 档不可读 config（V4=A）"


def test_read_share_and_strangers_cannot_dispatch_tasks() -> None:
    """**A6 反向（派活闸门）**（2026-09-24 修复）：`use` = 能派活、`read` = 不能派活。

    此前任务落库路径**从不校验** `employee_key` 的归属 / 共享 ⇒ `read` 档、零共享同事
    都能用他人的纳管员工建任务。反假：删掉 `_store_new_task` 里的 `ensure_can_dispatch` 调用 ⇒ 本用例必红。
    """
    seed()
    assert client.post(
        "/api/v1/workforce/agents/a-owner/shares",
        headers=headers(user_id="u-owner"),
        json={"grantee_user_id": "u-read", "permission": "read"},
    ).status_code == 201
    assert client.post(
        "/api/v1/workforce/agents/a-owner/shares",
        headers=headers(user_id="u-owner"),
        json={"grantee_user_id": "u-use", "permission": "use"},
    ).status_code == 201

    def dispatch(user_id: str) -> int:
        return client.post(
            "/api/v1/tasks",
            headers=headers(user_id=user_id),
            json={
                "title": "派活",
                "employee_key": "a-owner",
                "risk_level": "low",
                "budget": 0,
                "idempotency_key": f"dispatch-{user_id}",
            },
        ).status_code

    assert dispatch("u-owner") == 201, "归属人可派活"
    assert dispatch("u-use") == 201, "`use` 档可派活"
    assert dispatch("u-read") == 403, "`read` 档不得派活"
    assert dispatch("u-other") == 403, "零共享同事不得派活他人的纳管员工"


def test_roster_does_not_leak_other_peoples_employee_keys() -> None:
    """**A2 / A9 反假（读路径）**（2026-09-24 修复）：`roster` 的任务计数子源必须过 owner ∪ shares。

    此前 `counts = store.count_by_employee(tenant_id)` 是**租户级全量** ⇒ 任意登录身份都能拿到
    本租户全部员工标识 + 任务数（含只出现在**他人任务**里、目录中并不存在的键）。
    反假：把 `workforce_roster` 里的 `visible` 过滤注释掉 ⇒ 本用例必红。
    """
    seed()
    # 归属人：用自己的纳管员工建任务
    assert client.post(
        "/api/v1/tasks",
        headers=headers(user_id="u-owner"),
        json={
            "title": "甲的任务",
            "employee_key": "a-owner",
            "risk_level": "low",
            "budget": 0,
            "idempotency_key": "roster-leak-owner",
        },
    ).status_code == 201
    # 超管：建一个**未纳管**的键（只出现在任务里 —— 正是 admin-only 的 /candidates 所保护的数据）
    assert client.post(
        "/api/v1/tasks",
        headers=admin_headers(),
        json={
            "title": "超管的任务",
            "employee_key": "ghost-unmanaged-key",
            "risk_level": "low",
            "budget": 0,
            "idempotency_key": "roster-leak-admin",
        },
    ).status_code == 201

    theirs = client.get("/api/v1/workforce/roster", headers=headers(user_id="u-other")).json()
    assert theirs["items"] == [], "roster 不得把本租户全量员工标识与任务数发给无关身份"

    mine = client.get("/api/v1/workforce/roster", headers=headers(user_id="u-owner")).json()
    assert [(item["key"], item["task_count"]) for item in mine["items"]] == [("a-owner", 1)]

    # 超管：管理视角，仍看得到全部三源并集（回归护栏）
    admin = client.get("/api/v1/workforce/roster", headers=admin_headers()).json()
    assert {item["key"] for item in admin["items"]} == {"a-owner", "ghost-unmanaged-key"}


# --------------------------------------------------------------------------- A7


def test_route_layer_and_store_layer_agree() -> None:
    """**A7 · 两层同口径**：同一角色在**路由层**与**仓储层**必须得到同一结论。

    现状两层都写死 `super_admin`，所以「一致」是巧合；拆闸门后若只改一层，
    会出现「接口放行、仓储拒绝」或反之 —— 本用例专门防这个。
    """
    store = InMemoryWorkforceDirectoryStore()

    # 仓储层：普通员工读列表 —— 拆闸门后**不应**再抛 PolicyError
    try:
        store.list_employees(OWNER)
    except PolicyError as exc:  # pragma: no cover - 实现前必走这里
        pytest.fail(f"仓储层仍拒绝普通员工读列表，与路由层口径不一致：{exc}")
    except TypeError:
        # 方法签名尚未支持过滤参数 ⇒ 实现前同样算红
        pytest.fail("list_employees 尚未支持按 owner ∪ shares 过滤")


# --------------------------------------------------------------------------- A8


def test_admin_only_gates_stay_untouched() -> None:
    """**A8**：本批**不放宽**的方法，权限**逐字不变** —— 防止"顺手改宽"。"""
    for role in ("employee", "department_lead", "ceo", "customer_admin"):
        # 建岗位：仍仅超管
        created = client.post(
            "/api/v1/workforce/roles",
            headers=headers(role=role, user_id=f"u-{role}"),
            json={"role_key": f"r-{role}", "name": "岗"},
        )
        assert created.status_code == 403
        assert created.json()["detail"] == DIRECTORY_ADMIN_MESSAGE

        # 候选清单：跨模块只读方法（V3=A 不动）
        assert client.get(
            "/api/v1/workforce/candidates", headers=headers(role=role, user_id=f"u-{role}")
        ).status_code == 403


def test_super_admin_behavior_unchanged() -> None:
    """**A8 续**：超管的行为**零变化**（回归护栏）。"""
    seed()

    assert client.get("/api/v1/workforce/roles", headers=admin_headers()).status_code == 200
    assert client.get("/api/v1/workforce/agents", headers=admin_headers()).status_code == 200
    assert client.get("/api/v1/workforce/roster", headers=admin_headers()).status_code == 200
    assert client.get("/api/v1/workforce/candidates", headers=admin_headers()).status_code == 200


# --------------------------------------------------------------------------- A10


def test_read_path_does_not_leak_others_secrets() -> None:
    """**A10**：放开的读路径**不得**把他人提示词 / 模型 / 预算落进响应或审计明细。"""
    seed()
    # 给该员工配一段可识别的提示词
    assert client.patch(
        "/api/v1/workforce/agents/a-owner/config",
        headers=admin_headers(),
        json={"system_prompt": "SECRET-PROMPT-MARKER"},
    ).status_code == 200

    body = client.get("/api/v1/workforce/agents", headers=headers(user_id="u-other")).text

    assert "SECRET-PROMPT-MARKER" not in body, "普通员工的目录读响应不得含他人提示词"
