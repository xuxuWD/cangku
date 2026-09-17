"""§3.3 容器加固口径 + §8 U17 ⑥ 孤儿治理的真实容器验收（段二-3）。

**真容器验证**（不是静态检查）：需要本机 Docker 与钉死镜像；两者缺一时整组跳过
（skipped 计入基线，属预期）。
"""

from __future__ import annotations

import uuid

import pytest

from app.tool_execution.executor import (
    DEV_SHM_MOUNT,
    EXEC_USER,
    INTERNAL_NETWORK_NAME,
    MANAGED_LABEL,
    TMP_MOUNT,
    WORKSPACE_MOUNT,
    ContainerExecutor,
    OrphanLimitExceeded,
)
from app.tool_execution.errors import ToolExecutionConfigError
from app.tool_execution.cleanup import OrphanCleanupTask

# 应用镜像的基础镜像（digest 钉死，本机已有 ⇒ 无需联网拉取）。
IMAGE_DIGEST = (
    "python:3.12-slim@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea"
)
PIDS_LIMIT = 256
MEMORY_MB = 256
CPU_QUOTA = 1.0
TIMEOUT_SECONDS = 60


def _docker_client():
    docker = pytest.importorskip("docker")
    try:
        client = docker.from_env()
        client.ping()
    except Exception:  # noqa: BLE001 - 无守护进程 → 整组跳过
        pytest.skip("Docker 守护进程不可用，跳过真实容器验收")
    try:
        client.images.get(IMAGE_DIGEST)
    except Exception:  # noqa: BLE001 - 钉死镜像缺失 → 整组跳过（不联网拉取）
        pytest.skip("钉死镜像不在本机，跳过真实容器验收")
    return client


@pytest.fixture(scope="module")
def client():
    return _docker_client()


@pytest.fixture(scope="module", autouse=True)
def _purge_managed_containers(client):
    """进/出都清一遍托管容器，避免跨用例残留影响孤儿计数。"""

    def purge():
        for container in client.containers.list(
            all=True, filters={"label": f"{MANAGED_LABEL}=1"}
        ):
            container.remove(force=True)

    purge()
    yield
    purge()


@pytest.fixture()
def executor(client):
    return ContainerExecutor(
        image_digest=IMAGE_DIGEST,
        pids_limit=PIDS_LIMIT,
        memory_mb=MEMORY_MB,
        cpu_quota=CPU_QUOTA,
        timeout_seconds=TIMEOUT_SECONDS,
        client_factory=lambda: client,
    )


def cmd(code: str) -> dict:
    return {"executable": "python", "args": ["-c", code]}


def workspace(label: str) -> str:
    return f"/srv/exec-ws/t-{label}/{uuid.uuid4().hex[:8]}"


# --------------------------------------------------------------- 加固口径逐项


def test_container_spec_is_hardened(executor, client) -> None:
    container = executor.create(
        tool_key="cmd.run", params=cmd("import time; time.sleep(30)"), workspace_path=workspace("spec")
    )
    try:
        container.reload()
        host = container.attrs["HostConfig"]
        assert host["ReadonlyRootfs"] is True  # 根只读
        assert container.attrs["Config"]["User"] == EXEC_USER  # 非 root
        assert host["CapDrop"] == ["ALL"]  # 能力全剥夺
        assert host["SecurityOpt"] == ["no-new-privileges"]  # 禁止提权
        assert host["Privileged"] is False
        assert host["PidsLimit"] == PIDS_LIMIT
        assert host["Memory"] == MEMORY_MB * 1024 * 1024
        assert host["NanoCpus"] == int(CPU_QUOTA * 1_000_000_000)
        assert host["NetworkMode"] == INTERNAL_NETWORK_NAME
        assert "@sha256:" in container.attrs["Config"]["Image"]  # digest 钉死
        network = client.networks.get(INTERNAL_NETWORK_NAME)
        assert network.attrs["Internal"] is True  # 内网桥：无外网出口
        tmpfs = host["Tmpfs"]
        assert set(tmpfs) >= {WORKSPACE_MOUNT, TMP_MOUNT, DEV_SHM_MOUNT}
        assert "noexec" in tmpfs[WORKSPACE_MOUNT]
        assert "nosuid" in tmpfs[WORKSPACE_MOUNT]
        assert "nodev" in tmpfs[WORKSPACE_MOUNT]
        # G7（2026-09-15 真容器实测更正）：`uid/gid/mode` 必须**显式钉死**，不得依赖 Docker 默认值——
        # Docker 对 `--tmpfs` 的默认是 `mode=1777`，但**一旦容器带 `--workdir` 指向该 tmpfs**，
        # 该挂载会被改写成 `mode=755`（root:root）⇒ 以 65534 运行的工具**无法写工作卷**
        # （实测 `PermissionError: [Errno 13]`）。显式指定后，行为与是否设 workdir 无关。
        assert "uid=65534" in tmpfs[WORKSPACE_MOUNT]
        assert "gid=65534" in tmpfs[WORKSPACE_MOUNT]
        assert "mode=700" in tmpfs[WORKSPACE_MOUNT]  # 工作卷：仅执行者可读写
        assert "mode=1777" in tmpfs[TMP_MOUNT]  # /tmp 保持标准
        assert "mode=1777" in tmpfs[DEV_SHM_MOUNT]  # /dev/shm 保持标准
        # 不得挂 docker.sock
        mounts = host.get("Mounts") or []
        assert all("docker.sock" not in (m.get("Source") or "") for m in mounts)
    finally:
        executor.remove_container(container)


def test_effective_identity_and_capabilities_inside_container(executor) -> None:
    container = executor.create(
        tool_key="cmd.run",
        params=cmd(
            "import os;print(os.getuid(), os.getgid());"
            "print([l for l in open('/proc/self/status') if l.startswith('CapEff')][0].strip());"
            "open('/workspace/probe.txt','w').write('x')"
        ),
        workspace_path=workspace("identity"),
    )
    try:
        code = container.wait(timeout=TIMEOUT_SECONDS)["StatusCode"]
        logs = container.logs().decode()
        assert code == 0, logs
        assert "65534 65534" in logs  # 非 root 生效
        assert "CapEff:\t0000000000000000" in logs  # cap 全剥夺
    finally:
        executor.remove_container(container)


def test_workspace_is_owned_by_exec_user_and_writable(executor) -> None:
    """G7 功能回归：工作卷必须**由执行者拥有且可写**（真容器实测，不只看挂载字符串）。

    动机（2026-09-15 实测）：工作卷的可写性曾依赖 Docker 对 `--tmpfs` 的默认值；
    一旦容器带 `--workdir` 指向工作卷，该挂载会被改写成 `root:root mode=755` ⇒ 工具写失败。
    本用例断言「归属 + 权限 + 真能写入」三件事，使该回归**与是否设 workdir 无关**。
    """
    container = executor.create(
        tool_key="cmd.run",
        params=cmd(
            "import os,stat;"
            "s=os.stat('/workspace');"
            "print('MODE', oct(stat.S_IMODE(s.st_mode)), 'UID', s.st_uid, 'GID', s.st_gid);"
            "open('/workspace/probe.txt','w').write('x');"
            "print('WROTE_OK')"
        ),
        workspace_path=workspace("g7"),
    )
    try:
        code = container.wait(timeout=TIMEOUT_SECONDS)["StatusCode"]
        logs = container.logs().decode()
        assert code == 0, logs
        assert "MODE 0o700 UID 65534 GID 65534" in logs, logs
        assert "WROTE_OK" in logs, logs
    finally:
        executor.remove_container(container)


def test_workspace_starts_empty_and_is_destroyed_with_container(executor, client) -> None:
    container = executor.create(
        tool_key="cmd.run",
        params=cmd("import os;print(sorted(os.listdir('/workspace')))"),
        workspace_path=workspace("ws"),
    )
    container_id = container.id
    try:
        assert container.wait(timeout=TIMEOUT_SECONDS)["StatusCode"] == 0
        assert container.logs().decode().strip().endswith("[]")  # 生成即空
    finally:
        executor.remove_container(container)
    with pytest.raises(Exception):
        client.containers.get(container_id)  # 运行结束销毁（工作卷随容器消失）


def test_container_has_no_external_egress(executor) -> None:
    container = executor.create(
        tool_key="cmd.run",
        params=cmd(
            "import socket\n"
            "try:\n"
            "    socket.create_connection(('1.1.1.1', 53), timeout=3)\n"
            "    print('EGRESS_OK')\n"
            "except Exception as exc:\n"
            "    print('EGRESS_BLOCKED', type(exc).__name__)\n"
        ),
        workspace_path=workspace("net"),
    )
    try:
        container.wait(timeout=TIMEOUT_SECONDS)
        logs = container.logs().decode()
        assert "EGRESS_OK" not in logs, logs
        assert "EGRESS_BLOCKED" in logs, logs
    finally:
        executor.remove_container(container)


def test_timeout_kills_container(executor, client) -> None:
    quick = ContainerExecutor(
        image_digest=IMAGE_DIGEST,
        pids_limit=PIDS_LIMIT,
        memory_mb=MEMORY_MB,
        cpu_quota=CPU_QUOTA,
        timeout_seconds=2,
        client_factory=lambda: client,
    )
    outcome = quick.execute(
        tool_key="cmd.run", params=cmd("import time; time.sleep(120)"), workspace_path=workspace("to")
    )
    assert outcome.timed_out is True
    assert outcome.ok is False
    # 超时 = 拒绝并终止容器：不得留下任何托管容器残留
    assert quick.managed_containers() == []


# --------------------------------------------------------------- ⑥ 孤儿上限与清扫


def test_orphan_limit_refuses_then_cleanup_recovers(executor, client) -> None:
    # 造一个「崩溃残留」：起容器后把它从在跑集合里摘掉（= 本进程未再跟踪）
    leaked = executor.create(
        tool_key="cmd.run", params=cmd("import time; time.sleep(120)"), workspace_path=workspace("leak")
    )
    executor._live.discard(leaked.id)

    strict = ContainerExecutor(
        image_digest=IMAGE_DIGEST,
        pids_limit=PIDS_LIMIT,
        memory_mb=MEMORY_MB,
        cpu_quota=CPU_QUOTA,
        timeout_seconds=5,
        orphan_limit=0,
        client_factory=lambda: client,
    )
    with pytest.raises(OrphanLimitExceeded):
        strict.execute(
            tool_key="cmd.run", params=cmd("print('never')"), workspace_path=workspace("strict")
        )

    assert strict.cleanup_orphans() >= 1  # 清扫回收
    assert strict.managed_containers() == []
    outcome = strict.execute(
        tool_key="cmd.run", params=cmd("print('ok')"), workspace_path=workspace("after")
    )
    assert outcome.ok is True


def test_orphan_cleanup_task_runs_and_reports() -> None:
    class _Executor:
        def __init__(self) -> None:
            self.calls = 0

        def cleanup_orphans(self) -> int:
            self.calls += 1
            return 2

    fake = _Executor()
    task = OrphanCleanupTask(fake, interval_seconds=60)
    report = task.run_once()
    assert report.orphans_removed == 2
    assert fake.calls == 1


def test_orphan_cleanup_task_never_raises_on_failure() -> None:
    class _Boom:
        def cleanup_orphans(self) -> int:
            raise RuntimeError("daemon down")

    report = OrphanCleanupTask(_Boom(), interval_seconds=60).run_once()
    assert report.failures == 1


# --------------------------------------------------------------- 装配红线（无需容器）


def test_tag_image_is_rejected() -> None:
    with pytest.raises(ToolExecutionConfigError):
        ContainerExecutor(
            image_digest="alpine:latest",
            pids_limit=1,
            memory_mb=1,
            cpu_quota=1.0,
            timeout_seconds=1,
        )


def test_unknown_tool_fails_closed_before_starting_container(executor) -> None:
    """未实现 / 未装配的工具在**起容器之前**即 fail-closed（P2c-3 起 `fs.*` 已落地，
    故此处改用仍不装配的 `artifact.export` 作样本；口径不变）。"""
    with pytest.raises(ToolExecutionConfigError):
        executor.execute(
            tool_key="artifact.export",
            params={"path": "/workspace/a.txt", "target": "team-a"},
            workspace_path="/tmp/x",
        )
    with pytest.raises(ToolExecutionConfigError):
        executor.execute(tool_key="fs.chmod", params={"path": "/workspace/a.txt"}, workspace_path="/tmp/x")


def test_terminal_state_revoker_is_called_on_success(client) -> None:
    seen: list[str] = []
    executor = ContainerExecutor(
        image_digest=IMAGE_DIGEST,
        pids_limit=PIDS_LIMIT,
        memory_mb=MEMORY_MB,
        cpu_quota=CPU_QUOTA,
        timeout_seconds=TIMEOUT_SECONDS,
        client_factory=lambda: client,
        token_revoker=seen.append,
    )
    executor.execute(tool_key="cmd.run", params=cmd("print('ok')"), workspace_path="/srv/exec-ws/t-1/run-abc")
    assert seen == ["run-abc"]


def test_terminal_state_revoker_failure_does_not_break_execution(client) -> None:
    def boom(_bound: str) -> None:
        raise RuntimeError("gateway down")

    executor = ContainerExecutor(
        image_digest=IMAGE_DIGEST,
        pids_limit=PIDS_LIMIT,
        memory_mb=MEMORY_MB,
        cpu_quota=CPU_QUOTA,
        timeout_seconds=TIMEOUT_SECONDS,
        client_factory=lambda: client,
        token_revoker=boom,
    )
    outcome = executor.execute(
        tool_key="cmd.run", params=cmd("print('ok')"), workspace_path=workspace("rev")
    )
    assert outcome.ok is True
