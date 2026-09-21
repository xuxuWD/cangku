"""技能绑定闸门（第 11 轮专项）：**绑定必须指向真实存在且已启用的技能包**。

背景（第 9 轮真机实测登记 + 第 11 轮复核）：`POST /api/v1/skills/bindings` 原先**三条校验全缺**——
① 技能不存在也 `200`（写入**悬空绑定**）；② 技能 `submitted` / `disabled` 也能绑；③ 员工键不在目录也能绑。
本轮按专项方案 [`skill-binding-gate-plan.md`](file:///d:/徐徐AI学习/公司工作台/docs/contracts/skill-binding-gate-plan.md) 落地
**域内两条闸门**（技能存在 ⇒ `404`；技能已启用 ⇒ `409`）；**第 ③ 条（员工目录闸门）暂缓**，
原因见该文件 §7（与第 9 轮已裁决的「员工键可手动录入」冲突，需单独定夺），本文件用末尾一例**显式钉住该决定**。

**顺序**：权限优先（越权 ⇒ `403`，不泄露技能是否存在）→ 存在性（`404`）→ 已启用（`409`）。

**反假锚点**：去掉 `list_versions` 存在性判定 ⇒ 用例 1 / 5 必红；去掉 enabled 判定 ⇒ 用例 2 / 3 必红。
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


def test_agent_directory_gate_is_deferred_by_decision(skills_service) -> None:
    """**第 ③ 条闸门（员工键必须在数字员工目录内）本轮暂缓** —— 本用例钉住这一决定。

    暂缓理由（专项方案 §7）：第 9 轮已裁决「员工键 = 目录候选 **∪ 手动录入**」，
    而目录闸门会让"手动录入目录外的标识"**必然被拒**（且本机测试租户目录实测 `total = 0` ⇒ 正向路径不可构造）。
    两者需一并定夺，故本轮**只做域内两条**；一旦裁决"加目录闸门"，本用例应改为断言 `409`。
    """
    _enable("gate-outside-dir")

    response = client.post(
        BINDINGS, json={"skill_key": "gate-outside-dir", "agent_key": "agent-not-in-directory"}, headers=headers()
    )

    assert response.status_code == 200, response.text