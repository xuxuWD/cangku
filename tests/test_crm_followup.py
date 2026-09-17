"""跟进计划生成器（§2.7）测试：结构校验 / 引用真实性闸门 / 失败不落库 / 输入脱敏。

口径：全部经**脚本化生成器**（不真连模型）；网关失败 ⇒ `FollowupPlanError`（接口层 502）。
"""

from __future__ import annotations

import pytest

from app.audit.models import AuditAction
from app.crm import InMemoryCrmStore
from app.crm.followup import INSUFFICIENT_SUMMARY, FollowupPlanError, MockFollowupGenerator, sanitize_output
from app.crm.service import CrmService
from app.domain import UserContext
from tests.test_crm_service import FakeAudit

TENANT = "t-crm"
ALICE = "acct-alice"
OTHER_TENANT = "t-other"


class ScriptedGenerator:
    """脚本化生成器：返回固定 payload（或抛失败），记录收到的摘要。"""

    def __init__(self, payload: dict | None = None, *, fail: bool = False) -> None:
        self.payload = payload or {}
        self.fail = fail
        self.model_key = "test-model"
        self.seen: list[dict] = []

    def generate(self, summary: dict) -> dict:
        self.seen.append(summary)
        if self.fail:
            raise FollowupPlanError("gateway down")
        return self.payload


def _alice() -> UserContext:
    return UserContext(TENANT, ALICE, "employee")


def _setup(generator) -> tuple[CrmService, FakeAudit, dict]:
    audit = FakeAudit()
    service = CrmService(InMemoryCrmStore(), audit=audit, followup_generator=generator)
    account = service.create_account(_alice(), name="某某公司")
    contact = service.create_contact(_alice(), name="王小明", account_id=account.account_id, phone="13800001234")
    opportunity = service.create_opportunity(_alice(), account_id=account.account_id, name="商机A", amount_cents=100000)
    activity = service.log_activity(_alice(), kind="call", subject="电话沟通", account_id=account.account_id)
    return service, audit, {
        "account": account, "contact": contact, "opportunity": opportunity, "activity": activity,
    }


def test_mock_generator_yields_insufficient_evidence() -> None:
    service, audit, ctx = _setup(MockFollowupGenerator())
    insight = service.generate_followup_plan(_alice(), ctx["account"].account_id)
    assert insight.content["insufficient_evidence"] is True
    assert insight.content["summary"] == INSUFFICIENT_SUMMARY
    assert insight.content["actions"] == []
    assert insight.model_key == "mock"
    generated = [r for r in audit.records if r.action is AuditAction.CRM_INSIGHT_GENERATED]
    assert generated[0].detail["status"] == "insufficient"


def test_valid_actions_pass_reference_gate_and_persist() -> None:
    ids = {"account": "placeholder"}
    generator = ScriptedGenerator()  # payload 在下方按真实 id 组装
    service, audit, ctx = _setup(generator)
    generator.payload = {
        "actions": [
            {
                "action_type": "call",
                "target_ref": f"contact:{ctx['contact'].contact_id}",
                "reason": "距上次互动较久，建议电话回访",
                "evidence_refs": [
                    f"activity:{ctx['activity'].activity_id}",
                    f"opportunity:{ctx['opportunity'].opportunity_id}",
                ],
                "confidence": 0.72,
            }
        ],
        "summary": "建议尽快电话回访并推进商机",
    }
    insight = service.generate_followup_plan(_alice(), ctx["account"].account_id)
    assert "insufficient_evidence" not in insight.content  # 非「依据不足」路径
    action = insight.content["actions"][0]
    assert action["action_type"] == "call"
    assert action["evidence_refs"] == [
        f"activity:{ctx['activity'].activity_id}",
        f"opportunity:{ctx['opportunity'].opportunity_id}",
    ]
    assert action["confidence"] == 0.72
    assert insight.dropped_refs == []
    assert insight.input_digest and len(insight.input_digest) == 64
    generated = [r for r in audit.records if r.action is AuditAction.CRM_INSIGHT_GENERATED]
    assert generated[0].detail["status"] == "ok"
    # 落库回看
    items, total = service.list_insights(_alice(), ctx["account"].account_id)
    assert total == 1 and items[0].insight_id == insight.insight_id


def test_invalid_and_cross_tenant_references_are_dropped() -> None:
    generator = ScriptedGenerator()
    service, _, ctx = _setup(generator)
    generator.payload = {
        "actions": [
            {
                "action_type": "send_material",
                "target_ref": f"opportunity:{ctx['opportunity'].opportunity_id}",
                "reason": "需要补充资料",
                "evidence_refs": [
                    "activity:does-not-exist",              # 不存在
                    "opportunity:cross-tenant-id",          # 不存在（跨租户与不存在同判）
                    "account:some-other-account",           # 不属该客户
                ],
                "confidence": 0.5,
            }
        ],
        "summary": "建议发送资料",
    }
    insight = service.generate_followup_plan(_alice(), ctx["account"].account_id)
    assert len(insight.content["actions"]) == 1
    assert insight.content["actions"][0]["evidence_refs"] == []
    reasons = [item["reason"] for item in insight.dropped_refs]
    assert reasons.count("invalid_evidence_ref") == 3


def test_all_invalid_yields_server_generated_insufficient_text() -> None:
    generator = ScriptedGenerator()
    service, _, ctx = _setup(generator)
    generator.payload = {
        "actions": [
            {
                "action_type": "call",
                "target_ref": "contact:ghost",       # target 无效 ⇒ 整条丢弃
                "reason": "x",
                "evidence_refs": [],
                "confidence": 0.9,
            }
        ],
        "summary": "模型自由文本",
    }
    insight = service.generate_followup_plan(_alice(), ctx["account"].account_id)
    assert insight.content["insufficient_evidence"] is True
    assert insight.content["summary"] == INSUFFICIENT_SUMMARY  # 服务端固定文案，非模型文本
    assert insight.dropped_refs[0]["reason"] == "invalid_target_ref"


def test_structural_violations_are_dropped() -> None:
    generator = ScriptedGenerator()
    service, _, ctx = _setup(generator)
    generator.payload = {
        "actions": [
            {"action_type": "unknown_action", "target_ref": "account:x", "reason": "", "evidence_refs": [], "confidence": 0.5},
            {"action_type": "call", "target_ref": "bogus-ref", "reason": "", "evidence_refs": [], "confidence": 0.5},
            {"action_type": "call", "target_ref": f"account:{ctx['account'].account_id}", "reason": "ok",
             "evidence_refs": [], "confidence": 5},
            "not-a-dict",
        ],
        "summary": "s" * (400),
    }
    insight = service.generate_followup_plan(_alice(), ctx["account"].account_id)
    assert len(insight.content["actions"]) == 1
    # confidence 越界被 clamp 到 1.0；summary 超长被截断
    assert insight.content["actions"][0]["confidence"] == 1.0
    assert len(insight.content["summary"]) == 300
    reasons = {item["reason"] for item in insight.dropped_refs}
    assert {"invalid_action_type", "invalid_target_ref", "invalid_action"} <= reasons


def test_gateway_failure_raises_and_does_not_persist() -> None:
    service, audit, ctx = _setup(ScriptedGenerator(fail=True))
    with pytest.raises(FollowupPlanError):
        service.generate_followup_plan(_alice(), ctx["account"].account_id)
    items, total = service.list_insights(_alice(), ctx["account"].account_id)
    assert total == 0
    assert [r for r in audit.records if r.action is AuditAction.CRM_INSIGHT_GENERATED] == []


def test_summary_excludes_sensitive_fields() -> None:
    generator = ScriptedGenerator()
    service, _, ctx = _setup(generator)
    service.generate_followup_plan(_alice(), ctx["account"].account_id)
    seen = generator.seen[0]
    payload = str(seen)
    assert "13800001234" not in payload   # 电话不入模型输入
    assert "王小明" not in payload        # 联系人姓名不入模型输入
    assert seen["contact_count"] == 1
    assert seen["account"]["name"] == "某某公司"


def test_sanitize_output_limits_actions_and_refs() -> None:
    raw = {
        "actions": [
            {
                "action_type": "call",
                "target_ref": "account:a1",
                "reason": "r",
                "evidence_refs": [f"activity:a{i}" for i in range(12)],
                "confidence": 0.3,
            }
            for _ in range(8)
        ],
        "summary": "ok",
    }
    cleaned, drops = sanitize_output(raw)
    assert len(cleaned["actions"]) == 5
    assert len(cleaned["actions"][0]["evidence_refs"]) == 8
    assert any(item["reason"] == "too_many_actions" for item in drops)