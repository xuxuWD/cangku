"""`THIRD-PARTY-NOTICES.md` 与许可证正文的守护测试（C 项交付物）。

**为什么需要**（宪法 12.3 + 交付口径「每次升级都要重新生成 SBOM、核对许可证」）：
`THIRD-PARTY-NOTICES` 是一份**合规交付物**，它的价值完全取决于「内容是否真的覆盖了随产物分发的
组件」与「LGPL 义务三项是否真的写进去了」。没有守护时，下一次依赖升级必然让它静默过期——
这正是本仓反复出现过的漂移形态（挂在文档里的承诺没人守）。

本文件守护四件事：
  1. 产物存在且**由脚本生成**（带生成标记，防止有人手改后与脚本脱节）；
  2. **LGPL 义务三项齐备**（许可正文引用 / 可重链接说明 / 源码获取途径）——
     真源 `docs/dsh-integration-preflight-checklist.md` §B13 / §F7.4 要求「必须包含 2 条 LGPL」；
  3. **清单覆盖锁文件**：`requirements.lock` 的每个 Python 包、三个前端的每个 npm 包都在清单里；
  4. **copyleft 正文预置缺失时 fail-closed**（脚本必须报错退出，**不得**编造或静默跳过）。

**边界（不构成承诺）**：本文件**不**校验「声明值与许可证正文一致」，也**不**校验镜像内集合
（执行镜像尚未构建）——那两项在产物 §6 里已如实登记为未验证。
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
NOTICES = REPO_ROOT / "THIRD-PARTY-NOTICES.md"
SCRIPT = REPO_ROOT / "scripts" / "generate_third_party_notices.py"
LICENSES_DIR = REPO_ROOT / "licenses"

sys.path.insert(0, str(REPO_ROOT / "scripts"))

import generate_third_party_notices as generator  # noqa: E402


def _notices_text() -> str:
    assert NOTICES.is_file(), "缺少 THIRD-PARTY-NOTICES.md（应运行 scripts/generate_third_party_notices.py）"
    return NOTICES.read_text(encoding="utf-8")


def test_notices_is_generated_by_the_script():
    """产物必须带「脚本生成、勿手工编辑」标记 ⇒ 防止手改后与脚本脱节。"""
    text = _notices_text()
    assert "本文件由脚本生成，请勿手工编辑" in text
    assert "scripts/generate_third_party_notices.py" in text


def _section(text: str, heading: str) -> str:
    """取出 `## <heading>` 到下一个 `## ` 之间的正文（按标题前缀匹配，避免措辞微调即失效）。"""
    pattern = re.compile(
        rf"^##\s*\d+\.\s*{re.escape(heading)}.*?$(.*?)(?=^##\s*\d+\.|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    assert match, f"未找到章节：{heading}"
    return match.group(1)


def test_notices_discharges_lgpl_obligations():
    """LGPL 义务三项：许可正文引用 + 可重链接 + 源码获取途径。"""
    lgpl_section = _section(_notices_text(), "弱 copyleft")

    # ① 真源要求「必须包含 2 条 LGPL」——逐条列出，且不少于 2 条。
    rows = [line for line in lgpl_section.splitlines() if line.startswith("| `")]
    assert len(rows) >= 2, f"LGPL 条目不足 2 条：{rows}"
    assert any("@img/sharp-libvips" in row and "LGPL-3.0-or-later" in row for row in rows)
    assert any("sharp-wasm32" in row for row in rows)
    # 本清单扫出的 psycopg 两条（此前未登记）也必须在列——漏登记即回归。
    assert any("psycopg-binary" in row for row in rows)
    assert any("psycopg-pool" in row for row in rows)

    # ② 三项义务逐一落地（缺任一项即视为未履行）。
    assert "licenses/LGPL-3.0.txt" in lgpl_section
    assert "licenses/GPL-3.0.txt" in lgpl_section
    assert "可重链接" in lgpl_section
    assert "源码获取途径" in lgpl_section


def test_license_texts_are_present_and_authentic():
    """copyleft 正文必须预置且是**权威原文**（校验首行特征，防止放错文件或放占位符）。"""
    lgpl = (LICENSES_DIR / "LGPL-3.0.txt").read_text(encoding="utf-8")
    gpl = (LICENSES_DIR / "GPL-3.0.txt").read_text(encoding="utf-8")
    assert lgpl.lstrip().startswith("GNU LESSER GENERAL PUBLIC LICENSE")
    assert "Version 3, 29 June 2007" in lgpl
    assert gpl.lstrip().startswith("GNU GENERAL PUBLIC LICENSE")
    assert "Version 3, 29 June 2007" in gpl
    # 长度下限：防止用「一句话引用」冒充全文。
    assert len(lgpl) > 5000 and len(gpl) > 30000


def test_notices_lists_every_locked_python_package():
    """清单必须覆盖 `requirements.lock` 的每个包（口径 = 锁文件全量）。"""
    text = _notices_text()
    locked = generator.read_python_lock(REPO_ROOT / "requirements.lock")
    assert len(locked) >= 40, f"锁文件解析结果异常：{len(locked)} 个包"
    missing = [name for name, _ in locked if f"| `{name}` |" not in text]
    # 允许「本机未安装 dist-info」的包被如实登记为未取证，但**必须在未验证段点名**。
    unresolved = [
        name
        for name in missing
        if name not in text or "未找到 dist-info" not in text
    ]
    assert unresolved == [], f"锁文件里的包未进清单、也未登记未取证：{unresolved}"


def test_notices_lists_every_frontend_lock_entry():
    """三个前端的 npm 清单必须逐条进清单（lockfile 全量，保守从宽）。"""
    text = _notices_text()
    for app in ("admin-web", "companion-pwa", "desktop"):
        lock = json.loads((REPO_ROOT / app / "package-lock.json").read_text(encoding="utf-8"))
        entries = {
            path[len("node_modules/") :]: str(entry.get("version") or "")
            for path, entry in (lock.get("packages") or {}).items()
            if path.startswith("node_modules/") and entry.get("version")
        }
        assert entries, f"{app} 的 lock 解析结果为空"
        missing = [name for name, version in entries.items() if f"| `{name}` | {version} |" not in text]
        assert missing == [], f"{app} 有 {len(missing)} 个 npm 包未进清单，例如 {missing[:3]}"


def test_generator_fails_closed_without_required_copyleft_text(tmp_path: Path):
    """copyleft 正文缺失时必须**报错退出**，绝不静默生成一份没有正文的清单。"""
    empty_licenses = tmp_path / "licenses"
    empty_licenses.mkdir()
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--repo-root",
            str(REPO_ROOT),
            "--output",
            str(tmp_path / "out.md"),
            "--licenses-dir",
            str(empty_licenses),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert result.returncode != 0, "缺少 LGPL/GPL 正文时脚本竟然成功退出（fail-open）"
    assert "LGPL-3.0.txt" in (result.stdout + result.stderr)
    assert not (tmp_path / "out.md").exists(), "fail-closed 时不应产出半成品清单"


def test_normalize_license_does_not_guess_unknown_values():
    """归一**只做分组**：未知写法原样保留，空值标「未声明」——不猜测、不改写事实。"""
    assert generator.normalize_license("MIT") == "MIT"
    assert generator.normalize_license("Apache-2.0") == "Apache-2.0"
    assert generator.normalize_license("Apache-2.0 AND LGPL-3.0-or-later AND MIT") == (
        "Apache-2.0 AND LGPL-3.0-or-later AND MIT"
    )
    assert generator.normalize_license("") == "(未声明)"
    assert generator.normalize_license("SEE LICENSE IN LICENSE.txt") == "SEE LICENSE IN LICENSE.txt"


def test_licenses_directory_only_contains_referenced_texts():
    """`licenses/` 里不得留未被清单引用的散落文件（避免「放了但没写进清单」）。"""
    text = _notices_text()
    for path in sorted(LICENSES_DIR.glob("*.txt")):
        assert re.search(rf"licenses/{re.escape(path.name)}", text), (
            f"{path.name} 未被 THIRD-PARTY-NOTICES.md 引用"
        )


@pytest.mark.parametrize("name", ["LGPL-3.0.txt", "GPL-3.0.txt", "MPL-2.0.txt"])
def test_required_texts_are_not_placeholders(name: str):
    """正文里不得出现「待补 / TODO / 占位」一类字样（防占位符冒充全文）。"""
    body = (LICENSES_DIR / name).read_text(encoding="utf-8")
    for marker in ("TODO", "待补", "占位", "PLACEHOLDER"):
        assert marker not in body, f"{name} 含占位标记 {marker}"


def test_collected_texts_are_not_mere_pointers():
    """`licenses/` 里不得混入「指向别的文件的说明」——那比不收更糟（读者会以为义务已履行）。

    实测反例（2026-09-19）：`cryptography` 的 `LICENSE` 只有 197 字节，内容是
    「本软件按 LICENSE.APACHE 或 LICENSE.BSD 之一授权」的**指路说明**。
    本用例按「体积下限 + 必须出现许可惯用语」两道闸门拦住这类文件。
    """
    for path in sorted(LICENSES_DIR.glob("*.txt")):
        body = path.read_text(encoding="utf-8", errors="replace")
        assert len(body) >= 500, f"{path.name} 仅 {len(body)} 字节，疑似「指路说明」而非正文"
        assert re.search(
            r"(Permission is hereby granted|Redistribution and use in source and binary forms|"
            r"GENERAL PUBLIC LICENSE|Apache License|Mozilla Public License|"
            r"Permission to use, copy, modify|free and unencumbered software)",
            body,
        ), f"{path.name} 未出现任何许可惯用语，疑似非正文"
