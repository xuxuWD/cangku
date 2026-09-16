"""单机 staging 端口覆盖与建置方案的静态契约（方案 A：闲置台式机 + Docker Desktop）。

背景：单机 staging 要在**基础编排只绑 `127.0.0.1`** 的前提下，把 5432 / 6379 / 9000 / 8000
追加绑定到该机局域网地址——否则验收机与探针无法跨机访问，`scripts/staging_preflight.py`
的「独立主机」判据（非 localhost / 127.0.0.1）也不会通过。为此新增
`docker-compose.staging.yml`（本仓库唯一的 staging 端口覆盖文件）。本测试守护三件事：

  1. **只允许覆盖 `ports`**：密钥注入、服务定义、镜像引用一律沿用基础编排与
     `docker-compose.app.yml`，避免出现「第二份服务定义悄悄漂移」。
  2. **覆盖是「追加」而非替换**：容器端口必须都存在于基础编排同名服务；SeaweedFS
     控制台（宿主 9001 → 容器 8888）**不得**外扩到局域网。
  3. **绑定地址无默认值**（`${WORKBENCH_STAGING_BIND_IP:?…}`）：缺值在 compose 阶段
     显式报错（fail-closed），杜绝「漏配时悄悄绑到通配地址」。

另守护建置方案文档（`docs/staging-singlebox-build-plan.md`）的关键锚点：执行期按它照做，
锚点缺失意味着「照做会踩空」（三 `-f` 组合、授权点标注、偏差登记与待拍板节）。

说明：本测试只做静态文本/结构校验；真实起栈与验收属未执行项（见方案文档「状态」行）。
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
BASE_COMPOSE = ROOT / "docker-compose.yml"
APP_COMPOSE = ROOT / "docker-compose.app.yml"
OVERRIDE_COMPOSE = ROOT / "docker-compose.staging.yml"
BUILD_PLAN = ROOT / "docs" / "staging-singlebox-build-plan.md"

BIND_VAR = "WORKBENCH_STAGING_BIND_IP"
# 跨机真实可达的四个端口所属服务（对象存储控制台刻意不在列）
LAN_BOUND_SERVICES = {"postgres", "redis", "seaweedfs", "app"}
# 各服务必须追加到局域网的容器端口（与基础编排逐一对应）
EXPECTED_APPENDED_PORTS = {"postgres": "5432", "redis": "6379", "seaweedfs": "9000", "app": "8000"}


def load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def compose_services(path: Path) -> dict:
    return load(path).get("services") or {}


def declared_services() -> dict:
    """基础编排声明的服务全集（`app` 在 `docker-compose.app.yml`，其余在 `docker-compose.yml`）。"""
    return {**compose_services(BASE_COMPOSE), **compose_services(APP_COMPOSE)}


def container_port(entry: object) -> str:
    """从 compose 端口条目取容器侧端口；`:-` 默认值里的冒号不影响「取最后一段」。"""
    match = re.search(r":(\d+)$", str(entry).split("/")[0].strip())
    assert match, f"无法识别容器端口：{entry!r}"
    return match.group(1)


# ------------------------------------------------------------ 覆盖范围

def test_override_defines_only_the_four_lan_bound_services() -> None:
    override = compose_services(OVERRIDE_COMPOSE)
    declared = declared_services()

    # 判定依据：端口覆盖只允许覆盖基础编排里已存在的服务，且范围就是四个需跨机可达的
    # 服务；多覆盖一个服务就多一份「第二定义」漂移风险。
    assert set(override) == LAN_BOUND_SERVICES, sorted(override)
    for name in override:
        assert name in declared, f"覆盖了基础编排不存在的服务 {name}"


def test_override_only_touches_ports() -> None:
    for name, svc in compose_services(OVERRIDE_COMPOSE).items():
        # 判定依据：密钥、环境、镜像、卷一律沿用基础编排与 docker-compose.app.yml；
        # 覆盖文件只允许出现 `ports` 一个键（否则就是在复制第二份服务定义）。
        assert set(svc.keys()) == {"ports"}, (name, sorted(svc.keys()))


# ------------------------------------------------------------ 绑定语义

def test_bind_address_is_a_required_variable_without_default() -> None:
    text = OVERRIDE_COMPOSE.read_text(encoding="utf-8")

    # 判定依据：绑定地址必须 fail-closed——缺值即 compose 报错（`:?`），
    # 且全文不得出现通配地址（0.0.0.0），防止「漏配时悄悄绑到所有网卡」。
    assert "0.0.0.0" not in text
    for name, svc in compose_services(OVERRIDE_COMPOSE).items():
        for entry in svc["ports"]:
            assert str(entry).startswith("${" + BIND_VAR + ":?"), (name, entry)


def test_override_appends_the_same_container_ports_as_base() -> None:
    declared = declared_services()
    appended: dict[str, set[str]] = {}

    for name, svc in compose_services(OVERRIDE_COMPOSE).items():
        added = {container_port(entry) for entry in svc["ports"]}
        available = {container_port(entry) for entry in declared[name]["ports"]}
        # 判定依据：追加绑定必须指向同一容器端口（「追加」语义），
        # 绑到基础编排没发布的端口等于把服务指向空气。
        assert added <= available, (name, sorted(added - available))
        appended[name] = added

    # 四个跨机端口一个都不能少，且不多不少。
    expected = {name: {port} for name, port in EXPECTED_APPENDED_PORTS.items()}
    assert appended == expected, appended


def test_object_storage_console_is_not_exposed_to_lan() -> None:
    bound = [
        str(entry)
        for svc in compose_services(OVERRIDE_COMPOSE).values()
        for entry in svc["ports"]
    ]

    # 判定依据：SeaweedFS 控制台（宿主 9001 → 容器 8888）只供本机浏览器查看；
    # 外扩会多开一个面向局域网的 Web 面（基础编排里它维持 127.0.0.1）。
    # 只看**端口条目**（注释里出现"9001"是说明文字，不算外扩）。
    assert bound, "覆盖文件未声明任何端口"
    for entry in bound:
        assert "9001" not in entry, f"对象存储控制台宿主端口不应出现在覆盖条目：{entry}"
        assert "8888" not in entry, f"对象存储控制台容器端口不应出现在覆盖条目：{entry}"


# ------------------------------------------------------------ 建置方案文档锚点

def test_build_plan_keeps_execution_anchors() -> None:
    content = BUILD_PLAN.read_text(encoding="utf-8")

    # 判定依据：执行期按方案照做；下列锚点任一缺失都会让「照做」踩空——
    # 绑定变量名、固定三 `-f` 组合、写操作授权点标注、偏差/映射/待拍板三节、
    # 以及「不得为凑预检全绿而填假值」的诚实口径（未接入的外部 Runtime 如实 fail）。
    for anchor in (
        BIND_VAR,
        "docker-compose.staging.yml",
        "-f docker-compose.app.yml",
        "【授权点",
        "## 12. 偏差登记",
        "## 13. I1–I14 索取表映射",
        "## 14. 待拍板项",
        "不得为凑预检全绿而填",
    ):
        assert anchor in content, f"建置方案缺少锚点：{anchor}"