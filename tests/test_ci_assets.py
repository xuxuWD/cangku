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


# GitHub 已把下列 Action 大版本的运行时标记为弃用（当前被强制跑到 Node 24）。
# 该集合应随上游弃用进度增补，防止无意间回落。
DEPRECATED_ACTION_REFS = (
    "actions/checkout@v4",
    "actions/setup-node@v4",
    "actions/setup-python@v5",
)


def test_actions_are_pinned_to_explicit_non_deprecated_majors() -> None:
    content = read_workflow()
    refs = re.findall(r"uses:\s*(\S+)", content)

    assert refs, "工作流未引用任何 Action"

    for ref in refs:
        # 判定依据：必须写明确大版本；引用分支（@main/@master）等于把门禁交给上游随时刻变。
        assert re.fullmatch(r"[\w.-]+/[\w.-]+@v\d+", ref), f"Action 版本写法不规范：{ref}"

    # 判定依据：不得回落已被弃用的 Action 大版本。
    deprecated = sorted(set(refs) & set(DEPRECATED_ACTION_REFS))
    assert deprecated == [], f"CI 使用已弃用的 Action 版本：{deprecated}"


def read_job(name: str) -> str:
    """截取顶层 job `name` 的文本块（到下一个顶层 job 或文件末尾）。

    顶层 job 均以两个空格缩进，其内部键（services/steps/env 等）为四空格，
    因此 `^  \\S`（两个空格后紧跟非空白）恰好命中下一个 job 的起点。
    """
    content = read_workflow()
    match = re.search(rf"^  {name}:.*?(?=^  \S|\Z)", content, re.M | re.S)
    assert match, f"工作流缺少 {name} 任务"
    return match.group(0)


# postgres job 的真库服务镜像**逐字钉死**（含摘要值）。仅校验「存在合法形式的 sha256」
# 挡不住「换成另一个合法但不同的 sha256」，故此处把期望镜像串写成常量并对值比较。
POSTGRES_SERVICE_IMAGE = (
    "pgvector/pgvector:0.8.0-pg16@sha256:a132765ec351c65111b5b675928a3a0515a466a40f97277329db8b8209ad8bc9"
)


def test_postgres_job_exists_and_pins_service_image_by_digest() -> None:
    content = read_workflow()

    # 判定依据：真库门禁必须作为一个顶层 job 存在，否则「默认 skip」无人跑。
    assert re.search(r"^  postgres:", content, re.M), "jobs 中缺少 postgres 任务"

    job = read_job("postgres")
    # 判定依据：真库服务镜像必须按 sha256 摘要钉死，防止上游 tag 漂移悄悄换掉镜像。
    assert re.search(r"image:\s*\S+@sha256:[0-9a-f]{64}\b", job), "postgres 服务镜像未按摘要钉死"
    # 判定依据：上面的正则只看「形式」——换成另一个合法 sha256 不会报警。此处把镜像串
    # （含摘要值）与钉死常量逐字比较，摘要值与钉死值不符即失败。
    image_match = re.search(r"^\s*image:\s*(\S+)\s*$", job, re.M)
    assert image_match, "postgres 服务镜像未声明 image"
    pinned_image = image_match.group(1)
    assert pinned_image == POSTGRES_SERVICE_IMAGE, (
        f"postgres 服务镜像摘要值与钉死值不符：实际 {pinned_image!r}，"
        f"期望 {POSTGRES_SERVICE_IMAGE!r}"
    )
    # 判定依据：裸 tag（含 :latest）可被上游随时覆写，等同未钉死。
    assert ":latest" not in job, "postgres 服务镜像不得使用 :latest"


def test_postgres_job_applies_repo_migrations_and_sets_dsn() -> None:
    job = read_job("postgres")

    # 判定依据：必须调用仓库自身的迁移函数建表（而非另写一套 DDL），否则真库结构与代码漂移。
    assert "app.migrations import apply_migrations" in job
    assert "apply_migrations(conn" in job
    # 判定依据：真库用例由该变量门控；缺失即整体 skip（本 job 存在的意义就是把它设起来）。
    assert "WORKBENCH_TEST_DATABASE_URL" in job


def test_postgres_job_runs_only_the_real_db_modules() -> None:
    job = read_job("postgres")

    # 只取 pytest 调用本身（截到紧随其后的 junit 校验 heredoc 为止），排除注释与其它步骤。
    match = re.search(r"python -m pytest.*?(?=python - <<)", job, re.S)
    assert match, "postgres 任务缺少 pytest 调用"
    command = match.group(0)

    # 判定依据：本 job 只跑这几个由 DSN 门控的真库模块，命令里必须逐个出现；
    # 用「全称逐字断言」而非「包含任意一个」——后者在漏跑某个模块时仍会通过。
    # ⚠️ 教训（2026-09-15）：本断言此前只覆盖前三个模块，P3/P4 新增的 memory/skills 模块
    # 与知识治理模块先后漏守护——「job 里写了的」与「断言钉住的」必须逐条对齐，
    # 否则新增真库模块时只需忘改 ci.yml 一处，用例仍全绿而模块在 CI 里永远 skip。
    assert "tests/test_tool_action_store_postgres.py" in command
    assert "tests/test_dsh_execution_postgres.py" in command
    assert "tests/test_commercial_lifecycle_postgres.py" in command
    assert "tests/test_memory_postgres.py" in command
    assert "tests/test_skills_postgres.py" in command
    assert "tests/test_knowledge_governance_postgres.py" in command
    # 2026-09-16 补钉：下面两个模块此前已在 ci.yml 的 job 里，但**未被断言钉住**
    # （P6a 加 `test_evolution_postgres.py`、运行事件改造加 `test_runtime_events_postgres.py`
    # 时都漏了这一处）——正是上面教训所指的「job 里写了、断言没钉」。缺口已由本断言补上。
    assert "tests/test_evolution_postgres.py" in command
    assert "tests/test_runtime_events_postgres.py" in command
    # 2026-09-17 补钉：P5a CRM 真库回归（迁移 035，转化单事务 / 复合外键 / 报价与回款）
    assert "tests/test_crm_postgres.py" in command
    # 2026-09-17 补钉：P2b 实时流真库回归（迁移 036，序号 / 续播 / 熔断告知帧 / 脱敏落库 / 清理）
    assert "tests/test_conversation_stream_postgres.py" in command
    # 2026-09-17 补钉：P2c-3 产物登记真库回归（迁移 037，登记读回 / 跨租户拒写 / 保留期清理）
    assert "tests/test_run_artifacts_postgres.py" in command
    # 2026-09-17 补钉：P2c-4 会话模式 / 导出 / 物理删除真库回归（迁移 038，级联真删 / 保留 / 复删幂等）
    assert "tests/test_conversation_lifecycle_postgres.py" in command
    # 2026-09-17 补钉：P2c-6 会话协作真库回归（迁移 039，成员表约束 / 消息 sender_id / 成员读路径）
    assert "tests/test_conversation_members_postgres.py" in command


def test_postgres_job_requires_zero_skipped() -> None:
    job = read_job("postgres")

    # 判定依据：模块整体 skip 时 pytest 仍返回 0；必须显式零容忍 skipped（tests>0 且 skipped==0），
    # 否则「整模块被跳过」会被当成通过——这正是该 job 相对 backend job 的存在理由。
    assert "tests > 0 and skipped == 0 and failed == 0" in job


# sandbox job 的执行镜像**逐字钉死**：与 Dockerfile:14 / tests/test_container_executor.py:28 /
# tests/test_exec_sandbox_escape.py 同一取值（tag 可变、digest 不可变）。
EXEC_IMAGE = (
    "python:3.12-slim@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea"
)


def test_sandbox_job_exists_and_runs_the_real_container_regressions() -> None:
    content = read_workflow()

    # 判定依据（G5 / 规格 §8 U28）：两组真容器回归由「Docker + 钉死镜像」门控 ⇒ 默认 backend job
    # 里是 skip、不受守护；必须有一个顶层 job 把它们跑起来，否则「固化」只是纸面动作。
    assert re.search(r"^  sandbox:", content, re.M), "jobs 中缺少 sandbox 任务"

    job = read_job("sandbox")
    assert "tests/test_exec_sandbox_escape.py" in job, "sandbox 任务未跑逃逸回归"
    assert "tests/test_container_executor.py" in job, "sandbox 任务未跑加固口径回归"
    # 必须显式拉取钉死镜像：失败即 job 失败，不得静默降级为整组 skip。
    assert "docker pull" in job
    assert EXEC_IMAGE in job, "sandbox 任务的执行镜像与钉死值不符"


def test_sandbox_job_requires_zero_skipped() -> None:
    job = read_job("sandbox")

    # 判定依据（同 postgres job）：无 Docker / 缺镜像时整组 skip 且 pytest 仍返回 0，
    # 必须要求「真跑了且无一 skip」，否则该 job 会在环境退化后静默变成"永远绿"。
    assert "tests > 0 and skipped == 0 and failed == 0" in job
