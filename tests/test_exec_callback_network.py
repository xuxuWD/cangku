"""门禁 §B14 判据 E：**执行容器不可达工作台 app 的端口**（真实容器取证 · 段二补齐的空缺）。

背景：此前隔离**只靠「`workbench-exec-internal` 上只有网关一个成员」这一成员事实**，
`app/tool_execution/executor.py` **没有任何端口 / 目标级过滤** ⇒ 「执行容器不可达工作台」
**没有任何断言**。本用例把它变成**可判定的运行期断言**：

    同机起两个 stub 容器 —— 「边车 stub」挂 `workbench-exec-internal`（internal=true）、
    「工作台 stub」挂另一**普通** bridge 网络（代表工作台默认网络）；随后跑一个**执行容器**
    （只挂 `workbench-exec-internal`），断言：**可达边车、不可达工作台（按名与按 IP 皆然）**、
    且**无外网出口**。

需要本机 Docker 与钉死镜像；缺一时整组跳过（skipped 计入基线，属预期）。
"""

from __future__ import annotations

import time

import pytest

from app.tool_execution.executor import INTERNAL_NETWORK_NAME

IMAGE_DIGEST = (
    "python:3.12-slim@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea"
)
SIDECAR_NAME = "cb-net-sidecar-stub"
WORKBENCH_NAME = "cb-net-workbench-stub"
WORKBENCH_NETWORK = "cb-net-workbench-default"
SIDECAR_PORT = 19001
WORKBENCH_PORT = 19002


def _docker_client():
    docker = pytest.importorskip("docker")
    try:
        client = docker.from_env()
        client.ping()
    except Exception:  # noqa: BLE001 - 无守护进程 → 整组跳过
        pytest.skip("Docker 守护进程不可用，跳过网络隔离取证")
    try:
        client.images.get(IMAGE_DIGEST)
    except Exception:  # noqa: BLE001 - 钉死镜像缺失 → 整组跳过（不联网拉取）
        pytest.skip("钉死镜像不在本机，跳过网络隔离取证")
    return client


def _ensure_network(client, name: str, *, internal: bool) -> None:
    existing = client.networks.list(names=[name])
    for network in existing:
        if network.name == name:
            if bool((network.attrs or {}).get("Internal", False)) != internal:
                raise AssertionError(f"网络 {name} 的 internal 属性与预期不符")
            return
    client.networks.create(name, driver="bridge", internal=internal)


def _listen_cmd(port: int) -> list[str]:
    return [
        "python",
        "-c",
        "import http.server; "
        "http.server.HTTPServer(('0.0.0.0', %d), http.server.SimpleHTTPRequestHandler).serve_forever()"
        % port,
    ]


_PROBE = """
import socket, time
SIDECAR_IP = {sidecar_ip!r}
WORKBENCH_IP = {workbench_ip!r}
def probe(host, port, label):
    deadline = time.time() + 6
    while True:
        s = socket.socket(); s.settimeout(2)
        try:
            s.connect((host, port)); print('OK', label); return
        except Exception as exc:
            if time.time() > deadline:
                print('BLOCKED', label, type(exc).__name__); return
            time.sleep(0.3)
        finally:
            s.close()
probe(SIDECAR_IP, {sidecar_port}, 'sidecar_ip')
probe({sidecar_name!r}, {sidecar_port}, 'sidecar_name')
probe(WORKBENCH_IP, {workbench_port}, 'workbench_ip')
probe({workbench_name!r}, {workbench_port}, 'workbench_name')
probe('1.1.1.1', 53, 'internet')
"""


@pytest.fixture(scope="module")
def client():
    return _docker_client()


@pytest.fixture(scope="module")
def network_topology(client):
    """起边车 stub（内网）+ 工作台 stub（普通网），用完即清（含残留检查）。"""
    pre_clean(client)  # 清掉上一次异常中断可能残留的同名容器
    _ensure_network(client, INTERNAL_NETWORK_NAME, internal=True)
    _ensure_network(client, WORKBENCH_NETWORK, internal=False)
    containers = []
    topo: dict = {}
    try:
        workbench = client.containers.run(
            image=IMAGE_DIGEST,
            name=WORKBENCH_NAME,
            network=WORKBENCH_NETWORK,
            command=_listen_cmd(WORKBENCH_PORT),
            detach=True,
        )
        containers.append(workbench)
        sidecar = client.containers.run(
            image=IMAGE_DIGEST,
            name=SIDECAR_NAME,
            network=INTERNAL_NETWORK_NAME,
            command=_listen_cmd(SIDECAR_PORT),
            detach=True,
        )
        containers.append(sidecar)
        for container in (workbench, sidecar):
            container.reload()
        topo["workbench_ip"] = workbench.attrs["NetworkSettings"]["Networks"][WORKBENCH_NETWORK][
            "IPAddress"
        ]
        topo["sidecar_ip"] = sidecar.attrs["NetworkSettings"]["Networks"][INTERNAL_NETWORK_NAME][
            "IPAddress"
        ]
        topo["sidecar_network"] = sidecar.attrs["NetworkSettings"]["Networks"]
        assert topo["workbench_ip"] and topo["sidecar_ip"]
        time.sleep(1.0)  # 等监听就绪
        yield topo
    finally:
        for container in containers:
            try:
                container.remove(force=True)
            except Exception:  # noqa: BLE001
                pass
        for network in client.networks.list(names=[WORKBENCH_NETWORK]):
            if network.name == WORKBENCH_NETWORK:
                try:
                    network.remove()
                except Exception:  # noqa: BLE001
                    pass
        # 残留检查：用例跑完后不得残留参考容器（真正跑过的用例才会有）。
        remaining = {c.name for c in client.containers.list(all=True)}
        assert SIDECAR_NAME not in remaining, "边车 stub 容器残留"
        assert WORKBENCH_NAME not in remaining, "工作台 stub 容器残留"


def test_exec_container_cannot_reach_workbench_but_reaches_sidecar(client, network_topology) -> None:
    probe = _PROBE.format(
        sidecar_ip=network_topology["sidecar_ip"],
        workbench_ip=network_topology["workbench_ip"],
        sidecar_name=SIDECAR_NAME,
        workbench_name=WORKBENCH_NAME,
        sidecar_port=SIDECAR_PORT,
        workbench_port=WORKBENCH_PORT,
    )
    # 边车只挂内网一个网络（成员事实）：不得双宿到工作台默认网络。
    assert list(network_topology["sidecar_network"].keys()) == [INTERNAL_NETWORK_NAME]

    exec_container = client.containers.run(
        image=IMAGE_DIGEST,
        network=INTERNAL_NETWORK_NAME,
        command=["python", "-c", probe],
        detach=True,
    )
    try:
        exit_code = exec_container.wait(timeout=60)["StatusCode"]
        logs = exec_container.logs().decode()
        assert exit_code == 0, logs
        # 可达边车（按 IP 与按容器名皆可）——回调面是唯一被允许的入向。
        assert "OK sidecar_ip" in logs, logs
        assert "OK sidecar_name" in logs, logs
        # 不可达工作台（按 IP 与按名皆不可）——工作台其它端口不得暴露给执行容器。
        assert "BLOCKED workbench_ip" in logs, logs
        assert "BLOCKED workbench_name" in logs, logs
        # 无外网出口。
        assert "BLOCKED internet" in logs, logs
        assert "OK workbench" not in logs, logs
    finally:
        exec_container.remove(force=True)


def pre_clean(client) -> None:
    """尽力清掉同名残留容器（上一次异常中断可能留下）。"""
    for name in (SIDECAR_NAME, WORKBENCH_NAME):
        for container in client.containers.list(all=True, filters={"name": f"^{name}$"}):
            if container.name == name:
                try:
                    container.remove(force=True)
                except Exception:  # noqa: BLE001
                    pass

