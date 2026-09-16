"""单机 staging 端口覆盖、embedding 编排与建置方案的静态契约（方案 A：闲置台式机 + Docker Desktop）。

背景：单机 staging 要在**基础编排只绑 `127.0.0.1`** 的前提下，把 5432 / 6379 / 9000 / 8000
追加绑定到该机局域网地址——否则验收机与探针无法跨机访问，`scripts/staging_preflight.py`
的「独立主机」判据（非 localhost / 127.0.0.1）也不会通过。为此新增
`docker-compose.staging.yml`（本仓库唯一的 staging 端口覆盖文件）。本测试守护四件事：

  1. **只允许覆盖 `ports`**：密钥注入、服务定义、镜像引用一律沿用基础编排与
     `docker-compose.app.yml`，避免出现「第二份服务定义悄悄漂移」。
  2. **覆盖是「追加」而非替换**：容器端口必须都存在于基础编排同名服务；SeaweedFS
     控制台（宿主 9001 → 容器 8888）**不得**外扩到局域网。
  3. **绑定地址无默认值**（`${WORKBENCH_STAGING_BIND_IP:?…}`）：缺值在 compose 阶段
     显式报错（fail-closed），杜绝「漏配时悄悄绑到通配地址」。
  4. **embedding 编排（E1 定案 A，2026-09-16）**：独立文件 `docker-compose.embedding.yml`
     定义 TEI CPU 服务（镜像钉 digest、模型目录 `:?` 必填且只读挂载、仅宿主回环）——
     app 在容器网络内按服务名寻址，局域网不可达是有意为之。

另守护建置方案文档（`docs/staging-singlebox-build-plan.md`）的关键锚点：执行期按它照做，
锚点缺失意味着「照做会踩空」（固定四 `-f` 组合、embedding 编排锚点、授权点标注、
偏差登记与待拍板节）。

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
EMBEDDING_COMPOSE = ROOT / "docker-compose.embedding.yml"
BUILD_PLAN = ROOT / "docs" / "staging-singlebox-build-plan.md"

BIND_VAR = "WORKBENCH_STAGING_BIND_IP"
MODEL_DIR_VAR = "WORKBENCH_EMBEDDING_MODEL_DIR"
# TEI 加载的容器内模型路径（`--model-id` 与卷 target 必须同值）
EMBEDDING_MODEL_PATH = "/models/Qwen3-Embedding-0.6B"
# 镜像按 digest 钉死（tag 可变、digest 不可变；与 docker-compose.yml / Dockerfile 同口径）
EMBEDDING_IMAGE_PATTERN = re.compile(
    r"^ghcr\.io/huggingface/text-embeddings-inference:cpu-[\d.]+@sha256:[0-9a-f]{64}$"
)
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


def embedding_service() -> dict:
    """embedding 编排文件里的唯一服务（服务集必须恰为 `{embedding}`）。"""
    services = compose_services(EMBEDDING_COMPOSE)
    assert set(services) == {"embedding"}, sorted(services)
    return services["embedding"]


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


# ------------------------------------------------------------ embedding 编排（E1 定案 A）

def test_embedding_service_is_defined_only_in_the_new_file() -> None:
    # 判定依据（E1 定案 A，2026-09-16）：embedding 是**本方案新增独立文件**里的服务；
    # 基础两文件与端口覆盖文件都不得出现它——否则会出现第二份定义漂移。
    embedding_service()  # 断言新增文件内部自洽（服务集恰为 {embedding}）
    assert "embedding" not in declared_services()
    assert "embedding" not in compose_services(OVERRIDE_COMPOSE)


def test_embedding_image_is_pinned_by_digest() -> None:
    # 判定依据：与既有编排同口径——tag 可变、digest 不可变；
    # 钉 digest 才能保证「台式机上拉到的就是开发机取证过的那个镜像」。
    image = str(embedding_service()["image"])
    assert EMBEDDING_IMAGE_PATTERN.match(image), image


def test_embedding_model_dir_is_required_and_mounted_read_only() -> None:
    volumes = embedding_service().get("volumes") or []
    assert len(volumes) == 1, volumes
    entry = str(volumes[0])

    # 判定依据：模型在宿主预下载（方案 Step 2）后只读挂载——
    # `${…:?…}` 缺值即 compose 报错（fail-closed）；`:ro` 防容器写宿主模型目录；
    # 容器内路径与 `--model-id` 同值（见下一条）。
    assert "${" + MODEL_DIR_VAR + ":?" in entry, entry
    assert entry.endswith(f":{EMBEDDING_MODEL_PATH}:ro"), entry


def test_embedding_is_loopback_only_on_host() -> None:
    ports = embedding_service().get("ports") or []

    # 判定依据：embedding 只走容器网络（app 按服务名寻址）；宿主绑定仅 127.0.0.1 供调试，
    # 局域网不可达是有意为之——`docker-compose.staging.yml` 亦不得为它追加 `$IP` 绑定。
    assert [str(entry) for entry in ports] == ["127.0.0.1:8080:8080"], ports
    assert not any("0.0.0.0" in str(entry) for entry in ports), ports


def test_embedding_command_matches_model_mount_and_contract() -> None:
    command = embedding_service()["command"]
    text = " ".join(str(item) for item in command) if isinstance(command, list) else str(command)

    # 判定依据：开关必须与挂载路径 / 端口 / 截断口径逐一对应——
    # ① `--model-id` 与卷 target 同值；② `--port=8080` 与端口映射一致；
    # ③ `--max-input-length=8192` 与 app 侧 `WORKBENCH_EMBEDDING_MAX_TOKENS` 同口径
    #   （适配器 `embed()` 不做客户端截断，服务端截断是唯一闸门）。
    assert f"--model-id={EMBEDDING_MODEL_PATH}" in text, text
    assert "--port=8080" in text, text
    assert "--max-input-length=8192" in text, text
    # 超限走截断而非报错（P3 契约口径）
    assert "--auto-truncate" in text, text


def test_embedding_service_has_restart_and_bounded_logging() -> None:
    svc = embedding_service()

    # 判定依据：与 app 服务同口径——自愈（restart: unless-stopped）＋容器日志有界
    # （组 10.3「日志有界」）；模型加载失败与请求异常的唯一现场是 stdout。
    assert svc.get("restart") == "unless-stopped", svc.get("restart")
    logging = svc.get("logging") or {}
    options = logging.get("options") or {}
    assert logging.get("driver") == "json-file", logging
    assert str(options.get("max-size") or "").strip(), options
    assert str(options.get("max-file") or "").strip(), options


# ------------------------------------------------------------ 建置方案文档锚点

def test_build_plan_keeps_execution_anchors() -> None:
    content = BUILD_PLAN.read_text(encoding="utf-8")

    # 判定依据：执行期按方案照做；下列锚点任一缺失都会让「照做」踩空——
    # 绑定变量名、固定四 `-f` 组合、embedding 编排文件与两个必填锚点（模型目录变量、
    # 容器内服务名地址）、写操作授权点标注、偏差/映射/待拍板三节、以及
    # 「不得为凑预检全绿而填假值」的诚实口径（未接入的外部 Runtime 如实 fail）。
    for anchor in (
        BIND_VAR,
        "docker-compose.staging.yml",
        "-f docker-compose.app.yml",
        "docker-compose.embedding.yml",
        MODEL_DIR_VAR,
        "http://embedding:8080",
        "【授权点",
        "## 12. 偏差登记",
        "## 13. I1–I14 索取表映射",
        "## 14. 待拍板项",
        "不得为凑预检全绿而填",
    ):
        assert anchor in content, f"建置方案缺少锚点：{anchor}"