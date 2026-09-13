"""`WorkspaceManager` 与 `ContainerExecutor` 的装配口径（规格 §3.3 / §4.1.6-1）。

判据：工作目录「生成即空、运行结束销毁」；容器执行器按 §3.3 加固口径装配并**真实执行**
（夹具在 `tests/test_container_executor.py`）。本文件覆盖**装配期**口径：镜像 digest 必须钉死、
参数映射正确、Docker 不可用时**fail-closed**（不再有 `NotImplementedError` 占位）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.settings import Settings
from app.tool_execution.errors import ToolExecutionConfigError, WorkspaceError
from app.tool_execution.executor import ContainerExecutor
from app.tool_execution.workspace import WorkspaceManager


def test_workspace_is_fresh_and_empty_then_destroyed(tmp_path) -> None:
    manager = WorkspaceManager(str(tmp_path))
    path = manager.create("t-1", "run-1")
    assert Path(path).is_dir()
    assert list(Path(path).iterdir()) == []
    # 「生成即空」：已存在的工作目录不得被复用。
    with pytest.raises(WorkspaceError):
        manager.create("t-1", "run-1")
    manager.destroy("t-1", "run-1")
    assert not Path(path).exists()


def test_workspace_rejects_unsafe_segments(tmp_path) -> None:
    manager = WorkspaceManager(str(tmp_path))
    for tenant, run in (("../escape", "run-1"), ("t-1", "../escape"), ("t-1", "a/b")):
        with pytest.raises(WorkspaceError):
            manager.create(tenant, run)


def test_workspace_requires_a_root() -> None:
    for bad in ("", "   "):
        with pytest.raises(ToolExecutionConfigError):
            WorkspaceManager(bad)


def test_container_executor_maps_settings_to_args() -> None:
    settings = Settings(
        env="development",
        exec_image_digest="registry.local/dsh@sha256:abc",
        exec_pids_limit=64,
        exec_memory_mb=512,
        exec_cpu_quota=1.5,
        exec_timeout_seconds=120,
    )
    executor = ContainerExecutor.from_settings(settings)
    spec = executor.build_spec()
    args = spec.docker_args("/tmp/ws")
    assert args[:2] == ["run", "--rm"]
    assert args[args.index("--pids-limit") + 1] == "64"
    assert args[args.index("--memory") + 1] == "512m"
    assert args[args.index("--cpus") + 1] == "1.5"
    assert args[args.index("--pids-limit") + 1] != args[args.index("--memory") + 1]
    assert "registry.local/dsh@sha256:abc" in args
    # 超时是执行侧硬上限，不是 docker 参数；挂在 spec 上由 ⑧ 使用。
    assert spec.timeout_seconds == 120


def test_container_executor_execute_fails_closed_without_docker(tmp_path) -> None:
    """真实执行已落地（段二-3）：不再抛 `NotImplementedError`；Docker 不可用时 fail-closed。"""

    def no_docker():
        raise ToolExecutionConfigError("Docker 守护进程不可用")

    executor = ContainerExecutor(
        image_digest="registry.local/dsh@sha256:abc",
        pids_limit=64,
        memory_mb=512,
        cpu_quota=1.5,
        timeout_seconds=120,
        client_factory=no_docker,
    )
    with pytest.raises(ToolExecutionConfigError):
        executor.execute(
            tool_key="cmd.run",
            params={"executable": "python", "args": ["-c", "print(1)"]},
            workspace_path=str(tmp_path),
        )


def test_container_executor_rejects_tag_image(tmp_path) -> None:
    """§3.3：镜像必须按 digest 钉死，浮动 tag 一律拒绝。"""
    with pytest.raises(ToolExecutionConfigError):
        ContainerExecutor(
            image_digest="registry.local/dsh:latest",
            pids_limit=64,
            memory_mb=512,
            cpu_quota=1.5,
            timeout_seconds=120,
        )


def test_container_executor_requires_image_digest() -> None:
    with pytest.raises(ToolExecutionConfigError):
        ContainerExecutor(
            image_digest="",
            pids_limit=64,
            memory_mb=512,
            cpu_quota=1.5,
            timeout_seconds=120,
        )
