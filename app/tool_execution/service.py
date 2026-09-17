"""`ToolExecutionService`：段二工具执行的装配与**九步闸门**唯一入口（规格 §3.2 / §4.1.6）。

本步骤交付：①–⑨ 全流程（**⑧ 用假执行器**，离线可验收；真容器执行属段二-3）。

顺序与口径（不得颠倒 / 不得跳过）：
    ① 白名单（组装工具面过滤 + 执行入口再校验，两道）
    ② 参数结构化校验（未知字段一律拒绝）
    ③ 路径校验（realpath 后必须落在工作卷内，防 `../` 与符号链接逃逸）
    ④ 危险命令闸门（④-0 来源 / ④-1 名白名单 / ④-2 黑名单，顺序固定，任一命中即拒）
    ⑤ 风险定档 → `needs_approval`（段一唯一判定入口）
    ⑥ 需审批：**先落库、再阻塞**（未落库不得进入等待）
    ⑦ 授权位校验（既有 `ensure_execution_authorized` + 逐项校验）
    ⑧ 执行（本步骤为假执行器）
    ⑨ 结果只落摘要 + 审计（`tool.executed` / `tool.blocked`）

**两条不可协商口径**（§3.2）：
* `②③④` 先于 `⑤⑦`（先"能不能执行"，再"该不该执行"）；
* 审批通过后**从 ① 重跑全套闸门**（含 `②③④`），**禁止**任何"已校验"缓存或跳过。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any, Callable, Mapping, Sequence

from ..audit.models import AuditAction
from ..runtime.authorization import AuthorizationAction
from ..workforce.models import DEFAULT_APPROVAL_TIMEOUT_MINUTES, needs_approval
from .args_digest import args_digest
from .blacklist import CommandDenied, CommandGate
from .catalog import ParamRole, ToolSpec, ToolSpecCatalog
from .errors import BodyCipherError, ToolExecutionConfigError, ToolExecutionError
from .log import get_logger
from .params import ParamValidationError, path_param_names, validate_params
from .paths import PathDenied, PathGuard, path_blacklist_hit
from .store import ReasonCode, ToolAction, ToolActionStatus

BODY_PLACEHOLDER = "«body»"
DEFAULT_TRUSTED_ROOT = "/usr/bin"

# 判定留痕（§4.1.6-6）：②③④ 的**通过路径**也要留下可断言的痕迹，且不新增审计动作码。
GATE_WHITELIST = "①"
GATE_PARAMS = "②"
GATE_PATH = "③"
GATE_EXEC_SOURCE = "④-0"
GATE_EXEC_NAME = "④-1"
GATE_EXEC_BLACKLIST = "④-2"
GATE_RISK = "⑤"
GATE_PERSIST = "⑥"
GATE_AUTHORIZE = "⑦"
GATE_EXECUTE = "⑧"
GATE_AUDIT = "⑨"


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
    # ⑦ 授权位校验失败（未授权 / 摘要不一致 / 存在无授权项的待批动作）
    "not_authorized": FailureSemantics(409, ReasonCode.NOT_AUTHORIZED, ToolActionStatus.APPROVED, AuditAction.TOOL_BLOCKED),
    # ⑦ 之后·正文解密失败（P2 新增）：保持 approved，可重试 / 可人工介入
    "body_decrypt_failed": FailureSemantics(502, ReasonCode.RUNTIME_ERROR, ToolActionStatus.APPROVED, AuditAction.TOOL_BLOCKED),
    "timeout": FailureSemantics(504, ReasonCode.TIMEOUT, ToolActionStatus.APPROVED, AuditAction.TOOL_BLOCKED),
    "runtime_error": FailureSemantics(502, ReasonCode.RUNTIME_ERROR, ToolActionStatus.APPROVED, AuditAction.TOOL_BLOCKED),
    "executed": FailureSemantics(201, None, ToolActionStatus.APPROVED, AuditAction.TOOL_EXECUTED),
}

# §4.1.6-1.1①：⑥ 落库前加密失败 → 503、不落库、**不写 tool.* 审计**（未产生副作用）。
ENCRYPT_FAILURE_SEMANTICS = FailureSemantics(503, None, ToolActionStatus.PENDING, None)
# ⑥ 落库失败 → 503、不进入等待、不写 tool.* 审计。
PERSIST_FAILURE_SEMANTICS = FailureSemantics(503, None, ToolActionStatus.PENDING, None)

# ① 首次执行路径的码位（契约 :641 J9）：输入语义错误 → 422。
FIRST_PATH_NOT_IN_CATALOG_STATUS = 422


def parse_trusted_roots(value: str | Sequence[str] | None) -> tuple[str, ...]:
    """解析 `settings.exec_trusted_roots`（支持 `os.pathsep` / 逗号分隔）。"""
    if value is None:
        return (DEFAULT_TRUSTED_ROOT,)
    if isinstance(value, str):
        chunks: list[str] = []
        for part in value.split(os.pathsep):
            chunks.extend(part.split(","))
        return tuple(chunk.strip() for chunk in chunks if chunk.strip())
    return tuple(str(item).strip() for item in value if str(item).strip())


def assemble_tool_face(catalog: ToolSpecCatalog, *, artifact_export_enabled: bool) -> frozenset[str]:
    """① 组装工具面：从目录过滤出**本环境可执行**的工具集合。

    `WORKBENCH_ARTIFACT_EXPORT_ENABLED=false`（默认，fail-closed）时 `artifact.export` **不装配**（§4）。
    """
    face = {spec.key for spec in catalog.specs}
    if not artifact_export_enabled:
        face.discard("artifact.export")
    return frozenset(face)


@dataclass(frozen=True)
class ToolExecutionRequest:
    """一次工具执行请求（首次路径）。"""

    tenant_id: str
    run_id: str
    task_id: str
    step_id: str
    tool_key: str
    params: Mapping[str, Any]
    requested_by: str
    plan_digest: str
    autonomy_level: str = "approval_for_risky"
    risk_threshold: str = "high"
    approval_timeout_minutes: int = DEFAULT_APPROVAL_TIMEOUT_MINUTES
    action_id: str | None = None
    approval_id: str | None = None


@dataclass(frozen=True)
class ToolExecutionResult:
    """执行结果（§4.1.6-7 决议端点响应体的 `execution` 字段来源）。"""

    outcome: str
    code: int | None = None
    message_id: str | None = None
    approval_id: str | None = None
    action_id: str | None = None
    summary: Mapping[str, object] | None = None


class ToolExecutionService:
    """工具执行装配与**唯一执行入口**；依赖按 §4.1.6-1 注入。"""

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
        artifact_export_enabled: bool = False,
        tool_face: frozenset[str] | None = None,
        authorize_execution: Callable[[Any, str, Any], None] | None = None,
        trusted_roots: str | Sequence[str] | None = None,
        # ④-0 属主 / 权限位判定口径：默认即生产语义（属主 root、group/world 不可写）；
        # 可注入仅为测试在非 root 平台构造受信任假文件（不得放宽生产默认值）。
        trusted_uid: int = 0,
        write_mask: int = 0o022,
        needs_approval_fn: Callable[[str, str, str], bool] | None = None,
        now: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
        turn_tokens=None,
    ) -> None:
        self.catalog = catalog
        self.body_cipher = body_cipher
        self.executor = executor
        # ⑧ 前的**短期网关令牌**接线（§3.5 P1 第 3 条 ②④⑤）：一次 turn = 一次 ⑧ 执行。
        # 为 `None`（如单测直连 / backend=mock）时**不注入任何 env**（既有行为不变）。
        self.turn_tokens = turn_tokens
        self.workspace = workspace
        self.tool_actions = tool_actions
        self.run_records = run_records
        self.audit = audit
        self.artifact_export_enabled = artifact_export_enabled
        self.tool_face = (
            tool_face
            if tool_face is not None
            else assemble_tool_face(catalog, artifact_export_enabled=artifact_export_enabled)
        )
        # ⑦ 复用**既有** `RuntimeService.ensure_execution_authorized`（不另造一套）。
        self.authorize_execution = authorize_execution
        # ⑤ 复用段一唯一判定入口 `needs_approval`（不得自写判定）。
        self._needs_approval = needs_approval_fn or needs_approval
        self._now = now or (lambda: datetime.now(UTC))
        self._new_id = id_factory or _default_id
        self._path_guard = PathGuard()
        self._command_gate = CommandGate(
            trusted_roots=parse_trusted_roots(trusted_roots),
            workspace_root=workspace.root,
            trusted_uid=trusted_uid,
            write_mask=write_mask,
        )
        # 判定留痕：`gate_trace` 为本次调用序列；`gate_calls` 为累计计数（供"重跑"断言）。
        self.gate_trace: list[str] = []
        self.gate_calls: dict[str, int] = {}

    # ------------------------------------------------------------------ 公开入口

    def execute(
        self, request: ToolExecutionRequest, *, actor: Any = None, plan: Any = None
    ) -> ToolExecutionResult:
        """首次执行路径：①–⑨；⑤ 判定需审批时 ⑥ 落库并阻塞（不触达 ⑧）。"""
        return self._run_pipeline(request, resume_action=None, actor=actor, plan=plan)

    def resume(
        self,
        *,
        tenant_id: str,
        run_id: str,
        approval_id: str,
        actor: Any = None,
        plan: Any = None,
    ) -> ToolExecutionResult:
        """审批通过后的重跑入口（§4.1.6-4）：取回冻结参数 → 重算摘要 → **从 ① 重跑**。"""
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
            spec = self.catalog.get(action.tool_key)
        except ToolExecutionConfigError:
            # ① 审批后重跑路径：工具已不在组装面 → 409 + tool.blocked + 保持 approved
            self._raise_blocked(None, action, RE_RUN_FAILURE_SEMANTICS["not_in_catalog"])
        try:
            params = self._restore_params(action)
        except BodyCipherError:
            self._raise_blocked(None, action, RE_RUN_FAILURE_SEMANTICS["body_decrypt_failed"])
        # ⑦ 前置：按**完整参数**（含正文）重算 `args_digest` 并与本行比对（不一致 → 409）。
        if args_digest(params, path_params=path_param_names(spec)) != action.args_digest:
            self._raise_blocked(None, action, RE_RUN_FAILURE_SEMANTICS["not_authorized"])
        request = ToolExecutionRequest(
            tenant_id=action.tenant_id,
            run_id=action.run_id,
            task_id=action.task_id,
            step_id=action.step_id,
            tool_key=action.tool_key,
            params=params,
            requested_by=action.requested_by,
            plan_digest=action.plan_digest,
            action_id=action.action_id,
            approval_id=action.approval_id,
        )
        return self._run_pipeline(request, resume_action=action, actor=actor, plan=plan)

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

    # ------------------------------------------------------------------ 流水线

    def _run_pipeline(
        self, request: ToolExecutionRequest, *, resume_action: ToolAction | None, actor, plan
    ) -> ToolExecutionResult:
        self.gate_trace = []

        # ① 白名单：执行入口再校验（第二道；第一道在组装工具面）
        self._trace(GATE_WHITELIST)
        spec = self._step_whitelist(request, resume=resume_action is not None, action=resume_action)

        # ② 参数结构化校验（未知字段一律拒绝）
        self._trace(GATE_PARAMS)
        try:
            params = validate_params(spec, request.params)
        except ParamValidationError as exc:
            self._fail(request, spec, key="param_invalid", cause=exc)

        # ③ 路径校验（realpath 必须落在工作卷内，防 `../` 与符号链接逃逸）
        workspace_path = self.workspace.path_for(request.tenant_id, request.run_id)
        resolved_path: str | None = None
        if "path" in spec.params_schema:
            self._trace(GATE_PATH)
            try:
                resolved_path = self._path_guard.resolve(params["path"], workspace_path=workspace_path)
            except PathDenied as exc:
                self._fail(request, spec, key="path_denied", cause=exc)

        # ④ 危险命令闸门（三个子判定顺序固定；任一命中即拒）
        self._step_danger(request, spec, params, workspace_path, resolved_path, action=resume_action)

        # ⑤ 风险定档 → needs_approval（段一唯一判定入口）
        self._trace(GATE_RISK)
        if resume_action is not None:
            requires_approval = bool(resume_action.requires_approval)
        else:
            # 始终经段一唯一判定入口 `needs_approval`（不得因目录静态值短路而绕过它）。
            decided_by_policy = bool(
                self._needs_approval(
                    request.autonomy_level, spec.risk_level.value, request.risk_threshold
                )
            )
            requires_approval = bool(spec.requires_approval) or decided_by_policy

        if requires_approval and resume_action is None:
            # ⑥ 先落库、再阻塞（**未落库不得进入等待**）
            self._trace(GATE_PERSIST)
            persisted = self._persist_pending(request, spec, params)
            return ToolExecutionResult(
                outcome="pending_approval",
                code=202,
                approval_id=persisted.approval_id,
                action_id=persisted.action_id,
            )

        # ⑦ 授权位校验（既有 ensure_execution_authorized + 逐项校验）
        self._trace(GATE_AUTHORIZE)
        self._step_authorize(request, spec, resume_action, actor, plan)

        # ⑧ 执行（本步骤为假执行器）
        self._trace(GATE_EXECUTE)
        summary = self._step_execute(request, spec, params, workspace_path, resume_action)

        # ⑨ 结果只落摘要 + 审计
        self._trace(GATE_AUDIT)
        self._record_executed(request, spec, resume_action, summary)
        return ToolExecutionResult(
            outcome="executed",
            code=201,
            approval_id=resume_action.approval_id if resume_action else None,
            action_id=resume_action.action_id if resume_action else None,
            summary=summary,
        )

    def _step_whitelist(
        self, request: ToolExecutionRequest, *, resume: bool, action: ToolAction | None
    ) -> ToolSpec:
        """① 执行入口再校验：工具必须同时在**组装工具面**与**目录**内。"""
        in_face = request.tool_key in self.tool_face
        try:
            spec = self.catalog.get(request.tool_key)
        except ToolExecutionConfigError:
            spec = None
        if spec is None or not in_face:
            self._fail(
                request,
                spec,
                key="not_in_catalog",
                action=action,
                first_path=not resume,
            )
        return spec

    def _step_danger(
        self,
        request: ToolExecutionRequest,
        spec: ToolSpec,
        params: Mapping[str, Any],
        workspace_path: str,
        resolved_path: str | None,
        *,
        action: ToolAction | None,
    ) -> None:
        if "executable" in spec.params_schema:
            self._trace(GATE_EXEC_SOURCE)
            try:
                resolved_executable = self._command_gate.verify_source(params["executable"])
            except CommandDenied as exc:
                self._fail(request, spec, key="blacklisted", action=action, cause=exc)
            self._trace(GATE_EXEC_NAME)
            try:
                self._command_gate.verify_name(resolved_executable)
            except CommandDenied as exc:
                self._fail(request, spec, key="blacklisted", action=action, cause=exc)
            self._trace(GATE_EXEC_BLACKLIST)
            try:
                self._command_gate.verify_blacklist(
                    resolved_executable, params["args"], workspace_path=workspace_path
                )
            except CommandDenied as exc:
                self._fail(request, spec, key="blacklisted", action=action, cause=exc)
            return
        # 自建工具（fs.*）的 ④-2：C 类路径黑名单。`artifact.export` 的 ④ 不适用（§3.1.1 注 2）。
        if "path" in spec.params_schema and spec.key != "artifact.export":
            self._trace(GATE_EXEC_BLACKLIST)
            if resolved_path is not None and path_blacklist_hit(resolved_path):
                self._fail(
                    request, spec, key="blacklisted", action=action, message="命中 C 类路径黑名单"
                )

    def _step_authorize(
        self,
        request: ToolExecutionRequest,
        spec: ToolSpec,
        action: ToolAction | None,
        actor: Any,
        plan: Any,
    ) -> None:
        """⑦ 逐项校验 + 既有运行级闸门。"""
        rows = self.tool_actions.list_for_run(request.tenant_id, request.run_id)
        for row in rows:
            if row.requires_approval and row.status is not ToolActionStatus.APPROVED:
                self._fail(
                    request,
                    spec,
                    key="not_authorized",
                    action=action,
                    message="存在无对应授权项的待批动作",
                )
        if self.authorize_execution is None or actor is None or plan is None:
            return
        # §4.1.7-5：**显式传入**待判动作只读投影（8 字段，不含参数原文与 args_json）。
        # 无待判动作（⑤ 判定无需审批路径）→ 传 None（缺省，仅退化为运行级摘要比对）。
        pending_actions = [
            AuthorizationAction.from_row(row)
            for row in rows
            if bool(getattr(row, "requires_approval", False))
        ]
        try:
            self.authorize_execution(
                actor, request.run_id, plan, actions=(pending_actions or None)
            )
        except Exception as exc:  # noqa: BLE001 - 既有闸门抛出的受控异常一律映射为 409
            self._fail(request, spec, key="not_authorized", action=action, cause=exc)

    def _step_execute(
        self,
        request: ToolExecutionRequest,
        spec: ToolSpec,
        params: Mapping[str, Any],
        workspace_path: str,
        action: ToolAction | None,
    ) -> Mapping[str, object]:
        try:
            # ⑧ 前进入新 turn（§3.5 P1 第 3 条）：mint + 落自持绑定 + 登记当前执行；返回容器内 env。
            # 终态吊销由 `ContainerExecutor(token_revoker=…)` 触发（容器到达终态即 retire + revoke）。
            environment = None
            if self.turn_tokens is not None:
                environment = self.turn_tokens.open_turn(
                    tenant_id=request.tenant_id,
                    session_id=request.task_id,
                    run_id=request.run_id,
                )
            outcome = self.executor.execute(
                tool_key=spec.key,
                params=params,
                workspace_path=workspace_path,
                environment=environment,
                # P5a：进程内 CRM 工具需要操作者上下文（数据范围 = 会话操作者本人负责的对象）；
                # 容器执行器接受并忽略这两个参数（签名统一，既有行为不变）。
                requester=request.requested_by,
                tenant_id=request.tenant_id,
            )
        except Exception as exc:  # noqa: BLE001 - 铸令牌 / 执行异常一律 502
            self._fail(request, spec, key="runtime_error", action=action, cause=exc)
        if getattr(outcome, "timed_out", False):
            self._fail(request, spec, key="timeout", action=action)
        if not getattr(outcome, "ok", False):
            self._fail(request, spec, key="runtime_error", action=action)
        return dict(getattr(outcome, "summary", {}) or {})

    # ------------------------------------------------------------------ ⑥ / ⑨

    def _persist_pending(
        self, request: ToolExecutionRequest, spec: ToolSpec, params: Mapping[str, Any]
    ) -> ToolAction:
        now = self._now()
        body_params = [name for name, role in spec.param_roles.items() if role is ParamRole.BODY]
        args_json: dict[str, Any] = {}
        for name in spec.params_schema:
            args_json[name] = BODY_PLACEHOLDER if name in body_params else params[name]
        ciphertext: bytes | None = None
        expires_at: datetime | None = None
        if body_params:
            # 加密失败 → 503、不落库、不写 tool.* 审计（未产生副作用）。
            ciphertext = self.encrypt_body(str(params[body_params[0]]))
            expires_at = now + timedelta(minutes=int(request.approval_timeout_minutes))
        action = ToolAction(
            tenant_id=request.tenant_id,
            action_id=request.action_id or self._new_id(),
            approval_id=request.approval_id or self._new_id(),
            run_id=request.run_id,
            task_id=request.task_id,
            step_id=request.step_id,
            tool_key=spec.key,
            args_digest=args_digest(params, path_params=path_param_names(spec)),
            args_json=args_json,
            body_ciphertext=ciphertext,
            body_expires_at=expires_at,
            plan_digest=request.plan_digest,
            risk_level=spec.risk_level,
            requires_approval=True,
            status=ToolActionStatus.PENDING,
            requested_by=request.requested_by,
            requested_at=now,
        )
        try:
            return self.tool_actions.upsert(action)
        except Exception as exc:  # noqa: BLE001 - 落库失败一律 503，不进入等待
            get_logger().error("⑥ 待批动作落库失败，拒绝进入等待（§4.1.6-5）")
            raise ToolExecutionError(
                "审批请求暂时无法登记，请稍后重试",
                http_status=PERSIST_FAILURE_SEMANTICS.http_status,
                reason_code=PERSIST_FAILURE_SEMANTICS.reason_code,
                audit_action=PERSIST_FAILURE_SEMANTICS.audit_action,
                keep_approved=False,
            ) from exc

    def _record_executed(
        self,
        request: ToolExecutionRequest,
        spec: ToolSpec,
        action: ToolAction | None,
        summary: Mapping[str, object],
    ) -> None:
        if self.audit is None:
            return
        self.audit.record(
            AuditAction.TOOL_EXECUTED,
            tenant_id=request.tenant_id,
            actor_id=request.requested_by,
            target_type="tool_action",
            target_id=(action.action_id if action else request.step_id),
            detail={
                "tool_key": spec.key,
                "risk_level": spec.risk_level.value,
                "status": "executed",
                "reason": None,
                "run_id": request.run_id,
            },
        )

    # ------------------------------------------------------------------ 失败与留痕

    def _trace(self, step: str) -> None:
        self.gate_trace.append(step)
        self.gate_calls[step] = self.gate_calls.get(step, 0) + 1

    def _fail(
        self,
        request: ToolExecutionRequest,
        spec: ToolSpec | None,
        *,
        key: str,
        action: ToolAction | None = None,
        first_path: bool = False,
        message: str | None = None,
        cause: Exception | None = None,
    ) -> None:
        semantics = RE_RUN_FAILURE_SEMANTICS[key]
        status = semantics.http_status
        if key == "not_in_catalog" and first_path:
            status = FIRST_PATH_NOT_IN_CATALOG_STATUS
        risk_level = spec.risk_level.value if spec is not None else "high"
        tool_key = spec.key if spec is not None else request.tool_key
        self._write_blocked_audit(
            request,
            tool_key=tool_key,
            risk_level=risk_level,
            reason=semantics.reason_code,
            action=action,
        )
        if action is not None and semantics.action_status is ToolActionStatus.REJECTED:
            self._mark_rejected(action, semantics.reason_code)
        raise ToolExecutionError(
            message or "执行被拒绝",
            http_status=status,
            reason_code=semantics.reason_code,
            audit_action=semantics.audit_action,
            keep_approved=semantics.action_status is ToolActionStatus.APPROVED,
        ) from cause

    def _raise_blocked(
        self, request: ToolExecutionRequest | None, action: ToolAction, semantics: FailureSemantics
    ) -> None:
        self._write_blocked_audit(
            request,
            tool_key=action.tool_key,
            risk_level=action.risk_level.value,
            reason=semantics.reason_code,
            action=action,
        )
        if semantics.action_status is ToolActionStatus.REJECTED:
            self._mark_rejected(action, semantics.reason_code)
        raise ToolExecutionError(
            "执行被拒绝",
            http_status=semantics.http_status,
            reason_code=semantics.reason_code,
            audit_action=semantics.audit_action,
            keep_approved=semantics.action_status is ToolActionStatus.APPROVED,
        )

    def _write_blocked_audit(
        self,
        request: ToolExecutionRequest | None,
        *,
        tool_key: str,
        risk_level: str,
        reason: ReasonCode | None,
        action: ToolAction | None,
    ) -> None:
        if self.audit is None:
            return
        if action is not None:
            self.audit.record(
                AuditAction.TOOL_BLOCKED,
                tenant_id=action.tenant_id,
                actor_id=action.requested_by,
                target_type="tool_action",
                target_id=action.action_id,
                detail={
                    "tool_key": tool_key,
                    "risk_level": risk_level,
                    "status": action.status.value,
                    "reason": reason.value if reason else None,
                    "run_id": action.run_id,
                },
            )
            return
        tenant_id = request.tenant_id if request else None
        actor_id = request.requested_by if request else None
        run_id = request.run_id if request else None
        target_id = request.step_id if request else None
        self.audit.record(
            AuditAction.TOOL_BLOCKED,
            tenant_id=tenant_id,
            actor_id=actor_id,
            target_type="tool_action",
            target_id=target_id,
            detail={
                "tool_key": tool_key,
                "risk_level": risk_level,
                "status": "blocked",
                "reason": reason.value if reason else None,
                "run_id": run_id,
            },
        )

    def _mark_rejected(self, action: ToolAction, reason: ReasonCode) -> None:
        """④ 黑名单命中：`027` 行置 `rejected` 并清空正文密文列（审批落定即清，§3.4）。"""
        rejected = replace(
            action,
            status=ToolActionStatus.REJECTED,
            decided_by=action.decided_by or "system:tool-gate",
            decided_at=action.decided_at or self._now(),
            decision_source="tool-gate",
            reason_code=reason,
            body_ciphertext=None,
            body_expires_at=None,
        )
        try:
            self.tool_actions.upsert(rejected)
        except Exception as exc:  # noqa: BLE001 - 留痕失败不得掩盖原始拒绝
            get_logger().error("④ 黑名单命中后置 rejected 失败（§4.1.6-5 例外）")

    def _restore_params(self, action: ToolAction) -> dict:
        """控制参数从 `args_json` 取回；正文类参数从 `body_ciphertext` 解密还原（§4.1.6-4）。"""
        spec = self.catalog.get(action.tool_key)
        body_params = [name for name, role in spec.param_roles.items() if role is ParamRole.BODY]
        params = {
            name: action.args_json[name] for name in spec.params_schema if name not in body_params
        }
        if not body_params:
            return params
        if len(body_params) > 1:
            # §3.1.1 逐工具标注中每个工具至多一个 body 参数；多 body 不在规格内。
            raise ToolExecutionConfigError("多正文参数的还原不在本步骤范围内")
        if action.body_ciphertext is None:
            raise BodyCipherError("缺少受控正文密文，无法还原正文参数")
        params[body_params[0]] = self.body_cipher.decrypt(action.body_ciphertext)
        return params


def _default_id() -> str:
    from uuid import uuid4

    return uuid4().hex
