"""工具规格目录 `ToolSpecCatalog`（规格 §3.1 / §3.1.1）。

⚠️ 命名冲突：仓库内 `app/planner/models.py` 已有**同名不同构**的 `ToolCatalog`（规划器白名单），
本模块的 `ToolSpecCatalog` **不得复用该名、不得扩该类**；两者互不影响（§3.1 第七轮 P11）。

fail-closed 口径（§3.1 `param_roles`，P1）：`param_roles` **无默认值**——`params_schema` 的每个参数
都必须显式声明 `control` / `body`，**任一参数未声明即拒绝装配**（不是"默认按控制参数入库"）。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Mapping

from ..domain import RiskLevel
from .errors import ToolExecutionConfigError


class ParamRole(StrEnum):
    """参数角色：决定 ⑥ 落库时进 `args_json`（control）还是受控密文列（body）。"""

    CONTROL = "control"
    BODY = "body"


@dataclass(frozen=True)
class ToolSpec:
    """单个工具的执行声明（§3.1 字段表）。"""

    key: str
    params_schema: Mapping[str, str]
    param_roles: Mapping[str, ParamRole]
    risk_level: RiskLevel
    has_side_effect: bool
    requires_approval: bool
    reversible: bool

    def param_role_problems(self) -> list[str]:
        """返回本工具的参数角色声明问题（空列表 = 合规）。"""
        schema = set(self.params_schema)
        roles = set(self.param_roles)
        problems = [f"{self.key}.{name} 未声明 param_roles" for name in sorted(schema - roles)]
        problems += [
            f"{self.key}.{name} 声明了 param_roles 但不在 params_schema 内"
            for name in sorted(roles - schema)
        ]
        return problems


class ToolSpecCatalog:
    """工具规格目录；构造期即 fail-closed 校验（未声明角色 / 风险档不合规即拒绝装配）。"""

    def __init__(self, specs: tuple[ToolSpec, ...] | list[ToolSpec]) -> None:
        mapping: dict[str, ToolSpec] = {}
        problems: list[str] = []
        for spec in specs:
            if spec.key in mapping:
                raise ToolExecutionConfigError(f"工具目录存在重复 key：{spec.key}")
            mapping[spec.key] = spec
            problems.extend(spec.param_role_problems())
            if spec.risk_level not in RiskLevel:
                problems.append(f"{spec.key} 的 risk_level 非法：{spec.risk_level}")
            if spec.has_side_effect and not spec.requires_approval:
                problems.append(f"{spec.key} 有副作用但未要求审批")
            if not spec.reversible and spec.risk_level not in {RiskLevel.HIGH, RiskLevel.CRITICAL}:
                problems.append(f"{spec.key} 不可逆但风险档低于 high")
        if problems:
            raise ToolExecutionConfigError("工具目录声明不完整：" + "；".join(problems))
        self._specs = mapping

    @property
    def specs(self) -> tuple[ToolSpec, ...]:
        return tuple(self._specs.values())

    def get(self, key: str) -> ToolSpec:
        spec = self._specs.get(key)
        if spec is None:
            raise ToolExecutionConfigError(f"工具不在组装面内：{key}")
        return spec

    def param_role_problems(self) -> list[str]:
        """复核全目录的参数角色声明（启动期断言用；构造期已 fail-closed）。"""
        problems: list[str] = []
        for spec in self._specs.values():
            problems.extend(spec.param_role_problems())
        return problems


def default_tool_specs() -> tuple[ToolSpec, ...]:
    """§3.1.1 附录的工具清单与定档（逐条照抄，不得在实现时即兴定档）。"""
    return (
        ToolSpec(
            key="fs.list",
            params_schema={"path": "path"},
            param_roles={"path": ParamRole.CONTROL},
            risk_level=RiskLevel.LOW,
            has_side_effect=False,
            requires_approval=False,
            reversible=True,
        ),
        ToolSpec(
            key="fs.read",
            params_schema={"path": "path", "max_bytes": "integer"},
            param_roles={"path": ParamRole.CONTROL, "max_bytes": ParamRole.CONTROL},
            risk_level=RiskLevel.LOW,
            has_side_effect=False,
            requires_approval=False,
            reversible=True,
        ),
        ToolSpec(
            key="fs.stat",
            params_schema={"path": "path"},
            param_roles={"path": ParamRole.CONTROL},
            risk_level=RiskLevel.LOW,
            has_side_effect=False,
            requires_approval=False,
            reversible=True,
        ),
        ToolSpec(
            key="cmd.run",
            params_schema={"executable": "string", "args": "array"},
            param_roles={"executable": ParamRole.CONTROL, "args": ParamRole.CONTROL},
            risk_level=RiskLevel.MEDIUM,
            has_side_effect=False,
            requires_approval=False,
            reversible=True,
        ),
        ToolSpec(
            key="fs.write",
            params_schema={"path": "path", "content": "string"},
            param_roles={"path": ParamRole.CONTROL, "content": ParamRole.BODY},
            risk_level=RiskLevel.MEDIUM,
            has_side_effect=True,
            requires_approval=True,
            reversible=True,
        ),
        ToolSpec(
            key="fs.overwrite",
            params_schema={"path": "path", "content": "string"},
            param_roles={"path": ParamRole.CONTROL, "content": ParamRole.BODY},
            risk_level=RiskLevel.HIGH,
            has_side_effect=True,
            requires_approval=True,
            reversible=False,
        ),
        ToolSpec(
            key="fs.delete",
            params_schema={"path": "path"},
            param_roles={"path": ParamRole.CONTROL},
            risk_level=RiskLevel.HIGH,
            has_side_effect=True,
            requires_approval=True,
            reversible=False,
        ),
        ToolSpec(
            key="artifact.export",
            params_schema={"path": "path", "target": "string"},
            param_roles={"path": ParamRole.CONTROL, "target": ParamRole.CONTROL},
            risk_level=RiskLevel.CRITICAL,
            has_side_effect=True,
            requires_approval=True,
            reversible=False,
        ),
    )


def build_tool_spec_catalog() -> ToolSpecCatalog:
    return ToolSpecCatalog(default_tool_specs())
