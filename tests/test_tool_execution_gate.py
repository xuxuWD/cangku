"""九步闸门（段二-2）用例：①白名单 / ②参数 / ③路径 / ④危险命令 / ⑤定档 / ⑥落库 /
⑦授权 / ⑧假执行器 / ⑨摘要与审计 / 通过路径留痕 / 审批后重跑。

真源：`docs/superpowers/specs/2026-09-12-dsh-integration-design.md` §3.2 / §3.2.1 / §4.1.4 / §4.1.6。
**离线可验收**：全部用假执行器，不起容器、不连真库、不出网。
"""

from __future__ import annotations

import base64
import os
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from app.audit.models import AuditAction
from app.domain import RiskLevel, UserContext
from app.runtime.authorization import ExecutionNotAuthorized
from app.runtime.contracts import AgentPlan
from app.tool_execution.args_digest import args_digest
from app.tool_execution.blacklist import (
    READ_ONLY_WHITELIST,
    executable_blacklist_hit,
    normalize_args,
    param_blacklist_hit,
)
from app.tool_execution.body_cipher import BodyCipher
from app.tool_execution.catalog import ToolSpecCatalog, default_tool_specs
from app.tool_execution.errors import ToolExecutionError
from app.tool_execution.executor import DeterministicFakeExecutor
from app.tool_execution.params import path_param_names
from app.tool_execution.paths import path_blacklist_hit
from app.tool_execution.service import (
    BODY_PLACEHOLDER,
    GATE_EXEC_BLACKLIST,
    GATE_EXEC_NAME,
    GATE_EXEC_SOURCE,
    GATE_EXECUTE,
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

NOW = datetime(2026, 9, 13, 12, 0, tzinfo=UTC)
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
        self.calls: list[tuple] = []

    def __call__(self, actor, run_id, plan) -> None:
        self.calls.append((actor, run_id, plan))
        if not self.allow:
            raise ExecutionNotAuthorized("模拟既有闸门拒绝")


def _key() -> str:
    return base64.b64encode(os.urandom(32)).decode("ascii")


def _elf(path: str, *, body: bytes = b"\x7fELF" + b"\x00" * 64, mode: int = 0o555) -> str:
    with open(path, "wb") as handle:
        handle.write(body)
    os.chmod(path, mode)
    return path


def build_service(
    tmp_path,
    *,
    store=None,
    audit=None,
    executor=None,
    artifact_export_enabled: bool = False,
    authorize_execution=None,
    needs_approval_fn=None,
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
        now=lambda: NOW,
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
    assert row.body_expires_at > NOW
    # 未进入等待：trace 不含 ⑧。
    assert GATE_PERSIST in service.gate_trace
    assert GATE_EXECUTE not in service.gate_trace


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
    assert authorizer.calls == [(ACTOR, "run-1", PLAN)]


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
