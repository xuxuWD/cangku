from __future__ import annotations

import json
import logging

from .models import AuditRecord


AUDIT_LOGGER_NAME = "company_workbench.audit"
_configured = False


def configure_audit_logging(level: str) -> None:
    """安装单行 JSON 输出；幂等，重复调用不叠加 handler。"""
    global _configured
    logger = logging.getLogger(AUDIT_LOGGER_NAME)
    resolved = logging.getLevelName(str(level).upper())
    logger.setLevel(resolved if isinstance(resolved, int) else logging.INFO)
    if _configured:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.propagate = False
    _configured = True


def emit_audit_line(record: AuditRecord) -> None:
    """把审计记录写成一行 JSON；字段固定，不写入任何未声明内容。"""
    payload = {
        "event": "audit",
        "action": record.action.value,
        "actor_id": record.actor_id,
        "tenant_id": record.tenant_id,
        "target_type": record.target_type,
        "target_id": record.target_id,
        "phone_masked": record.phone_masked,
        "detail": record.detail,
        "record_id": record.record_id,
        "occurred_at": record.occurred_at.isoformat(),
    }
    logging.getLogger(AUDIT_LOGGER_NAME).info(json.dumps(payload, ensure_ascii=False, sort_keys=True))
