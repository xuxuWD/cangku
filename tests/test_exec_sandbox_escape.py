"""G5 沙箱逃逸回归（规格 §5 用例 **36–48**）——**真实容器**逐条取证。

口径来源：规格 §3.3 / §8 **U28**；[`docs/sandbox-boundary-decision.md`](../docs/sandbox-boundary-decision.md)
§3.1（2026-09-15 真容器实测）。本文件把调研给出的 **13 条逃逸用例**固化成**可判定的回归**：

    36 越界写 / 37 越界读 / 38 软链穿越 / 39 HTTP 出网 / 40 DNS 外泄 / 41 云元数据 /
    42 环境变量泄密 / 43 fork 炸弹 / 44 提权 / 45 持久化外溢 / 46 逃逸面侦察 /
    47 磁盘耗尽 / 48 Windows 穿透通道

每条断言都把**容器内原始输出**作为断言消息（`assert <判据>, logs`）⇒ 失败即附原始输出，不做转述。

**不得**把本文件全绿读成「沙箱是安全边界」：边界 = **主机边界 + 九步闸门 + 无长寿命凭据**，
容器层为**风险削减**（§15 #2 / §8 U28）。

未验证边界（不得外推）：
  1. 本组用例在**本机 Docker** 上取证；**生产执行宿主未复测**（§8 U28 第四节）。
  2. 用例 48 只证明**执行容器内**不存在 `cmd.exe` / `/mnt/c` 通道；**Windows 宿主侧**的 drvfs 与
     unix socket 两条穿透通道属 **R7**（桌面端是否承载工具执行），**另立裁决**，本文件不处理。
  3. 本组是**回归**（把已声明口径固化为断言），不是新的隔离机制。

需要本机 Docker 与钉死镜像；两者缺一时整组跳过（skipped 计入基线，属预期）。
"""

from __future__ import annotations

import os
import uuid

import pytest

from app.tool_execution.executor import (
    EXEC_USER,
    MANAGED_LABEL,
    ContainerExecutor,
)
from app.runtime.adapters.dsh import ENV_API_KEY, ENV_BASE_URL

# 与 Dockerfile:14 / tests/test_container_executor.py:28 同一取值（§4 执行镜像口径）。
IMAGE_DIGEST = (
    "python:3.12-slim@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea"
)
PIDS_LIMIT = 256
MEMORY_MB = 256
CPU_QUOTA = 1.0
TIMEOUT_SECONDS = 60
GATEWAY_URL = "http://workbench-model-gateway:8090"


def _docker_client():
    docker = pytest.importorskip("docker")
    try:
        client = docker.from_env()
        client.ping()
    except Exception:  # noqa: BLE001 - 无守护进程 → 整组跳过
        pytest.skip("Docker 守护进程不可用，跳过沙箱逃逸回归")
    try:
        client.images.get(IMAGE_DIGEST)
    except Exception:  # noqa: BLE001 - 钉死镜像缺失 → 整组跳过（不联网拉取）
        pytest.skip("钉死镜像不在本机，跳过沙箱逃逸回归")
    return client


@pytest.fixture(scope="module")
def client():
    return _docker_client()


@pytest.fixture(scope="module", autouse=True)
def _purge_managed_containers(client):
    """进/出都清一遍托管容器，避免跨用例残留（与 test_container_executor.py 同口径）。"""

    def purge():
        for container in client.containers.list(
            all=True, filters={"label": f"{MANAGED_LABEL}=1"}
        ):
            container.remove(force=True)

    purge()
    yield
    purge()


def _executor(client, **overrides) -> ContainerExecutor:
    kwargs = dict(
        image_digest=IMAGE_DIGEST,
        pids_limit=PIDS_LIMIT,
        memory_mb=MEMORY_MB,
        cpu_quota=CPU_QUOTA,
        timeout_seconds=TIMEOUT_SECONDS,
    )
    kwargs.update(overrides)
    return ContainerExecutor(client_factory=lambda: client, **kwargs)


@pytest.fixture()
def executor(client):
    return _executor(client)


def _cmd(code: str) -> dict:
    return {"executable": "python", "args": ["-c", code]}


def _workspace(label: str) -> str:
    return f"/srv/exec-ws/t-{label}/{uuid.uuid4().hex[:8]}"


def _run(
    executor: ContainerExecutor,
    code: str,
    *,
    label: str,
    workspace_path: str | None = None,
    environment: dict | None = None,
    timeout: int = TIMEOUT_SECONDS,
) -> tuple[int, str]:
    """起一个加固容器跑探针，返回 `(退出码, 容器内原始输出)`；容器用后即毁。"""
    container = executor.create(
        tool_key="cmd.run",
        params=_cmd(code),
        workspace_path=workspace_path or _workspace(label),
        environment=environment,
    )
    try:
        status = container.wait(timeout=timeout)["StatusCode"]
        logs = container.logs().decode("utf-8", "replace")
    finally:
        executor.remove_container(container)
    return status, logs


# --------------------------------------------------- 36 越界写（只读根 + 非 root）

def test_escape_write_outside_workspace_is_denied(executor) -> None:
    """用例 36：向只读根写文件必须被内核拒绝（`EROFS`）。"""
    _, logs = _run(
        executor,
        "try:\n"
        "    open('/etc/probe.txt','w').write('x')\n"
        "    print('WROTE_OK')\n"
        "except OSError as exc:\n"
        "    print('WRITE_BLOCKED', type(exc).__name__, exc.strerror)\n",
        label="36",
    )
    assert "WROTE_OK" not in logs, logs
    assert "WRITE_BLOCKED" in logs and "Read-only file system" in logs, logs


# --------------------------------------------------- 37 越界读（非 root）

def test_escape_read_protected_file_is_denied(executor) -> None:
    """用例 37：读 `/etc/shadow`（非全局可读）必须被拒，且**不得回显任何内容**。"""
    _, logs = _run(
        executor,
        "try:\n"
        "    data = open('/etc/shadow','rb').read()\n"
        "    print('READ_OK', len(data))\n"
        "except OSError as exc:\n"
        "    print('READ_BLOCKED', type(exc).__name__, exc.strerror)\n",
        label="37",
    )
    assert "READ_OK" not in logs, logs
    assert "READ_BLOCKED" in logs and "Permission denied" in logs, logs


# --------------------------------------------------- 38 软链穿越

def test_escape_symlink_traversal_is_denied(executor) -> None:
    """用例 38：工作卷内建指向 `/etc` 的符号链接，**写穿**与**读敏感文件**都必须被拒。"""
    _, logs = _run(
        executor,
        "import os\n"
        "os.symlink('/etc', '/workspace/esc')\n"
        "print('SYMLINK_CREATED', os.path.islink('/workspace/esc'))\n"
        "try:\n"
        "    open('/workspace/esc/probe.txt','w').write('x')\n"
        "    print('SYMLINK_WROTE_OK')\n"
        "except OSError as exc:\n"
        "    print('SYMLINK_WRITE_BLOCKED', type(exc).__name__, exc.strerror)\n"
        "try:\n"
        "    data = open('/workspace/esc/shadow','rb').read()\n"
        "    print('SYMLINK_READ_OK', len(data))\n"
        "except OSError as exc:\n"
        "    print('SYMLINK_READ_BLOCKED', type(exc).__name__, exc.strerror)\n",
        label="38",
    )
    assert "SYMLINK_CREATED True" in logs, logs
    assert "SYMLINK_WROTE_OK" not in logs, logs
    assert "SYMLINK_READ_OK" not in logs, logs
    assert "SYMLINK_WRITE_BLOCKED" in logs, logs
    assert "SYMLINK_READ_BLOCKED" in logs, logs


# --------------------------------------------------- 39 HTTP 出网 / 40 DNS 外泄 / 41 云元数据

def test_escape_http_egress_is_blocked(executor) -> None:
    """用例 39：内网桥（`--internal`）下对外 TCP 必须 `Network is unreachable`。"""
    _, logs = _run(
        executor,
        "import socket\n"
        "for host, port in (('1.1.1.1', 443), ('1.1.1.1', 80), ('8.8.8.8', 53)):\n"
        "    try:\n"
        "        socket.create_connection((host, port), timeout=3)\n"
        "        print('EGRESS_OK', host, port)\n"
        "    except OSError as exc:\n"
        "        print('EGRESS_BLOCKED', host, port, type(exc).__name__, exc.strerror)\n",
        label="39",
    )
    assert "EGRESS_OK" not in logs, logs
    assert logs.count("EGRESS_BLOCKED") == 3, logs
    assert "Network is unreachable" in logs, logs


def test_escape_dns_does_not_leak(executor) -> None:
    """用例 40：外部域名解析必须失败（内嵌 DNS 不得把查询转发给宿主 resolver）。"""
    _, logs = _run(
        executor,
        "import socket\n"
        "try:\n"
        "    print('DNS_RESOLVED', socket.gethostbyname('example.com'))\n"
        "except OSError as exc:\n"
        "    print('DNS_BLOCKED', type(exc).__name__, exc.strerror)\n",
        label="40",
    )
    assert "DNS_RESOLVED" not in logs, logs
    assert "DNS_BLOCKED" in logs, logs


def test_escape_cloud_metadata_is_unreachable(executor) -> None:
    """用例 41：云元数据端点 `169.254.169.254` 必须不可达。"""
    _, logs = _run(
        executor,
        "import socket\n"
        "try:\n"
        "    socket.create_connection(('169.254.169.254', 80), timeout=3)\n"
        "    print('METADATA_REACHABLE')\n"
        "except OSError as exc:\n"
        "    print('METADATA_BLOCKED', type(exc).__name__, exc.strerror)\n",
        label="41",
    )
    assert "METADATA_REACHABLE" not in logs, logs
    assert "METADATA_BLOCKED" in logs, logs


# --------------------------------------------------- 42 环境变量泄密

def test_escape_env_exposes_only_injected_whitelist(executor) -> None:
    """用例 42：容器内 env **只**承载白名单注入项；**宿主 env 与供应商密钥名不得出现**。

    注入物 = `build_token_env` 的两项（§3.3 凭据行 / G2 白名单）；本用例用**宿主侧 canary**
    证明「宿主 env 不会被整体透传进容器」（防止将来有人把 `os.environ` 直接灌进去）。
    令牌**值**不回显（只判等），避免测试产物中出现凭据明文。
    """
    canary_name = "WORKBENCH_ESCAPE_CANARY_SUPPLIER_KEY"
    canary_value = "leak-canary-value"
    os.environ[canary_name] = canary_value
    try:
        _, logs = _run(
            executor,
            "import json, os\n"
            f"print('ENV_KEYS', json.dumps(sorted(os.environ)))\n"
            f"print('TOKEN_INJECTED', os.environ.get({ENV_API_KEY!r}) == 'tok-probe')\n"
            f"print('BASE_URL_INJECTED', os.environ.get({ENV_BASE_URL!r}) == {GATEWAY_URL!r})\n",
            label="42",
            environment={ENV_API_KEY: "tok-probe", ENV_BASE_URL: GATEWAY_URL},
        )
    finally:
        os.environ.pop(canary_name, None)

    assert "TOKEN_INJECTED True" in logs, logs
    assert "BASE_URL_INJECTED True" in logs, logs
    for forbidden in (
        canary_name,
        canary_value,
        "MODEL_GATEWAY_UPSTREAM_API_KEY",
        "DEEPSEEK_API_KEY_SUPPLIER",
        "OPENAI_API_KEY_SUPPLIER",
    ):
        assert forbidden not in logs, f"{forbidden} 不得出现在容器环境/输出：{logs}"


# --------------------------------------------------- 43 fork 炸弹

def test_escape_fork_bomb_is_bounded_by_pids_limit(client) -> None:
    """用例 43：`--pids-limit` 必须真的拦住进程爆炸（探测到 `EAGAIN/EINVAL` 才算拦住）。"""
    tight = _executor(client, pids_limit=64, timeout_seconds=30)
    _, logs = _run(
        tight,
        "import os, time\n"
        "kept = []\n"
        "err = ''\n"
        "for _ in range(200):\n"
        "    try:\n"
        "        pid = os.fork()\n"
        "    except OSError as exc:\n"
        "        err = 'OSError subtype=%s errno=%s' % (type(exc).__name__, exc.errno)\n"
        "        break\n"
        "    if pid == 0:\n"
        "        time.sleep(15)\n"
        "        os._exit(0)\n"
        "    kept.append(pid)\n"
        "print('FORKED', len(kept), 'FORK_ERR', err or 'NONE')\n",
        label="43",
        timeout=30,
    )
    # 实测（2026-09-15 本机真容器，pids_limit=64）：`FORKED 63 FORK_ERR OSError subtype=BlockingIOError errno=11`
    # ⇒ 第 63 次 fork 被拒（EAGAIN）。**判据**：必须探测到 `OSError`（含子类）——`BlockingIOError` 是子类，
    # 故此处**只要求"抛的是 OSError 系"**，不写死具体子类名（不同内核/运行时可能给 EAGAIN 或 EINVAL）。
    assert "FORK_ERR NONE" not in logs, logs
    assert "FORK_ERR OSError" in logs, logs


# --------------------------------------------------- 44 提权

def test_escape_privilege_escalation_is_denied(executor) -> None:
    """用例 44：`setuid(0)` 与 `unshare(CLONE_NEWUSER)` 都必须被拒（cap 全剥夺 + no-new-privileges）。"""
    _, logs = _run(
        executor,
        "import os\n"
        "print('RUNNING_AS', os.getuid(), os.getgid())\n"
        "try:\n"
        "    os.setuid(0)\n"
        "    print('SETUID_OK')\n"
        "except Exception as exc:\n"
        "    print('SETUID_BLOCKED', type(exc).__name__)\n"
        "try:\n"
        "    os.unshare(os.CLONE_NEWUSER)\n"
        "    print('UNSHARE_OK')\n"
        "except Exception as exc:\n"
        "    print('UNSHARE_BLOCKED', type(exc).__name__)\n",
        label="44",
    )
    assert "RUNNING_AS 65534 65534" in logs, logs
    assert "SETUID_OK" not in logs and "SETUID_BLOCKED" in logs, logs
    assert "UNSHARE_OK" not in logs and "UNSHARE_BLOCKED" in logs, logs


# --------------------------------------------------- 45 持久化外溢

def test_escape_workspace_does_not_persist_across_containers(executor) -> None:
    """用例 45：工作卷**随容器销毁**——同一 `workspace_path` 的第二个容器必须看到空目录。

    若工作卷被换成宿主 bind / 命名卷（或未销毁），第二次必能看到 `persist.txt` ⇒ 必须红。
    """
    shared = _workspace("45")
    _, first = _run(
        executor,
        "open('/workspace/persist.txt','w').write('x')\n"
        "print('FIRST_WROTE', sorted(__import__('os').listdir('/workspace')))\n",
        label="45a",
        workspace_path=shared,
    )
    _, second = _run(
        executor,
        "import os\nprint('SECOND_SEES', sorted(os.listdir('/workspace')))\n",
        label="45b",
        workspace_path=shared,
    )
    assert "FIRST_WROTE ['persist.txt']" in first, first
    assert "SECOND_SEES []" in second, second


# --------------------------------------------------- 46 逃逸面侦察

def test_escape_reconnaissance_surface_is_minimal(executor) -> None:
    """用例 46：容器内可见的逃逸面必须最小——无 `docker.sock`、无 capability、seccomp 生效、`/sys` 不可写。"""
    _, logs = _run(
        executor,
        "import os\n"
        "print('DOCKER_SOCK', os.path.exists('/var/run/docker.sock'))\n"
        "print('HOST_MNT', os.path.exists('/mnt/c'))\n"
        "status = {}\n"
        "for line in open('/proc/self/status'):\n"
        "    if ':' in line:\n"
        "        key, value = line.split(':', 1)\n"
        "        status[key.strip()] = value.strip()\n"
        "print('CAPEFF', status.get('CapEff'))\n"
        "print('CAPBND', status.get('CapBnd'))\n"
        "print('NONEWPRIVS', status.get('NoNewPrivs'))\n"
        "print('SECCOMP', status.get('Seccomp'))\n"
        "try:\n"
        "    open('/sys/probe.txt','w').write('x')\n"
        "    print('SYS_WROTE_OK')\n"
        "except OSError as exc:\n"
        "    print('SYS_WRITE_BLOCKED', type(exc).__name__, exc.strerror)\n",
        label="46",
    )
    assert "DOCKER_SOCK False" in logs, logs
    assert "HOST_MNT False" in logs, logs
    assert "CAPEFF 0000000000000000" in logs, logs
    assert "CAPBND 0000000000000000" in logs, logs
    assert "NONEWPRIVS 1" in logs, logs
    assert "SECCOMP 2" in logs, logs
    assert "SYS_WROTE_OK" not in logs and "SYS_WRITE_BLOCKED" in logs, logs


# --------------------------------------------------- 47 磁盘耗尽

def test_escape_disk_exhaustion_is_bounded_by_scratch_quota(client) -> None:
    """用例 47：工作卷写超配额必须 `ENOSPC`（不得把宿主磁盘写满）。"""
    small = _executor(client, scratch_size_mb=8)
    _, logs = _run(
        small,
        "written = 0\n"
        "err = ''\n"
        "try:\n"
        "    with open('/workspace/fill.bin','wb') as fh:\n"
        "        for _ in range(64):\n"
        "            fh.write(b'x' * (1024 * 1024))\n"
        "            written += 1\n"
        "except OSError as exc:\n"
        "    err = '%s %s' % (type(exc).__name__, exc.errno)\n"
        "print('WRITTEN_MB', written, 'FILL_ERR', err or 'NONE')\n",
        label="47",
        timeout=30,
    )
    assert "FILL_ERR NONE" not in logs, logs
    assert "FILL_ERR OSError 28" in logs, logs  # 28 = errno.ENOSPC


# --------------------------------------------------- 48 Windows 穿透通道

def test_escape_windows_exec_channel_is_absent(executor) -> None:
    """用例 48：**执行容器内**不得存在 `cmd.exe` / `powershell.exe` / `/mnt/c` 通道。

    限定：本用例只覆盖**执行容器内**这一面——容器是 Linux 镜像，宿主 Windows 盘的
    drvfs 挂载与经 unix socket 交回宿主执行这两条通道属 **R7**（桌面端是否承载工具执行），
    本文件不处理、本条**不得**读成「Windows 穿透通道已收口」。
    """
    _, logs = _run(
        executor,
        "import os, shutil, subprocess\n"
        "print('CMD_EXE', shutil.which('cmd.exe') is not None)\n"
        "print('POWERSHELL', shutil.which('powershell.exe') is not None)\n"
        "print('HOST_MNT', os.path.exists('/mnt/c'))\n"
        "try:\n"
        "    subprocess.run(['cmd.exe','/c','echo','hi'], check=True, capture_output=True, timeout=5)\n"
        "    print('CMD_RAN')\n"
        "except Exception as exc:\n"
        "    print('CMD_BLOCKED', type(exc).__name__)\n",
        label="48",
    )
    assert "CMD_EXE False" in logs, logs
    assert "POWERSHELL False" in logs, logs
    assert "HOST_MNT False" in logs, logs
    assert "CMD_RAN" not in logs and "CMD_BLOCKED" in logs, logs


# --------------------------------------------------- 加固口径的静态兜底（无需容器）

def test_escape_probes_run_as_non_root_exec_user() -> None:
    """本组用例全部以 §3.3 的非 root 身份运行（防止将来把 `EXEC_USER` 改回 root 而回归静默失真）。"""
    assert EXEC_USER == "65534:65534"
