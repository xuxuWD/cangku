"""实时流写入网关（P2b §2.2）：脱敏 → 熔断 → 落库；熔断 / 写失败**显式告知 + 审计**。

- 顺序（规格 §2.2）：`redact_payload`（同一函数同规则；掩码幂等 ⇒ 不双重掩码）→ 组装帧 →
  同事务落库（序号分配在仓储内完成）。
- **熔断**：帧数 / 字节超上限 ⇒ 停止写后续帧，追加 `stream.unavailable` 告知帧（reason 为受控枚举）
  + 审计 `conversation.stream.unavailable`；**执行继续**（流是视图，权威结果在消息 / 运行 / 审计）。
- **写失败**：尽力置 `unavailable('write_failed')` + 审计；**不得**让流写入失败阻断或改变执行结果。
- **终态**：`run.completed` / `run.failed` ⇒ 状态置 `completed` / `failed` + `expires_at`。
- 脱敏失败 ⇒ **不落原文**（回退空 payload，fail-closed）。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from ..audit.models import AuditAction
from .stream import (
    REASON_BYTE_LIMIT,
    REASON_FRAME_LIMIT,
    REASON_WRITE_FAILED,
    STATUS_COMPLETED,
    STATUS_FAILED,
    StreamFrame,
    _now,
    _payload_bytes,
)

TERMINAL_FAILED_KIND = "run.failed"


def _redact(payload: dict[str, Any]) -> dict[str, Any]:
    """统一脱敏出口（复用运行时契约的 `redact_payload`；导入失败时 fail-closed 返回空）。"""
    try:
        from ..runtime.contracts import redact_payload

        return dict(redact_payload(payload))
    except Exception:  # noqa: BLE001 - 脱敏不可用 ⇒ 不落原文
        return {}


class StreamWriter:
    """把一次执行过程中的事件写为流帧（唯一写入入口）。"""

    def __init__(self, store, *, audit=None, retention_days: int = 7) -> None:
        self.store = store
        self.audit = audit
        self.retention_days = int(retention_days)

    def _expiry(self) -> datetime:
        return _now() + timedelta(days=self.retention_days)

    # ------------------------------------------------------------ 主入口

    def write(
        self,
        tenant_id: str,
        conversation_id: str,
        run_id: str,
        *,
        kind: str,
        payload: dict[str, Any] | None = None,
        is_terminal: bool = False,
    ) -> StreamFrame | None:
        """写一帧（脱敏 → 熔断 → 落库）；熔断 / 失败返回 `None`（已显式告知 + 审计）。"""
        redacted = _redact(payload or {})
        try:
            frame = self.store.append_frame(
                tenant_id, conversation_id, run_id, kind=kind, payload=redacted, is_terminal=is_terminal
            )
        except Exception:  # noqa: BLE001 - 写失败不阻断执行
            self._mark_unavailable(tenant_id, conversation_id, run_id, reason=REASON_WRITE_FAILED)
            return None
        if frame is None:
            self._mark_unavailable(
                tenant_id,
                conversation_id,
                run_id,
                reason=self._limit_reason(tenant_id, conversation_id, run_id, redacted),
            )
            return None
        if is_terminal:
            status = STATUS_FAILED if kind == TERMINAL_FAILED_KIND else STATUS_COMPLETED
            try:
                self.store.set_terminal(
                    tenant_id, conversation_id, run_id, status=status, expires_at=self._expiry()
                )
            except Exception:  # noqa: BLE001 - 终态标记失败只降级（读端按帧终态关流）
                pass
        return frame

    # ------------------------------------------------------------ 内部

    def _limit_reason(
        self, tenant_id: str, conversation_id: str, run_id: str, payload: dict[str, Any]
    ) -> str:
        try:
            state = self.store.get_state(tenant_id, conversation_id, run_id)
        except Exception:  # noqa: BLE001
            state = None
        if state is not None and state.frame_count >= int(self.store.max_frames):
            return REASON_FRAME_LIMIT
        if state is not None and state.byte_count + _payload_bytes(payload) > int(self.store.max_bytes):
            return REASON_BYTE_LIMIT
        return REASON_FRAME_LIMIT if state is None else REASON_BYTE_LIMIT

    def _mark_unavailable(
        self, tenant_id: str, conversation_id: str, run_id: str, *, reason: str
    ) -> None:
        try:
            self.store.append_unavailable(
                tenant_id, conversation_id, run_id, reason=reason, expires_at=self._expiry()
            )
        except Exception:  # noqa: BLE001 - 告知帧写入失败仍须留痕
            pass
        if self.audit is not None:
            try:
                self.audit.record(
                    AuditAction.CONVERSATION_STREAM_UNAVAILABLE,
                    tenant_id=tenant_id,
                    actor_id=None,
                    target_type="conversation",
                    target_id=conversation_id,
                    detail={"reason": reason, "run_id": run_id},
                )
            except Exception:  # noqa: BLE001 - 审计失败不得影响执行
                pass

    # ------------------------------------------------------------ 便捷出口

    def watermark(self, tenant_id: str, conversation_id: str, run_id: str, message_id: str) -> None:
        """助手消息落进消息表后回填水位（供客户端判断「结果已可经消息表读取」）。"""
        try:
            self.store.persist_watermark(tenant_id, conversation_id, run_id, message_id)
        except Exception:  # noqa: BLE001 - 水位失败不影响结果
            pass