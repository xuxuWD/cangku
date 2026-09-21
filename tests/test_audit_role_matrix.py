"""审计查询角色分档：**逐行钉死 `permission-matrix.md` §3 的「审计：查询」行**（第 10 轮 P0 缺口修复锚点）。

背景（2026-09-20 第 10 轮真机复测登记）：实现把审计查询收在 `{ceo, super_admin}` 之下
（`app/main.py` 的 `list_audits` 直接判 `context.role not in {"ceo", "super_admin"}`），与矩阵冲突：

| 资源 · 动作 | employee | department_lead | ceo | super_admin | customer_admin |
| --- | --- | --- | --- | --- | --- |
| 审计：查询 | ⚠️ **仅本人相关** | ✅ 本租户 | ✅ 本租户 | ✅ | ❌ |

**「仅本人相关」的落地口径（数据归属红线）**：`actor_id` 是**客户端可传的查询参数**，
若只靠界面隐藏 ⇒ 员工可在请求里填**任意** `actor_id` 读到别人（以及全租户）的操作记录，
撞矩阵 §8「不静默返回他人数据」。⇒ 由**服务端强制**：`employee` 一律注入 `actor_id = 自己`；
**显式传他人 `actor_id` ⇒ `403` + 原文原因**（不静默忽略 —— 静默忽略会让调用方以为"筛过了"）。

**反假锚点**：
- 分档改错（例如把 employee / department_lead 重新收回 `{ceo, super_admin}`）⇒ 必红；
- 去掉服务端自限（`resolve_actor_filter` 直接返回调用方给的值）⇒ 用例 1 / 2 必红。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import main
from app.audit.models import AuditAction, build_record, resolve_actor_filter
from app.audit.service import AuditService
from app.audit.store import InMemoryAuditStore
from app.domain import PolicyError, UserContext
from app.main import app

client = TestClient(app)

TENANT = "t-audit-roles"
'''矩阵 §3「审计：查询」行的四档角色（`customer_admin` ❌ 单列）。'''
READ_ROLES = ("employee", "department_lead", "ceo", "super_admin")
TENANT_WIDE_ROLES = ("department_lead", "ceo", "super_admin")
DENIED_ROLE = "customer_admin"
EMP_A = "acct-emp-a"
EMP_B = "acct-emp-b"


def headers(role: str = "super_admin", user_id: str = "acct-admin", tenant_id: str = TENANT) -> dict[str, str]:
    return {"X-Tenant-Id": tenant_id, "X-User-Id": user_id, "X-User-Role": role}


@pytest.fixture(autouse=True)
def audit_service(monkeypatch) -> AuditService:
    """隔离的审计仓储：本租户两条本人记录 + 一条他人记录 + 一条管理记录，另加他租户一条。"""
    store = InMemoryAuditStore()
    for record in (
        build_record(AuditAction.ACCOUNT_LOGIN_SUCCEEDED, tenant_id=TENANT, actor_id=EMP_A, target_id="acct-1"),
        build_record(AuditAction.ACCOUNT_PASSWORD_CHANGED, tenant_id=TENANT, actor_id=EMP_A, target_id="acct-1"),
        build_record(AuditAction.ACCOUNT_LOGIN_SUCCEEDED, tenant_id=TENANT, actor_id=EMP_B, target_id="acct-2"),
        build_record(AuditAction.PLAN_APPROVED, tenant_id=TENANT, actor_id="ceo-1", target_id="p-1"),
        build_record(AuditAction.PLAN_APPROVED, tenant_id="t-other", actor_id="u-other", target_id="p-9"),
    ):
        store.append(record)
    service = AuditService(store)
    monkeypatch.setattr(main, "audit_service", service)
    return service


# ------------------------------------------------------------ 四个业务角色都能查（矩阵三档 ✅/⚠️）


@pytest.mark.parametrize("role", READ_ROLES)
def test_audit_query_allowed_for_four_business_roles(role: str) -> None:
    """矩阵 §3 审计查询行：四个业务角色均 `200`（`customer_admin` 除外）。"""
    response = client.get("/api/v1/audits", headers=headers(role=role, user_id=EMP_A))

    assert response.status_code == 200, response.text
    assert response.json()["total"] >= 1


def test_audit_query_denied_for_customer_admin() -> None:
    """矩阵 §3 末列：`customer_admin` ❌。"""
    response = client.get("/api/v1/audits", headers=headers(role=DENIED_ROLE, user_id="acct-cust"))

    assert response.status_code == 403, response.text
    assert response.json()["detail"] == "当前岗位不能查看审计日志"


def test_audit_query_requires_login() -> None:
    """匿名 ⇒ `401`。"""
    assert client.get("/api/v1/audits").status_code == 401


# ------------------------------------------------------------ 员工：仅本人相关（服务端自限）


def test_employee_sees_only_own_records() -> None:
    """`employee` 只看到 `actor_id == 自己` 的记录（他人记录**不出现在列表里**）。"""
    body = client.get("/api/v1/audits", headers=headers(role="employee", user_id=EMP_A)).json()

    assert body["total"] == 2
    assert {item["actor_id"] for item in body["items"]} == {EMP_A}
    assert EMP_B not in {item["actor_id"] for item in body["items"]}


def test_employee_cannot_filter_by_someone_else() -> None:
    """`employee` 显式传他人 `actor_id` ⇒ **`403` + 原文**（不静默忽略，避免"以为筛过了"）。"""
    response = client.get(
        "/api/v1/audits", params={"actor_id": EMP_B}, headers=headers(role="employee", user_id=EMP_A)
    )

    assert response.status_code == 403, response.text
    assert response.json()["detail"] == "只能查看本人的审计记录，不能按他人筛选"


def test_employee_may_pass_own_actor_id() -> None:
    """`employee` 传**自己**的 `actor_id` 是合法输入（与自限结果一致）。"""
    response = client.get(
        "/api/v1/audits", params={"actor_id": EMP_A}, headers=headers(role="employee", user_id=EMP_A)
    )

    assert response.status_code == 200, response.text
    assert response.json()["total"] == 2


def test_employee_cannot_widen_by_other_filters() -> None:
    """`employee` 用其它筛选也**不能**把范围撑大（目标类型 / 动作筛选仍受自限约束，且不含他租户记录）。"""
    body = client.get(
        "/api/v1/audits",
        params={"action": "account.login.succeeded"},
        headers=headers(role="employee", user_id=EMP_A),
    ).json()

    assert body["total"] == 1
    assert all(item["actor_id"] == EMP_A for item in body["items"])


# ------------------------------------------------------------ 管理三档：本租户全量


@pytest.mark.parametrize("role", TENANT_WIDE_ROLES)
def test_tenant_wide_roles_see_other_actors_in_same_tenant(role: str) -> None:
    """`department_lead` / `ceo` / `super_admin` 看**本租户全量**（含他人记录），但**不含他租户**。"""
    body = client.get("/api/v1/audits", headers=headers(role=role, user_id="acct-x")).json()

    assert body["total"] == 4
    assert {item["actor_id"] for item in body["items"]} == {EMP_A, EMP_B, "ceo-1"}
    assert "u-other" not in {item["actor_id"] for item in body["items"]}


@pytest.mark.parametrize("role", TENANT_WIDE_ROLES)
def test_tenant_wide_roles_may_filter_by_other_actor(role: str) -> None:
    """管理三档可自由按他人 `actor_id` 筛选（矩阵 ✅ 本租户）。"""
    body = client.get("/api/v1/audits", params={"actor_id": EMP_B}, headers=headers(role=role)).json()

    assert body["total"] == 1
    assert body["items"][0]["actor_id"] == EMP_B


# ------------------------------------------------------------ 自限判定的域层锚点（反假）


def test_resolve_actor_filter_is_fail_closed_at_domain_layer() -> None:
    """域层同样 fail-closed（不只靠路由）：自限角色传他人 ⇒ `PolicyError`；管理角色原样放行。"""
    employee = UserContext(TENANT, EMP_A, "employee")
    with pytest.raises(PolicyError):
        resolve_actor_filter(employee, EMP_B)
    assert resolve_actor_filter(employee, None) == EMP_A
    assert resolve_actor_filter(employee, EMP_A) == EMP_A

    for role in TENANT_WIDE_ROLES:
        actor = UserContext(TENANT, "acct-x", role)
        assert resolve_actor_filter(actor, EMP_B) == EMP_B
        assert resolve_actor_filter(actor, None) is None


# ------------------------------------------------------------ 动作目录端点（新增）


def test_audit_actions_catalog_lists_every_action() -> None:
    """`GET /api/v1/audits/actions`：返回**动作全集**（单一来源 = 后端枚举，前端不复制 94 项）。"""
    response = client.get("/api/v1/audits/actions", headers=headers(role="super_admin"))

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body.keys()) == {"items", "total"}
    assert set(body["items"]) == {action.value for action in AuditAction}
    assert body["total"] == len(body["items"]) == len(AuditAction)


@pytest.mark.parametrize("role", READ_ROLES)
def test_audit_actions_catalog_allowed_for_four_business_roles(role: str) -> None:
    """动作目录与「审计：查询」同档（能查记录的人就能取筛选选项），四角色均 `200`。"""
    assert client.get("/api/v1/audits/actions", headers=headers(role=role, user_id=EMP_A)).status_code == 200


def test_audit_actions_catalog_denied_for_customer_admin_and_anonymous() -> None:
    """`customer_admin` ⇒ `403`；匿名 ⇒ `401`。"""
    denied = client.get("/api/v1/audits/actions", headers=headers(role=DENIED_ROLE, user_id="acct-cust"))
    assert denied.status_code == 403
    assert denied.json()["detail"] == "当前岗位不能查看审计日志"
    assert client.get("/api/v1/audits/actions").status_code == 401