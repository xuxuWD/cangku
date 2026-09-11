"""CI 门禁的静态契约：工作流必须覆盖仓库既有的提交门禁。

背景：`docs/delivery-gates.md` 的「每次提交必须满足」要求全量测试与编译检查通过，
但仓库此前没有任何 CI，全靠人工自觉。本测试守护工作流的存在与关键步骤，避免门禁被
误删或降级。

说明：真实 CI 运行结果无法在本机复现（本机只有静态文本可核对），因此**工作流的实际
执行属未验收项**，本测试只保证「门禁命令仍在」。
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


def read_workflow() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_workflow_triggers_on_push_and_pull_request_with_least_privilege() -> None:
    content = read_workflow()

    assert re.search(r"^on:", content, re.M), "缺少触发配置"
    assert re.search(r"^\s*push:", content, re.M)
    assert re.search(r"^\s*pull_request:", content, re.M)
    # 判定依据：pull_request_target 会在有写权限的上下文中运行他人代码，禁止使用。
    assert "pull_request_target" not in content
    # 判定依据：最小权限——CI 只读代码，不需要写权限。
    assert re.search(r"^\s*permissions:", content, re.M)
    assert "contents: read" in content


def test_backend_job_runs_the_same_gate_commands_as_documented() -> None:
    content = read_workflow()

    # 判定依据：与 delivery-gates.md「每次提交必须满足」第 2、3 条逐字一致。
    assert "python -m pytest -o addopts=" in content
    assert "python -m compileall -q app tests extract_pdf.py scripts" in content
    # 与 Dockerfile 的基础镜像保持一致，且满足 requires-python>=3.11。
    assert 'python-version: "3.12"' in content


def test_frontend_and_desktop_jobs_run_tests_and_builds() -> None:
    content = read_workflow()

    for directory in ("admin-web", "companion-pwa", "desktop"):
        assert directory in content, f"工作流缺少 {directory} 任务"

    assert "npm ci" in content
    # 判定依据：必须显式 `vitest run`，否则 vitest 会进入 watch 模式导致 CI 挂住。
    assert content.count("npx vitest run") == 2
    assert content.count("npm run build") == 2
    assert 'node-version: "22"' in content


def test_desktop_job_skips_electron_binary_download() -> None:
    content = read_workflow()

    # 判定依据：本工程单测不依赖 Electron 运行时，CI 无谓下载上百 MB 二进制只会拖慢门禁。
    assert "npm ci --ignore-scripts" in content
    assert "node --test" in content


def test_workflow_requires_no_secrets() -> None:
    content = read_workflow()

    # 判定依据：门禁只跑测试与编译，不应引用任何密钥；引用即意味着 CI 被赋予了凭据面。
    assert "secrets." not in content
