"""绑定面接口（第 9 轮）：**新增读端点 + 工具面门禁 + 边界如实钉住**。

覆盖口径（见 `docs/contracts/skill-bindings-api.md` §1/§2/§6/§7）：

- **新增 `GET /api/v1/skills/bindings`**：形状（`{items,total,limit,offset}`，条目键**不含 `tenant_id`**）、
  过滤（`agent_key` / `skill_key`）、分页（`limit` 1–200、`offset`）、未认证 `401`；
- **角色门禁（安全要件，§7）**：仅 `super_admin` ⇒ 其余四角色一律 `403`。
  为什么必须单独钉：`SkillService.list_bindings` 在读路径上**零角色判定**（仓储只按租户过滤）
  ⇒ 路由/服务少一处 `ensure_can_bind`，任何登录角色都能读到本租户全部绑定关系；
- **`tools` 端点门禁（2026-09-20 真机复测抓到的新缺口）**：实测四角色**全放行**（含 `customer_admin`），
  与矩阵 §3「技能域末列 `customer_admin` ❌」不符 ⇒ 本轮修：四个业务角色可读、`customer_admin` `403`；
- **边界如实钉住（§2 三条服务端事实）**：`bind` 不校验技能存在 / 是否 `enabled` / 员工键是否在目录
  ⇒ 均返回 `200`（可写入悬空绑定）。**这些用例钉的是"当前事实"，不是"期望行为"**：
  一旦将来补上闸门，它们会变红，从而**强制**同步契约与决策日志（不允许静默漂移）；
- **解绑边界**：不存在的绑定 ⇒ `404`（更正第 8 轮备注"未区分"的误读）；已 `disabled` ⇒ `200` 幂等。
"""

from __future__ import annotations

import hashlib

import pytest
from fastapi.testclient import TestClient

from app import main
from app.audit.service import AuditService
from app.audit.store import InMemoryAuditStore
from app.skills.service import SkillService
from app.skills.store import InMemorySkillStore
from app.skills.validator import SkillPackageValidator
from app.tool_execution.catalog import build_tool_spec_catalog

client = TestClient(main.app)

TENANT = "t-bindings"
SOURCE = "manual"
BODY = "# 绑定探针技能\n\n用于核对绑定面接口。"
BINDINGS = "/api/v1/skills/bindings"
'''矩阵 §3「技能」两行的角色档位。'''
ROLE_SUPER = "super_admin"
MANAGE_ROLES = ("ceo", ROLE_SUPER)
OTHER_ROLES = ("employee", "department_lead", "customer_admin")
AGENT = "agent-probe"


def headers(role: str = ROLE_SUPER, user_id: str | None = None, tenant_id: str = TENANT) -> dict[str, str]:
    return {
        "X-Tenant-Id": tenant_id,
        "X-User-Id": user_id or f"acct-{role}",
        "X-User-Role": role,
    }


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@pytest.fixture(autouse=True)
def skills_service(monkeypatch) -> SkillService:
    """内存技能服务（与生产装配同参：来源白名单 + 真实工具目录键集）。"""
    service = SkillService(
        InMemorySkillStore(),
        SkillPackageValidator(),
        allowed_sources=frozenset({SOURCE}),
        catalog_tool_keys=frozenset(spec.key for spec in build_tool_spec_catalog().specs),
        audit=AuditService(InMemoryAuditStore()),
    )
    monkeypatch.setattr(main, "skills_service", service)
    return service


# ------------------------------------------------------------ 目录侧前置（第 12 轮 ③A：绑定要求员工已纳管）

WORKFORCE_ROLES = "/api/v1/workforce/roles"
WORKFORCE_AGENTS = "/api/v1/workforce/agents"
ROLE_DIR = "bind-ops"
# 本文件用到的全部数字员工键（列表 / 分页用例会用 `agent-0/1/2`）。
MANAGED_AGENTS = (AGENT, "agent-0", "agent-1", "agent-2")


@pytest.fixture(autouse=True)
def managed_directory() -> None:
    """把本文件用到的数字员工键全部纳管（岗位 + 员工均 `active`）。

    `bind` 自第 12 轮起要求 `agent_key` 已在数字员工目录内且启用（专项方案 §11 裁决 ③A）；
    本文件的用例考的是**绑定面接口**（视图 / 分页 / 权限 / 审计），故缺省把这些键纳管，
    目录闸门自身的用例见 `tests/test_skill_binding_gates.py`。
    """
    role_status = client.post(
        WORKFORCE_ROLES, json={"role_key": ROLE_DIR, "name": "绑定面岗位"}, headers=headers()
    ).status_code
    assert role_status in (201, 409), role_status
    for agent_key in MANAGED_AGENTS:
        agent_status = client.post(
            WORKFORCE_AGENTS,
            json={"agent_key": agent_key, "name": "绑定面员工", "role_key": ROLE_DIR},
            headers=headers(),
        ).status_code
        assert agent_status in (201, 409), (agent_key, agent_status)


def _submit(key: str, *, role: str = "employee", version: str = "1.0.0", tools: list[str] | None = None):
    return client.post(
        "/api/v1/skills",
        json={
            "skill_key": key,
            "version": version,
            "name": "绑定探针技能",
            "description": "用于核对绑定面接口",
            "license": "Apache-2.0",
            "allowed_tools": tools or ["fs.read"],
            "source_key": SOURCE,
            "content_sha256": _sha256(BODY),
            "content_body": BODY,
        },
        headers=headers(role),
    )


def _enable(key: str, version: str = "1.0.0") -> None:
    """走完 提交 → 审核 → 启用（审核人用非提交人的管理角色）。"""
    assert _submit(key).status_code == 201
    assert client.post(
        f"/api/v1/skills/{key}/versions/{version}/review", params={"approved": "true"}, headers=headers("ceo")
    ).status_code == 200
    assert client.post(
        f"/api/v1/skills/{key}/versions/{version}/enable", headers=headers(ROLE_SUPER)
    ).status_code == 200


# ------------------------------------------------------------ 新增读端点：形状与分页


def test_bindings_list_shape_has_no_tenant_id(skills_service) -> None:
    """列表形状逐键：`{items,total,limit,offset}`；条目为绑定视图且**不含 `tenant_id`**。"""
    _enable("bind-shape")
    assert client.post(BINDINGS, json={"skill_key": "bind-shape", "agent_key": AGENT}, headers=headers()).status_code == 200

    response = client.get(BINDINGS, headers=headers())

    assert response.status_code == 200, response.text
    body = response.json()
    assert sorted(body.keys()) == ["items", "limit", "offset", "total"]
    assert body["total"] == 1 and body["limit"] == 50 and body["offset"] == 0
    item = body["items"][0]
    assert sorted(item.keys()) == ["agent_key", "created_at", "created_by", "skill_key", "status"]
    assert item["skill_key"] == "bind-shape"
    assert item["agent_key"] == AGENT
    assert item["status"] == "active"
    assert item["created_by"] == f"acct-{ROLE_SUPER}"
    assert "tenant_id" not in item


def test_bindings_list_filters_by_agent_and_skill(skills_service) -> None:
    """`agent_key` / `skill_key` 过滤逐条生效（组合时取交集）。"""
    _enable("bind-a")
    _enable("bind-b")
    client.post(BINDINGS, json={"skill_key": "bind-a", "agent_key": "agent-1"}, headers=headers())
    client.post(BINDINGS, json={"skill_key": "bind-a", "agent_key": "agent-2"}, headers=headers())
    client.post(BINDINGS, json={"skill_key": "bind-b", "agent_key": "agent-2"}, headers=headers())

    by_agent = client.get(BINDINGS, params={"agent_key": "agent-2"}, headers=headers()).json()
    by_skill = client.get(BINDINGS, params={"skill_key": "bind-a"}, headers=headers()).json()
    both = client.get(BINDINGS, params={"agent_key": "agent-2", "skill_key": "bind-a"}, headers=headers()).json()

    assert by_agent["total"] == 2
    assert sorted(item["skill_key"] for item in by_agent["items"]) == ["bind-a", "bind-b"]
    assert by_skill["total"] == 2
    assert both["total"] == 1
    assert both["items"][0]["agent_key"] == "agent-2"
    assert both["items"][0]["skill_key"] == "bind-a"


def test_bindings_list_paginates_and_validates_bounds(skills_service) -> None:
    """分页：`limit` / `offset` 原样回显；越界 `limit` ⇒ `422`（`detail` 是数组 ⇒ 前端回落固定文案）。"""
    _enable("bind-page")
    for index in range(3):
        client.post(BINDINGS, json={"skill_key": "bind-page", "agent_key": f"agent-{index}"}, headers=headers())

    page = client.get(BINDINGS, params={"limit": 2, "offset": 1}, headers=headers())

    assert page.status_code == 200, page.text
    body = page.json()
    assert body["limit"] == 2 and body["offset"] == 1
    assert body["total"] == 3
    assert len(body["items"]) == 2
    too_big = client.get(BINDINGS, params={"limit": 201}, headers=headers())
    assert too_big.status_code == 422
    assert isinstance(too_big.json()["detail"], list)


def test_bindings_list_requires_authentication() -> None:
    """未认证 ⇒ `401`（不得泄露"有没有绑定"）。"""
    response = client.get(BINDINGS)

    assert response.status_code == 401


# ------------------------------------------------------------ 角色门禁（安全要件 §7）


@pytest.mark.parametrize("role", ("ceo", "department_lead", "employee", "customer_admin"))
def test_bindings_list_forbidden_for_non_super_admin(skills_service, role: str) -> None:
    """**安全要件**：只有 `super_admin` 可读绑定关系；其余四角色一律 `403`（含 `ceo`）。

    依据：矩阵 §3 未列「绑定」行 ⇒ 沿用原口径（`BIND_ROLES` = `{super_admin}`，第 8 轮 D-026 已裁决
    "绑定口径不随复核对齐放开"）。去掉 `ensure_can_bind` ⇒ 本用例必红（反假锚点）。
    """
    _enable("bind-gate")
    client.post(BINDINGS, json={"skill_key": "bind-gate", "agent_key": AGENT}, headers=headers())

    response = client.get(BINDINGS, headers=headers(role=role))

    assert response.status_code == 403, response.text
    assert response.json()["detail"] == "只有超级管理员可以绑定或解绑技能"


def test_bindings_list_service_layer_is_fail_closed(skills_service) -> None:
    """服务层同样 fail-closed（不只靠路由）：直接调服务、传 `employee` ⇒ `PolicyError`。

    为什么两层都要判：`list_bindings` 原来只转发仓储（零判定），今后任何新调用方（worker / 脚本）
    都不会因"忘了在路由加闸门"而裸奔。
    """
    from app.domain import PolicyError, UserContext

    with pytest.raises(PolicyError):
        skills_service.list_bindings(UserContext(TENANT, "acct-employee", "employee"))


# ------------------------------------------------------------ 工具面门禁（本轮修复的新缺口）


def test_agent_tools_allowed_for_four_business_roles(skills_service) -> None:
    """四个业务角色均可读工具面（保持既有能力，不新收紧）。"""
    _enable("bind-tools")
    client.post(BINDINGS, json={"skill_key": "bind-tools", "agent_key": AGENT}, headers=headers())

    for role in ("employee", "department_lead", "ceo", ROLE_SUPER):
        response = client.get(f"/api/v1/skills/agents/{AGENT}/tools", headers=headers(role=role))
        assert response.status_code == 200, (role, response.text)
        assert response.json() == {"agent_key": AGENT, "tools": ["fs.read"]}


def test_agent_tools_forbidden_for_customer_admin(skills_service) -> None:
    """`customer_admin` ⇒ `403`（矩阵 §3 末列「技能域一律 ❌」；真机复测前该端点对其放行）。"""
    _enable("bind-tools-deny")

    response = client.get(f"/api/v1/skills/agents/{AGENT}/tools", headers=headers(role="customer_admin"))

    assert response.status_code == 403, response.text
    assert response.json()["detail"] == "当前岗位不能查看数字员工的工具面"


def test_agent_tools_service_layer_is_fail_closed(skills_service) -> None:
    """服务层同样 fail-closed：直接调 `expanded_tools_for_agent`、传 `customer_admin` ⇒ `PolicyError`。"""
    from app.domain import PolicyError, UserContext

    with pytest.raises(PolicyError):
        skills_service.expanded_tools_for_agent(UserContext(TENANT, "acct-customer", "customer_admin"), AGENT)


# ------------------------------------------------------------ 解绑边界（更正第 8 轮备注）


def test_unbind_missing_binding_returns_404(skills_service) -> None:
    """不存在的绑定 ⇒ `404`（源码判定：内存与 PG 两条实现一致）。

    更正：第 8 轮契约 §6 备注曾写「`unbind` 实测 `200`（对不存在的绑定也返回 `disabled`，未区分）」——
    本轮真机复测 `DELETE …?skill_key=r9-nope&agent_key=agent-nope` ⇒ **`404`** `{"detail":"binding …"}`
    ⇒ 那条 `200` 是**绑定行确实存在**（旧 `bind` 500 缺陷在序列化前已写入），原备注为**误读**。
    """
    response = client.delete(BINDINGS, params={"skill_key": "nope", "agent_key": "nope"}, headers=headers())

    assert response.status_code == 404, response.text
    assert response.json()["detail"] == "binding nope/nope"


def test_unbind_is_idempotent_for_disabled_binding(skills_service) -> None:
    """已 `disabled` 的绑定再解 ⇒ `200`（幂等，原样返回）。"""
    _enable("bind-idem")
    client.post(BINDINGS, json={"skill_key": "bind-idem", "agent_key": AGENT}, headers=headers())

    first = client.delete(BINDINGS, params={"skill_key": "bind-idem", "agent_key": AGENT}, headers=headers())
    second = client.delete(BINDINGS, params={"skill_key": "bind-idem", "agent_key": AGENT}, headers=headers())

    assert first.status_code == 200 and second.status_code == 200, (first.text, second.text)
    assert first.json() == second.json() == {"skill_key": "bind-idem", "agent_key": AGENT, "status": "disabled"}


# ------------------------------------------------------------ 绑定闸门（第 11 轮落地；原"已知缺口"用例已翻转）


def test_bind_rejects_nonexistent_skill(skills_service) -> None:
    """**第 11 轮闸门（已落地）**：`bind` 不存在的技能 ⇒ `404`，不再写入悬空绑定。

    本用例原为 `test_bind_accepts_nonexistent_skill_known_gap`（钉住旧事实、并写明"将来补闸门时应改为断言被拒"）——
    第 11 轮专项按该约定翻转。逐条闸门细节见 `tests/test_skill_binding_gates.py`。
    """
    response = client.post(BINDINGS, json={"skill_key": "ghost-skill", "agent_key": AGENT}, headers=headers())

    assert response.status_code == 404, response.text
    listed = client.get(BINDINGS, params={"skill_key": "ghost-skill"}, headers=headers()).json()
    assert listed["total"] == 0  # 悬空绑定不再产生


def test_bind_rejects_not_enabled_skill(skills_service) -> None:
    """**第 11 轮闸门（已落地）**：`submitted` 技能不可绑定 ⇒ `409`（工具面本就 fail-closed，现连绑定也收口）。"""
    assert _submit("bind-submitted").status_code == 201  # 停在 submitted

    bound = client.post(BINDINGS, json={"skill_key": "bind-submitted", "agent_key": AGENT}, headers=headers())

    assert bound.status_code == 409, bound.text
    assert bound.json()["detail"] == "只有已启用的技能包可以绑定"


def test_bind_rejects_agent_key_outside_directory(skills_service) -> None:
    """**第 ③ 条闸门（第 12 轮落地）**：员工键不在数字员工目录 ⇒ `409`（原先 `200`，可写"幽灵员工"绑定）。

    第 9 轮曾裁决"员工键可手动录入"并因此暂缓该闸门；第 12 轮用户按专项方案 §11 裁决 **③A**
    （加闸门 + 界面取消手动录入）⇒ 本用例由「钉住暂缓」**翻转为断言被拒**（与上两条同一手法）。
    """
    _enable("bind-outside")

    response = client.post(
        BINDINGS, json={"skill_key": "bind-outside", "agent_key": "agent-not-in-directory"}, headers=headers()
    )

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "该标识尚未纳入目录，请先在「数字员工设置」中纳管"


# ------------------------------------------------------------ 审计留痕


def test_bind_and_unbind_are_audited_with_agent_key_detail(skills_service) -> None:
    """绑定 / 解绑各有审计（复用 `skill.enabled` / `skill.disabled` 动作码，靠 `detail` 区分）。"""
    _enable("bind-audit")
    client.post(BINDINGS, json={"skill_key": "bind-audit", "agent_key": AGENT}, headers=headers())
    client.delete(BINDINGS, params={"skill_key": "bind-audit", "agent_key": AGENT}, headers=headers())

    records = [
        item
        for item in skills_service.audit.store.list_recent(TENANT)
        if item.detail.get("agent_key") == AGENT
    ]
    actions = [item.action.value for item in records]
    assert "skill.enabled" in actions  # 绑定（复用动作码）
    assert "skill.disabled" in actions  # 解绑（复用动作码）