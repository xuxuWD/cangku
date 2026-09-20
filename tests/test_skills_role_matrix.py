"""技能域角色门禁：**逐行钉死 `permission-matrix.md` §3 的「技能」两行**（第 8 轮缺口修复的锚点）。

背景（2026-09-20 第 8 轮契约真机复测登记）：实现把技能复核 / 启用 / 停用收在 `super_admin` 之下
（`app/skills/models.py` `REVIEW_ROLES = {"super_admin"}`），与矩阵 §3 冲突：

| 资源 · 动作 | employee | department_lead | ceo | super_admin | customer_admin |
| --- | --- | --- | --- | --- | --- |
| 技能：提交（自带 Skill 包） | ✅ | ✅ | ✅ | ✅ | ❌ |
| 技能：复核/启用/停用 | ❌ | ❌ | ✅ | ✅ | ❌ |

矩阵是权限口径的**唯一权威**（自定「实现与本文冲突时以本文为准」），故本轮按矩阵逐行对齐
（与第 7 轮知识域 P0 同一手法：**实现向矩阵对齐、不改矩阵口径**）。

另钉死两条**真缺陷修复**的锚点（2026-09-20 真机复测发现）：
- `POST /api/v1/skills/bindings` 曾恒 `500`（路由声明 `response_model=SkillView`，实际返回绑定形状，
  序列化阶段抛 `ResponseValidationError`）⇒ 本文件断言绑定返回 **200 + 绑定形状**
  （`{skill_key, agent_key, status}`）；仅声明"不报 500"不够，形状必须逐键对齐；
- `GET /api/v1/skills/agents/{agent_key}/tools` 依赖绑定落库 ⇒ 修复后应展开
  `allowed-tools ∩ 工具目录`（fail-closed 交集）。

**绑定口径本轮不动**：矩阵 §3 **未列**「绑定」行，契约 §1 定为仅 `super_admin`（`BIND_ROLES`）——
角色对齐是对**复核 / 启用 / 停用**三动作，**不得**顺带把绑定放开给 `ceo`（超出裁决范围），文末单列一例钉住。

**反假锚点**：
- 复核 / 启停档位改错（例如重新收回 `super_admin`、或放开给 `employee`）⇒ 必红；
- 绑定角色闸门被放开（`ceo` 能绑定）⇒ 必红；绑定响应模型回退成 `SkillView` ⇒ 必红（500）；
- 职责分离（提交人不得自审）被去掉 owner 闸门 ⇒ 文末两例必红。
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

TENANT = "t-skill-roles"
SOURCE = "manual"
BODY = "# 摘要助手\n\n生成结构化摘要的核心步骤：先取数、再归纳、最后校验。"
'''矩阵 §3「提交」行四个 ✅ 角色、管理行两个 ✅ 角色、末列 ❌ 角色。'''
SUBMIT_ROLES_OK = ("employee", "department_lead", "ceo", "super_admin")
MANAGE_ROLES_OK = ("ceo", "super_admin")
ROLE_EMPLOYEE = "employee"
DENIED_ROLE = "customer_admin"


def headers(role: str = "super_admin", user_id: str | None = None, tenant_id: str = TENANT) -> dict[str, str]:
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


def _submit(key: str, *, role: str = ROLE_EMPLOYEE, version: str = "1.0.0"):
    """提交一个合法技能包（正文 + 一致指纹），返回响应（调用方断言状态码）。"""
    return client.post(
        "/api/v1/skills",
        json={
            "skill_key": key,
            "version": version,
            "name": "摘要助手",
            "description": "生成结构化摘要",
            "license": "Apache-2.0",
            "allowed_tools": ["fs.read"],
            "source_key": SOURCE,
            "content_sha256": _sha256(BODY),
            "content_body": BODY,
        },
        headers=headers(role=role),
    )


def _submitted(key: str, *, role: str = ROLE_EMPLOYEE, version: str = "1.0.0") -> None:
    response = _submit(key, role=role, version=version)
    assert response.status_code == 201, response.text


# ------------------------------------------------------------ 提交行（✅ ×4 / ❌）


@pytest.mark.parametrize("role", SUBMIT_ROLES_OK)
def test_submit_allowed_for_four_roles(skills_service, role: str) -> None:
    """矩阵 §3 提交行：四个角色均可提交（`customer_admin` 除外）。"""
    response = _submit(f"rm-submit-{role}", role=role)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "submitted"
    assert body["owner_id"] == f"acct-{role}"


def test_submit_forbidden_for_customer_admin(skills_service) -> None:
    """矩阵 §3 提交行末列：`customer_admin` ❌（客户管理员不参与技能申报）。"""
    response = _submit("rm-submit-customer", role=DENIED_ROLE)

    assert response.status_code == 403, response.text


# ------------------------------------------------------------ 管理行（复核 / 启用 / 停用 → ceo + super_admin）


@pytest.mark.parametrize("role", MANAGE_ROLES_OK)
def test_review_allowed_for_manage_roles(skills_service, role: str) -> None:
    """矩阵 §3 管理行：`ceo` 与 `super_admin` 均可复核（员工提交、非本人审核）。"""
    _submitted(f"rm-review-{role}")

    response = client.post(
        f"/api/v1/skills/rm-review-{role}/versions/1.0.0/review",
        params={"approved": "true"},
        headers=headers(role=role),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "approved"
    assert body["reviewed_by"] == f"acct-{role}"


@pytest.mark.parametrize("role", (ROLE_EMPLOYEE, "department_lead", DENIED_ROLE))
def test_review_forbidden_for_others(skills_service, role: str) -> None:
    """矩阵 §3 管理行：低权角色与被拒角色一律 `403`（`employee` / `department_lead` / `customer_admin`）。"""
    _submitted(f"rm-review-deny-{role}")

    response = client.post(
        f"/api/v1/skills/rm-review-deny-{role}/versions/1.0.0/review",
        params={"approved": "true"},
        headers=headers(role=role),
    )

    assert response.status_code == 403, response.text


@pytest.mark.parametrize("role", MANAGE_ROLES_OK)
def test_enable_and_disable_allowed_for_manage_roles(skills_service, role: str) -> None:
    """矩阵 §3 管理行：`ceo` 与 `super_admin` 均可启用 / 停用（状态机 approved → enabled → disabled）。"""
    _submitted(f"rm-toggle-{role}")
    actor = headers(role=role)
    assert client.post(
        f"/api/v1/skills/rm-toggle-{role}/versions/1.0.0/review",
        params={"approved": "true"},
        headers=actor,
    ).status_code == 200

    enabled = client.post(f"/api/v1/skills/rm-toggle-{role}/versions/1.0.0/enable", headers=actor)
    disabled = client.post(f"/api/v1/skills/rm-toggle-{role}/versions/1.0.0/disable", headers=actor)

    assert enabled.status_code == 200, enabled.text
    assert enabled.json()["status"] == "enabled"
    assert disabled.status_code == 200, disabled.text
    assert disabled.json()["status"] == "disabled"


@pytest.mark.parametrize("role", (ROLE_EMPLOYEE, "department_lead", DENIED_ROLE))
def test_enable_forbidden_for_others(skills_service, role: str) -> None:
    """矩阵 §3 管理行：低权角色的启用 / 停用一律 `403`（不是 409，先判角色再判状态）。"""
    _submitted(f"rm-enable-deny-{role}")
    assert client.post(
        f"/api/v1/skills/rm-enable-deny-{role}/versions/1.0.0/review",
        params={"approved": "true"},
        headers=headers("super_admin"),
    ).status_code == 200
    actor = headers(role=role)

    enable = client.post(f"/api/v1/skills/rm-enable-deny-{role}/versions/1.0.0/enable", headers=actor)
    disable = client.post(f"/api/v1/skills/rm-enable-deny-{role}/versions/1.0.0/disable", headers=actor)

    assert enable.status_code == 403, enable.text
    assert disable.status_code == 403, disable.text


# ------------------------------------------------------------ 绑定：形状修复（真缺陷）+ 角色闸门不动


def test_bind_returns_binding_shape_and_tools_expand(skills_service) -> None:
    """`bind` 修复锚点：200 + 绑定形状（曾恒 500），且绑定后工具面按交集展开。"""
    _submitted("rm-bind")
    actor = headers("super_admin")
    assert client.post(
        "/api/v1/skills/rm-bind/versions/1.0.0/review", params={"approved": "true"}, headers=actor
    ).status_code == 200
    assert client.post("/api/v1/skills/rm-bind/versions/1.0.0/enable", headers=actor).status_code == 200

    bound = client.post(
        "/api/v1/skills/bindings",
        json={"skill_key": "rm-bind", "agent_key": "agent-rm"},
        headers=actor,
    )

    assert bound.status_code == 200, bound.text
    assert bound.json() == {"skill_key": "rm-bind", "agent_key": "agent-rm", "status": "active"}
    expanded = client.get("/api/v1/skills/agents/agent-rm/tools", headers=actor)
    assert expanded.status_code == 200, expanded.text
    assert expanded.json() == {"agent_key": "agent-rm", "tools": ["fs.read"]}


def test_bind_is_idempotent_and_survives_repeat(skills_service) -> None:
    """绑定重复调用返回同一形状（UPSERT active 幂等），不得在第二次变成 500 / 409。"""
    _submitted("rm-bind-idem")
    actor = headers("super_admin")
    assert client.post(
        "/api/v1/skills/rm-bind-idem/versions/1.0.0/review", params={"approved": "true"}, headers=actor
    ).status_code == 200
    assert client.post("/api/v1/skills/rm-bind-idem/versions/1.0.0/enable", headers=actor).status_code == 200
    payload = {"skill_key": "rm-bind-idem", "agent_key": "agent-rm-idem"}

    first = client.post("/api/v1/skills/bindings", json=payload, headers=actor)
    second = client.post("/api/v1/skills/bindings", json=payload, headers=actor)

    assert first.status_code == 200 and second.status_code == 200, (first.text, second.text)
    assert first.json() == second.json()


@pytest.mark.parametrize("role", ("ceo", ROLE_EMPLOYEE, "department_lead", DENIED_ROLE))
def test_bind_stays_super_admin_only(skills_service, role: str) -> None:
    """绑定口径**不随角色对齐放开**：矩阵未列「绑定」行，契约 §1 定为仅 `super_admin`。"""
    _submitted(f"rm-bind-deny-{role}")
    assert client.post(
        f"/api/v1/skills/rm-bind-deny-{role}/versions/1.0.0/review",
        params={"approved": "true"},
        headers=headers("super_admin"),
    ).status_code == 200
    assert client.post(
        f"/api/v1/skills/rm-bind-deny-{role}/versions/1.0.0/enable", headers=headers("super_admin")
    ).status_code == 200

    bind = client.post(
        "/api/v1/skills/bindings",
        json={"skill_key": f"rm-bind-deny-{role}", "agent_key": f"agent-{role}"},
        headers=headers(role=role),
    )
    unbind = client.delete(
        "/api/v1/skills/bindings",
        params={"skill_key": f"rm-bind-deny-{role}", "agent_key": f"agent-{role}"},
        headers=headers(role=role),
    )

    assert bind.status_code == 403, bind.text
    assert unbind.status_code == 403, unbind.text


def test_unbind_returns_binding_shape_and_empties_tools(skills_service) -> None:
    """解绑返回绑定形状（`disabled`），解绑后工具面为空交集（fail-closed）。"""
    _submitted("rm-unbind")
    actor = headers("super_admin")
    assert client.post(
        "/api/v1/skills/rm-unbind/versions/1.0.0/review", params={"approved": "true"}, headers=actor
    ).status_code == 200
    assert client.post("/api/v1/skills/rm-unbind/versions/1.0.0/enable", headers=actor).status_code == 200
    assert client.post(
        "/api/v1/skills/bindings", json={"skill_key": "rm-unbind", "agent_key": "agent-unbind"}, headers=actor
    ).status_code == 200

    unbound = client.delete(
        "/api/v1/skills/bindings",
        params={"skill_key": "rm-unbind", "agent_key": "agent-unbind"},
        headers=actor,
    )

    assert unbound.status_code == 200, unbound.text
    assert unbound.json() == {"skill_key": "rm-unbind", "agent_key": "agent-unbind", "status": "disabled"}
    expanded = client.get("/api/v1/skills/agents/agent-unbind/tools", headers=actor)
    assert expanded.status_code == 200
    assert expanded.json()["tools"] == []


# ------------------------------------------------------------ 职责分离：提交人不得自审（owner 闸门不随角色对齐放开）


@pytest.mark.parametrize("role", MANAGE_ROLES_OK)
def test_author_cannot_review_own_submission_after_role_alignment(skills_service, role: str) -> None:
    """管理角色提交的包，本人**仍不得自审**（403 原文为职责分离，而非角色不足）。"""
    _submitted(f"rm-self-{role}", role=role)

    response = client.post(
        f"/api/v1/skills/rm-self-{role}/versions/1.0.0/review",
        params={"approved": "true"},
        headers=headers(role=role),
    )

    assert response.status_code == 403, response.text
    assert response.json()["detail"] == "不能审核自己提交的技能包"