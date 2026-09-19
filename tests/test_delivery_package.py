"""交付包组装 / 核对脚本的守护测试（真源 `commercial-g0-design.md` §7 六项必含）。

**为什么需要**：交付包是**对外交付物**，`scripts/build_delivery_package.py` 是它的唯一组装入口。
此前「交付包必含哪六项」只写在真源里、**靠人工记忆组装**（漏一项不会有任何提示）。
本文件把两条防错线钉成可执行断言：

  1. **真源 §7 六项必含**：仓库内必备项缺失 ⇒ fail-closed（退出码 1），**绝不生成半成品包**；
     版本清单必须覆盖真源 §7 要求的五个维度，缺的**如实标记为 missing**（不臆造版本号）。
  2. **红线：密钥不进交付物**：只允许 `*.example` 模板，`.env` / `.env.*` 真值文件绝不入包；
     `CONFIG-AND-SECRETS.md` 只列键名与规则，不出现任何赋值形态。

外部构建产物（镜像 / 桌面安装包）的缺省标注与 `--check-only` 的 sha256 校验同样覆盖
——「没有这些产物时如实标注」正是本脚本默认要处理的情形。
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "build_delivery_package.py"

sys.path.insert(0, str(REPO_ROOT / "scripts"))

import build_delivery_package as builder  # noqa: E402

# 交付包里必须出现的落点（真源 §7 六项 + 生成的说明 / 清单 / 不完整声明）。
REQUIRED_PACKAGE_PATHS = (
    "README-FIRST.md",
    "migrations",
    "requirements.lock",
    ".env.staging.example",
    "scripts/migration_backup_drill.py",
    "scripts/monitoring_probe.py",
    "docs/private-deployment-runbook.md",
    "docs/handbooks/employee-handbook.md",
    "docs/handbooks/customer-admin-handbook.md",
    "docs/handbooks/troubleshooting-handbook.md",
    "THIRD-PARTY-NOTICES.md",
    "licenses/LGPL-3.0.txt",
    "CONFIG-AND-SECRETS.md",
    "MANIFEST.json",
    "INCOMPLETE.md",
)


def _build(tmp_path: Path, *args: str) -> subprocess.CompletedProcess:
    """在临时目录里跑一次组装（输出落在 tmp_path/out）。"""
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--repo-root", str(REPO_ROOT), "--output", str(tmp_path / "out"), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )


def _check(package_dir: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--check-only", str(package_dir)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )


def _manifest(package_dir: Path) -> dict:
    return json.loads((package_dir / "MANIFEST.json").read_text(encoding="utf-8"))


def test_repo_has_every_required_item() -> None:
    """真源 §7 六项在**本仓库内**必须齐备（缺任何一项都没有资格拼包）。"""
    items, problems = builder.collect_repo_items(REPO_ROOT)
    assert not problems, f"仓库内必备项缺失：{problems}"
    assert all(item.status == "included" for item in items), [
        item.label for item in items if item.status != "included"
    ]


def test_fails_closed_when_repo_item_missing(tmp_path: Path) -> None:
    """仓库内必备项缺失 ⇒ 退出码 1，且**不产出任何内容**（不生成半成品包）。"""
    fake_repo = tmp_path / "fake-repo"
    (fake_repo / "migrations").mkdir(parents=True)
    (fake_repo / "migrations" / "001_initial.sql").write_text("-- x\n", encoding="utf-8")
    output = tmp_path / "out"

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--repo-root", str(fake_repo), "--output", str(output)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )

    assert result.returncode == 1, f"应 fail-closed 退出 1：\n{result.stdout}{result.stderr}"
    assert not output.exists(), "必备项缺失时不得产出任何内容"
    assert "不组装交付包" in result.stdout


def test_build_without_external_artifacts_is_incomplete_but_safe(tmp_path: Path) -> None:
    """无镜像 / 无桌面安装包：包安全生成（缺项写入 INCOMPLETE.md），且必备落点齐全。"""
    result = _build(tmp_path, "--version", "1.2.3")
    assert result.returncode == 2, f"缺外部产物应退出 2，实际 {result.returncode}\n{result.stdout}"

    out = tmp_path / "out"
    for rel in REQUIRED_PACKAGE_PATHS:
        assert (out / rel).exists(), f"交付包缺少 {rel}"


def test_incomplete_marker_names_every_external_gap(tmp_path: Path) -> None:
    _build(tmp_path, "--version", "1.2.3")
    incomplete = (tmp_path / "out" / "INCOMPLETE.md").read_text(encoding="utf-8")
    assert "控制平面镜像" in incomplete
    assert "桌面端安装包" in incomplete


def test_manifest_versions_cover_required_dimensions(tmp_path: Path) -> None:
    """真源 §7：版本至少含控制平面 / 数据库迁移 / 桌面端 / Runtime / 岗位能力包五个维度。"""
    _build(tmp_path, "--version", "7.8.9")
    versions = _manifest(tmp_path / "out")["versions"]

    for key in (
        "control_plane_version",
        "database_migration_version",
        "desktop_version",
        "runtime_versions",
        "capability_pack_version",
    ):
        assert key in versions, f"版本清单缺少维度：{key}"

    assert versions["control_plane_version"] == "7.8.9"
    # 岗位能力包在本仓库内**没有独立产物** ⇒ 必须如实标记 missing，不得臆造版本号。
    assert versions["capability_pack_version"] == "missing"
    assert "不臆造" in versions["capability_pack_version_note"] or "没有独立产物" in versions["capability_pack_version_note"]
    # 迁移版本取自实际迁移清单（不是写死的）。
    migration_files = sorted(path.stem for path in (REPO_ROOT / "migrations").glob("*.sql"))
    assert versions["database_migration_version"] == migration_files[-1]
    assert versions["database_migration_count"] == len(migration_files)


def test_manifest_records_sha256_for_every_file(tmp_path: Path) -> None:
    """每个文件都要有 sha256（客户侧 `--check-only` 靠它验完整性）。"""
    _build(tmp_path, "--version", "1.0.0")
    out = tmp_path / "out"
    files = _manifest(out)["files"]
    assert files, "MANIFEST.json 未登记任何文件"

    for entry in files:
        assert set(entry) >= {"path", "bytes", "sha256"}
        target = out / entry["path"]
        assert target.is_file(), f"MANIFEST 登记了不存在的文件：{entry['path']}"
        assert entry["sha256"] == builder._sha256(target), f"sha256 与文件不符：{entry['path']}"


def test_no_real_env_file_enters_delivery(tmp_path: Path) -> None:
    """红线：交付物里绝不出现 `.env` / `.env.*` 真值文件，只允许 `*.example`。"""
    _build(tmp_path, "--version", "1.0.0")
    out = tmp_path / "out"

    offenders = [
        path for path in out.rglob("*")
        if path.is_file() and builder.is_forbidden_config_name(path.name)
    ]
    assert not offenders, f"交付物中出现真值配置文件：{[str(p) for p in offenders]}"

    for template in (".env.example", ".env.staging.example", ".env.sso.example"):
        assert (out / template).is_file(), f"缺少配置模板：{template}"


def test_forbidden_name_pattern_blocks_real_env_only() -> None:
    """判据本身要准：拦 `.env` / `.env.local`，**放行** `.env.staging.example`。"""
    is_forbidden = builder.is_forbidden_config_name
    assert is_forbidden(".env")
    assert is_forbidden(".env.local")
    assert is_forbidden(".env.production")
    assert not is_forbidden(".env.staging.example")
    assert not is_forbidden(".env.example")
    assert not is_forbidden("app/main.py")


def test_config_doc_lists_keys_but_never_values(tmp_path: Path) -> None:
    """`CONFIG-AND-SECRETS.md` 只列键名与规则——不得出现任何「键=值」赋值形态。"""
    out = tmp_path / "cfg"
    out.mkdir()
    builder._write_config_and_secrets(REPO_ROOT, out)
    text = (out / "CONFIG-AND-SECRETS.md").read_text(encoding="utf-8")

    keys = builder._read_env_keys(REPO_ROOT / ".env.staging.example")
    assert keys, "配置模板里没读到任何键名（模板是否完整？）"
    # 至少要有密钥类键名被列出（否则说明分类失效）。
    assert any(builder._SECRET_KEY_PATTERN.search(key) for key in keys)
    assert "密钥系统" in text and "注入规则" in text

    # 赋值形态一律不得出现（模板里才那样写）。
    for key in keys:
        assert f"{key}=" not in text, f"CONFIG-AND-SECRETS.md 出现了赋值形态：{key}="


def test_check_only_detects_tampered_file(tmp_path: Path) -> None:
    """`--check-only` 必须发现被改动的文件（sha256 不一致）并返回 1。"""
    _build(tmp_path, "--version", "1.0.0")
    out = tmp_path / "out"
    handbook = out / "docs" / "handbooks" / "employee-handbook.md"
    handbook.write_text(handbook.read_text(encoding="utf-8") + "\n（被改过）\n", encoding="utf-8")

    result = _check(out)

    assert result.returncode == 1, f"被改动的文件未被发现：\n{result.stdout}"
    assert "sha256 不一致" in result.stdout or "改动" in result.stdout


def test_check_only_accepts_pristine_package(tmp_path: Path) -> None:
    """原样交付包：无损坏 ⇒ 不返回 1（INCOMPLETE 时返回 2 并说明原因）。"""
    _build(tmp_path, "--version", "1.0.0")
    result = _check(tmp_path / "out")
    assert result.returncode in (0, 2), f"原样包不应报损坏：\n{result.stdout}"
    assert "sha256 不一致" not in result.stdout


def test_check_only_rejects_non_package_dir(tmp_path: Path) -> None:
    """不是交付包的目录要显式拒绝，不能"看起来通过了"。"""
    empty = tmp_path / "empty"
    empty.mkdir()
    result = _check(empty)
    assert result.returncode == 1
    assert "不是交付包" in result.stdout


@pytest.mark.parametrize("flag", ["--allow-incomplete"])
def test_allow_incomplete_returns_zero_but_keeps_the_notice(tmp_path: Path, flag: str) -> None:
    """`--allow-incomplete` 只放宽退出码，**不隐藏事实**：`INCOMPLETE.md` 照写。"""
    result = _build(tmp_path, "--version", "1.0.0", flag)
    assert result.returncode == 0
    assert (tmp_path / "out" / "INCOMPLETE.md").is_file(), "放宽退出码不得删除不完整声明"


def test_package_digest_is_deterministic_and_covers_every_file(tmp_path: Path) -> None:
    """整包指纹：确定性（两次构建相同），且与 `--check-only` 重算一致。"""
    assert _build(tmp_path, "--version", "1.0.0").returncode == 2
    out = tmp_path / "out"
    digest_file = out / builder.DIGEST_FILE_NAME
    assert digest_file.is_file(), f"缺 {builder.DIGEST_FILE_NAME}"
    recorded = re.search(r"sha256:([0-9a-f]{64})", digest_file.read_text(encoding="utf-8"))
    assert recorded, "PACKAGE-DIGEST.txt 里没有指纹"
    assert recorded.group(1) == builder.package_digest(out), "整包指纹与重算不一致"

    # 幂等：不动内容重算等于同值。
    assert builder.package_digest(out) == recorded.group(1)


def test_digest_catches_tampering_even_when_the_manifest_is_updated(tmp_path: Path) -> None:
    """**整包指纹的独立价值**：连 `MANIFEST.json` 一起改（逐文件校验形同虚设）时，仍能被抓到。

    场景：`MANIFEST.json` 也在包里 ⇒ 改了文件再顺手把清单里的 sha256 改成新值，
    逐文件校验会"通过"。整包指纹覆盖「清单本身」，因此重算即可发现不一致。
    """
    assert _build(tmp_path, "--version", "1.0.0").returncode == 2
    out = tmp_path / "out"
    handbook = out / "docs" / "handbooks" / "employee-handbook.md"
    handbook.write_text(handbook.read_text(encoding="utf-8") + "\n（被改）\n", encoding="utf-8")

    # 攻击者同步改清单：把该文件的 sha256 换成新值，让逐文件校验通过。
    manifest_path = out / "MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for entry in manifest["files"]:
        if entry["path"] == "docs/handbooks/employee-handbook.md":
            entry["sha256"] = builder._sha256(handbook)
            entry["bytes"] = handbook.stat().st_size
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    result = _check(out)

    assert result.returncode == 1, f"改了文件又改清单竟未被发现：\n{result.stdout}"
    assert "整包指纹不一致" in result.stdout
    # 前提校验：这一轮逐文件校验确实是"通过"的（否则本用例没在验指纹的独立价值）。
    assert "文件被改动" not in result.stdout


def test_unsigned_package_reports_missing_signature(tmp_path: Path) -> None:
    """未签名不是「损坏」，但必须在报告里看得见（不隐藏、不冒充已签）。"""
    assert _build(tmp_path, "--version", "1.0.0").returncode == 2
    out = tmp_path / "out"
    digest_text = (out / builder.DIGEST_FILE_NAME).read_text(encoding="utf-8")
    assert "未签名" in digest_text
    result = _check(out)
    assert "未签名 ⇒ 指纹不能证明发布方" in result.stdout


def test_signed_package_includes_signature_and_marks_it(tmp_path: Path) -> None:
    """提供签名文件时：随包复制、检查标记为已附签名；缺失的签名路径 fail-closed。"""
    sig = tmp_path / "fake.sig"
    sig.write_bytes(b"fake-signature-bytes")
    assert _build(tmp_path, "--version", "1.0.0", "--signature-file", str(sig)).returncode == 2
    out = tmp_path / "out"
    assert (out / builder.SIGNATURE_FILE_NAME).is_file(), "签名文件未随包"
    assert (out / builder.DIGEST_FILE_NAME).read_text(encoding="utf-8").startswith("# 交付包整包指纹")
    assert "已附" in _check(out).stdout

    # 缺失的签名路径 → fail（退出 1）；--force 以便越过「输出目录非空」这道前置。
    result = _build(
        tmp_path, "--version", "1.0.0", "--force", "--signature-file", str(tmp_path / "missing.sig")
    )
    assert result.returncode == 1
    assert "签名文件不存在" in result.stdout


def test_readme_first_is_the_entry_point_and_matches_reality(tmp_path: Path) -> None:
    """包内第一入口必须真的能指路：三步上手 + 手册入口 + **签名/完整性状态如实**。"""
    _build(tmp_path, "--version", "1.2.3")
    readme = (tmp_path / "out" / builder.README_FILE_NAME).read_text(encoding="utf-8")

    # 第一入口的最基本要求：告诉读者"先读 INCOMPLETE"（本包确实不完整）。
    assert "INCOMPLETE.md" in readme and "先读它" in readme
    assert "本包不完整" in readme

    # 三步上手：完整性核对命令 / 预检命令 / 手册入口。
    assert "--check-only" in readme
    assert "commercial_g0_preflight.py" in readme
    for handbook in (
        "docs/handbooks/customer-admin-handbook.md",
        "docs/handbooks/employee-handbook.md",
        "docs/handbooks/troubleshooting-handbook.md",
        "docs/private-deployment-runbook.md",
    ):
        assert handbook in readme, f"README 未指向 {handbook}"
        assert (tmp_path / "out" / handbook).is_file(), f"README 指向了不存在的 {handbook}"

    # 版本如实（与 MANIFEST 一致，不写死）。
    assert "1.2.3" in readme

    # 未签名必须显式声明（不暗示已签）。
    assert "本包未签名" in readme


def test_every_script_the_readme_tells_customers_to_run_is_in_the_package(tmp_path: Path) -> None:
    """README 让客户跑的**每个脚本**都必须真的在包里。

    为什么单列这条：首版 `README-FIRST.md` 写着 `python scripts/build_delivery_package.py --check-only .`，
    而打包脚本自己**没被复制进包**（`ops_scripts` 只列了三个运维脚本）⇒ 客户照做即 `can't open file`。
    2026-09-19 模拟客户解包时实测抓到，此前 21 条守护全绿却没发现（缺口就在"没断言脚本存在"）。
    """
    _build(tmp_path, "--version", "1.0.0")
    out = tmp_path / "out"
    readme = (out / builder.README_FILE_NAME).read_text(encoding="utf-8")

    referenced = set(re.findall(r"scripts/([A-Za-z0-9_]+\.py)", readme))
    assert referenced, "README 未提及任何脚本（检查是否漏写了上手命令）"
    for script in sorted(referenced):
        assert (out / "scripts" / script).is_file(), (
            f"README 让客户跑 scripts/{script}，但包里没有这个文件"
        )
    # 打包脚本自身必须在列（它是客户侧校验的入口）。
    assert "build_delivery_package.py" in referenced


def test_digest_file_tells_customers_to_run_a_script_that_exists(tmp_path: Path) -> None:
    """`PACKAGE-DIGEST.txt` 里给出的校验命令同样必须可执行（同一类缺陷的第二处落点）。"""
    _build(tmp_path, "--version", "1.0.0")
    out = tmp_path / "out"
    text = (out / builder.DIGEST_FILE_NAME).read_text(encoding="utf-8")
    for script in sorted(set(re.findall(r"scripts/([A-Za-z0-9_]+\.py)", text))):
        assert (out / "scripts" / script).is_file(), f"指纹文件让客户跑 scripts/{script}，但包里没有"


def test_image_ref_file_pins_digest_or_says_it_could_not(tmp_path: Path) -> None:
    """镜像引用文件：**要么钉 digest，要么如实说没取到**——不许只给一个可变 tag 就完事。

    测试环境里这个镜像名不存在 ⇒ 走「未取到」分支，文件必须写明原因与补救命令（不静默）。
    """
    _build(tmp_path, "--version", "1.0.0", "--image-ref", "workbench-app:nonexistent-tag-for-test")
    out = tmp_path / "out"
    image_file = out / builder.IMAGE_FILE_NAME
    assert image_file.is_file(), "未生成镜像引用文件"
    text = image_file.read_text(encoding="utf-8")

    assert "workbench-app:nonexistent-tag-for-test" in text
    if "未取到不可变 digest" in text:
        # 如实标注分支：必须给出原因与补救命令。
        assert "docker image inspect" in text
        assert "不能作为不可变引用" in text
    else:
        # 取到 digest 分支：必须是 repo@sha256:… 形态。
        assert "@sha256:" in text

    # 报告里也要看得见 digest 状态。
    result = _build(tmp_path, "--version", "1.0.0", "--force", "--image-ref", "workbench-app:nonexistent-tag-for-test")
    assert "控制平面镜像" in result.stdout


def test_image_digest_returns_empty_instead_of_guessing() -> None:
    """取不到 digest 时返回**空串**（调用方据此如实标注），绝不返回编造值。"""
    assert builder._image_digest("workbench-app:definitely-not-a-real-tag-zzz") == ""


def test_readme_marks_signed_package_as_signed(tmp_path: Path) -> None:
    sig = tmp_path / "x.sig"
    sig.write_bytes(b"sig")
    _build(tmp_path, "--version", "1.0.0", "--signature-file", str(sig))
    readme = (tmp_path / "out" / builder.README_FILE_NAME).read_text(encoding="utf-8")
    assert builder.SIGNATURE_FILE_NAME in readme
    assert "本包未签名" not in readme


def test_manifest_and_digest_cover_the_readme(tmp_path: Path) -> None:
    """README 属生成物，必须**被 MANIFEST 与整包指纹覆盖**（否则它可被随意替换而无人发现）。"""
    _build(tmp_path, "--version", "1.0.0")
    out = tmp_path / "out"
    manifest = _manifest(out)
    paths = {entry["path"] for entry in manifest["files"]}
    assert builder.README_FILE_NAME in paths, "MANIFEST 未登记 README-FIRST.md"
    # 改了 README 而不动清单 ⇒ 逐文件校验与整包指纹都应报错。
    readme = out / builder.README_FILE_NAME
    readme.write_text(readme.read_text(encoding="utf-8") + "\n（被改）\n", encoding="utf-8")
    result = _check(out)
    assert result.returncode == 1
    assert builder.README_FILE_NAME in result.stdout


def test_archive_is_outside_the_package_and_has_checksum(tmp_path: Path) -> None:
    """压缩包放在**输出目录同级**（不把自己装进自己），并给 `*.sha256` 供解包前校验。"""
    result = _build(tmp_path, "--version", "1.0.0", "--archive")
    assert result.returncode == 2
    archive = tmp_path / "out.tar.gz"
    checksum = tmp_path / "out.tar.gz.sha256"
    assert archive.is_file(), "未产出压缩包"
    assert checksum.is_file(), "未产出压缩包校验和"

    recorded = checksum.read_text(encoding="utf-8").split()[0]
    assert recorded == builder._sha256(archive), "压缩包校验和与文件不符"

    # 解包内容与目录一致，且压缩包里**没有**压缩包自己。
    with tarfile.open(archive) as tar:
        names = tar.getnames()
    assert any(name.endswith(builder.README_FILE_NAME) for name in names)
    assert not any(name.endswith(".tar.gz") for name in names), "压缩包里不应再有压缩包"
    assert not any(name.endswith("out.tar.gz.sha256") for name in names)
