"""生成 `THIRD-PARTY-NOTICES.md`（第三方组件与许可证清单）。

**为什么需要它**（宪法 12.3「第三方库逐个核对许可证」+ 交付口径「每次升级都要重新生成 SBOM」）：
交付物（应用镜像 / 执行镜像 / 桌面端 / 伴侣端 / 管理台）里打包了大量第三方组件，许可义务必须
**可重跑地**重新生成，而不是靠人工记忆维护一份手写清单——手写清单在下一次升级时必然漂移。

**证据来源（三类，均为「已安装树 / 锁文件」口径，不是凭印象）**：
  1. **应用镜像 Python 依赖**：`requirements.lock`（`--require-hashes` 钉死，构建期强制校验）
     的包清单 + 各包 `dist-info/METADATA` 的 `License-Expression` / `License` / 分类器。
  2. **执行镜像（dsh）npm 依赖**：外部安装树（`--dsh-tree`，Linux 口径 `npm ci` 产物）里各包
     `package.json` 的 `license` 字段。
  3. **三个前端（管理台 / 伴侣端 / 桌面端）npm 依赖**：各自 `package-lock.json` 的 `packages`
     条目（lockfileVersion 3 逐条带 `license`）。
  4. **许可证正文**：从安装树内各包随带的 `LICENSE*` 文件**原文收集**（不手写、不凭记忆），
     落到 `licenses/`；**copyleft 类（LGPL-3.0 / GPL-3.0）必须预先存在于 `licenses/`**，
     缺失即 fail-closed 报错——LGPL-3.0 正文在 `sharp` 生态里**并未随包提供**，
     只能取权威原文，绝不能由脚本编造。

**口径与边界（如实写进产物，不做过度承诺）**：
  - 前端与 dsh 的 npm 清单是 **lockfile / 安装树全量**（含 `devDependencies` 与 optional 平台包）
    ⇒ **保守从宽**（多列不构成违规，漏列才构成）；**不**声称等于最终镜像内的精确集合。
  - 未逐包比对「声明值与许可证正文一致」⇒ 产物里登记为未验证项。
  - 执行镜像尚未构建 ⇒ 「镜像内二次扫描」登记为未做（本脚本扫的是安装树，不是镜像层）。

用法：
    py scripts/generate_third_party_notices.py --dsh-tree "D:/path/to/_dsh-linux-verify/node_modules"
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

# copyleft / 弱 copyleft 类正文必须预先提供（不从包内收集）：缺失即 fail-closed。
# 依据：这些上游**往往不随带正文**（`@img/sharp-libvips-*` 无 LICENSE 文件、`certifi` 的 MPL
# 只有 989 字节的指路说明），只能取权威原文；缺失时宁可报错，也不生成一份「没有正文」的清单。
REQUIRED_LICENSE_TEXTS = ("LGPL-3.0", "GPL-3.0", "MPL-2.0")

# 安装树内视为「许可证正文」的文件名模式（大小写不敏感）。
LICENSE_FILE_PATTERN = re.compile(r"^(licen[cs]e|copying|notice)(\..*)?$", re.IGNORECASE)

# **正文内容特征**：收集到的文件必须命中对应族的特征串，否则**不收录**。
# 为什么必须校验（2026-09-19 实测）：`cryptography` 随带的 `LICENSE` 只有 197 字节，
# 内容是「本软件按 LICENSE.APACHE 或 LICENSE.BSD 之一授权」的**指路说明**，不是许可正文；
# `certifi` 的 MPL 说明也只有 989 字节。若按文件名照收，清单会拿「说明」冒充「正文」——
# 这比不收更糟（读者会以为义务已履行）。
_LICENSE_SIGNATURES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("LGPL", ("LESSER GENERAL PUBLIC LICENSE",)),
    ("GPL", ("GNU GENERAL PUBLIC LICENSE", "TERMS AND CONDITIONS")),
    ("Apache", ("Apache License", "Version 2.0, January 2004")),
    ("MPL", ("Mozilla Public License", "Version 2.0")),
    ("Mozilla", ("Mozilla Public License", "Version 2.0")),
    ("MIT", ("Permission is hereby granted",)),
    ("BSD", ("Redistribution and use in source and binary forms",)),
    ("ISC", ("Permission to use, copy, modify",)),
    ("Unlicense", ("This is free and unencumbered software",)),
    ("PSF", ("PYTHON SOFTWARE FOUNDATION LICENSE",)),
    ("Python", ("PYTHON SOFTWARE FOUNDATION LICENSE",)),
    ("0BSD", ("Permission to use, copy, modify",)),
)


def _text_matches_license(body: str, canonical: str) -> bool:
    """正文是否真的是该族许可（按特征串判定；认不出该族时**拒绝收录**）。

    **族名按长度降序匹配**：否则 `0BSD` 会先命中 `BSD`、`LGPL-3.0` 会先命中 `GPL`，
    用错族的特征串去校验 ⇒ 把**合法正文误判为无效**（2026-09-19 实测：`tslib` 的 0BSD
    正文因此被拒，而 0BSD 是常见许可，代价很大）。
    """
    ordered = sorted(_LICENSE_SIGNATURES, key=lambda item: -len(item[0]))
    for family, needles in ordered:
        if family.lower() not in canonical.lower():
            continue
        return all(needle in body for needle in needles)
    return False


def license_text_key(license_id: str) -> str:
    """许可证正文的**落盘键**：同一份正文的不同写法收敛到一个文件。

    收敛规则（只做**同义收敛**，不改变清单里登记的原始声明值）：
      - `LGPL-3.0` / `LGPL-3.0-only` / `LGPL-3.0-or-later` → `LGPL-3.0`（同一份正文）；
      - `GPL-3.0` 系列同理；
      - PyPI 分类器写法 `MIT License` → `MIT`、`Apache Software License` → `Apache-2.0`；
      - MPL 的多种写法（`MPL-2.0` / `Mozilla Public License 2.0 (MPL 2.0)`）→ `MPL-2.0`。
    """
    upper = license_id.upper()
    for base in ("LGPL-3.0", "GPL-3.0"):
        if upper.startswith(base):
            return base
    if "MOZILLA PUBLIC LICENSE" in upper or "MPL" in upper:
        return "MPL-2.0"
    if license_id == "MIT License":
        return "MIT"
    if license_id == "Apache Software License":
        return "Apache-2.0"
    return license_id


def _is_compound(license_id: str) -> bool:
    """复合表达式（`A OR B` / `A AND B`）：不为其收集正文（各分量的正文另有归属）。"""
    upper = license_id.upper()
    return " OR " in upper or " AND " in upper

# 许可证标识归一：把 npm / PyPI 里五花八门的写法收敛到用于分组的键。
# **只做归一分组，不改变清单里逐条登记的原始声明值**（避免「归一」变成「改写事实」）。
_NORMALIZE_RULES = (
    (re.compile(r"^MIT$", re.IGNORECASE), "MIT"),
    (re.compile(r"^Apache-2\.0$", re.IGNORECASE), "Apache-2.0"),
    (re.compile(r"^BSD-3-Clause$", re.IGNORECASE), "BSD-3-Clause"),
    (re.compile(r"^BSD-2-Clause$", re.IGNORECASE), "BSD-2-Clause"),
    (re.compile(r"^ISC$", re.IGNORECASE), "ISC"),
    (re.compile(r"^0BSD$", re.IGNORECASE), "0BSD"),
    (re.compile(r"^Unlicense$", re.IGNORECASE), "Unlicense"),
    (re.compile(r"^Python-2\.0$", re.IGNORECASE), "Python-2.0"),
)

# 弱 copyleft 义务履行说明（真源：`docs/dsh-integration-preflight-checklist.md` §B13 / §F7.4）。
# **逐族**写清「可重链接 + 声明 + 源码获取途径」——只写 sharp 会漏掉同类的 psycopg（LGPL-3.0-only）。
LGPL_OBLIGATION_NOTES = (
    "LGPL 属**弱 copyleft**：对外分发容器镜像 / 桌面产物即触发义务。本清单按"
    "「许可正文 + 可重链接 + 源码获取途径」三项逐族履行：",
    "",
    "1. **许可正文**：`licenses/LGPL-3.0.txt`（LGPL-3.0 全文）与 `licenses/GPL-3.0.txt`"
    "（LGPL-3.0 第 3 节并入 GPL-3.0 条款，故一并提供）。",
    "2. **可重链接（relinking）**：相关组件均以**未修改的独立包 / 独立共享库**形式随产物分发，"
    "未与我方代码静态链接、未修改其源码 ⇒ 使用方可自行替换为修改后的同版本库并重新运行："
    "`@img/sharp-libvips-*` 对应 `lib/libvips-cpp.so.*`；`psycopg-binary` 对应其内置 libpq 二进制。",
    "3. **源码获取途径**：上游源码公开发布，可自行取回同版本源码 —— "
    "`@img/sharp-libvips-*` ← `lovell/sharp-libvips`（内含 libvips 本体，上游 `libvips/libvips`）；"
    "`@img/sharp-wasm32` ← `lovell/sharp`；`psycopg` / `psycopg-binary` / `psycopg-pool` ← "
    "`psycopg/psycopg`。**当前交付包内不含上游源码副本**，仅提供上述公开获取途径；"
    "如需随交付包提供源码副本，请在交付前提出。",
)

# MPL-2.0 是**文件级**弱 copyleft：义务只落在「被修改的 MPL 文件」上。
MPL_OBLIGATION_NOTES = (
    "MPL-2.0 属**文件级**弱 copyleft（不是整库 copyleft）：义务只针对「被修改的 MPL 源文件」。"
    "相关组件以**未修改的独立包**形式分发 ⇒ 无「公开被修改文件」的义务；其源码可自上游公开仓库取回。"
    "**我方未修改这些组件的源码。**",
    "",
    "> ⚠️ **正文现状（如实）**：这些组件随带的许可文件**多为「指向别的文件的说明」而非 MPL 正文**"
    "（实测 `certifi` 的 MPL 说明仅 989 字节）⇒ 本脚本**拒绝把说明当正文收录**，"
    "并在下方「未验证与边界」里登记为**需人工补权威正文**。这不影响「我方未修改」这一义务判断，"
    "但**不得**据此认为 MPL 正文已随产物齐备。",
)


@dataclass
class Component:
    """一个第三方组件（用于清单一行）。"""

    name: str
    version: str
    license: str
    source: str  # 证据来源标签（Python / dsh / 前端包名）

    @property
    def key(self) -> str:
        return f"{self.name}@{self.version}"


@dataclass
class Inventory:
    components: list[Component] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def normalize_license(raw: str) -> str:
    """把许可证声明归一为分组键；未命中规则的写法原样保留（不猜测）。"""
    value = (raw or "").strip()
    if not value:
        return "(未声明)"
    for pattern, canonical in _NORMALIZE_RULES:
        if pattern.match(value):
            return canonical
    return value


def read_python_lock(lock_path: Path) -> list[tuple[str, str]]:
    """从 pip-compile 产物读出 `(name, version)` 清单。"""
    text = lock_path.read_text(encoding="utf-8")
    pairs = re.findall(r"^([A-Za-z0-9_.\-]+)==([^\s\\]+)", text, re.MULTILINE)
    # pip-compile 里 `psycopg[binary]==3.3.5` 这类带 extra 的写法归一为包名。
    return [(name.split("[")[0], version) for name, version in pairs]


def _python_license_field(metadata: Path) -> str:
    """从 METADATA 文本里取许可证声明（取不到返回空串，**不猜测**）。"""
    text = metadata.read_text(encoding="utf-8", errors="replace")
    expression = re.search(r"^License-Expression:\s*(.+)$", text, re.MULTILINE)
    if expression:
        return expression.group(1).strip()
    classifiers = re.findall(r"^Classifier:\s*License\s*::\s*(.+)$", text, re.MULTILINE)
    if classifiers:
        # 形如 "OSI Approved :: MIT License" ⇒ 取最后一段。
        return classifiers[-1].split("::")[-1].strip()
    plain = re.search(r"^License:\s*(.+)$", text, re.MULTILINE)
    return plain.group(1).strip() if plain else ""


def python_license_from_metadata(site_packages: Path, name: str) -> str | None:
    """读 dist-info 的 METADATA，取许可证声明；取不到返回 None（不猜测）。"""
    key = name.lower().replace("-", "_")
    candidates = list(site_packages.glob(f"{key}-*.dist-info/METADATA"))
    if not candidates:
        return None
    value = _python_license_field(candidates[0])
    return value or None


def collect_python_components(
    lock_path: Path, site_packages: Path, notes: list[str]
) -> list[Component]:
    components: list[Component] = []
    missing: list[str] = []
    for name, version in read_python_lock(lock_path):
        declared = python_license_from_metadata(site_packages, name)
        if declared is None:
            missing.append(f"{name}=={version}")
            continue
        components.append(
            Component(name=name, version=version, license=declared, source="应用镜像（Python）")
        )
    if missing:
        notes.append(
            "应用镜像 Python 依赖中以下包在本机安装树内**未找到 dist-info**"
            f"（多为平台限定包，Linux 构建时才安装）⇒ 其许可证声明**未取证**，不得读成已核：{', '.join(missing)}"
        )
    return components


def npm_license_from_tree(tree: Path, name: str) -> str | None:
    manifest = tree / name / "package.json"
    if not manifest.is_file():
        return None
    try:
        data = json.loads(manifest.read_text(encoding="utf-8", errors="replace"))
    except json.JSONDecodeError:
        return None
    value = data.get("license")
    if isinstance(value, dict):  # 老式写法：{"type": "MIT", "url": ...}
        value = value.get("type")
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(data.get("licenses"), list):  # 更老式写法
        parts = [item.get("type") for item in data["licenses"] if isinstance(item, dict)]
        parts = [part for part in parts if part]
        if parts:
            return " OR ".join(parts)
    return None


def collect_dsh_components(tree: Path, notes: list[str]) -> list[Component]:
    """扫 npm 安装树（含嵌套 `node_modules`）里的全部包。"""
    components: dict[tuple[str, str], Component] = {}
    missing: list[str] = []
    for manifest in sorted(tree.rglob("package.json")):
        if "node_modules" not in manifest.parts:
            continue
        try:
            data = json.loads(manifest.read_text(encoding="utf-8", errors="replace"))
        except json.JSONDecodeError:
            continue
        name, version = data.get("name"), data.get("version")
        if not isinstance(name, str) or not isinstance(version, str):
            continue
        if (name, version) in components:
            continue
        declared = npm_license_from_tree(manifest.parent, ".")
        if declared is None:
            missing.append(f"{name}@{version}")
            declared = "(未声明)"
        components[(name, version)] = Component(
            name=name, version=version, license=declared, source="执行镜像（dsh / npm）"
        )
    if missing:
        notes.append(
            "执行镜像 npm 依赖中以下包**未声明 `license` 字段** ⇒ 许可未取证，不得读成已核："
            + ", ".join(sorted(missing)[:20])
        )
    return sorted(components.values(), key=lambda item: (item.name, item.version))


def collect_frontend_components(repo_root: Path, notes: list[str]) -> list[Component]:
    """从三个前端的 `package-lock.json` 读 npm 清单（lockfileVersion 3 逐条带 license）。"""
    components: list[Component] = []
    for app in ("admin-web", "companion-pwa", "desktop"):
        lock = repo_root / app / "package-lock.json"
        if not lock.is_file():
            notes.append(f"前端 `{app}` 无 `package-lock.json` ⇒ 该产物依赖清单**未纳入**本清单。")
            continue
        data = json.loads(lock.read_text(encoding="utf-8"))
        for path, entry in sorted((data.get("packages") or {}).items()):
            if not path.startswith("node_modules/"):
                continue
            name = path[len("node_modules/") :]
            version = str(entry.get("version") or "")
            if not version:
                continue
            declared = entry.get("license") or "(未声明)"
            components.append(
                Component(
                    name=name,
                    version=version,
                    license=str(declared),
                    source=f"前端（{app}）",
                )
            )
    return components


def _package_license_file(package_dir: Path) -> Path | None:
    """在包目录里找随带的许可证正文（只取**本目录**，不递归，避免误取依赖的许可）。"""
    if not package_dir.is_dir():
        return None
    for child in sorted(package_dir.iterdir()):
        if child.is_file() and LICENSE_FILE_PATTERN.match(child.name):
            return child
    return None


def harvest_license_texts(
    trees: list[Path], site_packages: Path, licenses_dir: Path, needed: set[str]
) -> tuple[dict[str, str], list[str]]:
    """从安装树（npm）与 Python dist-info 收集各许可证正文（原文复制）。

    返回 `{归一标识: 落盘文件名}` 与说明。已在 `licenses/` 存在的文件**不覆盖**
    （预置的 copyleft 正文优先——那些包本身往往不随带正文）。
    """
    collected: dict[str, str] = {}
    notes: list[str] = []
    for canonical in sorted(needed):
        target = licenses_dir / f"{license_text_key(canonical)}.txt"
        if target.is_file():
            collected[canonical] = target.name
            continue
        if _is_compound(canonical):
            notes.append(
                f"许可证 `{canonical}` 是**复合表达式** ⇒ 不为其单独收集正文"
                "（各分量的正文另按其本名收录，如 `Apache-2.0` / `BSD-2-Clause`）。"
            )
            continue
        candidates = list(_iter_npm_license_texts(trees, canonical)) + list(
            _iter_python_license_texts(site_packages, canonical)
        )
        found = None
        rejected: list[str] = []
        for candidate in candidates:
            body = candidate.read_text(encoding="utf-8", errors="replace")
            if _text_matches_license(body, canonical):
                found = candidate
                break
            rejected.append(f"{candidate.parent.name}/{candidate.name}")
        if found is None:
            if rejected:
                notes.append(
                    f"许可证 `{canonical}` 找到的候选文件**全部未命中该族正文特征**"
                    "（多为「指向别的文件的说明」而非正文）⇒ **不收录**，"
                    f"需人工取权威原文放入 `licenses/{license_text_key(canonical)}.txt`。"
                    f"候选：{', '.join(rejected[:3])}"
                )
            else:
                notes.append(
                    f"许可证 `{canonical}` 的正文**未能从安装树收集**（相关包未随带 LICENSE 文件）"
                    f"⇒ 需人工取权威原文放入 `licenses/{license_text_key(canonical)}.txt`。"
                )
            continue
        licenses_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(found, target)
        collected[canonical] = target.name
        notes.append(f"许可证 `{canonical}` 正文取自 `{found.parent.name}` 随带文件（已按内容特征校验）。")
    return collected, notes


def _iter_npm_license_texts(trees: list[Path], canonical: str):
    """产出 npm 侧候选正文路径（**只产出候选，是否收录由调用方按内容特征判定**）。

    为什么不能「找到第一个就收」：实测 `node-addon-system` 的 `LICENSE` 并不含 BSD-3 正文，
    若首个候选即定案，会**既收不到正文、又不再尝试后面的正常包**（BSD-3 是高频许可，代价很大）。
    """
    for tree in trees:
        if not tree.is_dir():
            continue
        for manifest in sorted(tree.rglob("package.json")):
            if "node_modules" not in manifest.parts:
                continue
            try:
                data = json.loads(manifest.read_text(encoding="utf-8", errors="replace"))
            except json.JSONDecodeError:
                continue
            declared = data.get("license")
            if isinstance(declared, dict):
                declared = declared.get("type")
            if not isinstance(declared, str) or normalize_license(declared) != canonical:
                continue
            candidate = _package_license_file(manifest.parent)
            if candidate is not None:
                yield candidate


def _iter_python_license_texts(site_packages: Path, canonical: str):
    """Python 侧候选：`dist-info/licenses/**` 与 `dist-info/LICENSE*` 两处都产出。"""
    if not site_packages.is_dir():
        return
    for dist_info in sorted(site_packages.glob("*.dist-info")):
        metadata = dist_info / "METADATA"
        if not metadata.is_file():
            continue
        if normalize_license(_python_license_field(metadata)) != canonical:
            continue
        for candidate in sorted(dist_info.rglob("*")):
            if candidate.is_file() and LICENSE_FILE_PATTERN.match(candidate.name):
                yield candidate


def _render_inventory(components: list[Component], sources: list[str]) -> list[str]:
    lines: list[str] = []
    for source in sources:
        rows = [item for item in components if item.source == source]
        if not rows:
            continue
        lines.append(f"### {source}（{len(rows)} 个）")
        lines.append("")
        lines.append("| 组件 | 版本 | 许可证（声明值） |")
        lines.append("|---|---|---|")
        for item in sorted(rows, key=lambda entry: (entry.name.lower(), entry.version)):
            lines.append(f"| `{item.name}` | {item.version} | {item.license} |")
        lines.append("")
    return lines


def render(
    *,
    components: list[Component],
    license_files: dict[str, str],
    notes: list[str],
    dsh_tree_note: str,
) -> str:
    counts = Counter(normalize_license(item.license) for item in components)
    lgpl = sorted(
        (item for item in components if "LGPL" in normalize_license(item.license)),
        key=lambda entry: entry.key,
    )
    mpl = sorted(
        (item for item in components if "MPL" in normalize_license(item.license).upper()),
        key=lambda entry: entry.key,
    )
    sources = ["应用镜像（Python）", "执行镜像（dsh / npm）"]
    sources += sorted({item.source for item in components if item.source.startswith("前端（")})

    lines: list[str] = [
        "# THIRD-PARTY-NOTICES",
        "",
        "> **本文件由脚本生成，请勿手工编辑**：`py scripts/generate_third_party_notices.py`。",
        "> 口径依据：宪法 12.3（第三方库逐个核对许可证；素材授权可追溯）与交付口径"
        "「每次升级都要重新生成 SBOM、扫描漏洞、核对许可证」。",
        "",
        "## 1. 覆盖范围与证据来源",
        "",
        "本清单覆盖以下**随交付物分发**的第三方组件，逐类写明证据来源（口径 = 锁文件 / 安装树全量，"
        "**不是**凭印象，也**不声称**等于最终镜像内的精确集合）：",
        "",
        "| 产物 | 证据来源 | 口径 |",
        "|---|---|---|",
        "| 应用镜像（app / worker / beat 共用） | `requirements.lock`（`--require-hashes` 钉死）+ 各包 `dist-info/METADATA` | 锁文件全量 |",
        f"| 执行镜像（dsh 沙箱） | {dsh_tree_note} | 安装树全量（含 optional 平台包） |",
        "| 管理台 / 伴侣端 / 桌面端 | 各自 `package-lock.json` 的 `packages` 条目 | lockfile 全量（**含 devDependencies**，保守从宽） |",
        "",
        "> **保守从宽**：npm 清单按 lockfile / 安装树全量列出（含开发依赖与平台可选包）——"
        "多列不构成违规，**漏列才构成**；因此本清单**不**声称「等于最终镜像内的精确集合」。",
        "",
        "## 2. 许可证分布（按归一后的声明值）",
        "",
        "| 许可证 | 组件数 |",
        "|---|---|",
    ]
    for license_id, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"| {license_id} | {count} |")
    lines += [
        "",
        f"**合计 {len(components)} 个组件。**",
        "",
        "## 3. 弱 copyleft（LGPL / MPL）条目与义务履行",
        "",
        "### 3.1 LGPL（强于 MPL：整库弱 copyleft）",
        "",
        f"**含 LGPL 的条目共 {len(lgpl)} 个**（真源 `docs/dsh-integration-preflight-checklist.md`"
        " §B13 / §F7.4 要求「必须包含 2 条 LGPL」；**本清单扫出 4 条**——`sharp` 生态 2 条之外，"
        "应用镜像的 `psycopg` 系列同为 LGPL，此前未登记）：",
        "",
        "| 组件 | 版本 | 许可证（声明值） | 所在产物 |",
        "|---|---|---|---|",
    ]
    for item in lgpl:
        lines.append(f"| `{item.name}` | {item.version} | {item.license} | {item.source} |")
    if not lgpl:
        lines.append("| （无） | — | — | — |")
    lines += [""]
    lines += LGPL_OBLIGATION_NOTES
    lines += [
        "",
        "### 3.2 MPL-2.0（文件级弱 copyleft）",
        "",
        f"**含 MPL 的条目共 {len(mpl)} 个**：",
        "",
        "| 组件 | 版本 | 许可证（声明值） | 所在产物 |",
        "|---|---|---|---|",
    ]
    for item in mpl:
        lines.append(f"| `{item.name}` | {item.version} | {item.license} | {item.source} |")
    if not mpl:
        lines.append("| （无） | — | — | — |")
    lines += [""]
    lines += MPL_OBLIGATION_NOTES
    lines += [
        "",
        "## 4. 组件清单",
        "",
    ]
    lines += _render_inventory(components, sources)
    lines += [
        "## 5. 许可证正文",
        "",
        "| 许可证 | 正文文件 |",
        "|---|---|",
    ]
    for license_id in sorted(license_files):
        lines.append(f"| {license_id} | [`licenses/{license_files[license_id]}`](licenses/{license_files[license_id]}) |")
    lines += [
        "",
        "> 其余许可证（MIT / Apache-2.0 / BSD / ISC 等）的正文**随各自组件包一并分发**"
        "（安装树内各包目录下的 `LICENSE*` 文件），本文件不重复抄录。",
        "",
        "## 6. 未验证与边界（不得读成已验）",
        "",
    ]
    for index, note in enumerate(notes, start=1):
        lines.append(f"{index}. {note}")
    lines += [
        "",
        "以下三项**未做**，属已知边界，**不构成「许可已全部核对」的承诺**：",
        "",
        "1. **未逐包比对「声明值与许可证正文一致」**：本清单登记的是各组件的**声明值**"
        "（`package.json` 的 `license` / `METADATA` 的许可证字段），未逐包阅读 500+ 份 LICENSE 正文做交叉核验。",
        "2. **未做「镜像内二次扫描」**：本清单扫的是**锁文件与安装树**，不是**镜像层**——"
        "执行镜像（含 dsh）尚未构建（`WORKBENCH_EXEC_IMAGE_DIGEST` 留空、仓库内无该镜像定义）"
        "⇒ 镜像内实际集合与本文清单的一致性**未验证**；镜像定义冻结后须在镜像内复跑同一扫描。",
        "3. **未评估各许可证的商标 / 专利条款**（如 Apache-2.0 §6 商标限制、BSD 的背书条款）"
        "对具体交付形态的影响；如需对外交付，建议按交付合同做一次法务复核。",
        "",
        "> 本清单**只登记核对状态与证据来源，不构成任何代码复用或采购决定**。",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="生成 THIRD-PARTY-NOTICES.md")
    parser.add_argument("--repo-root", default=".", help="仓库根目录（默认当前目录）")
    parser.add_argument("--output", default="THIRD-PARTY-NOTICES.md")
    parser.add_argument("--python-lock", default="requirements.lock")
    parser.add_argument("--site-packages", default=".venv/Lib/site-packages")
    parser.add_argument("--licenses-dir", default="licenses")
    parser.add_argument(
        "--dsh-tree",
        default="",
        help="dsh 执行镜像的 npm 安装树（`node_modules` 目录）；留空则该项标注为未扫描",
    )
    parser.add_argument(
        "--dsh-tree-label",
        default="Linux `npm ci` 安装树（dsh 执行镜像依赖）",
        help="写进产物的**可移植**来源描述（不落本机绝对路径，避免交付物含个人路径）",
    )
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    licenses_dir = (repo_root / args.licenses_dir).resolve()
    notes: list[str] = []
    trees: list[Path] = []

    components = collect_python_components(
        repo_root / args.python_lock, repo_root / args.site_packages, notes
    )
    if args.dsh_tree:
        dsh_tree = Path(args.dsh_tree).resolve()
        if not dsh_tree.is_dir():
            raise SystemExit(f"dsh 安装树不存在：{dsh_tree}（--dsh-tree 需指向 node_modules 目录）")
        trees.append(dsh_tree)
        components += collect_dsh_components(dsh_tree, notes)
        dsh_tree_note = args.dsh_tree_label
    else:
        dsh_tree_note = "**未扫描**（未提供 `--dsh-tree`）⇒ 该产物依赖**未纳入**本清单"
        notes.append(
            "执行镜像（dsh）的 npm 依赖**本轮未扫描**（未提供 `--dsh-tree`）⇒ 该产物的第三方组件"
            "**未纳入**本清单，不得读成已核。"
        )
    components += collect_frontend_components(repo_root, notes)

    missing_required = [
        name for name in REQUIRED_LICENSE_TEXTS if not (licenses_dir / f"{name}.txt").is_file()
    ]
    if missing_required:
        raise SystemExit(
            "缺少必须预置的许可证正文（fail-closed，脚本不编造正文）："
            + ", ".join(f"licenses/{name}.txt" for name in missing_required)
        )

    needed = {normalize_license(item.license) for item in components}
    license_files, harvest_notes = harvest_license_texts(
        trees, repo_root / args.site_packages, licenses_dir, needed
    )
    notes += harvest_notes
    for required in REQUIRED_LICENSE_TEXTS:
        license_files.setdefault(required, f"{required}.txt")

    output = repo_root / args.output
    output.write_text(
        render(
            components=components,
            license_files=license_files,
            notes=notes,
            dsh_tree_note=dsh_tree_note,
        ),
        encoding="utf-8",
    )
    print(f"已生成 {output}（组件 {len(components)} 个）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
