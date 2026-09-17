"""CRM（P5a）：客户主数据 + 商务主线（报价 → 合同）+ 智能化打底。

规格：`docs/superpowers/specs/2026-09-17-crm-p5a-design.md`（已评审，2026-09-17）。
- `models`：领域模型 / 状态机白名单 / 权限判定（单一来源）
- `masking`：敏感字段密级（掩码 / 剥离）
- `pricing`：报价金额引擎（纯函数）
- `store` / `store_postgres`：内存与 PG 仓储（方法集一致）
- `service`：业务服务（权限 / 状态机 / 审计 / 单事务转化）
"""

from .models import (
    HEALTH_BAND_GREEN,
    HEALTH_BAND_YELLOW,
    HEALTH_WEIGHTS,
    SENSITIVE_FIELDS,
)
from .service import CrmService
from .store import InMemoryCrmStore

__all__ = [
    "CrmService",
    "InMemoryCrmStore",
    "SENSITIVE_FIELDS",
    "HEALTH_WEIGHTS",
    "HEALTH_BAND_GREEN",
    "HEALTH_BAND_YELLOW",
]