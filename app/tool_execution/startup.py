"""启动期断言（规格 §4.1.6-3）：fail-closed，但**不拒绝整个服务进程启动**。

口径与 §3.5/§3.6 的 `restrict` 空交集一致：拒绝启用真实执行、记 `error` 告警即可，
进程照常起来（一处配置错误不该打挂整个工作台）。
"""

from __future__ import annotations

from .log import get_logger


def assert_real_execution_ready(
    *,
    tool_execution,
    run_records,
    tool_actions,
    catalog,
) -> bool:
    """断言真实执行所需的装配件齐备；返回 `True` = 放行，`False` = 拒绝启用（已记 error）。

    - `backend=dsh` 时 `tool_execution`、`run_records`、`tool_actions` 三者必须非 `None`；
    - `ToolSpecCatalog` 中每个工具的每个参数都必须显式声明 `param_roles`。
    """
    problems: list[str] = []
    if tool_execution is None:
        problems.append("tool_execution 未装配")
    if run_records is None:
        problems.append("run_records 未装配")
    if tool_actions is None:
        problems.append("tool_actions 未装配")
    if catalog is None:
        problems.append("ToolSpecCatalog 未装配")
    else:
        problems.extend(catalog.param_role_problems())

    if problems:
        logger = get_logger()
        for problem in problems:
            logger.error("段二真实执行未启用：%s", problem)
        return False
    return True
