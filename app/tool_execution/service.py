"""`ToolExecutionService`：段二工具执行的装配与执行入口（规格 §4.1.6）。

本步骤交付范围（**不含** ①–⑨ 闸门全流程）：
    - 构造依赖按 §4.1.6-1 装配；
    - `resume(...)` 的**入口与失败语义骨架**：
        · §4.1.6-1.1 的两条加解密失败语义（⑥ 加密失败 → 503 不写审计；重跑解密失败 → 502 + tool.blocked）；
        · §4.1.6-5 失败表的码位映射（`RE_RUN_FAILURE_SEMANTICS`）。

**①–⑨ 闸门全流程属后续步骤**：未实现的步骤一律显式 `raise NotImplementedError` 并标注步骤号，
**不得假装成功**。
"""

from __future__ import annotations

from dataclasses import dataclass

from ..audit.models import AuditAction
from .catalog import ParamRole
from .errors import BodyCipherError, ToolExecutionError
from .log import get_logger
from .store import ReasonCode, ToolAction, ToolActionStatus


@dataclass(frozen=True)
class FailureSemantics:
    """一次失败的受控语义：HTTP 码 + reason 枚举 + 027 行落地 + 审计动作。"""

    http_status: int
    reason_code: ReasonCode | None
    action_status: ToolActionStatus
    audit_action: AuditAction | None


# §4.1.6-5 失败表（**审批后重跑路径**）：键 = 失败点。
RE_RUN_FAILURE_SEMANTICS: dict[str, FailureSemantics] = {
    # ① 工具已不在组装面（审批后重跑路径取 409，状态漂移冲突；首次执行路径由契约取 422）
    "not_in_catalog": FailureSemantics(409, ReasonCode.NOT_IN_CATALOG, ToolActionStatus.APPROVED, AuditAction.TOOL_BLOCKED),
    "param_invalid": FailureSemantics(422, ReasonCode.PARAM_INVALID, ToolActionStatus.APPROVED, AuditAction.TOOL_BLOCKED),
    "path_denied": FailureSemantics(403, ReasonCode.PATH_DENIED, ToolActionStatus.APPROVED, AuditAction.TOOL_BLOCKED),
    # ④ 黑名单命中：**置 rejected**，不允许审批放行
    "blacklisted": FailureSemantics(403, ReasonCode.BLACKLISTED, ToolActionStatus.REJECTED, AuditAction.TOOL_BLOCKED),
    # ⑦ 之后·正文解密失败（P2 新增）：保持 approved，可重试 / 可人工介入
    "body_decrypt_failed": FailureSemantics(502, ReasonCode.RUNTIME_ERROR, ToolActionStatus.APPROVED, AuditAction.TOOL_BLOCKED),
    "timeout": FailureSemantics(504, ReasonCode.TIMEOUT, ToolActionStatus.APPROVED, AuditAction.TOOL_BLOCKED),
    "runtime_error": FailureSemantics(502, ReasonCode.RUNTIME_ERROR, ToolActionStatus.APPROVED, AuditAction.TOOL_BLOCKED),
    "executed": FailureSemantics(201, None, ToolActionStatus.APPROVED, AuditAction.TOOL_EXECUTED),
}

# §4.1.6-1.1①：⑥ 落库前加密失败 → 503、不落库、**不写 tool.* 审计**（未产生副作用）。
ENCRYPT_FAILURE_SEMANTICS = FailureSemantics(503, None, ToolActionStatus.PENDING, None)


@dataclass(frozen=True)
class ToolExecutionResult:
    """执行结果（§4.1.6-7 决议端点响应体的 `execution` 字段来源）。"""

    outcome: str
    code: int | None = None
    message_id: str | None = None


class ToolExecutionService:
    """工具执行装配与入口；依赖按 §4.1.6-1 注入。"""

    def __init__(
        self,
        *,
        catalog,
        body_cipher,
        executor,
        workspace,
        tool_actions,
        run_records=None,
        audit=None,
    ) -> None:
        self.catalog = catalog
        self.body_cipher = body_cipher
        self.executor = executor
        self.workspace = workspace
        self.tool_actions = tool_actions
        self.run_records = run_records
        self.audit = audit

    def encrypt_body(self, plaintext: str) -> bytes:
        """⑥ 落库前加密（§4.1.6-1.1①）：失败 → 503、不落库、不写 `tool.*` 审计。"""
        try:
            return self.body_cipher.encrypt(plaintext)
        except BodyCipherError as exc:
            get_logger().error("⑥ 正文加密失败，拒绝落库并按 503 返回（§4.1.6-1.1①）")
            raise ToolExecutionError(
                "审批请求暂时无法登记，请稍后重试",
                http_status=ENCRYPT_FAILURE_SEMANTICS.http_status,
                reason_code=ENCRYPT_FAILURE_SEMANTICS.reason_code,
                audit_action=ENCRYPT_FAILURE_SEMANTICS.audit_action,
                keep_approved=False,
            ) from exc

    def resume(self, *, tenant_id: str, run_id: str, approval_id: str) -> ToolExecutionResult:
        """审批通过后的重跑入口（§4.1.6-4）。

        **本步骤只到"参数还原"为止**：还原成功后的 ⑦ 摘要重算与 ①–⑨ 闸门属后续步骤。
        """
        action = self.tool_actions.find_approved(
            tenant_id=tenant_id, run_id=run_id, approval_id=approval_id
        )
        if action is None:
            raise ToolExecutionError(
                "授权已失效，请重新审批",
                http_status=409,
                reason_code=ReasonCode.NOT_AUTHORIZED,
                audit_action=None,
                keep_approved=True,
            )
        try:
            self._restore_params(action)
        except BodyCipherError as exc:
            semantics = RE_RUN_FAILURE_SEMANTICS["body_decrypt_failed"]
            self._record_blocked(action, semantics)
            raise ToolExecutionError(
                "执行失败",
                http_status=semantics.http_status,
                reason_code=semantics.reason_code,
                audit_action=semantics.audit_action,
                keep_approved=True,
            ) from exc

        # ⑦ 的"重算完整参数 args_digest 并比对"与 ①–⑥、⑧、⑨ 的闸门/执行/落库属后续步骤。
        raise NotImplementedError(
            "段二九步闸门的 ①–⑥、⑧、⑨ 与 ⑦ 摘要比对尚未实现（§4.1.6-4 / -5）；"
            "本步骤只交付装配与 resume 的失败语义骨架"
        )

    def _restore_params(self, action: ToolAction) -> dict:
        """控制参数从 `args_json` 取回；正文类参数从 `body_ciphertext` 解密还原（§4.1.6-4）。"""
        spec = self.catalog.get(action.tool_key)
        body_params = [
            name for name, role in spec.param_roles.items() if role is ParamRole.BODY
        ]
        params = {
            name: action.args_json[name]
            for name in spec.params_schema
            if name not in body_params
        }
        if not body_params:
            return params
        if len(body_params) > 1:
            # §3.1.1 逐工具标注中每个工具至多一个 body 参数；多 body 不在规格内。
            raise NotImplementedError("多正文参数的还原不在本步骤范围内")
        if action.body_ciphertext is None:
            raise BodyCipherError("缺少受控正文密文，无法还原正文参数")
        params[body_params[0]] = self.body_cipher.decrypt(action.body_ciphertext)
        return params

    def _record_blocked(self, action: ToolAction, semantics: FailureSemantics) -> None:
        if semantics.audit_action is None or self.audit is None:
            return
        self.audit.record(
            semantics.audit_action,
            tenant_id=action.tenant_id,
            actor_id=action.requested_by,
            target_type="tool_action",
            target_id=action.action_id,
            detail={
                "tool_key": action.tool_key,
                "risk_level": action.risk_level.value,
                "status": action.status.value,
                "reason": semantics.reason_code.value if semantics.reason_code else None,
                "run_id": action.run_id,
            },
        )
