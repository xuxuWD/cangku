"""组 10.5：任务金额改**整数分**（用户裁决 2026-09-19 选项 A = 加法式；迁移 `044_task_budget_cents`）。

判据与口径：
  - 宪法 §3 数据红线「**金额不用浮点**（整数分或 Decimal）」；运行层早已是 `budget_cents: int`
    （`app/runtime/contracts.py:70`），本批把**任务层**对齐到同一口径。
  - **加法式**：新增权威列 `budget_cents`，旧列 `budget`（元 / 浮点）保留为兼容列；两列**恰好一个有值**
    （迁移里的互斥 CHECK）；新写入一律只写 `budget_cents`。
  - **兼容**：`POST /tasks` 的老请求体（只给 `budget`，单位元）**指纹逐字不变** ⇒ 重放仍返回原任务
    （幂等）；视图同时给 `budget_cents`（权威）与 `budget`（= cents / 100，老页面不改也能用）。
  - 闸门阈值与改前**逐字等价**：原「元 > 1000」⇒ 现「分 > 100000」。

覆盖：正常流程（查库 / 视图字段）、临界值（0 / 阈值边界 / 四舍五入）、异常与非法输入（两字段同传 422、
负数 422）、真库两代行的水合并存。
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from app.domain import PolicyError, RiskLevel, Task, TaskStatus, UserContext, ensure_can_create, yuan_to_cents
from app.main import app
from app.repository import PostgresTaskRepository

client = TestClient(app)

DSN = os.environ.get("WORKBENCH_TEST_DATABASE_URL")
requires_db = pytest.mark.skipif(
    not DSN,
    reason="未设置 WORKBENCH_TEST_DATABASE_URL，跳过真库集成测试",
)


def headers(role: str = "employee", user_id: str = "u-1", tenant_id: str = "t-1") -> dict[str, str]:
    return {"X-Tenant-Id": tenant_id, "X-User-Id": user_id, "X-User-Role": role}


def _payload(**overrides) -> dict[str, object]:
    payload: dict[str, object] = {
        "title": "组 10.5 预算用例",
        "employee_key": "content-operator",
        "risk_level": "low",
        "idempotency_key": "budget-cents-001",
    }
    payload.update(overrides)
    return payload


# ------------------------------------------------------------ 元 → 分：换算用 Decimal，不直接乘 100


def test_yuan_to_cents_is_decimal_exact() -> None:
    """`0.29 * 100 = 28.999…`：直接乘再取整会少 1 分 —— 换算必须走 Decimal（四舍五入到分）。"""
    assert yuan_to_cents(0.29) == 29
    assert yuan_to_cents(0.1) == 10
    assert yuan_to_cents(8.7) == 870
    assert yuan_to_cents("0.005") == 1  # 半分进位（ROUND_HALF_UP）
    assert yuan_to_cents(0) == 0
    assert yuan_to_cents(1000) == 100_000


def test_yuan_to_cents_rejects_non_finite() -> None:
    for bad in (float("nan"), float("inf")):
        with pytest.raises(PolicyError):
            yuan_to_cents(bad)


def test_task_budget_in_cents_prefers_authoritative_column() -> None:
    """新行（只有 `budget_cents`）直取；历史行（只有 `budget`）按同一 Decimal 换算；两列都空 ⇒ 0。"""
    base = dict(
        tenant_id="t-1", project_id=None, created_by="u-1", employee_key="e", title="t",
        risk_level=RiskLevel.LOW, idempotency_key="k", request_fingerprint="f", status=TaskStatus.QUEUED,
    )
    assert Task(**base, budget_cents=1234, budget=None).budget_in_cents() == 1234
    assert Task(**base, budget=0.29, budget_cents=None).budget_in_cents() == 29
    assert Task(**base, budget=None, budget_cents=None).budget_in_cents() == 0


# ------------------------------------------------------------ 闸门：阈值与改前逐字等价（元 > 1000 ⇒ 分 > 100000）


def test_high_risk_threshold_equivalence_at_the_boundary() -> None:
    employee = UserContext("t-1", "u-1", "employee")
    ensure_can_create(employee, RiskLevel.HIGH, 100_000)  # 恰好 1000 元：允许（原判据是 `>`）
    with pytest.raises(PolicyError):
        ensure_can_create(employee, RiskLevel.HIGH, 100_001)  # 超出 1 分即拒
    with pytest.raises(PolicyError):
        ensure_can_create(employee, RiskLevel.HIGH, -1)  # 负数仍拒


# ------------------------------------------------------------ 接口：权威字段 / 互斥 / 兼容指纹


def test_create_task_with_budget_cents_returns_authoritative_and_mirrored_fields() -> None:
    response = client.post(
        "/api/v1/tasks",
        headers=headers(),
        json=_payload(budget_cents=1234, idempotency_key="budget-cents-new-1"),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["budget_cents"] == 1234  # 权威字段
    assert body["budget"] == 12.34  # 兼容字段（= cents / 100）


def test_create_task_rejects_both_budget_fields() -> None:
    """两个金额字段同传 ⇒ `422`：**不静默取其一**（避免「以为按分、其实按元」）。"""
    response = client.post(
        "/api/v1/tasks",
        headers=headers(),
        json=_payload(budget=1, budget_cents=1, idempotency_key="budget-both-1"),
    )

    assert response.status_code == 422


def test_create_task_without_budget_defaults_to_zero_cents() -> None:
    response = client.post(
        "/api/v1/tasks",
        headers=headers(),
        json=_payload(idempotency_key="budget-none-1"),
    )

    assert response.status_code == 201
    assert response.json()["budget_cents"] == 0
    assert response.json()["budget"] == 0


def test_fingerprint_source_is_byte_identical_for_legacy_payloads() -> None:
    """**兼容性关键用例（字节级）**：老请求（只给 `budget`）的指纹源必须**与 10.5 之前逐字节相同**。

    为什么不能只测「同版本内重放」：那种测法在**任何**指纹算法下都自洽（创建与重放用同一份源码），
    它测不出「部署新版后，老客户端重放**历史**请求会拿到 `409`」这一真实风险。
    本用例直接钉住**指纹源的键集与取值**（10.5 之前 = `model_dump()` 的 6 个键，含元-浮点 `budget`）。
    """
    from app.main import TaskCreate

    legacy = TaskCreate(
        title="老请求", employee_key="content-operator", risk_level="low",
        budget=0.29, idempotency_key="legacy-fp-1",
    )
    assert legacy.fingerprint_source() == {
        "title": "老请求",
        "employee_key": "content-operator",
        "risk_level": "low",
        "budget": 0.29,
        "idempotency_key": "legacy-fp-1",
        "project_id": None,
    }, "老请求的指纹源被改动 ⇒ 历史幂等键会失效"

    fresh = TaskCreate(
        title="老请求", employee_key="content-operator", risk_level="low",
        budget_cents=29, idempotency_key="legacy-fp-1",
    )
    source = fresh.fingerprint_source()
    assert "budget" not in source and source["budget_cents"] == 29  # 新请求只带整数分


def test_legacy_budget_payload_keeps_fingerprint_and_idempotency() -> None:
    """**兼容性关键用例**：老请求体（只给 `budget`，单位元）指纹**逐字不变** ⇒ 重放返回原任务。

    若把新字段无条件塞进指纹源（例如直接把 `model_dump()` 全量入库），同一份老请求重放会得到
    **不同的指纹** ⇒ 客户端重试会拿到 `409`（幂等被破坏）。
    """
    payload = _payload(budget=0.29, idempotency_key="budget-legacy-1")

    first = client.post("/api/v1/tasks", headers=headers(), json=payload)
    second = client.post("/api/v1/tasks", headers=headers(), json=payload)

    assert first.status_code == 201
    assert second.status_code == 200  # 幂等命中
    assert second.json()["id"] == first.json()["id"]
    # 老字段按 Decimal 换算落分（0.29 元 = 29 分，不是 28）。
    assert first.json()["budget_cents"] == 29


def test_new_style_payload_is_idempotent_too() -> None:
    payload = _payload(budget_cents=500, idempotency_key="budget-cents-replay-1")

    first = client.post("/api/v1/tasks", headers=headers(), json=payload)
    second = client.post("/api/v1/tasks", headers=headers(), json=payload)

    assert first.status_code == 201 and second.status_code == 200
    assert first.json()["budget_cents"] == 500


# ------------------------------------------------------------ 真库：两代行共存与水合


@requires_db
def test_repository_hydrates_both_generations_of_rows() -> None:
    """真库：新行（只有 `budget_cents`）与历史行（只有 `budget`）都能水合，且互斥约束真的在拦人。"""
    import psycopg

    tenant = "t-budget-cents-pg"
    with psycopg.connect(DSN, autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM workbench_audit_events WHERE tenant_id = %s", (tenant,))
            cursor.execute("DELETE FROM workbench_event_outbox WHERE tenant_id = %s", (tenant,))
            cursor.execute("DELETE FROM workbench_tasks WHERE tenant_id = %s", (tenant,))
            # 新行：只写整数分（`budget` 为 NULL）。
            cursor.execute(
                "INSERT INTO workbench_tasks (id, tenant_id, created_by, employee_key, title,"
                " risk_level, budget, budget_cents, idempotency_key, request_fingerprint, status)"
                " VALUES (%s, %s, 'u-1', 'e', '新行', 'low', NULL, 1234, 'k-new', 'f', 'queued')",
                (f"{tenant}-new", tenant),
            )
            # 历史行：只写元-浮点（`budget_cents` 为 NULL）。
            cursor.execute(
                "INSERT INTO workbench_tasks (id, tenant_id, created_by, employee_key, title,"
                " risk_level, budget, budget_cents, idempotency_key, request_fingerprint, status)"
                " VALUES (%s, %s, 'u-1', 'e', '历史行', 'low', 0.29, NULL, 'k-legacy', 'f', 'queued')",
                (f"{tenant}-legacy", tenant),
            )
            # 不变量：**两列都空** ⇒ 真库拒绝（「至少一列有值」；口径与理由见迁移 044 文件头）。
            with pytest.raises(psycopg.errors.CheckViolation):
                cursor.execute(
                    "INSERT INTO workbench_tasks (id, tenant_id, created_by, employee_key, title,"
                    " risk_level, budget, budget_cents, idempotency_key, request_fingerprint, status)"
                    " VALUES (%s, %s, 'u-1', 'e', '两列都空', 'low', NULL, NULL, 'k-bad', 'f', 'queued')",
                    (f"{tenant}-bad", tenant),
                )
        try:
            repository = PostgresTaskRepository(connection)
            rows = repository.list_for_tenant(tenant, limit=10, offset=0)[0]
            by_id = {row.id: row for row in rows}  # 顺序按 id 升序 ⇒ 按 id 取名，不赌位置
            new_row, legacy_row = by_id[f"{tenant}-new"], by_id[f"{tenant}-legacy"]
            assert (new_row.id, new_row.budget_cents, new_row.budget) == (f"{tenant}-new", 1234, None)
            assert new_row.budget_in_cents() == 1234
            assert (legacy_row.id, legacy_row.budget_cents, legacy_row.budget) == (
                f"{tenant}-legacy", None, 0.29,
            )
            assert legacy_row.budget_in_cents() == 29  # 历史行按 Decimal 归一到分
        finally:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM workbench_audit_events WHERE tenant_id = %s", (tenant,))
                cursor.execute("DELETE FROM workbench_event_outbox WHERE tenant_id = %s", (tenant,))
                cursor.execute("DELETE FROM workbench_tasks WHERE tenant_id = %s", (tenant,))