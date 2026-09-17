"""九步闸门（段二-2）用例：①白名单 / ②参数 / ③路径 / ④危险命令 / ⑤定档 / ⑥落库 /
⑦授权 / ⑧假执行器 / ⑨摘要与审计 / 通过路径留痕 / 审批后重跑。

真源：`docs/superpowers/specs/2026-09-12-dsh-integration-design.md` §3.2 / §3.2.1 / §4.1.4 / §4.1.6。
**离线可验收**：全部用假执行器，不起容器、不连真库、不出网。
"""

from __future__ import annotations

import ast
import base64
import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.audit.models import AuditAction
from app.domain import RiskLevel, Task, TaskStatus, TaskStore, UserContext
from app.runtime.authorization import (
    AUTHORIZATION_ACTION_FIELDS,
    AuthorizationAction,
    ExecutionNotAuthorized,
    authorization_action_field_names,
    plan_digest,
    validate_authorization_action,
)
from app.runtime.contracts import AgentPlan
from app.runtime.records import InMemoryRunRecordStore
from app.runtime.run_metrics import RunMetricsService
from app.runtime.service import RuntimeService
from app.tool_execution.args_digest import args_digest
from app.tool_execution.blacklist import (
    READ_ONLY_WHITELIST,
    CommandDenied,
    ExecutableTrust,
    executable_blacklist_hit,
    normalize_args,
    param_blacklist_hit,
)
from app.tool_execution.body_cipher import BodyCipher
from app.tool_execution.catalog import ToolSpecCatalog, default_tool_specs
from app.tool_execution.errors import ToolExecutionError
from app.tool_execution.executor import (
    DeterministicFakeExecutor,
    ExecutionOutcome,
    OutputCapture,
)
from app.tool_execution.params import path_param_names
from app.tool_execution.paths import path_blacklist_hit
from app.tool_execution.service import (
    BODY_PLACEHOLDER,
    GATE_EXEC_BLACKLIST,
    GATE_EXEC_NAME,
    GATE_EXEC_SOURCE,
    GATE_EXECUTE,
    GATE_PARAMS,
    GATE_PATH,
    GATE_PERSIST,
    GATE_WHITELIST,
    ToolExecutionRequest,
    ToolExecutionService,
    assemble_tool_face,
)
from app.tool_execution.store import (
    InMemoryToolActionStore,
    ReasonCode,
    ToolAction,
    ToolActionStatus,
)
from app.tool_execution.workspace import WorkspaceManager
from app.workforce.models import DEFAULT_APPROVAL_TIMEOUT_MINUTES

NOW = datetime(2026, 9, 13, 12, 0, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[1]
ACTOR = UserContext("t-1", "u-1", "employee")
PLAN = AgentPlan.from_steps([{"step_id": "step-1", "kind": "write", "tool": "fs.write"}])


class RecordingAudit:
    def __init__(self) -> None:
        self.calls: list[tuple[AuditAction, dict]] = []

    def record(self, action: AuditAction, **kwargs) -> None:
        self.calls.append((action, kwargs))


class ExplodingStore(InMemoryToolActionStore):
    def upsert(self, action: ToolAction) -> ToolAction:  # noqa: D102
        raise RuntimeError("db down")


class RecordingAuthorizer:
    def __init__(self, *, allow: bool = True) -> None:
        self.allow = allow
        self.calls: list[dict] = []

    def __call__(self, actor, run_id, plan, *, actions=None) -> None:
        self.calls.append(
            {"actor": actor, "run_id": run_id, "plan": plan, "actions": actions}
        )
        if not self.allow:
            raise ExecutionNotAuthorized("模拟既有闸门拒绝")


def _key() -> str:
    return base64.b64encode(os.urandom(32)).decode("ascii")


def _elf(path: str, *, body: bytes = b"\x7fELF" + b"\x00" * 64, mode: int = 0o555) -> str:
    with open(path, "wb") as handle:
        handle.write(body)
    os.chmod(path, mode)
    return path


def _current_owner_uid() -> int:
    """④-0 属主判定的「受信任属主」在**当前平台**的可注入期望值。

    * POSIX：返回**当前进程 uid**（`os.getuid()`）——tmp 目录内新建的假可执行文件属主即该 uid，
      从而在**非 root** 环境下也能被 ④-0 视为「受信任属主」而继续走后续判定。
    * Windows：无 POSIX 属主语义，`os.stat().st_uid` **恒为 0**，故只能取 0；此时「属主必须是 0」
      **退化为恒真**、本质上**不可判定**（详见 `test_exec_source_owner_check_platform_semantics`）。
    """
    getuid = getattr(os, "getuid", None)
    return int(getuid()) if getuid is not None else 0


def build_service(
    tmp_path,
    *,
    store=None,
    audit=None,
    executor=None,
    artifact_export_enabled: bool = False,
    authorize_execution=None,
    needs_approval_fn=None,
    trusted_uid: int | None = None,
    write_mask: int | None = None,
    file_changes_max: int = 0,
    artifacts=None,
):
    trusted = tmp_path / "trusted"
    trusted.mkdir(exist_ok=True)
    workspace_root = tmp_path / "ws"
    workspace_root.mkdir(exist_ok=True)
    service = ToolExecutionService(
        catalog=ToolSpecCatalog(default_tool_specs()),
        body_cipher=BodyCipher.from_base64(_key()),
        executor=executor or DeterministicFakeExecutor(),
        workspace=WorkspaceManager(str(workspace_root)),
        tool_actions=store or InMemoryToolActionStore(),
        run_records=None,
        audit=audit,
        artifact_export_enabled=artifact_export_enabled,
        authorize_execution=authorize_execution,
        needs_approval_fn=needs_approval_fn,
        trusted_roots=(str(trusted),),
        # ④-0 属主口径按平台注入（生产默认 0 由 ToolExecutionService 保证，不在此覆盖）。
        trusted_uid=_current_owner_uid() if trusted_uid is None else trusted_uid,
        write_mask=0o022 if write_mask is None else write_mask,
        now=lambda: NOW,
        # P2c-3：变更通道与产物登记（缺省关闭 / 不登记 ⇒ 既有用例零变化）。
        file_changes_max=file_changes_max,
        artifacts=artifacts,
    )
    return service, trusted, workspace_root


def request(tool_key: str, params: dict, **overrides) -> ToolExecutionRequest:
    base = dict(
        tenant_id="t-1",
        run_id="run-1",
        task_id="task-1",
        step_id="step-1",
        tool_key=tool_key,
        params=params,
        requested_by="u-1",
        plan_digest="sha256:plan",
        autonomy_level="full_auto",
        risk_threshold="high",
    )
    base.update(overrides)
    return ToolExecutionRequest(**base)


def run_cmd(executable: str, args: list) -> ToolExecutionRequest:
    return request("cmd.run", {"executable": executable, "args": list(args)})


def approved_action(
    *, tool_key: str, params: dict, args_digest_value: str | None = None, **overrides
) -> ToolAction:
    spec = ToolSpecCatalog(default_tool_specs()).get(tool_key)
    base = dict(
        tenant_id="t-1",
        action_id="act-1",
        approval_id="appr-1",
        run_id="run-1",
        task_id="task-1",
        step_id="step-1",
        tool_key=tool_key,
        args_digest=args_digest_value or args_digest(params, path_params=path_param_names(spec)),
        args_json={name: params[name] for name in params},
        plan_digest="sha256:plan",
        risk_level=RiskLevel.MEDIUM,
        requires_approval=True,
        status=ToolActionStatus.APPROVED,
        requested_by="u-1",
        requested_at=NOW,
        decided_by="ceo-1",
        decided_at=NOW,
        decision_source="user",
    )
    base.update(overrides)
    return ToolAction(**base)


# --------------------------------------------------------------------- ① 白名单


def test_face_filter_is_two_layers(tmp_path) -> None:
    """① 两道：组装工具面过滤 `artifact.export`（默认关闭不装配）。"""
    catalog = ToolSpecCatalog(default_tool_specs())
    assert "artifact.export" not in assemble_tool_face(catalog, artifact_export_enabled=False)
    assert "artifact.export" in assemble_tool_face(catalog, artifact_export_enabled=True)


def test_execute_rejects_tool_not_in_assembled_face(tmp_path) -> None:
    audit = RecordingAudit()
    store = InMemoryToolActionStore()
    service, _trusted, _ws = build_service(tmp_path, store=store, audit=audit)

    with pytest.raises(ToolExecutionError) as excinfo:
        service.execute(request("artifact.export", {"path": "/workspace/a", "target": "x"}))

    assert excinfo.value.http_status == 422
    assert excinfo.value.reason_code is ReasonCode.NOT_IN_CATALOG
    # 未落库、未进入等待。
    assert store.list_for_run("t-1", "run-1") == []
    assert [action for action, _ in audit.calls] == [AuditAction.TOOL_BLOCKED]


def test_execute_rejects_unknown_tool(tmp_path) -> None:
    service, _trusted, _ws = build_service(tmp_path)
    with pytest.raises(ToolExecutionError) as excinfo:
        service.execute(request("not.a.tool", {}))
    assert excinfo.value.http_status == 422
    assert excinfo.value.reason_code is ReasonCode.NOT_IN_CATALOG


def test_artifact_export_enabled_passes_step1_and_blocks_for_approval(tmp_path) -> None:
    store = InMemoryToolActionStore()
    service, _trusted, _ws = build_service(
        tmp_path, store=store, artifact_export_enabled=True
    )
    result = service.execute(
        request("artifact.export", {"path": "/workspace/a", "target": "x"})
    )
    assert result.outcome == "pending_approval"
    assert result.code == 202
    assert store.list_for_run("t-1", "run-1")[0].status is ToolActionStatus.PENDING


# --------------------------------------------------------------------- ② 参数


def test_unknown_parameter_is_rejected(tmp_path) -> None:
    service, _trusted, _ws = build_service(tmp_path)
    with pytest.raises(ToolExecutionError) as excinfo:
        service.execute(request("fs.list", {"path": "/workspace", "extra": 1}))
    assert excinfo.value.http_status == 422
    assert excinfo.value.reason_code is ReasonCode.PARAM_INVALID


def test_wrong_type_is_rejected(tmp_path) -> None:
    service, _trusted, _ws = build_service(tmp_path)
    with pytest.raises(ToolExecutionError) as excinfo:
        service.execute(request("fs.read", {"path": "/workspace/a", "max_bytes": "huge"}))
    assert excinfo.value.reason_code is ReasonCode.PARAM_INVALID


def test_missing_parameter_is_rejected(tmp_path) -> None:
    service, _trusted, _ws = build_service(tmp_path)
    with pytest.raises(ToolExecutionError) as excinfo:
        service.execute(request("fs.read", {"path": "/workspace/a"}))
    assert excinfo.value.reason_code is ReasonCode.PARAM_INVALID


# --------------------------------------------------------------------- ③ 路径


def test_parent_traversal_is_rejected(tmp_path) -> None:
    service, _trusted, _ws = build_service(tmp_path)
    with pytest.raises(ToolExecutionError) as excinfo:
        service.execute(request("fs.read", {"path": "/workspace/../../etc/passwd", "max_bytes": 1}))
    assert excinfo.value.http_status == 403
    assert excinfo.value.reason_code is ReasonCode.PATH_DENIED


def test_symlink_escape_is_rejected(tmp_path) -> None:
    service, _trusted, ws = build_service(tmp_path)
    service.workspace.create("t-1", "run-1")
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    link = ws / "t-1" / "run-1" / "escape"
    os.symlink(str(outside), str(link))

    with pytest.raises(ToolExecutionError) as excinfo:
        service.execute(request("fs.read", {"path": "/workspace/escape", "max_bytes": 1}))
    assert excinfo.value.reason_code is ReasonCode.PATH_DENIED


def test_path_inside_workspace_passes(tmp_path) -> None:
    service, _trusted, _ws = build_service(tmp_path)
    result = service.execute(request("fs.list", {"path": "/workspace"}))
    assert result.outcome == "executed"
    assert result.code == 201


# --------------------------------------------------------------------- ④ 危险命令


def test_exec_source_rejects_shebang(tmp_path) -> None:
    service, trusted, _ws = build_service(tmp_path)
    _elf(str(trusted / "ls"), body=b"#!/bin/sh\necho hi\n")
    with pytest.raises(ToolExecutionError) as excinfo:
        service.execute(run_cmd(str(trusted / "ls"), []))
    assert excinfo.value.http_status == 403
    assert excinfo.value.reason_code is ReasonCode.BLACKLISTED
    assert GATE_EXEC_SOURCE in service.gate_trace


def test_exec_source_rejects_non_elf(tmp_path) -> None:
    service, trusted, _ws = build_service(tmp_path)
    _elf(str(trusted / "ls"), body=b"MZ" + b"\x00" * 32)
    with pytest.raises(ToolExecutionError) as excinfo:
        service.execute(run_cmd(str(trusted / "ls"), []))
    assert excinfo.value.reason_code is ReasonCode.BLACKLISTED


def test_exec_source_rejects_outside_trusted_root(tmp_path) -> None:
    service, _trusted, ws = build_service(tmp_path)
    rogue = _elf(str(ws / "ls"))  # 工作卷内的同名 ELF
    with pytest.raises(ToolExecutionError) as excinfo:
        service.execute(run_cmd(rogue, []))
    assert excinfo.value.reason_code is ReasonCode.BLACKLISTED
    assert GATE_EXEC_SOURCE in service.gate_trace


def test_exec_source_rejects_owner_mismatch(tmp_path) -> None:
    """④-0 属主不匹配**必须拒**（两平台均可判定 → 证明属主检查不是空转）。

    注入期望属主 = 假文件真实属主 + 1，与假文件必然不同：
    * POSIX：真实属主 = 当前进程 uid → 注入 uid+1；
    * Windows：`os.stat().st_uid` 恒为 0 → 注入 1。
    """
    service, trusted, _ws = build_service(tmp_path, trusted_uid=_current_owner_uid() + 1)
    _elf(str(trusted / "ls"))
    with pytest.raises(ToolExecutionError) as excinfo:
        service.execute(run_cmd(str(trusted / "ls"), []))
    assert excinfo.value.http_status == 403
    assert excinfo.value.reason_code is ReasonCode.BLACKLISTED
    assert GATE_EXEC_SOURCE in service.gate_trace
    # 该文件本身是合法 ELF / 在受信任根内 / 属主与 ④-1 名白名单均无问题：
    # 命中原因只能是属主不匹配（对照 ④-1 未被触达）。
    assert GATE_EXEC_NAME not in service.gate_trace


def test_exec_source_owner_check_platform_semantics(tmp_path) -> None:
    """④-0 属主检查在**当前平台**的判定能力（**显式断言**，不靠 skip 含混）。

    * POSIX：`st_uid` 反映真实属主 → 属主检查**可判定**（真：`trusted_uid=真实属主` 通过；
      假：`trusted_uid=真实属主+1` 被拒）。
    * Windows：无 POSIX 属主语义、`os.stat().st_uid` **恒为 0** → 「属主必须是 0」
      **退化为恒真**，本平台**无法**构造「属主非 0 的真实文件」，故「属主非 root 被拒」
      这条生产语义在 Windows 上属**不可判定**；此处显式断言该退化事实。
      判定逻辑本身并非空转：Windows 上仍可用**注入非 0 期望值**命中
      （见 `test_exec_source_rejects_owner_mismatch`）。
    """
    path = _elf(str(tmp_path / "probe.elf"))
    actual_uid = os.stat(path).st_uid
    if os.name == "posix":
        assert actual_uid == os.getuid(), "POSIX 上文件属主应为当前进程 uid"
        assert ExecutableTrust(trusted_roots=[str(tmp_path)], trusted_uid=actual_uid).verify(path)
        with pytest.raises(CommandDenied):
            ExecutableTrust(trusted_roots=[str(tmp_path)], trusted_uid=actual_uid + 1).verify(path)
    else:
        # Windows：属主恒 0 ⇒ 期望 0 的属主检查退化为恒真（不可判定为假）。
        assert actual_uid == 0, "Windows 上 st_uid 应为恒 0；若不为 0，需重估本平台判定口径"
        assert ExecutableTrust(trusted_roots=[str(tmp_path)], trusted_uid=0).verify(path)


def test_exec_source_write_mask_is_injectable(tmp_path) -> None:
    """④-0 权限位口径可注入且真实生效：默认 `0o022` 拒 group/world 可写；显式 `0` 时不因该位拒。

    两平台均可判定：POSIX `chmod 0o777` 置位 world-writable；Windows `chmod` 仅切只读位，
    可写文件 `st_mode` 含 `0o666`（`& 0o022 != 0`）。
    """
    path = _elf(str(tmp_path / "writable.elf"), mode=0o777)
    owner = os.stat(path).st_uid  # 与真实属主对齐，单独考察权限位（避免属主分支先行拒绝掩盖本判定）
    with pytest.raises(CommandDenied, match="group/world"):
        ExecutableTrust(trusted_roots=[str(tmp_path)], trusted_uid=owner).verify(path)
    # 注入 write_mask=0：该位不再拒绝（属主 / 受信任根 / ELF 等其余判定不变）。
    assert ExecutableTrust(
        trusted_roots=[str(tmp_path)], trusted_uid=owner, write_mask=0
    ).verify(path)


def test_exec_name_whitelist_is_fail_closed(tmp_path) -> None:
    service, trusted, _ws = build_service(tmp_path)
    _elf(str(trusted / "catz"))
    with pytest.raises(ToolExecutionError) as excinfo:
        service.execute(run_cmd(str(trusted / "catz"), []))
    assert excinfo.value.reason_code is ReasonCode.BLACKLISTED
    assert GATE_EXEC_NAME in service.gate_trace


def test_exec_name_in_whitelist_passes_to_execution(tmp_path) -> None:
    service, trusted, _ws = build_service(tmp_path)
    _elf(str(trusted / "ls"))
    result = service.execute(run_cmd(str(trusted / "ls"), ["/workspace"]))
    assert result.outcome == "executed"
    assert GATE_EXEC_BLACKLIST in service.gate_trace


class _OutputExecutor:
    """只回「执行摘要 + 有界输出」的假执行器（P2c-2 用例；不启容器）。"""

    def __init__(self, output: OutputCapture) -> None:
        self._output = output

    def execute(self, **kwargs):  # noqa: ANN003 - 与真实执行器同签名（此处仅回填）
        return ExecutionOutcome(
            ok=True,
            summary={"tool_key": "cmd.run", "status": "ok", "exit_code": 0},
            output=self._output,
        )


def test_bounded_output_rides_along_and_never_pollutes_executed_audit(tmp_path) -> None:
    """P2c-2 §2.6：有界摘录**只随帧回传** —— 结果携带 `output`，`tool.executed` 审计**零污染**。"""
    audit = RecordingAudit()
    capture = OutputCapture(
        excerpt="line1\nAuthorization: Bearer abcdef1234567890",
        truncated=True,
        bytes_read=4096,
    )
    service, trusted, _ws = build_service(tmp_path, audit=audit, executor=_OutputExecutor(capture))
    _elf(str(trusted / "ls"))
    result = service.execute(run_cmd(str(trusted / "ls"), ["/workspace"]))

    assert result.outcome == "executed"
    assert result.output == {
        "output_excerpt": "line1\nAuthorization: Bearer abcdef1234567890",
        "output_truncated": True,
        "output_bytes": 4096,
    }
    executed = [call for call in audit.calls if call[0] == AuditAction.TOOL_EXECUTED]
    assert executed, "已执行必须写 tool.executed"
    detail = executed[-1][1]["detail"]
    assert set(detail) <= {"tool_key", "risk_level", "status", "reason", "run_id"}
    assert "output_excerpt" not in detail  # 摘录不进审计
    assert "abcdef1234567890" not in str(detail)  # 内容不进审计


class _FileChangeExecutor:
    """只回「执行摘要 + 文件变更」的假执行器（P2c-3 用例；不启容器）。"""

    def __init__(self, *changes, truncated: bool = False) -> None:
        self._changes = tuple(changes)
        self._truncated = truncated

    def execute(self, **kwargs):  # noqa: ANN003 - 与真实执行器同签名（此处仅回填）
        return ExecutionOutcome(
            ok=True,
            summary={"tool_key": "fs.write", "status": "ok", "exit_code": 0},
            file_changes=self._changes,
            file_changes_truncated=self._truncated,
        )


class RecordingArtifactStore:
    """记录登记请求的假仓储（P2c-3 用例；`register` 签名与真实仓储一致）。"""

    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[dict] = []
        self.fail = fail

    def register(self, tenant_id, run_id, changes, *, now=None) -> int:  # noqa: ANN001
        if self.fail:
            raise RuntimeError("登记仓储不可用")
        items = tuple(changes)
        self.calls.append({"tenant_id": tenant_id, "run_id": run_id, "changes": items, "now": now})
        return len(items)


def _change(index: int, *, kind: str = "created"):
    from app.tool_execution.file_ops import FileChange

    return FileChange(
        virtual_path=f"/workspace/{index}.txt",
        change_kind=kind,
        bytes=index,
        sha256=f"sha256:{index}",
        diff_excerpt=f"content-{index}",
    )


def test_file_changes_ride_along_truncated_and_registered(tmp_path) -> None:
    """P2c-3 §2.7：变更记录**按同一上限截断**后同时进结果与产物登记（帧里有的才登记）。"""
    audit = RecordingAudit()
    artifacts = RecordingArtifactStore()
    service, trusted, _ws = build_service(
        tmp_path,
        audit=audit,
        executor=_FileChangeExecutor(_change(0), _change(1), _change(2)),
        file_changes_max=2,
        artifacts=artifacts,
    )
    _elf(str(trusted / "ls"))
    result = service.execute(run_cmd(str(trusted / "ls"), ["/workspace"]))

    assert result.outcome == "executed"
    payload = dict(result.output or {})
    assert [item["virtual_path"] for item in payload["file_changes"]] == [
        "/workspace/0.txt",
        "/workspace/1.txt",
    ]
    assert payload["file_changes_truncated"] is True  # 截断**显式告知**
    assert len(artifacts.calls) == 1
    registered = artifacts.calls[0]["changes"]
    assert [item.virtual_path for item in registered] == ["/workspace/0.txt", "/workspace/1.txt"]
    assert artifacts.calls[0]["tenant_id"] == "t-1" and artifacts.calls[0]["run_id"] == "run-1"
    # 不进审计（口径不变）
    executed = [call for call in audit.calls if call[0] == AuditAction.TOOL_EXECUTED]
    assert set(executed[-1][1]["detail"]) <= {"tool_key", "risk_level", "status", "reason", "run_id"}


def test_file_changes_channel_off_keeps_output_shape(tmp_path) -> None:
    """`file_changes_max=0`（默认）⇒ **不产出、不登记**：既有输出形状逐字不变。"""
    artifacts = RecordingArtifactStore()
    service, trusted, _ws = build_service(
        tmp_path,
        executor=_FileChangeExecutor(_change(0)),
        artifacts=artifacts,
    )
    _elf(str(trusted / "ls"))
    result = service.execute(run_cmd(str(trusted / "ls"), ["/workspace"]))

    assert result.output is None  # 既无摘录也无变更 ⇒ 无回传字段
    assert artifacts.calls == []


def test_artifact_registration_failure_never_changes_execution_result(tmp_path) -> None:
    """登记是「视图」：仓储失败**不影响执行结果**（结果仍 201，变更仍随帧回传）。"""
    artifacts = RecordingArtifactStore(fail=True)
    service, trusted, _ws = build_service(
        tmp_path,
        executor=_FileChangeExecutor(_change(0)),
        file_changes_max=50,
        artifacts=artifacts,
    )
    _elf(str(trusted / "ls"))
    result = service.execute(run_cmd(str(trusted / "ls"), ["/workspace"]))

    assert result.outcome == "executed" and result.code == 201
    assert len(result.output["file_changes"]) == 1


def test_blacklist_layer_a_executable_names() -> None:
    for name in ("rm", "sudo", "curl", "docker", "apt-get", "bash", "env", "busybox", "python"):
        assert executable_blacklist_hit(name), name
    assert executable_blacklist_hit("/usr/bin/rm") is True  # realpath 归一
    assert executable_blacklist_hit("myrm") is False
    assert executable_blacklist_hit("python.exe") is True  # 扩展名剥离
    assert executable_blacklist_hit("ls") is False
    # A8 内联代码：python -c / node -e（亦被 A12 裸解释器覆盖）
    assert executable_blacklist_hit("python", ["-c", "import os"]) is True
    assert executable_blacklist_hit("node", ["-e", "1"]) is True


def test_blacklist_layer_b_parameters() -> None:
    assert param_blacklist_hit("find", ["-delete"]) is True
    assert param_blacklist_hit("sed", ["-i", "a"]) is True
    assert param_blacklist_hit("sed", ["--in-place=.bak", "a"]) is True
    assert param_blacklist_hit("chmod", ["777", "a"]) is True
    assert param_blacklist_hit("chmod", ["a+rwx", "a"]) is True
    assert param_blacklist_hit("tar", ["-P", "-xf", "a.tar"]) is True
    assert param_blacklist_hit("git", ["config", "--global", "x"]) is True
    assert param_blacklist_hit("ls", ["/workspace"]) is False


def test_blacklist_layer_c_paths() -> None:
    for path in (
        "/etc/shadow",
        "/etc/sudoers",
        "/root/.bashrc",
        "/proc/self/environ",
        "/proc/1234/environ",
        "/proc/self/maps",
        "/sys/kernel/x",
        "/dev/sda",
        "~/.ssh/id_rsa",
        "/var/run/secrets/token",
        "/workspace/.env",
        "/workspace/key.pem",
        "/workspace/id_rsa",
    ):
        assert path_blacklist_hit(path), path
    assert path_blacklist_hit("/workspace/report.md") is False


def test_blacklist_layer_c_through_service(tmp_path) -> None:
    """工作卷内名为 `.env` 的文件仍须被 ④-2 C 拦下。"""
    service, _trusted, ws = build_service(tmp_path)
    service.workspace.create("t-1", "run-1")
    (ws / "t-1" / "run-1" / ".env").write_text("SECRET=1", encoding="utf-8")
    with pytest.raises(ToolExecutionError) as excinfo:
        service.execute(request("fs.read", {"path": "/workspace/.env", "max_bytes": 10}))
    assert excinfo.value.reason_code is ReasonCode.BLACKLISTED


def test_normalize_args_covers_r1() -> None:
    assert normalize_args(["-rf"]) == ["-r", "-f"]
    assert normalize_args(["--in-place=.bak"]) == ["--in-place", ".bak"]
    assert normalize_args(['"quoted"']) == ["quoted"]
    assert normalize_args(["RM"]) == ["rm"]
    assert READ_ONLY_WHITELIST == frozenset({"ls", "cat", "head", "tail", "wc", "stat", "file"})


# --------------------------------------------------- 参数规范化（§4.1.4 / 用例 28）


def test_args_digest_canonicalization_rules() -> None:
    assert args_digest({"a": 1, "b": 2}) == args_digest({"b": 2, "a": 1})  # 键序无关
    assert args_digest({"a": 1}) != args_digest({"a": 1.0})  # 类型不同
    assert args_digest({"a": 1.0}) == args_digest({"a": 1.00})  # 同为 float
    assert args_digest({"a": None}) != args_digest({})  # 缺键 ≠ null
    # 路径参数：分隔归一 / 折叠 / 去尾斜杠；不做大小写折叠。
    assert args_digest({"p": "a//b"}, path_params=("p",)) == args_digest(
        {"p": "a/b"}, path_params=("p",)
    )
    assert args_digest({"p": "a/./b/"}, path_params=("p",)) == args_digest(
        {"p": "a/b"}, path_params=("p",)
    )
    assert args_digest({"p": "A"}, path_params=("p",)) != args_digest(
        {"p": "a"}, path_params=("p",)
    )
    assert args_digest({"a": [1, 2]}) == args_digest({"a": [1, 2]})  # 稳定
    assert args_digest({"a": [1, 2]}) != args_digest({"a": [2, 1]})  # 数组顺序敏感
    assert args_digest({"a": 1}).startswith("sha256:")


# --------------------------------------------------------------------- ⑤ 风险定档


def test_critical_tool_needs_approval_even_for_full_auto(tmp_path) -> None:
    store = InMemoryToolActionStore()
    calls: list[tuple] = []

    def spy(autonomy: str, risk: str, threshold: str) -> bool:
        calls.append((autonomy, risk, threshold))
        from app.workforce.models import needs_approval

        return needs_approval(autonomy, risk, threshold)

    service, _trusted, _ws = build_service(
        tmp_path, store=store, artifact_export_enabled=True, needs_approval_fn=spy
    )
    result = service.execute(
        request("artifact.export", {"path": "/workspace/a", "target": "x"})
    )
    assert result.outcome == "pending_approval"
    # 必须经段一唯一判定入口 needs_approval（不得自写判定）。
    assert calls == [("full_auto", "critical", "high")]


# --------------------------------------------------------------------- ⑥ 落库


def test_pending_action_is_persisted_before_waiting(tmp_path) -> None:
    store = InMemoryToolActionStore()
    service, _trusted, _ws = build_service(tmp_path, store=store)
    result = service.execute(
        request("fs.write", {"path": "/workspace/a.txt", "content": "机密正文"})
    )
    assert result.outcome == "pending_approval"
    rows = store.list_for_run("t-1", "run-1")
    assert len(rows) == 1
    row = rows[0]
    assert row.status is ToolActionStatus.PENDING
    # 控制参数落 args_json；正文以占位常量替代（正文不落本列）。
    assert row.args_json == {"path": "/workspace/a.txt", "content": BODY_PLACEHOLDER}
    assert row.body_ciphertext is not None
    assert row.body_expires_at is not None
    # 用例 32①：`body_expires_at` = **该动作的审批超时时刻**（= 落库时刻 + 审批超时），不是随便一个未来值。
    assert row.body_expires_at == NOW + timedelta(minutes=DEFAULT_APPROVAL_TIMEOUT_MINUTES)
    # 未进入等待：trace 不含 ⑧。
    assert GATE_PERSIST in service.gate_trace
    assert GATE_EXECUTE not in service.gate_trace


# ------------------------------- 用例 32② / 32⑤ / 32⑥：密文不是明文、未等待不落密文、占位常量


def test_body_ciphertext_is_not_plaintext_and_meets_aesgcm_length_bound(tmp_path) -> None:
    """用例 32②(a)(b)（§3.4 约束 1 / Q2）：密文不是明文；长度下界 = 正文字节数 + 28。

    28 = AES-256-GCM 的 12B nonce + 16B tag（**有来源**，不是拍脑袋的常数）；下界不成立即
    说明**未按定死算法加密**（例如"只追加 nonce+tag 而不加密"会被 (a) 直接命中）。
    """
    store = InMemoryToolActionStore()
    service, _trusted, _ws = build_service(tmp_path, store=store)
    body = "机密正文：这段内容绝不应当以明文落库"
    service.execute(request("fs.write", {"path": "/workspace/a.txt", "content": body}))

    blob = store.list_for_run("t-1", "run-1")[0].body_ciphertext
    assert blob is not None
    # (a) hex / 原始字节均不含正文原文。
    assert body.encode("utf-8").hex() not in blob.hex()
    assert body.encode("utf-8") not in blob
    # (b) 长度下界：正文字节数 + 28（nonce 12B + tag 16B）。
    assert len(blob) >= len(body.encode("utf-8")) + 28


def test_action_not_entering_approval_leaves_no_body_ciphertext(tmp_path) -> None:
    """用例 32⑤（§3.4 红线范围声明）：未进入审批等待的动作**不落**密文列。"""
    store = InMemoryToolActionStore()
    service, _trusted, _ws = build_service(tmp_path, store=store)

    result = service.execute(request("fs.list", {"path": "/workspace"}))

    assert result.outcome == "executed"
    rows = store.list_for_run("t-1", "run-1")
    assert rows == []  # 无需审批 → 不产生待批动作
    assert all(row.body_ciphertext is None and row.body_expires_at is None for row in rows)


def test_body_placeholder_never_participates_in_digest_or_rebuild(tmp_path) -> None:
    """用例 32⑥ / §3.4 约束 5：占位常量只落 `args_json`（按键区分），**不参与** `args_digest`。"""
    store = InMemoryToolActionStore()
    service, _trusted, _ws = build_service(tmp_path, store=store)
    body = "机密正文"
    spec = ToolSpecCatalog(default_tool_specs()).get("fs.write")

    pending = service.execute(request("fs.write", {"path": "/workspace/a.txt", "content": body}))
    row = store.get("t-1", pending.action_id)

    assert row.args_json == {"path": "/workspace/a.txt", "content": BODY_PLACEHOLDER}
    # `args_digest` 按**完整参数（含正文）**一次算定。
    assert row.args_digest == args_digest(
        {"path": "/workspace/a.txt", "content": body}, path_params=path_param_names(spec)
    )
    # 若占位常量参与了摘要，二者会相等——如实断言**不相等**，堵死"拿占位值反算摘要"。
    assert row.args_digest != args_digest(row.args_json, path_params=path_param_names(spec))


# ---------------------------------------------- 用例 33①：审计明细不含正文与 args_digest


def test_blocked_audit_detail_has_no_body_and_no_args_digest(tmp_path) -> None:
    """用例 33①（§3.4 审计明细最小集）：`tool.blocked` 明细**不含**正文，也**不含** `args_digest`。"""
    audit = RecordingAudit()
    store = InMemoryToolActionStore()
    service, _trusted, _ws = build_service(tmp_path, store=store, audit=audit)
    body = "机密正文"
    pending = service.execute(request("fs.write", {"path": "/workspace/a.txt", "content": body}))
    row = store.get("t-1", pending.action_id)
    # 篡改密文 → 重跑解密失败 → 502 + `tool.blocked`（§4.1.6-5「⑦ 之后·正文解密失败」行）。
    tampered = bytearray(row.body_ciphertext)
    tampered[-1] ^= 0x01
    store.upsert(
        replace(
            row,
            status=ToolActionStatus.APPROVED,
            decided_by="ceo-1",
            decided_at=NOW,
            decision_source="user",
            body_ciphertext=bytes(tampered),
        )
    )

    with pytest.raises(ToolExecutionError) as excinfo:
        service.resume(tenant_id="t-1", run_id="run-1", approval_id=pending.approval_id)

    assert excinfo.value.http_status == 502
    assert [action for action, _ in audit.calls] == [AuditAction.TOOL_BLOCKED]
    detail = audit.calls[0][1]["detail"]
    assert set(detail) <= {"tool_key", "risk_level", "status", "reason", "run_id"}
    assert "args_digest" not in detail
    assert body not in str(detail)


# ---------------------------------- 用例 33③：`artifact.export` 导出通道不携带流程密文

_FORBIDDEN_EXPORT_NAMES = frozenset({"body_ciphertext", "body_cipher"})


def _export_channel_identifier_refs() -> set[str]:
    """按 AST 收集**导出通道实现面**（容器执行器）引用的标识符（避开文档字符串里的词）。"""
    names: set[str] = set()
    tree = ast.parse((ROOT / "app" / "tool_execution" / "executor.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            names.add(node.module or "")
            for alias in node.names:
                names.add(alias.name)
    return names & _FORBIDDEN_EXPORT_NAMES


def test_export_channel_source_never_touches_process_ciphertext() -> None:
    """用例 33③（§3.4 约束 3）：`artifact.export` 的导出通道与审批密文列**无关**。

    导出通道的实现面 = 容器执行器（组装命令 + 产出摘要）；以 AST 断言该模块**零引用**
    `body_ciphertext` / `body_cipher`，故导出物不可能携带流程密文。
    """
    assert _export_channel_identifier_refs() == set()


def test_persist_failure_returns_503_without_waiting(tmp_path) -> None:
    audit = RecordingAudit()
    service, _trusted, _ws = build_service(tmp_path, store=ExplodingStore(), audit=audit)
    with pytest.raises(ToolExecutionError) as excinfo:
        service.execute(request("fs.write", {"path": "/workspace/a.txt", "content": "x"}))
    assert excinfo.value.http_status == 503
    # 未产生副作用 / 未进入等待：不写 tool.* 审计、不触达 ⑧。
    assert audit.calls == []
    assert GATE_EXECUTE not in service.gate_trace


# --------------------------------------------------------------------- ⑦ 授权


def test_resume_rejects_unapproved_pending_action(tmp_path) -> None:
    """逐项授权：同运行内有另一个未批准的待批动作 → 409，不执行。"""
    store = InMemoryToolActionStore()
    approved = approved_action(
        tool_key="fs.list", params={"path": "/workspace"}, args_json={"path": "/workspace"}
    )
    store.upsert(approved)
    store.upsert(
        replace(
            approved_action(tool_key="fs.list", params={"path": "/workspace"}, args_json={"path": "/workspace"}),
            action_id="act-2",
            approval_id="appr-2",
            step_id="step-2",
            status=ToolActionStatus.PENDING,
            decided_by=None,
            decided_at=None,
            decision_source=None,
        )
    )
    audit = RecordingAudit()
    service, _trusted, _ws = build_service(tmp_path, store=store, audit=audit)

    with pytest.raises(ToolExecutionError) as excinfo:
        service.resume(tenant_id="t-1", run_id="run-1", approval_id="appr-1")

    assert excinfo.value.http_status == 409
    assert excinfo.value.reason_code is ReasonCode.NOT_AUTHORIZED
    assert [action for action, _ in audit.calls] == [AuditAction.TOOL_BLOCKED]


def test_resume_rejects_args_digest_mismatch(tmp_path) -> None:
    store = InMemoryToolActionStore()
    store.upsert(
        approved_action(
            tool_key="fs.list",
            params={"path": "/workspace"},
            args_json={"path": "/workspace/other"},
            args_digest_value="sha256:" + "0" * 64,
        )
    )
    service, _trusted, _ws = build_service(tmp_path, store=store)
    with pytest.raises(ToolExecutionError) as excinfo:
        service.resume(tenant_id="t-1", run_id="run-1", approval_id="appr-1")
    assert excinfo.value.http_status == 409
    assert excinfo.value.reason_code is ReasonCode.NOT_AUTHORIZED


def test_resume_calls_existing_ensure_execution_authorized(tmp_path) -> None:
    store = InMemoryToolActionStore()
    store.upsert(
        approved_action(tool_key="fs.list", params={"path": "/workspace"}, args_json={"path": "/workspace"})
    )
    authorizer = RecordingAuthorizer()
    service, _trusted, _ws = build_service(
        tmp_path, store=store, authorize_execution=authorizer
    )
    result = service.resume(
        tenant_id="t-1", run_id="run-1", approval_id="appr-1", actor=ACTOR, plan=PLAN
    )
    assert result.outcome == "executed"
    assert len(authorizer.calls) == 1
    call = authorizer.calls[0]
    assert (call["actor"], call["run_id"], call["plan"]) == (ACTOR, "run-1", PLAN)
    # §4.1.7-5：审批后重跑（需审批路径）必须**显式传入**待判动作投影，不得留空。
    assert call["actions"] is not None
    assert len(call["actions"]) == 1
    assert isinstance(call["actions"][0], AuthorizationAction)


def test_resume_rejected_by_existing_gate_is_409(tmp_path) -> None:
    store = InMemoryToolActionStore()
    store.upsert(
        approved_action(tool_key="fs.list", params={"path": "/workspace"}, args_json={"path": "/workspace"})
    )
    service, _trusted, _ws = build_service(
        tmp_path, store=store, authorize_execution=RecordingAuthorizer(allow=False)
    )
    with pytest.raises(ToolExecutionError) as excinfo:
        service.resume(
            tenant_id="t-1", run_id="run-1", approval_id="appr-1", actor=ACTOR, plan=PLAN
        )
    assert excinfo.value.http_status == 409
    assert excinfo.value.reason_code is ReasonCode.NOT_AUTHORIZED


# --------------------------------------------------------------------- ⑧ 假执行器


def test_resume_blacklist_hit_sets_rejected_not_approval_exempt(tmp_path) -> None:
    """④ 黑名单命中：审批**不允许放行**，`027` 行必须置 `rejected`。"""
    store = InMemoryToolActionStore()
    trusted = tmp_path / "trusted"
    trusted.mkdir(exist_ok=True)
    _elf(str(trusted / "rm"))
    params = {"executable": str(trusted / "rm"), "args": []}
    store.upsert(
        approved_action(
            tool_key="cmd.run", params=params, args_json=dict(params), risk_level=RiskLevel.MEDIUM
        )
    )
    audit = RecordingAudit()
    service, _trusted, _ws = build_service(tmp_path, store=store, audit=audit)

    with pytest.raises(ToolExecutionError) as excinfo:
        service.resume(tenant_id="t-1", run_id="run-1", approval_id="appr-1")

    assert excinfo.value.http_status == 403
    assert excinfo.value.reason_code is ReasonCode.BLACKLISTED
    assert excinfo.value.keep_approved is False
    assert store.get("t-1", "act-1").status is ToolActionStatus.REJECTED
    assert [action for action, _ in audit.calls] == [AuditAction.TOOL_BLOCKED]


def test_fake_executor_is_deterministic(tmp_path) -> None:
    store = InMemoryToolActionStore()
    store.upsert(
        approved_action(tool_key="fs.list", params={"path": "/workspace"}, args_json={"path": "/workspace"})
    )
    audit = RecordingAudit()
    service, _trusted, _ws = build_service(
        tmp_path, store=store, audit=audit, executor=DeterministicFakeExecutor()
    )
    first = service.resume(tenant_id="t-1", run_id="run-1", approval_id="appr-1")
    second = service.resume(tenant_id="t-1", run_id="run-1", approval_id="appr-1")
    assert first.outcome == "executed"
    assert first.summary == second.summary
    assert first.summary["tool_key"] == "fs.list"


def test_executor_timeout_maps_to_504(tmp_path) -> None:
    store = InMemoryToolActionStore()
    store.upsert(
        approved_action(tool_key="fs.list", params={"path": "/workspace"}, args_json={"path": "/workspace"})
    )
    audit = RecordingAudit()
    service, _trusted, _ws = build_service(
        tmp_path, store=store, audit=audit, executor=DeterministicFakeExecutor(timed_out=True)
    )
    with pytest.raises(ToolExecutionError) as excinfo:
        service.resume(tenant_id="t-1", run_id="run-1", approval_id="appr-1")
    assert excinfo.value.http_status == 504
    assert excinfo.value.reason_code is ReasonCode.TIMEOUT
    assert store.get("t-1", "act-1").status is ToolActionStatus.APPROVED
    assert [action for action, _ in audit.calls] == [AuditAction.TOOL_BLOCKED]


def test_executor_failure_maps_to_502(tmp_path) -> None:
    store = InMemoryToolActionStore()
    store.upsert(
        approved_action(tool_key="fs.list", params={"path": "/workspace"}, args_json={"path": "/workspace"})
    )
    service, _trusted, _ws = build_service(
        tmp_path, store=store, executor=DeterministicFakeExecutor(ok=False)
    )
    with pytest.raises(ToolExecutionError) as excinfo:
        service.resume(tenant_id="t-1", run_id="run-1", approval_id="appr-1")
    assert excinfo.value.http_status == 502
    assert excinfo.value.reason_code is ReasonCode.RUNTIME_ERROR


# --------------------------------------------------------------------- ⑨ 摘要与审计


def test_executed_audit_is_minimal_and_summary_only(tmp_path) -> None:
    store = InMemoryToolActionStore()
    store.upsert(
        approved_action(tool_key="fs.list", params={"path": "/workspace"}, args_json={"path": "/workspace"})
    )
    audit = RecordingAudit()
    service, _trusted, _ws = build_service(tmp_path, store=store, audit=audit)
    result = service.resume(tenant_id="t-1", run_id="run-1", approval_id="appr-1")

    assert [action for action, _ in audit.calls] == [AuditAction.TOOL_EXECUTED]
    detail = audit.calls[0][1]["detail"]
    assert set(detail) <= {"tool_key", "risk_level", "status", "reason", "run_id"}
    assert detail["tool_key"] == "fs.list"
    assert detail["risk_level"] == "low"
    assert "args_digest" not in detail
    # 结果只落摘要：不含参数原文 / 宿主路径。
    assert "args_digest" not in (result.summary or {})
    assert "/tmp" not in str(result.summary)


# --------------------------------------------------------------------- 通过路径留痕 / 重跑


def test_resume_reruns_steps_1_to_4_and_leaves_trace(tmp_path) -> None:
    store = InMemoryToolActionStore()
    service, _trusted, _ws = build_service(tmp_path, store=store)
    pending = service.execute(
        request("fs.write", {"path": "/workspace/a.txt", "content": "机密正文"})
    )
    # 审批通过（等价于决议端点把 027 行置 approved）。
    row = store.get("t-1", pending.action_id)
    store.upsert(
        replace(
            row,
            status=ToolActionStatus.APPROVED,
            decided_by="ceo-1",
            decided_at=NOW,
            decision_source="user",
        )
    )

    resume = service.resume(
        tenant_id="t-1", run_id="run-1", approval_id=pending.approval_id
    )

    assert resume.outcome == "executed"
    # 重跑必须**重新经过** ①–④（不是从 ⑦ 续跑）。
    for step in (GATE_WHITELIST, "②", "③", GATE_EXEC_BLACKLIST):
        assert step in service.gate_trace, step
        assert service.gate_calls[step] >= 2, step
    # ⑧ 只在审批通过后的重跑里发生一次（首次执行停在 ⑥）。
    assert service.gate_calls[GATE_EXECUTE] == 1


# --------------------------------------------- 用例 29：`actions` 缺省语义 + 投影（P0）

_RUNTIME_STEPS = [
    {"step_id": "s1", "kind": "read", "tool": "knowledge.search"},
    {"step_id": "s2", "kind": "write", "tool": "file.write"},
]
_DECIDER = UserContext("t-1", "ceo-1", "ceo")


def _runtime_task(task_store: TaskStore) -> Task:
    task = Task(
        tenant_id="t-1",
        project_id=None,
        created_by="u-1",
        employee_key="content-operator",
        title="用例 29",
        risk_level=RiskLevel.LOW,
        budget=1,
        idempotency_key="case-29",
        request_fingerprint="fp",
        status=TaskStatus.QUEUED,
    )
    task_store.create(ACTOR, task)
    return task


def build_runtime_service(*, tool_actions=None):
    task_store = TaskStore()
    task = _runtime_task(task_store)
    record_store = InMemoryRunRecordStore()
    service = RuntimeService(
        task_store,
        run_metrics=RunMetricsService(record_store),
        tool_actions=tool_actions,
    )
    return service, record_store, task


def _start_runtime_run(service: RuntimeService, task: Task) -> str:
    run_id, _key, _version = service.start(
        ACTOR, task.id, "mock", _RUNTIME_STEPS, "product_manager"
    )
    return run_id


def _approval_row(run_id: str, **overrides) -> ToolAction:
    return approved_action(
        tool_key="fs.list",
        params={"path": "/workspace"},
        args_json={"path": "/workspace"},
        run_id=run_id,
        **overrides,
    )


def test_use_case_29_1_default_actions_executes_once_on_no_approval_path(tmp_path) -> None:
    """① `actions` 缺省 + 「⑤ 判定无需审批」路径 → 只退化为运行级摘要比对，且进入 ⑧（执行器被调用一次）。"""
    executor = DeterministicFakeExecutor()
    authorizer = RecordingAuthorizer()
    service, _trusted, _ws = build_service(
        tmp_path, executor=executor, authorize_execution=authorizer
    )

    result = service.execute(request("fs.list", {"path": "/workspace"}), actor=ACTOR, plan=PLAN)

    assert result.outcome == "executed"
    assert result.code == 201
    # 打桩断言：执行器被调用**一次**。
    assert executor.call_count == 1
    assert len(executor.calls) == 1
    assert executor.calls[0]["tool_key"] == "fs.list"
    # ②③④ 的判定留痕存在（§4.1.6-6）。
    for step in (GATE_PARAMS, GATE_PATH, GATE_EXEC_BLACKLIST):
        assert step in service.gate_trace, step
    # 缺省 → 既有闸门收到 actions=None（只退化为运行级摘要比对，不含 fail-open）。
    assert authorizer.calls[0]["actions"] is None


def test_use_case_29_1_default_actions_is_run_level_digest_only() -> None:
    """① 缺省在无需审批路径只做**运行级摘要比对**：计划与授权一致→放行；变更→拒绝。"""
    service, _record_store, task = build_runtime_service(tool_actions=InMemoryToolActionStore())
    run_id = _start_runtime_run(service, task)
    service.decide_approval(_DECIDER, run_id, "s2", True)
    state = service.snapshot(_DECIDER, run_id)

    # 一致 → 放行（动作缺省，仅比对运行级摘要）。
    service.ensure_execution_authorized(_DECIDER, run_id, state.plan)

    changed = AgentPlan.from_steps(
        [
            {"step_id": "s1", "kind": "read", "tool": "knowledge.search"},
            {"step_id": "s2", "kind": "delete", "tool": "file.delete"},
        ]
    )
    with pytest.raises(ExecutionNotAuthorized):
        service.ensure_execution_authorized(_DECIDER, run_id, changed)


def test_use_case_29_2_default_actions_on_approval_path_is_refused() -> None:
    """② `actions` 缺省却处于「⑤ 判定需审批」路径 → 必须拒绝（接口层 409）。"""
    store = InMemoryToolActionStore()
    service, _record_store, task = build_runtime_service(tool_actions=store)
    run_id = _start_runtime_run(service, task)
    state = service.snapshot(_DECIDER, run_id)
    store.upsert(_approval_row(run_id, plan_digest=plan_digest(state.plan)))

    with pytest.raises(ExecutionNotAuthorized) as excinfo:
        service.ensure_execution_authorized(_DECIDER, run_id, state.plan)  # 缺省

    assert "缺省" in str(excinfo.value)
    # 对照：显式传入投影则放行 —— 证明拒绝原因是「缺省」而非其它。
    row = store.list_for_run("t-1", run_id)[0]
    service.ensure_execution_authorized(
        _DECIDER, run_id, state.plan, actions=[AuthorizationAction.from_row(row)]
    )


def test_use_case_29_3_projection_has_exactly_eight_non_empty_fields() -> None:
    """③ 投影 8 字段逐个非空；`args_digest` 与 §4.1.4 一致；不含参数原文与 `args_json`。"""
    spec = ToolSpecCatalog(default_tool_specs()).get("fs.list")
    params = {"path": "/workspace"}
    row = approved_action(tool_key="fs.list", params=params, args_json={"path": "/workspace"})

    action = AuthorizationAction.from_row(row)

    # 逐字段：恰好 8 个、逐个非空，字段集合不含 args_json。
    assert authorization_action_field_names() == AUTHORIZATION_ACTION_FIELDS
    assert len(AUTHORIZATION_ACTION_FIELDS) == 8
    assert "args_json" not in authorization_action_field_names()
    for name in AUTHORIZATION_ACTION_FIELDS:
        assert getattr(action, name), name
    assert action.missing_fields() == ()
    assert validate_authorization_action(action) is None

    # args_digest 与 §4.1.4 算法一致。
    assert action.args_digest == args_digest(params, path_params=path_param_names(spec))

    # 反例：投影中不含参数原文与 args_json（整行才有 args_json，投影刻意没有）。
    assert not hasattr(action, "args_json")
    assert hasattr(row, "args_json")
    assert "args_json" not in repr(action)
    assert "/workspace" not in repr(action)
    assert "content" not in repr(action)
    # 且投影**不是** store 的整行 ToolAction（命名冲突显式改名，未 shadow / 未复用同一类）。
    assert type(action) is AuthorizationAction
    assert not isinstance(action, ToolAction)


def test_use_case_29_3_missing_field_fails_closed() -> None:
    """③ 反例：投影任一字段为空 → fail-closed（不得静默通过）。"""
    row = approved_action(tool_key="fs.list", params={"path": "/workspace"})
    for name in AUTHORIZATION_ACTION_FIELDS:
        empty = False if name == "requires_approval" else ""
        broken = replace(AuthorizationAction.from_row(row), **{name: empty})
        assert name in broken.missing_fields(), name
        with pytest.raises(ExecutionNotAuthorized):
            validate_authorization_action(broken)
