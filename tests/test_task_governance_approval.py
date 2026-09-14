"""任务创建的治理判定：四档风险 × 数字员工自治配置（段一规格 §2.1 / §2.2）。

判定唯一入口是 `needs_approval`，唯一消费点是任务创建时的 `status`。
本文件同时守护「`critical` 只能由负责人发起」（X3）与「员工不存在/已停用回落既有口径」。
"""

from __future__ import annotations

from itertools import count

import pytest
from fastapi.testclient import TestClient

from app import main
from app.audit.service import AuditService
from app.audit.store import InMemoryAuditStore
from app.domain import PolicyError, RiskLevel, TaskStatus, TaskStore, UserContext, ensure_can_create
from app.main import app
from app.workforce.service import WorkforceDirectoryService
from app.workforce.store import InMemoryWorkforceDirectoryStore

client = TestClient(app)
ADMIN = UserContext("t-1", "admin-1", "super_admin")
_SEQ = count(1)


def headers(role: str, user_id: str = "u-1") -> dict[str, str]:
    return {"X-Tenant-Id": "t-1", "X-User-Id": user_id, "X-User-Role": role}


def create_task(*, role: str, employee_key: str, risk_level: str) -> tuple[int, str]:
    response = client.post(
        "/api/v1/tasks",
        headers=headers(role),
        json={
            "title": "治理判定用例",
            "employee_key": employee_key,
            "risk_level": risk_level,
            "budget": 0,
            "idempotency_key": f"governance-{next(_SEQ)}",
        },
    )
    payload = response.json()
    return response.status_code, payload.get("status", "")


def create_employee(
    store: InMemoryWorkforceDirectoryStore,
    agent_key: str,
    *,
    autonomy_level: str,
    risk_threshold: str,
) -> None:
    store.create_employee(ADMIN, agent_key=agent_key, name=f"员工-{agent_key}", role_key="content-operator")
    store.update_agent_config(
        ADMIN, agent_key, autonomy_level=autonomy_level, risk_threshold=risk_threshold
    )


@pytest.fixture
def directory(monkeypatch):
    task_store = TaskStore()
    store = InMemoryWorkforceDirectoryStore()
    store.create_role(ADMIN, role_key="content-operator", name="自媒体运营岗")
    service = WorkforceDirectoryService(store, audit=AuditService(InMemoryAuditStore()))
    monkeypatch.setattr(main, "store", task_store)
    monkeypatch.setattr(main, "workforce_directory_store", store)
    monkeypatch.setattr(main, "workforce_directory_service", service)
    return store


@pytest.mark.parametrize(
    ("autonomy_level", "risk_threshold", "risk_level", "expected_status"),
    [
        # 免批生效：除 critical 外都直接入队
        ("full_auto", "critical", "low", TaskStatus.QUEUED),
        ("full_auto", "critical", "high", TaskStatus.QUEUED),
        # D18 兜底：full_auto 也不得豁免 critical
        ("full_auto", "critical", "critical", TaskStatus.PENDING_APPROVAL),
        # 按阈值：阈值 high 只批 high 及以上
        ("approval_for_risky", "high", "medium", TaskStatus.QUEUED),
        ("approval_for_risky", "high", "high", TaskStatus.PENDING_APPROVAL),
        # 阈值可配：调到 low 即一律审批
        ("approval_for_risky", "low", "low", TaskStatus.PENDING_APPROVAL),
        # 一律审批：阈值不参与
        ("approval_for_all", "critical", "low", TaskStatus.PENDING_APPROVAL),
    ],
)
def test_task_status_follows_employee_governance(
    directory, autonomy_level: str, risk_threshold: str, risk_level: str, expected_status: TaskStatus
) -> None:
    # `critical` 只能由负责人发起（X3），所以统一用 ceo 创建，避免与创建权限混在一起。
    create_employee(
        directory, "content-writer", autonomy_level=autonomy_level, risk_threshold=risk_threshold
    )

    status_code, status = create_task(role="ceo", employee_key="content-writer", risk_level=risk_level)

    assert status_code == 201
    assert status == expected_status.value
    # 宪法要求：正常流程必须查库核对，不只看接口返回。本用例默认内存任务仓储。
    stored = main.store.list_pending_approval("t-1", limit=50) if expected_status is TaskStatus.PENDING_APPROVAL else []
    if expected_status is TaskStatus.PENDING_APPROVAL:
        assert [task.risk_level.value for task in stored] == [risk_level]


def test_unknown_employee_falls_back_to_existing_rule(directory) -> None:
    """目录里没有这个标识（历史自由文本）→ 与今天完全一致：不低于 high 即审批。"""
    assert create_task(role="ceo", employee_key="nobody", risk_level="high") == (201, "pending_approval")
    assert create_task(role="ceo", employee_key="nobody", risk_level="medium") == (201, "queued")


def test_disabled_employee_falls_back_to_existing_rule(directory) -> None:
    """已停用的员工不参与治理判定，同样回落既有口径（不放宽）。"""
    create_employee(directory, "content-writer", autonomy_level="full_auto", risk_threshold="critical")
    directory.update_employee(ADMIN, "content-writer", status="disabled")

    assert create_task(role="ceo", employee_key="content-writer", risk_level="high") == (
        201,
        "pending_approval",
    )


def test_role_disabled_employee_falls_back_to_existing_rule(directory) -> None:
    """岗位停用连带：所属岗位停用后，该员工不参与治理判定 → 回落既有口径（**收严不放宽**）。

    口径与 `agent_is_active` 一致（员工 active **且** 岗位 active）；本用例同时锁定「岗位停用」
    在任务创建路径上的表现：不再套用该员工的免批配置，而是回落「不低于 high 即审批」。
    """
    create_employee(directory, "content-writer", autonomy_level="full_auto", risk_threshold="critical")
    # 治理生效时：`full_auto` + `critical` ⇒ `high` 免批（对照组，证明配置确实被消费）
    assert create_task(role="ceo", employee_key="content-writer", risk_level="high") == (201, "queued")

    directory.update_role(ADMIN, "content-operator", status="disabled")

    assert create_task(role="ceo", employee_key="content-writer", risk_level="high") == (
        201,
        "pending_approval",
    )


def test_employee_key_lookup_follows_directory_normalization(directory) -> None:
    """标识按目录口径归一（转小写）：大小写不同**不是两个员工**，故套用同一份治理配置。"""
    create_employee(directory, "content-writer", autonomy_level="full_auto", risk_threshold="critical")

    assert create_task(role="ceo", employee_key="Content-Writer", risk_level="high") == (201, "queued")


def test_malformed_employee_key_falls_back_to_existing_rule(directory) -> None:
    """目录规则外的标识（含特殊字符）→ 查不到 → 回落既有口径，且不抛异常。"""
    assert create_task(role="ceo", employee_key="!!!", risk_level="high") == (201, "pending_approval")


@pytest.mark.parametrize("role", ["employee", "department_lead"])
def test_critical_creation_is_limited_to_leadership(directory, role: str) -> None:
    """X3：普通员工与部门负责人不得发起 critical 任务。"""
    status_code, _status = create_task(role=role, employee_key="content-writer", risk_level="critical")

    assert status_code == 403


def test_leadership_can_create_critical_but_it_still_needs_approval(directory) -> None:
    create_employee(directory, "content-writer", autonomy_level="approval_for_risky", risk_threshold="high")

    assert create_task(role="super_admin", employee_key="content-writer", risk_level="critical") == (
        201,
        "pending_approval",
    )


@pytest.mark.parametrize("risk_level", ["extreme", "CRITICAL", "", "critical "])
def test_unknown_risk_level_is_rejected(directory, risk_level: str) -> None:
    """未知风险档一律 422（大小写与空白都不做宽松回落）。"""
    status_code, _status = create_task(role="ceo", employee_key="content-writer", risk_level=risk_level)

    assert status_code == 422


def test_read_agent_governance_is_tenant_scoped_and_returns_none_when_unusable(directory) -> None:
    """治理字段读取：跨租户查不到、不存在查不到、停用查不到；非法标识不抛异常。"""
    create_employee(directory, "content-writer", autonomy_level="full_auto", risk_threshold="critical")
    other_tenant = UserContext("t-2", "admin-2", "super_admin")

    assert directory.read_agent_governance(ADMIN, "content-writer") == ("full_auto", "critical")
    assert directory.read_agent_governance(other_tenant, "content-writer") is None
    assert directory.read_agent_governance(ADMIN, "nobody") is None
    assert directory.read_agent_governance(ADMIN, "!!!") is None

    directory.update_employee(ADMIN, "content-writer", status="disabled")
    assert directory.read_agent_governance(ADMIN, "content-writer") is None


@pytest.mark.parametrize(
    ("role", "risk_level", "budget"),
    [
        ("employee", RiskLevel.CRITICAL, 0),  # X3：员工不得发起 critical
        ("department_lead", RiskLevel.CRITICAL, 10_000),
        ("employee", RiskLevel.HIGH, 1001),  # 既有的预算闸门仍然生效
    ],
)
def test_ensure_can_create_rejects(role: str, risk_level: RiskLevel, budget: float) -> None:
    with pytest.raises(PolicyError):
        ensure_can_create(UserContext("t-1", "u-1", role), risk_level, budget)


def test_ensure_can_create_allows() -> None:
    ensure_can_create(UserContext("t-1", "u-1", "employee"), RiskLevel.HIGH, 1000)
    ensure_can_create(UserContext("t-1", "u-1", "ceo"), RiskLevel.CRITICAL, 10_000)
