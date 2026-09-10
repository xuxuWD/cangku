"""容器化资产的静态校验。

本机不保证有 Docker 守护进程，因此这里只做**静态文本断言**：
确认镜像定义符合基线（非 root、无密钥、有健康检查），以及编排文件强制从环境注入密钥。
真实镜像构建与容器运行属于待验收项，不在本测试覆盖范围内。
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def dockerignore_entries() -> set[str]:
    lines = read(".dockerignore").splitlines()
    return {line.strip() for line in lines if line.strip() and not line.strip().startswith("#")}


def test_dockerfile_uses_slim_base_and_runs_as_non_root() -> None:
    content = read("Dockerfile")

    assert "FROM python:3.12-slim" in content
    assert "groupadd" in content and "useradd" in content
    assert "USER workbench" in content
    # 必须显式指定运行用户，且不能在 USER 之后又切回 root
    assert content.index("USER workbench") < content.index('CMD ["uvicorn"')
    assert "USER root" not in content


def test_dockerfile_has_healthcheck_against_health_endpoint() -> None:
    content = read("Dockerfile")

    assert "HEALTHCHECK" in content
    assert "/api/v1/health" in content

    # slim 镜像不含外部 HTTP 客户端：健康检查命令必须走标准库，不得调用 curl 之类外部命令
    healthcheck = content.split("HEALTHCHECK", 1)[1]
    assert "urllib.request" in healthcheck
    healthcheck_command = healthcheck.split("CMD", 1)[1].splitlines()[0]
    assert "curl" not in healthcheck_command
    assert "wget" not in healthcheck_command


def test_dockerfile_starts_uvicorn_on_all_interfaces() -> None:
    content = read("Dockerfile")

    assert "uvicorn" in content
    assert "app.main:app" in content
    assert "0.0.0.0" in content
    assert "EXPOSE 8000" in content


def test_dockerfile_bakes_no_secret_values() -> None:
    content = read("Dockerfile")

    for forbidden in (
        "WORKBENCH_AUTH_SECRET=",
        "WORKBENCH_BACKUP_ENCRYPTION_KEY=",
        "WORKBENCH_BOOTSTRAP_TOKEN=",
        "WORKBENCH_DB_PASSWORD=",
        "WORKBENCH_MINIO_PASSWORD=",
    ):
        assert forbidden not in content


def test_dockerfile_does_not_copy_tests_or_frontend() -> None:
    content = read("Dockerfile")

    assert "COPY tests" not in content
    assert "COPY admin-web" not in content


def test_dockerignore_excludes_local_state_and_secrets() -> None:
    entries = dockerignore_entries()

    for required in (
        ".git",
        ".venv",
        "__pycache__",
        ".worktrees",
        ".superpowers",
        "tests",
        "admin-web",
        ".env",
        ".env.*",
    ):
        assert required in entries


def test_compose_app_requires_secrets_from_environment() -> None:
    content = read("docker-compose.app.yml")

    for name in (
        "WORKBENCH_AUTH_SECRET",
        "WORKBENCH_BACKUP_ENCRYPTION_KEY",
        "WORKBENCH_BOOTSTRAP_TOKEN",
        "WORKBENCH_DB_PASSWORD",
    ):
        assert f"{name}:?" in content, f"{name} 必须用 :? 强制注入"


def test_compose_app_bakes_no_secret_literals() -> None:
    content = read("docker-compose.app.yml")

    for forbidden in ("sk-", "replace-with-a-long-random"):
        assert forbidden not in content


def test_compose_app_uses_production_settings_and_internal_hosts() -> None:
    content = read("docker-compose.app.yml")

    assert "WORKBENCH_ENV: production" in content
    assert "WORKBENCH_STORAGE_BACKEND: postgres" in content
    # 容器内必须用服务名而不是 localhost
    assert "@postgres:5432" in content
    assert "redis://redis:6379" in content
    assert "localhost" not in content


def test_compose_app_is_wired_to_infrastructure_services() -> None:
    content = read("docker-compose.app.yml")

    assert "build:" in content
    assert "- postgres" in content
    assert "- redis" in content
    assert "127.0.0.1:" in content
