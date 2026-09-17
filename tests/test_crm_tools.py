"""CRM 受控工具面（§2.8）测试：分发 / 参数白名单 / 操作者上下文 / 数据范围（own）/ 剥离。

网络与容器均不涉及（进程内执行器 + 假 inner 路由）。
"""

from __future__ import annotations

import pytest

from app.crm import InMemoryCrmStore
from app.crm.service import CrmService
from app.crm.tools import ALLOWED_PARAMS, CrmRoutingExecutor, CrmToolError, CrmToolExecutor
from app.domain import UserContext
from tests.test_crm_service import FakeAudit

TENANT = "t-crm"
ALICE = "acct-alice"
BOB = "acct-bob"


def _alice() -> UserContext:
    return UserContext(TENANT, ALICE, "employee")


def _bob() -> UserContext:
    return UserContext(TENANT, BOB, "employee")


@pytest.fixture()
def executor():
    audit = FakeAudit()
    service = CrmService(InMemoryCrmStore(), audit=audit)
    account = service.create_account(_alice(), name="某某公司", industry="制造业")
    service.create_contact(_alice(), name="王小明", account_id=account.account_id, phone="13800001234", email="ming@corp.cn")
    opportunity = service.create_opportunity(_alice(), account_id=account.account_id, name="商机A", amount_cents=100000)
    activity = service.log_activity(_alice(), kind="call", subject="电话沟通", account_id=account.account_id)
    service.create_account(_bob(), name="Bob 的客户")
    return CrmToolExecutor(lambda: service), {
        "account": account, "opportunity": opportunity, "activity": activity,
    }


def _call(executor, key: str, params: dict, *, requester: str = ALICE):
    return executor.execute(
        tool_key=key, params=params, workspace_path="", requester=requester, tenant_id=TENANT
    )


def test_account_search_is_own_scoped_and_masks_nothing_sensitive(executor) -> None:
    tool, ctx = executor
    outcome = _call(tool, "crm.account.search", {"query": "某某"})
    assert outcome.ok
    assert outcome.summary["returned"] == 1
    assert outcome.summary["accounts"][0]["name"] == "某某公司"
    # bob 视角：看不到 alice 的客户
    bob_outcome = _call(tool, "crm.account.search", {}, requester=BOB)
    assert bob_outcome.summary["returned"] == 1
    assert bob_outcome.summary["accounts"][0]["name"] == "Bob 的客户"


def test_account_get_returns_opportunities_and_activities_without_pii(executor) -> None:
    tool, ctx = executor
    outcome = _call(tool, "crm.account.get", {"account_id": ctx["account"].account_id})
    assert outcome.ok
    assert outcome.summary["account"]["account_id"] == ctx["account"].account_id
    assert outcome.summary["opportunities"][0]["opportunity_id"] == ctx["opportunity"].opportunity_id
    assert len(outcome.summary["recent_activities"]) == 1
    payload = str(outcome.summary)
    assert "13800001234" not in payload and "ming@corp.cn" not in payload and "王小明" not in payload


def test_opportunity_list_validates_stage_and_limit(executor) -> None:
    tool, _ = executor
    assert _call(tool, "crm.opportunity.list", {"stage": "qualification"}).ok
    with pytest.raises(CrmToolError):
        _call(tool, "crm.opportunity.list", {"stage": "bogus"})
    with pytest.raises(CrmToolError):
        _call(tool, "crm.opportunity.list", {"limit": "10"})


def test_progress_summary_only_me_scope(executor) -> None:
    tool, _ = executor
    outcome = _call(tool, "crm.progress.summary", {})
    assert outcome.ok and outcome.summary["scope"] == "me"
    assert outcome.summary["metrics"]["pipeline_coverage_note"] == "no_target"
    with pytest.raises(CrmToolError):
        _call(tool, "crm.progress.summary", {"scope": "all"})


def test_activity_log_writes_as_agent_and_rejects_task_kind(executor) -> None:
    tool, ctx = executor
    outcome = _call(
        tool, "crm.activity.log",
        {"kind": "note", "subject": "AI 记录", "content": "客户有意向", "account_id": ctx["account"].account_id},
    )
    assert outcome.ok and outcome.summary["tool"] == "crm.activity.log"
    with pytest.raises(CrmToolError):
        # task 类属人类计划：数字员工禁写（service 拒绝 ⇒ 工具层映射为失败）
        _call(tool, "crm.activity.log", {"kind": "task", "subject": "x"})


def test_unknown_params_and_missing_context_rejected(executor) -> None:
    tool, _ = executor
    with pytest.raises(CrmToolError):
        _call(tool, "crm.account.search", {"bogus_param": 1})
    with pytest.raises(CrmToolError):
        tool.execute(tool_key="crm.account.search", params={}, workspace_path="")  # 缺 requester/tenant
    with pytest.raises(CrmToolError):
        _call(tool, "fs.read", {"path": "/x"})  # 非 CRM 工具不在本执行器职责内


def test_routing_executor_splits_crm_and_inner() -> None:
    class FakeInner:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def execute(self, *, tool_key, params, workspace_path, spec=None, environment=None, requester=None, tenant_id=None):
            self.calls.append({"tool_key": tool_key, "requester": requester, "tenant_id": tenant_id})
            from app.tool_execution.executor import ExecutionOutcome

            return ExecutionOutcome(ok=True, timed_out=False, summary={"inner": True})

    service = CrmService(InMemoryCrmStore(), audit=FakeAudit())
    inner = FakeInner()
    router = CrmRoutingExecutor(crm=CrmToolExecutor(lambda: service), inner=inner)
    crm_outcome = router.execute(
        tool_key="crm.progress.summary", params={}, workspace_path="", requester=ALICE, tenant_id=TENANT
    )
    assert crm_outcome.summary["tool"] == "crm.progress.summary"
    inner_outcome = router.execute(
        tool_key="fs.list", params={"path": "/workspace"}, workspace_path="", requester=ALICE, tenant_id=TENANT
    )
    assert inner_outcome.summary == {"inner": True}
    assert inner.calls == [{"tool_key": "fs.list", "requester": ALICE, "tenant_id": TENANT}]


def test_allowed_params_match_catalog_schema() -> None:
    from app.tool_execution.catalog import build_tool_spec_catalog

    catalog = build_tool_spec_catalog()
    for spec in catalog.specs:
        if not spec.key.startswith("crm."):
            continue
        assert set(spec.params_schema) == set(ALLOWED_PARAMS[spec.key]), spec.key
    assert len({key for key in ALLOWED_PARAMS}) == 5