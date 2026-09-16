"""worker / beat 容器编排的静态契约（`docker-compose.app.yml` + `Dockerfile`）。

背景：2026-09-15 补齐 worker/beat 编排之前，仓库只有 `app` 一个应用服务，
**没有任何 `celery beat` 启动命令**（本机联调时 grep 全仓确认）⇒ 知识治理到期扫描
（规格 §4 N3）在容器化部署下根本不会跑。本测试用真实 YAML 结构守护该编排，
防止三类回归：

  1. **beat 被合回 worker**（`celery worker -B` 内嵌）：Windows 上 Celery 直接拒绝，
     且单进程耦合会让「worker 挂 = 调度也挂」；本测试要求 beat 是**独立服务**。
  2. **排程间隔两边不一致**：`knowledge-review-scan` 的间隔由 **beat** 侧读取
     （`create_celery_app` 建排程表），若 worker 与 beat 的
     `WORKBENCH_KNOWLEDGE_REVIEW_SCAN_INTERVAL_SECONDS` 不同，配置只在一边生效。
  3. **密钥内联或缺失 fail-closed**：worker/beat 同样必须用 `:?required` 注入，
     且**不得**出现明文口令。

说明：本测试只做**静态文本/结构**校验；真实镜像构建与容器启动属未验收项
（见 `docs/private-deployment-runbook.md`「容器化部署」段的既有声明）。
"""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "docker-compose.app.yml"
DOCKERFILE = ROOT / "Dockerfile"

BEAT_SCHEDULE_PATH = "/var/lib/celery"
BEAT_SCHEDULE_VOLUME = "workbench-celerybeat"
SCAN_INTERVAL_KEY = "WORKBENCH_KNOWLEDGE_REVIEW_SCAN_INTERVAL_SECONDS"


def load_compose() -> dict:
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))


def service(name: str) -> dict:
    services = load_compose().get("services") or {}
    assert name in services, f"docker-compose.app.yml 缺少 {name} 服务"
    return services[name]


def command_text(name: str) -> str:
    command = service(name)["command"]
    if isinstance(command, list):
        return " ".join(str(item) for item in command)
    return str(command)


# ------------------------------------------------------------ 服务构成

def test_compose_declares_app_worker_and_beat() -> None:
    services = load_compose().get("services") or {}

    # 判定依据：N3 到期扫描需要 beat；扫描执行需要 worker；迁移只许 app 跑 ⇒ 三者必须齐备。
    for name in ("app", "worker", "beat"):
        assert name in services, f"缺少服务 {name}"


def test_worker_and_beat_reuse_the_same_image() -> None:
    images = set()
    for name in ("app", "worker", "beat"):
        svc = service(name)
        build = svc.get("build") or {}
        # 判定依据：三个进程必须同镜像（同代码同依赖），只以 command 区分；用不同镜像会悄悄漂移。
        assert build.get("context") == "." and build.get("dockerfile") == "Dockerfile", name
        images.add(svc.get("image"))
    # 判定依据：三服务必须显式声明**同一个镜像名**（可注入固定 tag ⇒ 构建产物可追溯），
    # 且是 `--no-build` 起栈的前提（否则 compose 每次 up 都触发一次构建）。
    assert len(images) == 1, images
    assert "${WORKBENCH_APP_IMAGE:-workbench-app}" in images, images


def test_worker_runs_celery_worker_without_embedded_beat() -> None:
    text = command_text("worker")

    assert "app.worker" in text and " worker " in f" {text} ", text
    # 判定依据：**禁止 `-B`/`--beat` 内嵌**——Windows 上 Celery 直接拒绝，生产也不推荐。
    assert "-B" not in text.split(), text
    assert "--beat" not in text, text


def test_beat_is_a_separate_service_with_schedule_on_named_volume() -> None:
    beat = service("beat")
    text = command_text("beat")

    assert "beat" in text and "-A" in text and "app.worker" in text, text
    assert "-B" not in text.split(), text
    # 判定依据：排程状态必须落命名卷，否则容器重建后可能重复派发或漏发。
    assert f"--schedule={BEAT_SCHEDULE_PATH}/beat-schedule" in text, text
    mounts = beat.get("volumes") or []
    assert any(BEAT_SCHEDULE_VOLUME in str(item) and BEAT_SCHEDULE_PATH in str(item) for item in mounts), mounts
    assert BEAT_SCHEDULE_VOLUME in (load_compose().get("volumes") or {}), "顶层 volumes 未声明"


def test_beat_schedule_directory_is_precreated_and_owned_in_image() -> None:
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")

    # 判定依据：非 root 运行 + 命名卷默认 root 属主 ⇒ 镜像内必须预建并 chown，
    # 卷首次挂载继承属主，beat 才写得进 schedule 文件（否则「编排看着对、起不来」）。
    assert f"mkdir -p {BEAT_SCHEDULE_PATH}" in dockerfile, "Dockerfile 未预建 beat 排程目录"
    assert f"chown workbench:workbench {BEAT_SCHEDULE_PATH}" in dockerfile, "Dockerfile 未授权 beat 排程目录"


# ------------------------------------------------------------ 配置与 fail-closed

def test_worker_and_beat_require_secrets_fail_closed() -> None:
    for name in ("worker", "beat"):
        env = service(name)["environment"]

        # 判定依据：密钥只从环境注入；`:?` 让缺失即启动失败，不留「空密钥也能起」的缝。
        for key in ("WORKBENCH_DATABASE_URL", "WORKBENCH_REDIS_URL", "WORKBENCH_AUTH_SECRET", "WORKBENCH_BACKUP_ENCRYPTION_KEY"):
            assert key in env, (name, key)
            assert ":?" in str(env[key]) or str(env[key]).startswith(("redis://", "postgresql")), (name, key, env[key])
        assert ":?required" in env["WORKBENCH_DATABASE_URL"], name
        assert ":?required" in env["WORKBENCH_AUTH_SECRET"], name
        assert ":?required" in env["WORKBENCH_BACKUP_ENCRYPTION_KEY"], name


def test_app_service_declares_required_embedding_endpoint() -> None:
    env = service("app")["environment"]

    # 判定依据（P3 记忆层，2026-09-15 容器演练发现）：生产 bootstrap 在缺
    # WORKBENCH_EMBEDDING_BASE_URL 时直接抛错 ⇒ app 容器会进重启循环。
    # 必须在编排层就用 `:?required` 让「缺配置」在 compose 阶段显式失败，而不是起不来反复重启。
    assert "WORKBENCH_EMBEDDING_BASE_URL" in env, env.keys()
    assert ":?required" in env["WORKBENCH_EMBEDDING_BASE_URL"], env["WORKBENCH_EMBEDDING_BASE_URL"]


def test_worker_and_beat_agree_on_scan_interval() -> None:
    worker_interval = service("worker")["environment"][SCAN_INTERVAL_KEY]
    beat_interval = service("beat")["environment"][SCAN_INTERVAL_KEY]

    # 判定依据：排程间隔由 beat 侧读取（create_celery_app 建排程表）；两边不一致时
    # 「改配置只在一边生效」，表现为「配了 30s 却 1h 才扫」这类难查的现象。
    assert worker_interval == beat_interval, (worker_interval, beat_interval)


def test_worker_and_beat_restart_unless_stopped() -> None:
    for name in ("worker", "beat"):
        # 判定依据：异步/调度进程必须自愈（容器退出后自动拉起），否则「挂了没人知道」。
        assert service(name).get("restart") == "unless-stopped", name


def test_app_data_volume_is_precreated_and_owned_in_image() -> None:
    app = service("app")
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")

    # 判定依据（2026-09-15 容器演练实测）：内容库（默认 SQLite）要写 /srv/workbench/data，
    # 非 root 用户无权限 ⇒ app 启动即 PermissionError 并进入重启循环。
    # 与 beat 排程目录同手法：镜像预建 + 授权 + 命名卷持久化。
    mounts = app.get("volumes") or []
    assert any("workbench-app-data" in str(item) and "/srv/workbench/data" in str(item) for item in mounts), mounts
    assert "workbench-app-data" in (load_compose().get("volumes") or {}), "顶层 volumes 未声明"
    assert "mkdir -p /srv/workbench/data" in dockerfile, "Dockerfile 未预建内容库目录"
    assert "chown workbench:workbench /srv/workbench/data" in dockerfile, "Dockerfile 未授权内容库目录"


def test_beat_disables_inherited_http_healthcheck() -> None:
    healthcheck = service("beat").get("healthcheck") or {}

    # 判定依据（2026-09-15 容器演练发现）：Dockerfile 的镜像级 HEALTHCHECK 探 HTTP 8000，
    # beat 不开端口 ⇒ 继承后容器**永远 unhealthy**（假警报）。必须显式 disable。
    assert healthcheck.get("disable") is True, healthcheck


def test_app_services_bound_container_log_growth() -> None:
    # 判定依据（组 10.3「运行事件 / 日志有界」/ change-record 2026-09-15 未验证项 ②）：
    # 三服务日志只写 stdout（审计为单行 JSON），此前未设上限 ⇒ 容器日志无界增长，
    # 会先于「磁盘容量告警」把人写爆盘。这里按服务显式限制轮转份数与单份大小。
    for name in ("app", "worker", "beat"):
        logging = service(name).get("logging") or {}
        options = logging.get("options") or {}

        assert logging.get("driver") == "json-file", (name, logging)
        assert str(options.get("max-size") or "").strip(), (name, options)
        assert str(options.get("max-file") or "").strip(), (name, options)


def test_worker_bounds_child_lifetime_with_configurable_budget() -> None:
    tokens = [t for t in command_text("worker").split() if t.startswith("--max-tasks-per-child")]

    # 判定依据（2026-09-16 容量测算演练，见 change-record 同日条目）：
    # 不设上限时子进程寿命无限，第三方客户端若按任务泄漏内存，会在无人值守长跑中持续累积；
    # 实测单次重装配成本仅 ≈0.27s、任务速率约 8.6k/天 ⇒ 每天回收 2–4 次、开销 <1.5s/天，
    # 因此默认给出**有界且可调**的上限（`WORKBENCH_WORKER_MAX_TASKS_PER_CHILD`，默认 1000）。
    assert len(tokens) == 1, tokens
    assert "WORKBENCH_WORKER_MAX_TASKS_PER_CHILD" in tokens[0], tokens[0]
    assert tokens[0].endswith(":-1000}"), tokens[0]


def test_worker_healthcheck_uses_broker_ping() -> None:
    healthcheck = service("worker").get("healthcheck") or {}
    text = " ".join(str(item) for item in healthcheck.get("test") or [])

    # 判定依据：slim 镜像无 curl ⇒ 用 celery 自身经 broker 探活；缺健康检查则 compose/k8s
    # 无从判断 worker 是否真的活着（进程在 ≠ 消费正常）。
    assert "inspect ping" in text and "app.worker" in text, text