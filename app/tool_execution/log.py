"""工具执行的独立日志通道。

**刻意不写审计日志通道**（`company_workbench.audit`）：审计只承载工具动作的
`tool.executed` / `tool.blocked`，装配告警属运行日志，混入会污染审计可读性。
"""

from __future__ import annotations

import logging


LOGGER_NAME = "company_workbench.tool_execution"


def get_logger() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)
