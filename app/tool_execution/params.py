"""② 参数结构化校验（规格 §3.2 / §3.1）。

口径（fail-closed）：
* 参数必须是对象；
* **未知字段一律拒绝**（白名单）——不得用「忽略未知字段」的宽松解析；
* schema 声明的每个参数都必须存在且类型相符。

本模块不做默认值填充：目录未声明默认值，缺参即拒（保守分支）。
"""

from __future__ import annotations

from typing import Any, Mapping

from .catalog import ToolSpec


class ParamValidationError(ValueError):
    """参数不符合 schema（接口层按 422 处理；`reason_code=param_invalid`）。"""


_TYPE_CHECKS: dict[str, object] = {
    "path": lambda value: isinstance(value, str) and value != "",
    "string": lambda value: isinstance(value, str),
    "integer": lambda value: isinstance(value, int) and not isinstance(value, bool),
    "boolean": lambda value: isinstance(value, bool),
    "array": lambda value: isinstance(value, list),
}


def validate_params(spec: ToolSpec, params: Mapping[str, Any]) -> dict[str, Any]:
    """校验并返回一张**只含 schema 声明键**的参数副本（未声明键一律拒绝）。"""
    if not isinstance(params, Mapping):
        raise ParamValidationError("参数必须是对象")
    unknown = sorted(str(key) for key in params if key not in spec.params_schema)
    if unknown:
        raise ParamValidationError(f"存在未声明的参数：{','.join(unknown)}")
    validated: dict[str, Any] = {}
    for name, type_name in spec.params_schema.items():
        if name not in params:
            raise ParamValidationError(f"缺少必填参数：{name}")
        check = _TYPE_CHECKS.get(type_name)
        if check is None:
            raise ParamValidationError(f"schema 类型未登记：{type_name}")
        if not check(params[name]):
            raise ParamValidationError(f"参数类型不符：{name}")
        validated[name] = params[name]
    return validated


def path_param_names(spec: ToolSpec) -> tuple[str, ...]:
    """schema 中声明为「路径」类型的参数名（供 §4.1.4 规则 4 与 ③ 使用）。"""
    return tuple(name for name, type_name in spec.params_schema.items() if type_name == "path")
