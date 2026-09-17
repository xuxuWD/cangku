"""CRM API（P5a，§2.12）接口测试：认证 / 401·403·404·409·422 / 掩码与揭示 / 全链路。

隔离手法同 `tests/test_conversation_api.py`：monkeypatch 替换 `main.crm_service`（内存仓储 + 内存审计）。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import main
from app.audit.service import AuditService
from app.audit.store import InMemoryAuditStore
from app.crm import InMemoryCrmStore
from app.crm.service import CrmService
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    store = InMemoryCrmStore()
    audit_store = InMemoryAuditStore()
    audit = AuditService(audit_store)
    service = CrmService(store, audit=audit)
    monkeypatch.setattr(main, "crm_service", service)
    return service, audit_store


def headers(role: str = "employee", user_id: str = "u-1", tenant_id: str = "t-1") -> dict[str, str]:
    return {"X-Tenant-Id": tenant_id, "X-User-Id": user_id, "X-User-Role": role}


def _create_account(**extra) -> dict:
    response = client.post("/api/v1/crm/accounts", headers=headers(), json={"name": "某某公司", **extra})
    assert response.status_code == 201, response.text
    return response.json()


# ------------------------------------------------------------ 认证与校验


def test_requires_authentication() -> None:
    assert client.get("/api/v1/crm/accounts").status_code == 401
    assert client.post("/api/v1/crm/accounts", json={"name": "x"}).status_code == 401


def test_unknown_fields_rejected_and_customer_admin_forbidden() -> None:
    response = client.post(
        "/api/v1/crm/accounts", headers=headers(), json={"name": "某公司", "bogus": 1}
    )
    assert response.status_code == 422  # extra=forbid（白名单）
    # customer_admin 不进 CRM 模块 ⇒ 403
    response = client.get("/api/v1/crm/accounts", headers=headers(role="customer_admin"))
    assert response.status_code == 403


# ------------------------------------------------------------ 主链路（线索 → 转化 → 商机 → 报价 → 合同 → 回款）


def test_full_business_chain() -> None:
    lead = client.post(
        "/api/v1/crm/leads",
        headers=headers(),
        json={"name": "王小明", "company": "某某科技", "phone": "13800001234", "email": "ming@corp.cn"},
    ).json()
    assert lead["phone"] == "138****1234"  # 线索列表口径：默认掩码

    converted = client.post(
        f"/api/v1/crm/leads/{lead['lead_id']}/convert",
        headers=headers(),
        json={"create_opportunity": True, "opportunity_name": "首单"},
    )
    assert converted.status_code == 201, converted.text
    account_id = converted.json()["account"]["account_id"]
    opportunity_id = converted.json()["opportunity"]["opportunity_id"]

    # 商机阶段：qualification → proposal → negotiation → won
    for stage in ("proposal", "negotiation", "won"):
        response = client.post(
            f"/api/v1/crm/opportunities/{opportunity_id}/stage", headers=headers(), json={"to_stage": stage}
        )
        assert response.status_code == 200, response.text
    assert response.json()["stage"] == "won" and response.json()["closed_at"] is not None
    # 非法迁移 ⇒ 409；详情含阶段事件时间线（4 条）
    assert client.post(
        f"/api/v1/crm/opportunities/{opportunity_id}/stage", headers=headers(), json={"to_stage": "lost"}
    ).status_code == 409
    detail = client.get(f"/api/v1/crm/opportunities/{opportunity_id}", headers=headers()).json()
    assert [event["to_stage"] for event in detail["stage_events"]] == [
        "qualification", "proposal", "negotiation", "won",
    ]

    # 报价：建 → 改行 → 确认 → 冻结（改行 409）→ 转合同
    quote = client.post(
        "/api/v1/crm/quotes",
        headers=headers(),
        json={
            "account_id": account_id,
            "lines": [{"description": "服务费", "qty": "2", "unit_price_cents": 50000, "tax_rate_bp": 1300}],
        },
    )
    assert quote.status_code == 201, quote.text
    quote_id = quote.json()["quote"]["quote_id"]
    assert quote.json()["quote"]["total_cents"] == 113000  # 100000 + 13000
    assert client.post(f"/api/v1/crm/quotes/{quote_id}/confirm", headers=headers()).status_code == 200
    assert client.put(
        f"/api/v1/crm/quotes/{quote_id}/lines",
        headers=headers(),
        json={"lines": [{"description": "x", "qty": 1, "unit_price_cents": 1}]},
    ).status_code == 409
    contract = client.post(f"/api/v1/crm/quotes/{quote_id}/convert-to-contract", headers=headers())
    assert contract.status_code == 201, contract.text
    contract_id = contract.json()["contract_id"]
    assert contract.json()["amount_cents"] == 113000

    # 合同：提交待签 → 人工登记签署 → 回款（超限 409）
    assert client.post(
        f"/api/v1/crm/contracts/{contract_id}/submit-for-sign", headers=headers()
    ).status_code == 200
    signed = client.post(
        f"/api/v1/crm/contracts/{contract_id}/register-signature",
        headers=headers(),
        json={"signed_at": "2026-09-17T10:00:00Z"},
    )
    assert signed.status_code == 200 and signed.json()["status"] == "signed"
    paid = client.post(
        f"/api/v1/crm/contracts/{contract_id}/register-payment",
        headers=headers(),
        json={"amount_cents": 113000},
    )
    assert paid.status_code == 200 and paid.json()["paid_cents"] == 113000
    assert client.post(
        f"/api/v1/crm/contracts/{contract_id}/register-payment",
        headers=headers(),
        json={"amount_cents": 1},
    ).status_code == 409


# ------------------------------------------------------------ 敏感字段（掩码 + 揭示）


def test_contact_masking_and_reveal() -> None:
    account = _create_account()
    contact = client.post(
        f"/api/v1/crm/accounts/{account['account_id']}/contacts",
        headers=headers(),
        json={"name": "王小明", "phone": "13800001234", "email": "ming@corp.cn"},
    )
    assert contact.status_code == 201
    contact_id = contact.json()["contact_id"]
    assert contact.json()["phone"] == "138****1234"
    assert contact.json()["email"] == "m***@corp.cn"

    # 列表同样掩码（不给明文）
    listed = client.get(f"/api/v1/crm/accounts/{account['account_id']}/contacts", headers=headers()).json()
    assert listed["items"][0]["phone"] == "138****1234"

    # 揭示：专用端点 + 明文 + no-store
    reveal = client.post(
        f"/api/v1/crm/contacts/{contact_id}/reveal", headers=headers(), json={"field": "phone"}
    )
    assert reveal.status_code == 200
    assert reveal.json()["value"] == "13800001234"
    assert reveal.headers.get("cache-control") == "no-store"
    # 非敏感字段 ⇒ 422
    assert client.post(
        f"/api/v1/crm/contacts/{contact_id}/reveal", headers=headers(), json={"field": "name"}
    ).status_code == 422


# ------------------------------------------------------------ 权限矩阵（own / all）与指标


def test_ownership_and_progress_scope() -> None:
    account = _create_account()  # u-1 的客户
    # 他人（u-2）读 ⇒ 404（不泄露存在性）
    assert client.get(
        f"/api/v1/crm/accounts/{account['account_id']}", headers=headers(user_id="u-2")
    ).status_code == 404
    # ceo 可读
    assert client.get(
        f"/api/v1/crm/accounts/{account['account_id']}", headers=headers(role="ceo", user_id="u-3")
    ).status_code == 200
    # 员工请求 scope=all ⇒ 403；CEO ⇒ 200
    assert client.get("/api/v1/crm/progress/summary?scope=all", headers=headers()).status_code == 403
    summary = client.get("/api/v1/crm/progress/summary?scope=all", headers=headers(role="ceo"))
    assert summary.status_code == 200
    assert summary.json()["pipeline_coverage"] is None  # 无目标 ⇒ null（不编造分母）
    assert summary.json()["pipeline_coverage_note"] == "no_target"
    # 目标写入：employee ⇒ 403；ceo ⇒ 200
    target_payload = {"owner_id": "u-1", "period_month": "2026-09-01", "amount_target_cents": 1000000}
    assert client.put("/api/v1/crm/targets", headers=headers(), json=target_payload).status_code == 403
    assert client.put("/api/v1/crm/targets", headers=headers(role="ceo"), json=target_payload).status_code == 200


def test_reveal_is_audited_without_value(_isolate) -> None:
    """揭露必留痕且明细不含明文（审计层哨兵；服务层另有更细的明细断言）。"""
    service, audit_store = _isolate
    account = _create_account()
    contact = client.post(
        f"/api/v1/crm/accounts/{account['account_id']}/contacts",
        headers=headers(),
        json={"name": "王小明", "phone": "13800001234"},
    ).json()
    client.post(f"/api/v1/crm/contacts/{contact['contact_id']}/reveal", headers=headers(), json={"field": "phone"})
    payload = str(getattr(audit_store, "records", [])) + str(getattr(audit_store, "_records", []))
    assert "13800001234" not in payload