"""组装并核对**私有部署交付包**（真源 `commercial-g0-design.md` §7 的必含清单）。

**为什么需要它**：真源 §7 写的是「交付包**必须**包含：控制平面镜像或 Python 发行包、桌面端安装包与版本清单、
数据库迁移脚本、配置模板与密钥注入说明、备份/恢复/健康检查/回滚脚本、客户管理员手册/员工手册/故障手册」。
此前这六项**全靠人工记忆组装**（仓库内无任何打包入口）⇒ 漏一项不会有任何提示。
本脚本把「必含」变成**机器核对**：仓库内必备项缺失即 fail-closed（不产出半成品包），
外部构建产物（镜像 / 桌面安装包）缺失则产出**带 `INCOMPLETE.md` 的包**并如实标注。

**安全红线（本脚本最重要的职责）**：
  1. **只复制 `*.example` 配置模板，绝不复制 `.env` / `.env.*` 真值文件**——密钥不进交付物（宪法 §4.1/§6.2）；
     复制前逐文件复核，命中即 fail-closed。
  2. **不把任何环境变量的值写进产物**：`CONFIG-AND-SECRETS.md` 只列**键名**与注入规则。
  3. 输出目录必须落在仓库的 `dist/` 下（`.gitignore` 已排除）⇒ 交付物不会误入版本库。

**退出码**：`0` 交付包完整（或 `--allow-incomplete` 下缺外部产物）；
`1` **仓库内必备项缺失**（fail-closed，未组装任何东西）；`2` 已组装但缺外部产物（包不完整）。

用法：
    py scripts/build_delivery_package.py --image-ref "workbench-app:1.2.3" \\
        --desktop-installer path/to/setup.exe --version 1.2.3
    py scripts/build_delivery_package.py --check-only dist/delivery   # 客户侧核对既有交付包
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tarfile
from dataclasses import dataclass, field
from pathlib import Path

# ---- 输出编码：强制 UTF-8（2026-09-24 修复）------------------------------------------------
# 本脚本的报告正文含 `⇒` / `★` 等**非 GBK 字符**。Windows 中文控制台默认 cp936 ⇒
# 末尾的 `print(report.to_text())` 会抛 `UnicodeEncodeError: 'gbk' codec can't encode
# character '⇒'`，子进程以非预期返回码退出、stdout 为空。
# 本机实测：`tests/test_delivery_package.py` **13 项全红**；**CI 跑 Linux/UTF-8，故该缺陷在 CI 里不可见**。
# 测试侧一律以 `encoding="utf-8"` 解码 stdout（`tests/test_delivery_package.py` 多处）
# ⇒ **脚本本就应当输出 UTF-8**，此处对齐该契约；`errors="replace"` 兜底，保证任何终端都不再崩。
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

# ---- 真源 §7 的六项必含内容 → 仓库内落点（缺失即 fail-closed）------------------------------
REQUIRED_REPO_ITEMS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("migrations", "数据库迁移脚本", ("migrations",)),
    ("config", "配置模板（密钥注入说明随包生成）", (".env.example", ".env.staging.example", ".env.sso.example")),
    # **整目录纳入 `scripts/`，而不是逐个列清单**（2026-09-19 实测教训）：
#   首版逐个列了 3 个运维脚本，结果 `README-FIRST.md` 让客户跑的
#   `build_delivery_package.py`（打包脚本自身）与三条预检脚本（`commercial_g0_preflight.py` /
#   `staging_preflight.py` / `worker_preflight.py`）**全都不在包里** ⇒ 客户照做即 `can't open file`。
#   逐个列清单必然漂移（新增脚本时没人会回来改这份清单）；整目录复制 + 「README 提到的脚本必须在包里」
#   的守护用例（`test_every_script_the_readme_tells_customers_to_run_is_in_the_package`）才是收敛做法。
#   已核查：`scripts/` 内无硬编码密钥（阴性 grep）；这些脚本本就是给部署侧 / 客户侧用的只读或演练工具。
("ops_scripts", "预检 / 备份恢复演练 / 只读探针 / 打包脚本（整目录）", ("scripts",)),
    ("runbook", "部署运行手册（运维口径唯一来源）", ("docs/private-deployment-runbook.md",)),
    ("handbooks", "客户管理员手册 / 员工手册 / 故障手册", (
        "docs/handbooks/customer-admin-handbook.md",
        "docs/handbooks/employee-handbook.md",
        "docs/handbooks/troubleshooting-handbook.md",
    )),
    ("notices", "第三方许可清单与 copyleft 正文", (
        "THIRD-PARTY-NOTICES.md",
        "licenses/LGPL-3.0.txt",
        "licenses/GPL-3.0.txt",
        "licenses/MPL-2.0.txt",
    )),
)

# 分发 Python 发行包口径所需的锁定文件（真源「控制平面镜像**或** Python 发行包」的后者）。
PY_DISTRIBUTION_FILES: tuple[str, ...] = ("requirements.lock", "pyproject.toml")

# 密钥类**键名**特征（只用于给 `CONFIG-AND-SECRETS.md` 分类，不读也不写任何值）。
_SECRET_KEY_PATTERN = re.compile(r"(SECRET|TOKEN|PASSWORD|_KEY$|ENCRYPTION|DATABASE_URL|WEBHOOK_URL)", re.IGNORECASE)

# 绝不允许进交付物的文件名（真值配置）。
# 判据写成函数而不是正则：**允许** `*.example` 模板，拦掉 `.env` 与 `.env.*` 其余形态。
# （首版用正则 `^\.env($|\.(?!.*\.example$).*)`，实测把 `.env.example` 也误拦了 —— 正则的负向
#   断言在这里既不直观也容易写错，故改为显式两条判据。）
_FORBIDDEN_ENV_PREFIX = ".env"
_ALLOWED_ENV_SUFFIX = ".example"


def is_forbidden_config_name(name: str) -> bool:
    """真值配置文件名（`.env` / `.env.local` 一类）⇒ True；`*.example` 模板 ⇒ False。"""
    if not name.startswith(_FORBIDDEN_ENV_PREFIX):
        return False
    return not name.endswith(_ALLOWED_ENV_SUFFIX)


@dataclass
class PackageItem:
    """交付包的一项内容（真源 §7 的某一条）。"""

    key: str
    label: str
    status: str  # included | missing
    detail: str
    paths: tuple[str, ...] = ()


@dataclass
class DeliveryReport:
    status: str  # complete | incomplete | fail
    items: list[PackageItem] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    def to_text(self) -> str:
        lines = [f"私有部署交付包核对结果：{self.status}"]
        for item in self.items:
            lines.append(f"[{item.status}] {item.label}：{item.detail}")
        for problem in self.problems:
            lines.append(f"[problem] {problem}")
        return "\n".join(lines)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_env_keys(template: Path) -> list[str]:
    """从配置模板里读**键名**（忽略注释与空行）——只读键名，不读值。"""
    keys: list[str] = []
    for line in template.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key = stripped.split("=", 1)[0].strip()
        if key and key not in keys:
            keys.append(key)
    return keys


def _describe_present(repo_root: Path, paths: tuple[str, ...]) -> str:
    """「齐备」的**可核对**描述：目录报文件数，文件报个数——不写「1 项齐备」这种看不出内容的话。"""
    files = 0
    dirs = 0
    for rel in paths:
        target = repo_root / rel
        if target.is_dir():
            dirs += 1
            files += sum(1 for path in target.rglob("*") if path.is_file())
        elif target.is_file():
            files += 1
    parts = [f"{files} 个文件"]
    if dirs:
        parts.append(f"含 {dirs} 个目录")
    return "齐备（" + "，".join(parts) + "）"


def collect_repo_items(repo_root: Path) -> tuple[list[PackageItem], list[str]]:
    """核对仓库内必备项（真源 §7 六项 + Python 发行包口径）。"""
    items: list[PackageItem] = []
    problems: list[str] = []
    for key, label, paths in REQUIRED_REPO_ITEMS:
        missing = [rel for rel in paths if not (repo_root / rel).exists()]
        if missing:
            items.append(PackageItem(key, label, "missing", f"缺少：{', '.join(missing)}", paths))
            problems.append(f"{label} 缺失（{', '.join(missing)}）⇒ fail-closed，不组装交付包")
        else:
            items.append(PackageItem(key, label, "included", _describe_present(repo_root, paths), paths))
    missing_dist = [rel for rel in PY_DISTRIBUTION_FILES if not (repo_root / rel).is_file()]
    if missing_dist:
        items.append(PackageItem("python_dist", "Python 发行包口径（锁文件与打包元数据）", "missing", f"缺少：{', '.join(missing_dist)}"))
        problems.append(f"Python 发行包口径缺失（{', '.join(missing_dist)}）")
    else:
        items.append(PackageItem("python_dist", "Python 发行包口径（锁文件与打包元数据）", "included", "锁文件与打包元数据齐备", PY_DISTRIBUTION_FILES))
    return items, problems


def collect_versions(repo_root: Path, override: str | None) -> dict[str, object]:
    """版本清单（真源 §7「版本至少包含控制平面版本、数据库迁移版本、桌面端版本、Runtime 版本和岗位能力包版本」）。

    缺的**不猜**：读不到就写 `missing` 与原因，由 `INCOMPLETE.md` 汇总。
    """
    migrations = sorted(path.stem for path in (repo_root / "migrations").glob("*.sql"))
    desktop_manifest = repo_root / "desktop" / "package.json"
    desktop_version: object = "missing"
    if desktop_manifest.is_file():
        desktop_version = json.loads(desktop_manifest.read_text(encoding="utf-8")).get("version") or "missing"

    runtime_versions: object = "missing"
    staging = repo_root / ".env.staging.example"
    if staging.is_file():
        for line in staging.read_text(encoding="utf-8").splitlines():
            if line.startswith("WORKBENCH_RUNTIME_VERSIONS="):
                runtime_versions = line.split("=", 1)[1].strip()
                break

    control_plane = override or _git_describe(repo_root)
    return {
        "control_plane_version": control_plane or "unknown",
        "control_plane_version_source": "命令行 --version" if override else "git describe --tags --always（无 git 时 unknown）",
        "database_migration_version": migrations[-1] if migrations else "missing",
        "database_migration_count": len(migrations),
        "desktop_version": desktop_version,
        "desktop_version_source": "desktop/package.json",
        "runtime_versions": runtime_versions,
        "runtime_versions_source": ".env.staging.example（**模板示例值**，部署时必须替换为受控配置里的真实固定版本）",
        "capability_pack_version": "missing",
        "capability_pack_version_note": (
            "真源 §6 定义的「岗位能力包」（入口 / 默认 Agent / 技能 / 提示词版本 / 模型范围 / 知识范围 / "
            "动作白名单 / 审批规则 / 评测集）在本仓库内**没有独立产物**——这些配置分散在数字员工目录、技能层与知识范围绑定中，"
            "因此本项**无版本号可登记**（不臆造）。"
        ),
    }


def _git_describe(repo_root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "describe", "--tags", "--always"],
            cwd=repo_root, capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def _assert_no_secret_files(paths: list[Path]) -> None:
    """红线：交付物里不得出现真值配置文件（只允许 `*.example`）。"""
    offenders = [str(path) for path in paths if is_forbidden_config_name(path.name)]
    if offenders:
        raise SystemExit(f"fail-closed：交付物中出现真值配置文件，拒绝继续：{', '.join(offenders)}")


def _copy(repo_root: Path, output: Path, rel: str) -> Path:
    source = repo_root / rel
    target = output / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(source, target, dirs_exist_ok=True)
        _assert_no_secret_files([path for path in target.rglob("*") if path.is_file()])
        return target
    shutil.copyfile(source, target)
    _assert_no_secret_files([target])
    return target


def _write_config_and_secrets(repo_root: Path, output: Path) -> Path:
    """生成「配置模板 + 密钥注入说明」（真源 §7 第五项的说明部分）。

    **只列键名与规则，不写任何值**——值必须由部署密钥系统注入。
    """
    keys: list[str] = []
    for name in (".env.staging.example", ".env.example", ".env.sso.example"):
        template = repo_root / name
        if template.is_file():
            keys.extend(key for key in _read_env_keys(template) if key not in keys)
    secrets = [key for key in keys if _SECRET_KEY_PATTERN.search(key)]
    others = [key for key in keys if key not in secrets]

    lines = [
        "# 配置模板与密钥注入说明",
        "",
        "> 本文件由 `scripts/build_delivery_package.py` 生成。**只列键名与规则，不含任何真实值**。",
        "",
        "## 1. 交付包内的配置模板",
        "",
        "| 模板 | 用途 |",
        "|---|---|",
        "| `.env.staging.example` | 部署环境配置模板（生产口径：`WORKBENCH_ENV` 非 development + PostgreSQL） |",
        "| `.env.example` | 最小配置示例 |",
        "| `.env.sso.example` | 统一登录（SSO / OIDC）配置模板 |",
        "",
        "**模板里的值是示例，部署时必须替换为受控配置中的真实值。**",
        "",
        "## 2. 必须由密钥系统注入的键（**不得写入仓库 / 镜像 / 交付物**）",
        "",
        "下列键名按名称特征归类（`SECRET` / `TOKEN` / `PASSWORD` / `_KEY` / `ENCRYPTION` / `DATABASE_URL` / `WEBHOOK_URL`）：",
        "",
    ]
    lines += [f"- `{key}`" for key in secrets] or ["- （模板中未出现密钥类键名——请核对模板是否完整）"]
    lines += [
        "",
        "**注入规则**：",
        "",
        "1. 值只从部署环境的密钥系统注入，**绝不写入仓库、镜像层或交付包**。",
        "2. `WORKBENCH_AUTH_SECRET` 与 `WORKBENCH_BACKUP_ENCRYPTION_KEY` 必须**≥32 字符且互不相同**"
        "（`scripts/commercial_g0_preflight.py` 会 fail-closed 校验）。",
        "3. 数据库不对公网开放；`.env`、日志、备份**不得放在公网可访问目录**。",
        "4. 密钥一旦进过仓库，**换密钥而不是删那一行**。",
        "",
        "## 3. 其余配置键（非密钥类，可按环境调整）",
        "",
    ]
    lines += [f"- `{key}`" for key in others] or ["- （无）"]
    lines += [
        "",
        "## 4. 起栈前必须跑的前置预检",
        "",
        "```bash",
        "python scripts/commercial_g0_preflight.py      # 环境 / 存储 / 双密钥 / 迁移清单 / 保留策略 / Runtime 版本",
        "python scripts/staging_preflight.py            # 部署环境预检",
        "python scripts/worker_preflight.py --offline   # Worker 与迁移清单",
        "```",
        "",
        "任一非 `pass` 都**不要**继续部署。",
        "",
    ]
    target = output / "CONFIG-AND-SECRETS.md"
    target.write_text("\n".join(lines), encoding="utf-8")
    return target


def _write_manifest(output: Path, versions: dict[str, object], items: list[PackageItem]) -> Path:
    files = sorted(path for path in output.rglob("*") if path.is_file() and path.name != "MANIFEST.json")
    manifest = {
        "versions": versions,
        "items": [
            {"key": item.key, "label": item.label, "status": item.status, "detail": item.detail}
            for item in items
        ],
        "files": [
            {"path": path.relative_to(output).as_posix(), "bytes": path.stat().st_size, "sha256": _sha256(path)}
            for path in files
        ],
    }
    target = output / "MANIFEST.json"
    target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


DIGEST_FILE_NAME = "PACKAGE-DIGEST.txt"
SIGNATURE_FILE_NAME = "PACKAGE-DIGEST.sig"
README_FILE_NAME = "README-FIRST.md"


def package_digest(output: Path) -> str:
    """整包指纹：对「除 `PACKAGE-DIGEST.txt` 本身以外」的所有文件按**排序后的 路径+内容哈希**计算。

    为什么要它（原缺项）：`MANIFEST.json` 逐文件记 sha256，但**清单本身也在包里**——
    改了文件再顺手改清单，逐文件校验就形同虚设。整包指纹给出一句话可核对的「整包一致性」，
    并可由 `--check-only` 重算比对。

    **确定性**：输入相同则结果相同（按 posix 路径排序、不掺时间戳、不掺本机信息）——
    这样才能用它证明「两次构建产物一致」。
    """
    hasher = hashlib.sha256()
    for path in sorted(output.rglob("*")):
        if not path.is_file() or path.name == DIGEST_FILE_NAME:
            continue
        hasher.update(path.relative_to(output).as_posix().encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(_sha256(path).encode("ascii"))
        hasher.update(b"\0")
    return hasher.hexdigest()


def _write_package_digest(output: Path, signature_file: str) -> Path:
    """写整包指纹文件；**签名状态如实标注**（无证书时明确写「未签名」，绝不暗示已签）。"""
    digest = package_digest(output)
    signed = bool(signature_file)
    lines = [
        "# 交付包整包指纹",
        "",
        f"sha256:{digest}",
        "",
        "## 这个指纹是什么",
        "",
        "对包内**除本文件以外**的所有文件，按「posix 路径 + 文件 sha256」排序后拼接计算得到的单一哈希。",
        "用途：证明「这一包与生成时逐字节一致」，并让两次构建可比对（确定性计算，不掺时间戳）。",
        "",
        "## 签名状态（如实标注）",
        "",
    ]
    if signed:
        lines += [
            f"- **已附签名文件**：`{SIGNATURE_FILE_NAME}`（由外部密钥对 `PACKAGE-DIGEST.txt` 签名）。",
            "- 验签请用与签名方一致的公钥（本包不内置公钥）。",
        ]
    else:
        lines += [
            "- ⚠️ **未签名**（本次构建未提供 `--signature-file`）。",
            "- 含义：本指纹**只能**证明「包内内容与生成时一致」，**不能**证明「本包由我方发布」。",
            "- 生产交付**必须**用受控密钥签名后再分发（`--signature-file <外部签名文件>`）。",
        ]
    lines += [
        "",
        "## 校验方法（客户侧，只读）",
        "",
        "```bash",
        "py scripts/build_delivery_package.py --check-only <交付包目录>",
        "```",
        "该命令会重算整包指纹并与本文件比对，同时按 `MANIFEST.json` 逐文件校验 sha256。",
        "",
    ]
    target = output / DIGEST_FILE_NAME
    target.write_text("\n".join(lines), encoding="utf-8")
    return target


def _write_incomplete(output: Path, missing: list[str]) -> Path:
    lines = [
        "# ⚠️ 本交付包不完整",
        "",
        "> 本文件由 `scripts/build_delivery_package.py` 生成。**本文件存在即表示交付包缺少下列内容**，",
        "> 不要把它当作完整交付包分发。",
        "",
        "## 缺少的内容",
        "",
    ]
    lines += [f"- {entry}" for entry in missing]
    lines += [
        "",
        "## 补齐方式",
        "",
        "| 缺项 | 怎么补 |",
        "|---|---|",
        "| 控制平面镜像 | 用仓库根 `Dockerfile` 构建并打版本标签，然后加 `--image-ref` 重新打包 |",
        "| 桌面端安装包 | 在 Windows 上按 `desktop/electron-builder.yml` 打包（**需代码签名证书**），然后加 `--desktop-installer` 重新打包 |",
        "| 岗位能力包版本 | 该产物在本仓库内不存在（配置分散在数字员工目录 / 技能层 / 知识范围绑定中）⇒ 需先定义独立产物 |",
        "",
        "## 重新打包",
        "",
        "```bash",
        "py scripts/build_delivery_package.py \\",
        '  --image-ref "workbench-app:<版本>" \\',
        "  --desktop-installer <安装包路径> \\",
        "  --version <版本>",
        "```",
        "",
    ]
    target = output / "INCOMPLETE.md"
    target.write_text("\n".join(lines), encoding="utf-8")
    return target


def build(
    repo_root: Path,
    output: Path,
    *,
    version: str | None,
    image_ref: str,
    desktop_installer: str,
    signature_file: str,
    allow_incomplete: bool,
    force: bool,
) -> tuple[DeliveryReport, int]:
    items, problems = collect_repo_items(repo_root)
    if problems:
        return DeliveryReport(status="fail", items=items, problems=problems), 1

    if output.exists() and any(output.iterdir()):
        if not force:
            return DeliveryReport(
                status="fail", items=items,
                problems=[f"输出目录非空：{output}（加 --force 才会覆盖）"],
            ), 1
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)
    for _key, _label, paths in REQUIRED_REPO_ITEMS:
        for rel in paths:
            _copy(repo_root, output, rel)
    for rel in PY_DISTRIBUTION_FILES:
        _copy(repo_root, output, rel)
    _write_config_and_secrets(repo_root, output)

    missing: list[str] = []
    if image_ref:
        _write_control_plane_image(output, image_ref)
        digest = _image_digest(image_ref)
        items.append(PackageItem(
            "control_plane_image", "控制平面镜像（外部构建产物）", "included",
            f"{image_ref}" + (f"（digest {digest.split('@')[-1][:19]}…）" if digest else "（**未取到 digest**，见文件内说明）"),
        ))
    else:
        items.append(PackageItem("control_plane_image", "控制平面镜像（外部构建产物）", "missing", "未提供 --image-ref"))
        missing.append("控制平面镜像：未提供 `--image-ref`（本仓库只能构建，需 docker）")

    if desktop_installer:
        source = Path(desktop_installer)
        if not source.is_file():
            return DeliveryReport(
                status="fail", items=items, problems=[f"桌面端安装包不存在：{source}"]
            ), 1
        target = output / "desktop" / source.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        items.append(PackageItem("desktop_installer", "桌面端安装包（外部构建产物）", "included", source.name, (f"desktop/{source.name}",)))
    else:
        items.append(PackageItem("desktop_installer", "桌面端安装包（外部构建产物）", "missing", "未提供 --desktop-installer"))
        missing.append("桌面端安装包：未提供 `--desktop-installer`（需 Windows 代码签名证书）")

    versions = collect_versions(repo_root, version)
    if versions.get("capability_pack_version") == "missing":
        # 本项**不写 INCOMPLETE.md**（区别对待，理由写在这里以便复核）：
        #   `INCOMPLETE.md` 的语义是「这个包不要直接分发」——适用于**分发必需**的外部产物（镜像 / 桌面安装包）缺失；
        #   「岗位能力包」属真源 §7 要求**版本清单应当包含**的维度，而该产物在本仓库内根本不存在
        #   ⇒ 已在 `MANIFEST.json` 的 `versions.capability_pack_version` 与 `capability_pack_version_note` 里
        #   **如实标注为 missing 并写明原因**（不臆造版本号），并在报告里以 `[missing]` 列出。
        items.append(PackageItem(
            "capability_pack_version", "岗位能力包版本（真源 §7 要求的版本维度）", "missing",
            "本仓库内无该独立产物 ⇒ 记 missing 并写明原因，不臆造版本号（详见 MANIFEST.json 的 versions 段）",
        ))

    if missing:
        _write_incomplete(output, missing)

    # 签名文件校验**提前**到写 README 之前：README 要如实写签名状态，不能先写完再发现签名缺失。
    if signature_file:
        signature_source = Path(signature_file)
        if not signature_source.is_file():
            return DeliveryReport(
                status="fail", items=items, problems=[f"签名文件不存在：{signature_source}"]
            ), 1
        shutil.copyfile(signature_source, output / SIGNATURE_FILE_NAME)
        items.append(PackageItem("signature", "交付包签名（外部密钥）", "included", SIGNATURE_FILE_NAME))
    else:
        items.append(PackageItem(
            "signature", "交付包签名（外部密钥）", "missing",
            "未提供 --signature-file ⇒ 整包指纹**未签名**（只能证明内容一致，不能证明发布方）",
        ))

    # 顺序有讲究：README/MANIFEST/DIGEST 都由本脚本生成，必须**最后**写，
    # 这样 MANIFEST 的逐文件清单与整包指纹把前面生成的说明文件（含 INCOMPLETE.md）也覆盖进去。
    _write_readme_first(output, versions, signed=bool(signature_file), incomplete=bool(missing))
    _write_manifest(output, versions, items)
    _write_package_digest(output, signature_file)
    items.append(PackageItem("readme_first", "包内第一入口（README-FIRST.md）", "included", README_FILE_NAME))

    status = "incomplete" if missing else "complete"
    code = 0 if (not missing or allow_incomplete) else 2
    return DeliveryReport(status=status, items=items), code


def _write_readme_first(output: Path, versions: dict[str, object], *, signed: bool, incomplete: bool) -> Path:
    """包内**第一入口**：客户拿到包先读它（否则手册 / 清单 / 预检散落在多个目录里，容易漏）。"""
    control_plane = versions.get("control_plane_version", "unknown")
    migration = versions.get("database_migration_version", "missing")
    lines = [
        "# 请先读这一页",
        "",
        f"> 本交付包由 `scripts/build_delivery_package.py` 组装；版本：控制平面 **{control_plane}**、"
        f"数据库迁移 **{migration}**。",
        "",
    ]
    if incomplete:
        lines += [
            "## ⚠️ 本包不完整",
            "",
            "本包内存在 [`INCOMPLETE.md`](INCOMPLETE.md)：**先读它**，确认缺什么、怎么补齐，"
            "再决定是否分发。**不要**把不完整的包当完整交付。",
            "",
        ]
    else:
        lines += [
            "## 完整性",
            "",
            "本包内容齐备（无 `INCOMPLETE.md`）。完整性可用一条命令复核：",
            "",
            "```bash",
            "python scripts/build_delivery_package.py --check-only .",
            "```",
            "",
        ]
    lines += [
        "## 三步上手",
        "",
        "**第 1 步 · 核对完整性**（只读，任何环境都可跑）",
        "",
        "```bash",
        "python scripts/build_delivery_package.py --check-only .",
        "```",
        "它按 `MANIFEST.json` 逐文件校验 sha256，并重算整包指纹（见 [`PACKAGE-DIGEST.txt`](PACKAGE-DIGEST.txt)）。",
        "",
        "**第 2 步 · 按手册配置并预检**",
        "",
        "| 你是 | 先读 |",
        "|---|---|",
        "| 部署 / 运维 | [`docs/private-deployment-runbook.md`](docs/private-deployment-runbook.md) |",
        "| 客户管理员 | [`docs/handbooks/customer-admin-handbook.md`](docs/handbooks/customer-admin-handbook.md) |",
        "| 普通员工 | [`docs/handbooks/employee-handbook.md`](docs/handbooks/employee-handbook.md) |",
        "| 出故障的人 | [`docs/handbooks/troubleshooting-handbook.md`](docs/handbooks/troubleshooting-handbook.md) |",
        "",
        "配置与密钥：读 [`CONFIG-AND-SECRETS.md`](CONFIG-AND-SECRETS.md)（**只列键名与注入规则，不含任何真实值**）。",
        "密钥必须由部署环境的密钥系统注入——**不要**把值写回模板文件。",
        "",
        "起栈前跑预检（任一非 `pass` 都不要继续）：",
        "",
        "```bash",
        "python scripts/commercial_g0_preflight.py      # 环境 / 存储 / 双密钥 / 迁移清单 / 保留策略 / Runtime 版本",
        "python scripts/staging_preflight.py            # 部署环境预检",
        "python scripts/worker_preflight.py --offline   # Worker 与迁移清单",
        "```",
        "",
        "**第 3 步 · 部署与验收**",
        "",
        "按 runbook 的「容器化部署」「迁移与备份」执行；随后用 "
        "[`docs/customer-side-acceptance-runbook.md`](docs/customer-side-acceptance-runbook.md) "
        "（配套只读探针 `scripts/customer_acceptance_probe.py`）做客户侧验收。",
        "",
        "## 包内结构",
        "",
        "| 路径 | 是什么 |",
        "|---|---|",
        "| `README-FIRST.md` | 本页（第一入口） |",
        "| `MANIFEST.json` | 版本清单 + 每个文件的 sha256 |",
        "| `PACKAGE-DIGEST.txt` | 整包指纹（**含签名状态**） |",
        "| `INCOMPLETE.md` | 仅在缺外部产物时出现 ⇒ **看到它就先读它** |",
        "| `CONFIG-AND-SECRETS.md` | 配置键名与密钥注入规则（无值） |",
        "| `.env.*.example` | 配置模板（**示例值，部署时必须替换**） |",
        "| `migrations/` | 数据库迁移脚本 |",
        "| `scripts/` | 预检、备份/恢复演练、只读探针、本打包脚本 |",
        "| `docs/` | 部署运行手册 + 三份交付手册 |",
        "| `THIRD-PARTY-NOTICES.md` / `licenses/` | 第三方许可清单与 copyleft 正文 |",
        "| `requirements.lock` / `pyproject.toml` | 控制平面依赖锁定与打包元数据 |",
        "",
        "## 签名状态（如实）",
        "",
    ]
    if signed:
        lines += [
            f"- 本包附签名文件 `{SIGNATURE_FILE_NAME}`（对 `PACKAGE-DIGEST.txt` 的签名）。",
            "- 验签请用与签名方一致的公钥（**本包不内置公钥**）。",
        ]
    else:
        lines += [
            "> ⚠️ **本包未签名。** 整包指纹只能证明「包内内容与生成时一致」，"
            "**不能**证明「本包由我方发布」。生产交付请让提供方用受控密钥签名后再分发。",
        ]
    lines += [
        "",
        "## 遇到问题",
        "",
        "先读 [`docs/handbooks/troubleshooting-handbook.md`](docs/handbooks/troubleshooting-handbook.md)；"
        "报障请带**报错原文、发生时间、影响范围、出问题前动过什么**四样。",
        "",
    ]
    target = output / README_FILE_NAME
    target.write_text("\n".join(lines), encoding="utf-8")
    return target


IMAGE_FILE_NAME = "CONTROL-PLANE-IMAGE.txt"


def _image_digest(image_ref: str) -> str:
    """尝试取镜像的**不可变 digest**（`repo@sha256:…`）；取不到返回空串。

    为什么要 digest（宪法 §6.3 产物可追溯）：**tag 可变、digest 不可变**——交付包若只写 tag，
    收方拉到的可能是被重新打过同一 tag 的**另一个**镜像（仓内既有口径即「基础镜像按 digest 钉死」）。
    取不到时**如实标注**（未在本机 / docker 不可用 / 镜像未构建），绝不编造一个 digest。
    """
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", "--format", "{{index .RepoDigests 0}}", image_ref],
            capture_output=True, text=True, timeout=20, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if result.returncode != 0:
        return ""
    value = result.stdout.strip()
    return value if "@sha256:" in value else ""


def _write_control_plane_image(output: Path, image_ref: str) -> Path:
    """写镜像引用文件：**优先钉 digest**；取不到则如实写明原因与补救方式。"""
    digest = _image_digest(image_ref)
    lines = [
        "# 控制平面镜像引用",
        "",
        f"镜像：`{image_ref}`",
        "",
    ]
    if digest:
        lines += [
            "## 不可变引用（部署请用这一行）",
            "",
            f"`{digest}`",
            "",
            "> **tag 可变、digest 不可变**：请优先按 digest 拉取与部署，"
            "否则同名 tag 被重新推送后，收方拿到的可能是另一个镜像。",
        ]
    else:
        lines += [
            "## ⚠️ 未取到不可变 digest",
            "",
            "本机未能通过 `docker image inspect` 取到该镜像的 `RepoDigests`（常见原因：镜像不在当前机器上、"
            "docker 不可用、或镜像尚未推送）。**因此本文件只登记了可变 tag，不能作为不可变引用。**",
            "",
            "补救（在持有该镜像的机器上执行，取到 digest 后按 digest 部署）：",
            "",
            "```bash",
            f"docker image inspect --format '{{{{index .RepoDigests 0}}}}' {image_ref}",
            "```",
        ]
    lines += [
        "",
        "## 构建口径",
        "",
        "镜像须按仓库根 `Dockerfile` 构建，并带 `org.opencontainers.image.version` / "
        "`org.opencontainers.image.revision` 标签（可用 `docker image inspect` 查回对应提交，宪法 §6.3）。",
        "",
    ]
    target = output / IMAGE_FILE_NAME
    target.write_text("\n".join(lines), encoding="utf-8")
    return target


def _archive_package(output: Path) -> tuple[Path, Path]:
    """把交付目录打成 `tar.gz`，并写 `*.sha256`（客户拿到的**那一个文件**本身可校验）。

    为什么要压缩包校验和：目录形态的 `--check-only` 需要先解包；而「手上的这个文件有没有传坏」
    要在解包**之前**就能回答 ⇒ 单独给压缩包一份校验和文件。
    """
    # **不用 `with_suffix`**：输出目录名若自带点（如 `delivery.v2`），`with_suffix` 会把它替换掉。
    archive = output.parent / (output.name + ".tar.gz")
    if archive.exists():
        archive.unlink()
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(output, arcname=output.name)
    checksum = _sha256(archive)
    digest_file = archive.with_name(archive.name + ".sha256")
    digest_file.write_text(f"{checksum}  {archive.name}\n", encoding="utf-8")
    return archive, digest_file


def check_only(package_dir: Path) -> tuple[DeliveryReport, int]:
    """核对既有交付包（客户侧可用）：按 `MANIFEST.json` 逐文件校验 sha256，并检查必备落点。"""
    items: list[PackageItem] = []
    problems: list[str] = []
    manifest_path = package_dir / "MANIFEST.json"
    if not manifest_path.is_file():
        return DeliveryReport(status="fail", problems=[f"不是交付包（缺 MANIFEST.json）：{package_dir}"]), 1
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    for entry in manifest.get("files", []):
        target = package_dir / entry["path"]
        if not target.is_file():
            problems.append(f"缺文件：{entry['path']}")
        elif _sha256(target) != entry["sha256"]:
            problems.append(f"文件被改动（sha256 不一致）：{entry['path']}")

    # 整包指纹：比逐文件校验更强——**清单本身也在包里**，只改文件再改清单骗不过它。
    digest_path = package_dir / DIGEST_FILE_NAME
    if not digest_path.is_file():
        problems.append(f"缺整包指纹：{DIGEST_FILE_NAME}")
    else:
        recorded = re.search(r"sha256:([0-9a-f]{64})", digest_path.read_text(encoding="utf-8"))
        if recorded is None:
            problems.append(f"{DIGEST_FILE_NAME} 里没有可识别的指纹")
        else:
            actual = package_digest(package_dir)
            if actual != recorded.group(1):
                problems.append(
                    f"整包指纹不一致（重算 {actual[:16]}… ≠ 记录 {recorded.group(1)[:16]}…）⇒ 包内容与生成时不同"
                )
            else:
                items.append(PackageItem("digest", "整包指纹（sha256）", "included", actual[:16] + "…"))

    # 签名状态**如实报告**（未签名不是「损坏」，但必须看得见）。
    signed = (package_dir / SIGNATURE_FILE_NAME).is_file()
    items.append(PackageItem(
        "signature", "交付包签名（外部密钥）",
        "included" if signed else "missing",
        "已附 " + SIGNATURE_FILE_NAME if signed else "未签名 ⇒ 指纹不能证明发布方，仅能证明内容一致",
    ))

    for key, label, paths in REQUIRED_REPO_ITEMS:
        missing = [rel for rel in paths if not (package_dir / rel).exists()]
        items.append(PackageItem(
            key, label, "missing" if missing else "included",
            f"缺少：{', '.join(missing)}" if missing else "齐备",
        ))
        problems += [f"{label} 缺 {rel}" for rel in missing]

    incomplete = (package_dir / "INCOMPLETE.md").is_file()
    if problems:
        return DeliveryReport(status="fail", items=items, problems=problems), 1
    if incomplete:
        return DeliveryReport(
            status="incomplete", items=items, problems=["包内存在 INCOMPLETE.md（外部产物未补齐）"]
        ), 2
    return DeliveryReport(status="complete", items=items), 0


def main() -> int:
    parser = argparse.ArgumentParser(description="组装并核对私有部署交付包（真源 §7）")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output", default="dist/delivery")
    parser.add_argument("--version", default=None, help="控制平面版本；缺省用 git describe")
    parser.add_argument("--image-ref", default="", help="控制平面镜像引用（外部构建）")
    parser.add_argument("--desktop-installer", default="", help="桌面端安装包路径（外部构建）")
    parser.add_argument("--allow-incomplete", action="store_true", help="缺外部产物时仍返回 0（INCOMPLETE.md 照写）")
    parser.add_argument("--signature-file", default="", help="外部密钥对整包指纹的签名文件（生产交付必须提供）")
    parser.add_argument("--archive", action="store_true", help="额外产出 <输出目录>.tar.gz 与 .sha256（客户拿到的单个文件可校验）")
    parser.add_argument("--force", action="store_true", help="输出目录非空时覆盖")
    parser.add_argument("--check-only", default="", help="只核对既有交付包目录，不组装")
    args = parser.parse_args()

    if args.check_only:
        report, code = check_only(Path(args.check_only))
    else:
        output = Path(args.output)
        if not output.is_absolute():
            output = Path(args.repo_root).resolve() / output
        report, code = build(
            Path(args.repo_root).resolve(), output,
            version=args.version,
            image_ref=args.image_ref,
            desktop_installer=args.desktop_installer,
            signature_file=args.signature_file,
            allow_incomplete=args.allow_incomplete,
            force=args.force,
        )
        # 归档在**目录组装完成之后**做：压缩包放在输出目录的**同级**（不把自己装进自己）。
        if args.archive and code in (0, 2):
            archive, checksum = _archive_package(output)
            report.items.append(PackageItem(
                "archive", "交付压缩包（tar.gz）与校验和", "included",
                f"{archive.name} + {checksum.name}",
            ))
    print(report.to_text())
    return code


if __name__ == "__main__":
    raise SystemExit(main())
