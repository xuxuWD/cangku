"""审计导出接口（第 13 轮）：权限（仅 `super_admin`）、筛选、上限、格式、脱敏与导出留痕。

契约：`docs/contracts/audit-export-plan.md`（§3 接口设计 / §4 安全要件 / §8 复测清单）；
后端接口真源 `docs/api-contract.md` 的 `GET /api/v1/audits/export` 节。

**为什么单列这一组**：导出与查询**不同档**（矩阵 §3「审计：导出」仅 `super_admin` ✅，其余四列全 ❌），
且导出会把数据**带出系统** ⇒ 权限、脱敏、上限（不静默截断）与"导出留痕"四条都必须逐条钉死。

**反假锚点**：把 `ensure_can_export_audits` 换成 `ensure_can_read_audits` ⇒ 权限组必红；
去掉 `total > limit` 判定 ⇒ 超限组必红；去掉 `audit_service.record(AUDIT_EXPORTED...)` ⇒ 留痕组必红。
"""

from __future__ import annotations

import csv
import io
import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app import main
from app.audit.models import AuditAction, build_record
from app.audit.service import AuditService
from app.audit.store import InMemoryAuditStore

client = TestClient(main.app)

EXPORT = "/api/v1/audits/export"
TENANT = "t-1"


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    """三行本租户记录（含一行带掩码手机号）+ 一行**别的租户**（用于核对跨租户不泄露）。"""
    store = InMemoryAuditStore()
    store.append(
        build_record(
            AuditAction.ACCOUNT_LOGIN_SUCCEEDED,
            tenant_id=TENANT,
            actor_id="u-1",
            phone_masked="136****0001",
            detail={"status": "ok"},
        )
    )
    store.append(
        build_record(
            AuditAction.PLAN_APPROVED,
            tenant_id=TENANT,
            actor_id="ceo-1",
            target_type="plan_proposal",
            target_id="p-1",
            detail={"step_count": 2},
        )
    )
    store.append(
        build_record(
            AuditAction.SKILL_ENABLED,
            tenant_id=TENANT,
            actor_id="u-1",
            target_type="skill",
            target_id="summarize@1.0.0",
            detail={"skill_key": "summarize", "agent_key": "agent-1"},
        )
    )
    store.append(
        build_record(
            AuditAction.PLAN_APPROVED,
            tenant_id="t-2",
            actor_id="u-2",
            target_id="p-9",
            detail={"step_count": 1},
        )
    )
    audit = AuditService(store)
    monkeypatch.setattr(main, "audit_service", audit)
    return audit


def headers(role: str = "super_admin", user_id: str = "root-1", tenant_id: str = TENANT) -> dict[str, str]:
    return {"X-Tenant-Id": tenant_id, "X-User-Id": user_id, "X-User-Role": role}


def _exported_audits(audit: AuditService) -> list:
    records, _ = audit.query(TENANT, actions=[AuditAction.AUDIT_EXPORTED])
    return records


# ------------------------------------------------------------ 正向：CSV / JSON 形状


def test_super_admin_exports_csv_with_bom_and_row_header() -> None:
    """CSV：`200` + 附件头 + `X-Exported-Rows` + **BOM** + 表头 + 三行本租户记录。"""
    response = client.get(EXPORT, headers=headers())

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/csv")
    assert response.headers["content-disposition"].startswith('attachment; filename="audit-t-1-')
    assert response.headers["content-disposition"].endswith('.csv"')
    assert response.headers["x-exported-rows"] == "3"
    text = response.content.decode("utf-8")
    assert text.startswith("\ufeff")  # Excel 中文兼容
    rows = list(csv.reader(io.StringIO(text.lstrip("\ufeff"))))
    assert rows[0] == [
        "record_id",
        "action",
        "actor_id",
        "target_type",
        "target_id",
        "phone_masked",
        "detail",
        "occurred_at",
    ]
    assert len(rows) == 4  # 表头 + 3 行
    assert [row[1] for row in rows[1:]] == ["skill.enabled", "plan.approved", "account.login.succeeded"]  # 新 → 旧


def test_super_admin_exports_json_with_same_shape() -> None:
    """JSON：字段与列表端点**逐字一致**（含 `null`），并带 `exported_at`。"""
    response = client.get(EXPORT, params={"format": "json"}, headers=headers())

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert body["total"] == 3
    assert "exported_at" in body
    assert set(body["items"][0]) == {
        "record_id",
        "action",
        "actor_id",
        "target_type",
        "target_id",
        "phone_masked",
        "detail",
        "occurred_at",
    }
    assert body["items"][0]["action"] == "skill.enabled"
    assert body["items"][0]["detail"] == {"skill_key": "summarize", "agent_key": "agent-1"}


# ------------------------------------------------------------ 权限：仅 super_admin


@pytest.mark.parametrize("role", ("ceo", "department_lead", "employee", "customer_admin"))
def test_export_requires_super_admin(role: str) -> None:
    """矩阵 §3「审计：导出」其余四列全 ❌ ⇒ 一律 `403`（**与查询分档不同**：`ceo` 能查不能导）。"""
    response = client.get(EXPORT, headers=headers(role=role))

    assert response.status_code == 403, response.text
    assert response.json()["detail"] == "只有超级管理员可以导出审计日志"


def test_export_requires_authentication() -> None:
    """匿名 ⇒ `401`（不得泄露"有没有记录"）。"""
    assert client.get(EXPORT).status_code == 401


def test_permission_check_wins_over_parameter_validation() -> None:
    """越权优先：`ceo` 传非法 `format` ⇒ 仍 `403`（不是 `422`）—— 不通过错误码探测校验细节。"""
    response = client.get(EXPORT, params={"format": "xml"}, headers=headers(role="ceo"))

    assert response.status_code == 403, response.text


# ------------------------------------------------------------ 参数校验与上限


def test_export_rejects_illegal_format() -> None:
    """`format` 只能是 `csv` / `json`（其它 ⇒ `422`，不静默回落）。"""
    response = client.get(EXPORT, params={"format": "xml"}, headers=headers())

    assert response.status_code == 422, response.text
    assert "format" in response.json()["detail"]


def test_export_rejects_limit_over_max() -> None:
    """`limit` 上限 5000（越界 ⇒ `422`）。"""
    assert client.get(EXPORT, params={"limit": 5001}, headers=headers()).status_code == 422


def test_export_rejects_overflow_without_truncating() -> None:
    """**超限不静默截断**：命中 3 条 > `limit=2` ⇒ `422`，文案含命中数与上限，且**不写审计**。

    为什么"拒绝"而不是"截断"：截断会让使用者以为"导全了"（宪法：不得静默）。
    """
    response = client.get(EXPORT, params={"limit": 2}, headers=headers())

    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert "命中 3 条" in detail and "上限 2 条" in detail
    assert _exported_audits(main.audit_service) == []


def test_export_rejects_unknown_action_and_naive_time() -> None:
    """未知动作码 ⇒ `422`；时间不带时区 ⇒ `422`（与查询同一口径）。"""
    assert client.get(EXPORT, params={"action": "nope.nope"}, headers=headers()).status_code == 422

    naive = client.get(EXPORT, params={"since": "2026-09-11T08:00:00"}, headers=headers())
    assert naive.status_code == 422
    assert "since 必须带时区" in naive.json()["detail"]


# ------------------------------------------------------------ 筛选与租户隔离


def test_export_respects_filters() -> None:
    """`action` / `target_id` 筛选逐条生效（与查询同名同义）。"""
    by_action = client.get(EXPORT, params={"format": "json", "action": "plan.approved"}, headers=headers())
    assert by_action.status_code == 200, by_action.text
    assert [item["action"] for item in by_action.json()["items"]] == ["plan.approved"]

    by_target = client.get(EXPORT, params={"format": "json", "target_id": "summarize@1.0.0"}, headers=headers())
    assert [item["target_id"] for item in by_target.json()["items"]] == ["summarize@1.0.0"]


def test_export_never_leaks_other_tenant() -> None:
    """跨租户**不可能**：租户只从鉴权上下文取（别的租户那行不出现）。"""
    body = client.get(EXPORT, params={"format": "json"}, headers=headers()).json()

    assert body["total"] == 3
    assert all(item["target_id"] != "p-9" for item in body["items"])


def test_export_keeps_phone_masked() -> None:
    """手机号列**只有掩码值**（不出现明文手机号）。"""
    response = client.get(EXPORT, headers=headers())

    text = response.content.decode("utf-8")
    assert "136****0001" in text
    assert "13600000001" not in text


# ------------------------------------------------------------ 导出留痕（audit.exported）


def test_successful_export_writes_exactly_one_audit_record() -> None:
    """成功导出 ⇒ **恰好 1 条** `audit.exported`，明细 `{format, rows, filters}`。"""
    response = client.get(
        EXPORT, params={"format": "json", "action": "plan.approved"}, headers=headers()
    )
    assert response.status_code == 200

    records = _exported_audits(main.audit_service)
    assert len(records) == 1
    record = records[0]
    assert record.actor_id == "root-1"
    assert record.detail == {"format": "json", "rows": 1, "filters": "action=plan.approved"}


def test_rejected_export_writes_no_audit() -> None:
    """被拒（`403` / `422`）**不写审计**（与既有 4xx 口径一致）。"""
    assert client.get(EXPORT, headers=headers(role="ceo")).status_code == 403
    assert client.get(EXPORT, params={"format": "xml"}, headers=headers()).status_code == 422
    assert client.get(EXPORT, params={"limit": 2}, headers=headers()).status_code == 422

    assert _exported_audits(main.audit_service) == []


def test_export_audit_record_is_visible_in_query() -> None:
    """留痕可被查询到（动作目录里也有该码值 ⇒ 界面下拉自动跟随）。"""
    client.get(EXPORT, headers=headers())

    listed = client.get(
        "/api/v1/audits", params={"action": "audit.exported"}, headers=headers(role="super_admin")
    )
    assert listed.status_code == 200, listed.text
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["action"] == "audit.exported"

    catalog = client.get("/api/v1/audits/actions", headers=headers(role="super_admin")).json()
    assert "audit.exported" in catalog["items"]
