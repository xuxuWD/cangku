"""技能绑定闸门（第 11 轮建立 · 第 12 轮补齐第 ③ 条）。

背景（第 9 轮真机实测登记 + 第 11/12 轮复核）：`POST /api/v1/skills/bindings` 原先**三条校验全缺**——
① 技能不存在也 `200`（写入**悬空绑定**）；② 技能 `submitted` / `disabled` 也能绑；③ 员工键不在目录也能绑。

- **第 11 轮**：落地**域内两条**（技能存在 ⇒ `404`；技能已启用 ⇒ `409`），第 ③ 条按用户裁决暂缓；
- **第 12 轮**（用户按专项方案 §11 裁决 **③A / ④A / ⑥A / ⑦维持**）：补齐
  - **③ 员工必须已纳管且启用**（**路由层**闸门，复用 `ensure_agent_binding_available`）⇒ `409`；
  - **④ `agent_key` 归一化 + 字符集校验**（与目录域同一份 `normalize_key`）⇒ 非法 `422`；
  - **⑥ 幂等调用不重复写审计**（仅"新建 / 状态翻转"时写）；
  - ⑦ 维持"闸门先于幂等判定"（技能停用后重复 `bind` 仍 `409`）。

**判定顺序**：权限优先（越权 ⇒ `403`，不泄露任何存在性）→ 标识合法性（`422`）→ 技能存在（`404`）
→ 技能已启用（`409`）→ 员工已纳管（`409`）。

**反假锚点**：去掉 `list_versions` 存在性判定 ⇒ 用例「技能不存在」必红；去掉 enabled 判定 ⇒ 「未启用」必红；
去掉路由层目录闸门 ⇒ 「未纳管」必红；去掉 `normalize_key` ⇒ 「非法标识」与「归一化」必红；
去掉审计收敛的前置读取 ⇒ 「幂等不重复写审计」必红。
"""

from __future__ import annotations

import hashlib

import pytest
from fastapi.testclient import TestClient

from app import main
from app.audit.service import AuditService
from app.audit.store import InMemoryAuditStore
from app.domain import PolicyError, UserContext
from app.skills.models import SkillNotFound, SkillStateConflict
from app.skills.service import SkillService
from app.skills.store import InMemorySkillStore
from app.skills.validator import SkillPackageValidator
from app.tool_execution.catalog import build_tool_spec_catalog

client = TestClient(main.app)

TENANT = "t-bind-gates"
SOURCE = "manual"
BODY = "# 绑定闸门探针\n\n用于核对绑定闸门。"
BINDINGS = "/api/v1/skills/bindings"
AGENT = "agent-gate"
ROLE = "gate-ops"
# 「员工被停用」「岗位被停用」两例各用**独立**岗位 / 员工：内存目录是进程级单例，
# 若用同一个岗位去停用，会连带把后续用例的 AGENT 一起变成不可用（用例间互相污染）。
AGENT_OFF = "agent-gate-off"
ROLE_OFF = "gate-ops-off"
AGENT_ROLE_OFF = "agent-gate-role-off"
UNMANAGED = "agent-not-in-directory"

WORKFORCE_ROLES = "/api/v1/workforce/roles"
WORKFORCE_AGENTS = "/api/v1/workforce/agents"


def headers(role: str = "super_admin", user_id: str | None = None, tenant_id: str = TENANT) -> dict[str, str]:
    return {"X-Tenant-Id": tenant_id, "X-User-Id": user_id or f"acct-{role}", "X-User-Role": role}


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@pytest.fixture(autouse=True)
def skills_service(monkeypatch) -> SkillService:
    service = SkillService(
        InMemorySkillStore(),
        SkillPackageValidator(),
        allowed_sources=frozenset({SOURCE}),
        catalog_tool_keys=frozenset(spec.key for spec in build_tool_spec_catalog().specs),
        audit=AuditService(InMemoryAuditStore()),
    )
    monkeypatch.setattr(main, "skills_service", service)
    return service


# ------------------------------------------------------------ 目录侧辅助（第 12 轮）


def _ensure_role(role_key: str) -> None:
    """建岗位（幂等：已存在 ⇒ `409` 视为成功）。"""
    status = client.post(
        WORKFORCE_ROLES, json={"role_key": role_key, "name": "闸门岗位"}, headers=headers()
    ).status_code
    assert status in (201, 409), status


def _ensure_agent(agent_key: str, role_key: str = ROLE) -> None:
    """纳管数字员工（幂等：已存在 ⇒ `409` 视为成功）。"""
    _ensure_role(role_key)
    status = client.post(
        WORKFORCE_AGENTS,
        json={"agent_key": agent_key, "name": "闸门员工", "role_key": role_key},
        headers=headers(),
    ).status_code
    assert status in (201, 409), status


@pytest.fixture(autouse=True)
def managed_directory() -> None:
    """把 `AGENT` 纳管（岗位 + 员工均 `active`）。

    多数用例考的是**技能侧**闸门（404 / 409）与幂等 / 审计，不应被目录闸门挡住 ⇒ 缺省把 `AGENT` 纳管。
    目录闸门自身的用例用 `UNMANAGED` 或不纳管的键。
    """
    _ensure_agent(AGENT)



def _submit(key: str, *, content: str = BODY) -> str:
    """提交一个技能包，返回其正文（供指纹一致）。"""
    assert (
        client.post(
            "/api/v1/skills",
            json={
                "skill_key": key,
                "version": "1.0.0",
                "name": "绑定闸门探针",
                "description": "用于核对绑定闸门",
                "license": "Apache-2.0",
                "allowed_tools": ["fs.read"],
                "source_key": SOURCE,
                "content_sha256": _sha256(content),
                "content_body": content,
            },
            headers=headers("employee"),
        ).status_code
        == 201
    )
    return content


def _review(key: str) -> None:
    assert (
        client.post(
            f"/api/v1/skills/{key}/versions/1.0.0/review", params={"approved": "true"}, headers=headers("ceo")
        ).status_code
        == 200
    )


def _enable(key: str) -> None:
    _submit(key)
    _review(key)
    assert client.post(f"/api/v1/skills/{key}/versions/1.0.0/enable", headers=headers()).status_code == 200


def _disable(key: str) -> None:
    assert client.post(f"/api/v1/skills/{key}/versions/1.0.0/disable", headers=headers()).status_code == 200


# ------------------------------------------------------------ 闸门一：技能必须存在（404）


def test_bind_rejects_nonexistent_skill(skills_service) -> None:
    """技能不存在 ⇒ `404`（不写入任何绑定行）。"""
    response = client.post(BINDINGS, json={"skill_key": "ghost-skill", "agent_key": AGENT}, headers=headers())

    assert response.status_code == 404, response.text
    assert client.get(BINDINGS, headers=headers()).json()["total"] == 0


def test_bind_rejects_nonexistent_skill_at_service_layer(skills_service) -> None:
    """域层同样 fail-closed（不只靠路由/界面）：直接调服务 ⇒ `SkillNotFound`。"""
    with pytest.raises(SkillNotFound):
        skills_service.bind_skill(UserContext(TENANT, "acct-admin", "super_admin"), AGENT, "ghost-skill")


# ------------------------------------------------------------ 闸门二：技能必须已启用（409）


def test_bind_rejects_submitted_skill(skills_service) -> None:
    """`submitted`（未审核未启用）⇒ `409`「只有已启用的技能包可以绑定」。"""
    _submit("gate-submitted")

    response = client.post(BINDINGS, json={"skill_key": "gate-submitted", "agent_key": AGENT}, headers=headers())

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "只有已启用的技能包可以绑定"


def test_bind_rejects_disabled_skill(skills_service) -> None:
    """`disabled`（曾启用后停用）⇒ `409`（同样不可绑定）。"""
    _enable("gate-disabled")
    _disable("gate-disabled")

    response = client.post(BINDINGS, json={"skill_key": "gate-disabled", "agent_key": AGENT}, headers=headers())

    assert response.status_code == 409, response.text


def test_bind_rejects_approved_but_not_enabled_skill(skills_service) -> None:
    """`approved`（已审核未启用）⇒ `409`（"已审核"不等于"已启用"）。"""
    _submit("gate-approved")
    _review("gate-approved")

    response = client.post(BINDINGS, json={"skill_key": "gate-approved", "agent_key": AGENT}, headers=headers())

    assert response.status_code == 409, response.text


def test_bind_rejects_not_enabled_skill_at_service_layer(skills_service) -> None:
    """域层同样 fail-closed：直接调服务绑 `submitted` 技能 ⇒ `SkillStateConflict`。"""
    _submit("gate-service")
    with pytest.raises(SkillStateConflict):
        skills_service.bind_skill(UserContext(TENANT, "acct-admin", "super_admin"), AGENT, "gate-service")


# ------------------------------------------------------------ 正向路径与幂等（不得误伤）


def test_bind_enabled_skill_succeeds(skills_service) -> None:
    """已启用技能 ⇒ `200` + 绑定形状（正向路径不受新闸门影响）。"""
    _enable("gate-ok")

    response = client.post(BINDINGS, json={"skill_key": "gate-ok", "agent_key": AGENT}, headers=headers())

    assert response.status_code == 200, response.text
    assert response.json() == {"skill_key": "gate-ok", "agent_key": AGENT, "status": "active"}
    expanded = client.get(f"/api/v1/skills/agents/{AGENT}/tools", headers=headers())
    assert expanded.json() == {"agent_key": AGENT, "tools": ["fs.read"]}


def test_rebind_active_pair_is_idempotent(skills_service) -> None:
    """已 `active` 的同一对重复绑定 ⇒ 仍 `200`（幂等语义不变）。"""
    _enable("gate-idem")
    first = client.post(BINDINGS, json={"skill_key": "gate-idem", "agent_key": AGENT}, headers=headers())
    second = client.post(BINDINGS, json={"skill_key": "gate-idem", "agent_key": AGENT}, headers=headers())

    assert first.status_code == 200 and second.status_code == 200, (first.text, second.text)
    assert first.json() == second.json()


def test_rebind_after_skill_disabled_is_rejected(skills_service) -> None:
    """**行为变化（须显式登记）**：绑定后技能被停用 ⇒ 再 `bind` 同一对 ⇒ `409`（而非继续 200）。

    闸门**先于**幂等判定：这样"已存在的绑定"不会成为绕过闸门的后门。
    """
    _enable("gate-then-disable")
    assert client.post(BINDINGS, json={"skill_key": "gate-then-disable", "agent_key": AGENT}, headers=headers()).status_code == 200
    _disable("gate-then-disable")

    response = client.post(BINDINGS, json={"skill_key": "gate-then-disable", "agent_key": AGENT}, headers=headers())

    assert response.status_code == 409, response.text


# ------------------------------------------------------------ 权限优先 + 解绑通道 + 审计


def test_permission_check_wins_over_existence(skills_service) -> None:
    """越权者绑**不存在**的技能 ⇒ `403`（不是 `404`）⇒ 不通过错误码探测技能是否存在。"""
    response = client.post(
        BINDINGS,
        json={"skill_key": "ghost-skill", "agent_key": AGENT},
        headers=headers("employee", user_id="acct-employee"),
    )

    assert response.status_code == 403, response.text
    assert response.json()["detail"] == "只有超级管理员可以绑定或解绑技能"


def test_unbind_still_works_for_rows_that_now_violate_gates(skills_service) -> None:
    """**清理通道必须保留**：对"技能此后被停用"的历史绑定行，`unbind` 仍 `200`（解绑不校验技能状态）。

    否则脏数据将无法清理（且解绑是唯一的回收动作）。
    """
    _enable("gate-legacy")
    assert client.post(BINDINGS, json={"skill_key": "gate-legacy", "agent_key": AGENT}, headers=headers()).status_code == 200
    _disable("gate-legacy")

    response = client.delete(BINDINGS, params={"skill_key": "gate-legacy", "agent_key": AGENT}, headers=headers())

    assert response.status_code == 200, response.text
    assert response.json() == {"skill_key": "gate-legacy", "agent_key": AGENT, "status": "disabled"}


def test_rejected_bind_writes_no_audit(skills_service) -> None:
    """被拒的绑定**不写审计**（与既有 4xx 口径一致）：审计只记录真正发生的动作。"""
    _submit("gate-audit")

    assert client.post(BINDINGS, json={"skill_key": "gate-audit", "agent_key": AGENT}, headers=headers()).status_code == 409
    records = [
        item for item in skills_service.audit.store.list_recent(TENANT) if item.detail.get("agent_key") == AGENT
    ]
    assert records == []


# ------------------------------------------------------------ 闸门三：员工必须已纳管且启用（409，第 12 轮）


def test_bind_rejects_unmanaged_agent_key(skills_service) -> None:
    """**第 12 轮 ③A 落地**：员工键不在数字员工目录 ⇒ `409`（原先 `200`，可写"幽灵员工"绑定）。

    文案沿用目录域既有口径（与知识范围写路径闸门同一条），`detail` 里给出纳管去处。
    """
    _enable("gate-outside-dir-2")

    response = client.post(
        BINDINGS, json={"skill_key": "gate-outside-dir-2", "agent_key": UNMANAGED}, headers=headers()
    )

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "该标识尚未纳入目录，请先在「数字员工设置」中纳管"
    # 被拒不写任何行、不写审计
    assert client.get(BINDINGS, params={"agent_key": UNMANAGED}, headers=headers()).json()["total"] == 0
    assert [i for i in skills_service.audit.store.list_recent(TENANT) if i.detail.get("agent_key") == UNMANAGED] == []


def test_bind_rejects_disabled_employee(skills_service) -> None:
    """员工被**停用** ⇒ `409`（`agent_is_active` 的口径：员工自身须 `active`）。"""
    _ensure_agent(AGENT_OFF)
    assert (
        client.patch(f"{WORKFORCE_AGENTS}/{AGENT_OFF}", json={"status": "disabled"}, headers=headers()).status_code
        == 200
    )
    _enable("gate-off-employee")

    response = client.post(
        BINDINGS, json={"skill_key": "gate-off-employee", "agent_key": AGENT_OFF}, headers=headers()
    )

    assert response.status_code == 409, response.text


def test_bind_rejects_agent_whose_role_disabled(skills_service) -> None:
    """员工所在**岗位**被停用 ⇒ 连带 `409`（岗位停用约束其员工）。"""
    _ensure_agent(AGENT_ROLE_OFF, role_key=ROLE_OFF)
    assert (
        client.patch(f"{WORKFORCE_ROLES}/{ROLE_OFF}", json={"status": "disabled"}, headers=headers()).status_code
        == 200
    )
    _enable("gate-off-role")

    response = client.post(
        BINDINGS, json={"skill_key": "gate-off-role", "agent_key": AGENT_ROLE_OFF}, headers=headers()
    )

    assert response.status_code == 409, response.text


def test_bind_accepts_managed_active_agent(skills_service) -> None:
    """正向路径：员工**已纳管且启用** + 技能已启用 ⇒ `200`（不误伤）。

    注：`managed_directory` 夹具已把 `AGENT` 纳管，故其余用例同样跑在"已纳管"前提上；
    本用例显式核对"目录闸门不会挡住合法绑定"。
    """
    _enable("gate-managed")

    response = client.post(BINDINGS, json={"skill_key": "gate-managed", "agent_key": AGENT}, headers=headers())

    assert response.status_code == 200, response.text
    assert response.json() == {"skill_key": "gate-managed", "agent_key": AGENT, "status": "active"}


# ------------------------------------------------------------ 键归一化与字符集（422，第 12 轮 ④A）


def test_bind_normalizes_agent_key(skills_service) -> None:
    """`" Agent-Gate "` / `"AGENT-GATE"` 归一化后与 `agent-gate` **同一行**（幂等命中，不新增行）。"""
    _enable("gate-normalize")

    first = client.post(
        BINDINGS, json={"skill_key": "gate-normalize", "agent_key": f"  {AGENT.upper()}  "}, headers=headers()
    )
    second = client.post(
        BINDINGS, json={"skill_key": "gate-normalize", "agent_key": AGENT.upper()}, headers=headers()
    )

    assert first.status_code == 200, first.text
    assert first.json() == {"skill_key": "gate-normalize", "agent_key": AGENT, "status": "active"}
    assert second.status_code == 200, second.text
    # 归一化后是同一对 ⇒ 只有一行
    listed = client.get(BINDINGS, params={"skill_key": "gate-normalize"}, headers=headers()).json()
    assert listed["total"] == 1
    assert listed["items"][0]["agent_key"] == AGENT


def test_bind_rejects_illegal_agent_key(skills_service) -> None:
    """非法标识（空格 / 大写以外还含其它字符）⇒ `422`（与目录域 `normalize_key` 同一份校验）。"""
    _enable("gate-illegal")

    response = client.post(
        BINDINGS, json={"skill_key": "gate-illegal", "agent_key": "bad key!"}, headers=headers()
    )

    assert response.status_code == 422, response.text
    assert "只能包含" in response.json()["detail"]


def test_unbind_normalizes_agent_key(skills_service) -> None:
    """解绑同样归一化：绑 `Agent-Gate`、用 `AGENT-GATE` 解绑 ⇒ 命中同一行（`disabled`）。"""
    _enable("gate-unbind-normalize")
    assert (
        client.post(
            BINDINGS, json={"skill_key": "gate-unbind-normalize", "agent_key": AGENT.capitalize()}, headers=headers()
        ).status_code
        == 200
    )

    response = client.delete(
        BINDINGS, params={"skill_key": "gate-unbind-normalize", "agent_key": AGENT.upper()}, headers=headers()
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"skill_key": "gate-unbind-normalize", "agent_key": AGENT, "status": "disabled"}


def test_permission_check_wins_over_normalization(skills_service) -> None:
    """越权者传**非法标识** ⇒ 仍 `403`（不是 `422`）⇒ 越权者拿不到任何校验细节。"""
    response = client.post(
        BINDINGS,
        json={"skill_key": "gate-illegal-2", "agent_key": "bad key!"},
        headers=headers("employee", user_id="acct-employee"),
    )

    assert response.status_code == 403, response.text


# ------------------------------------------------------------ 审计收敛（第 12 轮 ⑥A）


def _binding_audits(skills_service, action: str) -> list:
    """按 `detail.agent_key` 过滤：技能启停也复用 `skill.enabled`/`skill.disabled` 动作码。"""
    return [
        item
        for item in skills_service.audit.store.list_recent(TENANT)
        if item.action.value == action and item.detail.get("agent_key") == AGENT
    ]


def test_idempotent_rebind_writes_audit_once(skills_service) -> None:
    """幂等重复 `bind` ⇒ **审计只落一条**（原先每次调用都落一条，真机实测同一 target 最多 8 条）。"""
    _enable("gate-audit-once")

    assert client.post(BINDINGS, json={"skill_key": "gate-audit-once", "agent_key": AGENT}, headers=headers()).status_code == 200
    assert client.post(BINDINGS, json={"skill_key": "gate-audit-once", "agent_key": AGENT}, headers=headers()).status_code == 200

    assert len(_binding_audits(skills_service, "skill.enabled")) == 1


def test_idempotent_unbind_writes_audit_once(skills_service) -> None:
    """幂等重复 `unbind` ⇒ `skill.disabled` 只落一条。"""
    _enable("gate-audit-unbind-once")
    client.post(BINDINGS, json={"skill_key": "gate-audit-unbind-once", "agent_key": AGENT}, headers=headers())

    client.delete(BINDINGS, params={"skill_key": "gate-audit-unbind-once", "agent_key": AGENT}, headers=headers())
    client.delete(BINDINGS, params={"skill_key": "gate-audit-unbind-once", "agent_key": AGENT}, headers=headers())

    assert len(_binding_audits(skills_service, "skill.disabled")) == 1


def test_state_flip_writes_audit_again(skills_service) -> None:
    """**状态翻转仍要留痕**：`bind → unbind → bind` ⇒ `enabled` 2 条、`disabled` 1 条。"""
    _enable("gate-audit-flip")
    client.post(BINDINGS, json={"skill_key": "gate-audit-flip", "agent_key": AGENT}, headers=headers())
    client.delete(BINDINGS, params={"skill_key": "gate-audit-flip", "agent_key": AGENT}, headers=headers())
    client.post(BINDINGS, json={"skill_key": "gate-audit-flip", "agent_key": AGENT}, headers=headers())

    assert len(_binding_audits(skills_service, "skill.enabled")) == 2
    assert len(_binding_audits(skills_service, "skill.disabled")) == 1