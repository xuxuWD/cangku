"""网页管理台与手机伴侣端的依赖必须精确锁定。

背景：两个前端的 `package.json` 曾把全部依赖写成 `"latest"`，只有 `package-lock.json`
兜底——任何人执行 `npm install` 都会把依赖漂移到最新版，与 CI 中 `npm ci` 解析出的版本
不一致（可复现性被破坏）。本测试同时防两种漂移：

1. `package.json` 出现范围符（`^` / `~` / `latest` / `*`）；
2. `package.json` 与 lockfile 实际解析版本不一致（改了却忘记同步 lock）。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECTS = ("admin-web", "companion-pwa")
EXACT_VERSION = re.compile(r"\d+\.\d+\.\d+")


def read_json(relative: str) -> dict:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def test_frontend_dependencies_are_pinned_to_the_lockfile_versions() -> None:
    for project in PROJECTS:
        package = read_json(f"{project}/package.json")
        lock = read_json(f"{project}/package-lock.json")
        locked = lock.get("packages", {})

        for section in ("dependencies", "devDependencies"):
            declared = package.get(section) or {}
            assert declared, f"{project} 缺少 {section}"

            for name, spec in declared.items():
                # 判定依据：必须是精确版本，禁止 ^ / ~ / latest / * 等范围写法。
                assert EXACT_VERSION.fullmatch(spec), (
                    f"{project} {section} 的 {name} 未精确锁定：{spec}"
                )
                resolved = (locked.get(f"node_modules/{name}") or {}).get("version")
                # 判定依据：声明版本必须等于 lockfile 实际解析版本，否则 npm ci 与
                # npm install 会得到不同结果。
                assert resolved == spec, (
                    f"{project} 的 {name} 声明为 {spec}，lockfile 解析为 {resolved}"
                )
