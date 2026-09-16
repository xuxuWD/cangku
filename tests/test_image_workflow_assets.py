"""镜像构建工作流的静态契约：守护 `.github/workflows/image.yml` 的关键设计与安全边界。

背景：「镜像仓库推送准备」要求构建产物可追溯（OCI 标签带版本号与构建编号），同时
**推送默认关闭**、凭据只在被开关门控的步骤内引用。

说明：真实 CI 运行结果无法在本机复现（本机只有静态文本可核对），因此**工作流的实际
执行、真实推送与真实标签校验均属未验收项**；本测试只保证「设计仍在、边界仍收紧」。

规范与 `.github/workflows/ci.yml` 同源：最小权限（只有 `contents: read`）、Action 必须写
`owner/repo@vN` 且不得回落到已弃用大版本、不得使用会在写权限上下文中跑他人代码的触发。
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "image.yml"

# 与 Dockerfile:28-32 的 5 个 OCI 标签逐字一致；少一个即「产物不可追溯」。
OCI_LABELS = (
    "org.opencontainers.image.title",
    "org.opencontainers.image.description",
    "org.opencontainers.image.version",
    "org.opencontainers.image.revision",
    "org.opencontainers.image.source",
)

# 推送开关的**逐字**门控条件：引用仓库变量（不引用 secrets），默认未配置即整步跳过。
GATED_PUSH_CONDITION = "if: vars.WORKBENCH_IMAGE_PUSH == 'true'"

# 与 tests/test_ci_assets.py:75-96 同源的弃用清单（该文件是权威定义，此处静态复制，
# 使本测试不依赖跨模块导入；两处应随上游弃用进度同步增补，防止无意间回落）。
DEPRECATED_ACTION_REFS = (
    "actions/checkout@v4",
    "actions/setup-node@v4",
    "actions/setup-python@v5",
)


def read_workflow() -> str:
    assert WORKFLOW.exists(), f"缺少镜像构建工作流：{WORKFLOW.relative_to(ROOT)}"
    return WORKFLOW.read_text(encoding="utf-8")


def read_steps() -> list[str]:
    """按 6 空格缩进的 `- ` 切出每个 step 的文本块。

    step 均以六个空格缩进，其内部键（name/if/env/run 等）为八个空格，
    job 级键（runs-on/steps 等）为四个空格，因此 `^    \\S` 恰好命中步骤区之后的边界。
    """
    matches = re.finditer(r"^      - .*?(?=^      - |^    \S|\Z)", read_workflow(), re.M | re.S)
    return [match.group(0) for match in matches]


def step_containing(needle: str) -> str:
    for step in read_steps():
        if needle in step:
            return step
    raise AssertionError(f"工作流缺少包含 {needle!r} 的步骤")


def test_workflow_triggers_on_manual_dispatch_and_tag_push_only() -> None:
    content = read_workflow()

    assert re.search(r"^on:", content, re.M), "缺少触发配置"
    assert re.search(r"^\s*workflow_dispatch:", content, re.M), "缺少手工触发（workflow_dispatch）"
    assert re.search(r"^\s*push:", content, re.M), "缺少 tag 触发"
    # 判定依据：镜像工作流不进 PR 门禁，只在打标签时构建；否则每次提交都白构建一次镜像。
    assert re.search(r'^\s*tags:\s*\[?"v\*"\]?\s*$', content, re.M), "push 必须只触发在 v* 标签上"
    # 判定依据：pull_request_target 会在有写权限的上下文中运行他人代码，禁止使用；
    # 镜像工作流亦不得进入 PR 门禁（PR 门禁由 ci.yml 负责）。
    assert "pull_request" not in content


def test_workflow_uses_read_only_permissions_and_concurrency() -> None:
    content = read_workflow()

    # 判定依据：最小权限——本工作流只读代码、构建镜像并可选推送，不需要写权限。
    assert re.search(r"^permissions:", content, re.M), "缺少顶层 permissions"
    assert re.search(r"^\s*contents:\s*read\s*$", content, re.M), "权限必须收紧为 contents: read"
    # 判定依据：并发控制避免同一 ref 上重复构建/重复推送（与 ci.yml 同风格）。
    assert re.search(r"^concurrency:", content, re.M), "缺少 concurrency"
    assert re.search(r"^\s*group:\s*\S+", content, re.M), "concurrency 缺少 group"


def test_version_and_revision_are_derived_from_tag_input_and_sha() -> None:
    content = read_workflow()
    account = step_containing("GITHUB_OUTPUT")

    # 判定依据：tag 触发取标签名、手工触发取输入值、缺省回退到提交短值，revision 恒为该次提交 SHA。
    assert "github.ref_type" in account, "缺少「是否为 tag 触发」的判定依据"
    assert "github.ref_name" in account, "tag 触发的版本号未取 github.ref_name"
    assert "inputs.version" in account, "手工触发的版本号未取 workflow_dispatch 输入"
    assert "github.sha" in account, "构建编号未取 github.sha"
    assert "${COMMIT_SHA:0:12}" in account, "缺省时未回退到提交短值"

    # 版本与构建编号必须经步骤输出传给后续步骤，否则 build/校验会各算一套。
    assert "steps.meta.outputs.version" in content
    assert "steps.meta.outputs.revision" in content


def test_build_step_injects_version_and_revision_build_args() -> None:
    step = step_containing("docker build")

    # 判定依据：Dockerfile:26-27 的两个 ARG 只有用 --build-arg 注入才会写进 OCI 标签，
    # 否则镜像永远停在 dev / unknown（产物不可追溯）。
    assert "--build-arg" in step
    assert "WORKBENCH_IMAGE_VERSION=${VERSION}" in step, "未注入 WORKBENCH_IMAGE_VERSION"
    assert "WORKBENCH_IMAGE_REVISION=${REVISION}" in step, "未注入 WORKBENCH_IMAGE_REVISION"


def test_verification_step_checks_all_oci_labels_and_rejects_defaults() -> None:
    step = step_containing("docker image inspect")

    # 判定依据：5 个标签逐个校验存在性（用「全称逐字断言」而非「任一存在」）。
    for label in OCI_LABELS:
        assert label in step, f"校验步骤未覆盖 OCI 标签 {label}"

    # 判定依据：只断言「标签存在」挡不住 ARG 未生效——Dockerfile 的默认值恰好让标签非空。
    # 因此必须显式拒绝默认值 dev / unknown，命中即 job 失败。
    assert re.search(r"""["']dev["']""", step), "校验步骤未拒绝默认版本值 dev"
    assert re.search(r"""["']unknown["']""", step), "校验步骤未拒绝默认构建编号 unknown"


def test_push_steps_are_gated_off_by_default() -> None:
    content = read_workflow()

    # 判定依据：推送出口必须唯一；多写一处即多一个不受本测试守护的推送面。
    assert content.count("docker push") == 1, "docker push 必须只出现一次"

    push_step = step_containing("docker push")
    assert GATED_PUSH_CONDITION in push_step, "推送步骤未被 vars.WORKBENCH_IMAGE_PUSH 门控"
    # 逐字断言条件表达式，避免退化成「只要出现 vars. 就算门控」。
    condition = re.search(r"^\s*if:\s*(.+)$", push_step, re.M)
    assert condition, "推送步骤没有 if 条件（无条件推送 = 默认就会推）"
    assert condition.group(1).strip() == "vars.WORKBENCH_IMAGE_PUSH == 'true'", (
        f"推送门控条件与约定不符：{condition.group(1).strip()!r}"
    )

    # 判定依据：默认关闭 ⇒ 连登录都不得发生（登录即意味着凭据被使用）。
    login_step = step_containing("docker login")
    assert GATED_PUSH_CONDITION in login_step, "登录步骤未被 vars.WORKBENCH_IMAGE_PUSH 门控"


def test_secrets_are_only_referenced_inside_gated_steps() -> None:
    content = read_workflow()

    gated_steps = []
    for step in read_steps():
        if "secrets." in step:
            gated_steps.append(step)
            # 判定依据：任何未被门控的 secrets 引用都意味着「默认路径上就会用到凭据」。
            assert GATED_PUSH_CONDITION in step, "引用 secrets 的步骤必须被推送开关门控"

    assert gated_steps, "工作流未引用任何 secrets（与「凭据走 secrets」的设计不符）"
    assert "secrets.REGISTRY_USERNAME" in content, "登录凭据未取自 secrets.REGISTRY_USERNAME"
    assert "secrets.REGISTRY_PASSWORD" in content, "登录凭据未取自 secrets.REGISTRY_PASSWORD"
    assert "vars.WORKBENCH_IMAGE_REPOSITORY" in content, "推送仓库地址未取自仓库变量"


def test_actions_are_pinned_to_explicit_non_deprecated_majors() -> None:
    refs = re.findall(r"uses:\s*(\S+)", read_workflow())

    assert refs, "工作流未引用任何 Action"
    for ref in refs:
        # 判定依据：必须写明确大版本；引用分支（@main/@master）等于把构建交给上游随时刻变。
        assert re.fullmatch(r"[\w.-]+/[\w.-]+@v\d+", ref), f"Action 版本写法不规范：{ref}"

    # 判定依据：不得回落已被弃用的 Action 大版本。
    deprecated = sorted(set(refs) & set(DEPRECATED_ACTION_REFS))
    assert deprecated == [], f"使用已弃用的 Action 版本：{deprecated}"


def test_no_latest_tag_and_no_credential_echo() -> None:
    content = read_workflow()

    # 判定依据：latest 可被随时覆写，等同未钉死（宪法 §6.3 产物可追溯）。
    assert ":latest" not in content, "镜像标签不得使用 :latest"

    # 判定依据：凭据不得回显到日志（本机只能静态检查「有没有把凭据变量交给 echo 输出」）。
    leaked = re.search(r"echo[^\n]*(REGISTRY_PASSWORD|REGISTRY_USERNAME)", content)
    assert leaked is None, f"凭据不得回显到日志：{leaked.group(0) if leaked else ''}"
