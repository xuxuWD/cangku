"""`ToolSpecCatalog` 的 `param_roles` fail-closed 口径（规格 §3.1 / §3.1.1 / §4.1.6-3）。

判据：**任一参数未显式声明角色即拒绝装配**（无默认值）；附录 §3.1.1 的工具清单逐条可查。
"""

from __future__ import annotations

import pytest

from app.domain import RiskLevel
from app.tool_execution.catalog import (
    ParamRole,
    ToolSpec,
    ToolSpecCatalog,
    default_tool_specs,
)
from app.tool_execution.errors import ToolExecutionConfigError


def _spec(**overrides) -> ToolSpec:
    base = dict(
        key="fs.write",
        params_schema={"path": "string", "content": "string"},
        param_roles={"path": ParamRole.CONTROL, "content": ParamRole.BODY},
        risk_level=RiskLevel.MEDIUM,
        has_side_effect=True,
        requires_approval=True,
        reversible=True,
    )
    base.update(overrides)
    return ToolSpec(**base)


def test_rejects_param_without_declared_role() -> None:
    with pytest.raises(ToolExecutionConfigError):
        ToolSpecCatalog([_spec(param_roles={"path": ParamRole.CONTROL})])


def test_rejects_role_for_unknown_param() -> None:
    with pytest.raises(ToolExecutionConfigError):
        ToolSpecCatalog(
            [
                _spec(
                    param_roles={
                        "path": ParamRole.CONTROL,
                        "content": ParamRole.BODY,
                        "ghost": ParamRole.BODY,
                    }
                )
            ]
        )


def test_rejects_side_effect_without_approval() -> None:
    with pytest.raises(ToolExecutionConfigError):
        ToolSpecCatalog([_spec(has_side_effect=True, requires_approval=False)])


def test_rejects_irreversible_below_high() -> None:
    with pytest.raises(ToolExecutionConfigError):
        ToolSpecCatalog([_spec(risk_level=RiskLevel.LOW, reversible=False)])


def test_rejects_duplicate_tool_key() -> None:
    with pytest.raises(ToolExecutionConfigError):
        ToolSpecCatalog([_spec(), _spec()])


def test_default_catalog_declares_every_param_role() -> None:
    catalog = ToolSpecCatalog(default_tool_specs())
    # 无问题 = 每个工具的每个参数都已显式声明角色（构造期已保证，此处显式复核）。
    assert catalog.param_role_problems() == []
    body_tools = {
        spec.key for spec in catalog.specs if ParamRole.BODY in spec.param_roles.values()
    }
    # §3.1.1：P2a 段二内仅 fs.write / fs.overwrite 含 body 类参数；
    # P5a 起 crm.activity.log 的 subject / content 亦为 body 类（进程内工具同样受受控密文列保护）。
    assert body_tools == {"fs.write", "fs.overwrite", "crm.activity.log"}


def test_default_catalog_covers_appendix_tool_list() -> None:
    catalog = ToolSpecCatalog(default_tool_specs())
    expected = {
        "fs.list",
        "fs.read",
        "fs.stat",
        "cmd.run",
        "fs.write",
        "fs.overwrite",
        "fs.delete",
        "artifact.export",
    }
    # P5a CRM 受控工具面（crm-p5a-design §2.8）：读 ×4（low）+ 写 ×1（medium）。
    expected |= {
        "crm.account.search",
        "crm.account.get",
        "crm.opportunity.list",
        "crm.progress.summary",
        "crm.activity.log",
    }
    assert {spec.key for spec in catalog.specs} == expected
    # critical 的承担工具 = artifact.export（§3.1.1）。
    assert catalog.get("artifact.export").risk_level is RiskLevel.CRITICAL
    # CRM 写工具的风险档 = medium（走九步闸门审批；§2.8）。
    assert catalog.get("crm.activity.log").risk_level is RiskLevel.MEDIUM
