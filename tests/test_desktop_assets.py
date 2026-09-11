"""Windows 桌面端（Electron 安全壳）静态资产的契约校验。

本机没有 Electron 运行时、没有代码签名证书，也无法启动 GUI，因此这里只做
**静态文本断言**：确认壳工程具备安全基线、打包配置就位、且没有引入自动更新。
真实安装包构建、代码签名、公证与干净电脑测试（宪法 2.5）均属于未验收项。
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESKTOP = ROOT / "desktop"

# 打包/依赖/内置产物产生的目录不属于我们维护的源码，扫描时排除。
EXCLUDED_DIRS = {"node_modules", "release", "web"}


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def desktop_files() -> list[Path]:
    return [
        path
        for path in DESKTOP.rglob("*")
        if path.is_file() and not EXCLUDED_DIRS.intersection(path.relative_to(DESKTOP).parts)
    ]


def test_package_json_declares_entry_and_scripts() -> None:
    package = json.loads(read("desktop/package.json"))

    # 判定依据：主进程入口必须指向 src/main.cjs（CommonJS 壳），脚本需覆盖
    # 开发启动、零依赖测试、内置产物复制与打包四类动作。
    assert package["name"] == "company-workbench-desktop"
    assert package["private"] is True
    assert package["main"] == "src/main.cjs"
    assert "type" not in package

    scripts = package["scripts"]
    for name in ("start", "test", "copy:web", "pack", "dist"):
        assert name in scripts, f"package.json 缺少脚本 {name}"

    assert scripts["test"] == "node --test"


def test_package_json_has_no_auto_update_dependency() -> None:
    package = json.loads(read("desktop/package.json"))

    # 判定依据：本工程明确不含自动更新，不得出现 electron-updater。
    assert "electron-updater" not in json.dumps(package)


def test_config_module_freezes_web_security_baseline() -> None:
    content = read("desktop/src/config.cjs")

    for expected in (
        "contextIsolation: true",
        "nodeIntegration: false",
        "sandbox: true",
        "webSecurity: true",
        "allowRunningInsecureContent: false",
    ):
        assert expected in content, f"config.cjs 缺少安全项 {expected}"


def test_main_process_guards_navigation_and_windows() -> None:
    content = read("desktop/src/main.cjs")

    # 判定依据：外链交给系统浏览器（deny 新窗口）、导航白名单拦截、
    # 单实例锁、禁止 webview 挂载，四项缺一不可。
    for expected in (
        "setWindowOpenHandler",
        "action: 'deny'",
        "will-navigate",
        "preventDefault",
        "requestSingleInstanceLock",
        "will-attach-webview",
    ):
        assert expected in content, f"main.cjs 缺少 {expected}"

    # 禁止开启 nodeIntegration。
    assert "nodeIntegration: true" not in content


def test_preload_exposes_only_frozen_metadata() -> None:
    content = read("desktop/src/preload.cjs")

    assert "contextBridge.exposeInMainWorld" in content

    # 判定依据：预加载脚本不得向渲染进程透出任何 Node 能力。
    for forbidden in (
        "ipcRenderer",
        "child_process",
        "require('fs')",
        'require("fs")',
        "remote",
    ):
        assert forbidden not in content, f"preload.cjs 不应出现 {forbidden}"


def test_electron_builder_config_is_safe_and_unsigned() -> None:
    content = read("desktop/electron-builder.yml")

    for expected in ("appId", "asar: true", "nsis", "target"):
        assert expected in content, f"electron-builder.yml 缺少 {expected}"

    # 判定依据：必须用中文注释如实说明「未配置代码签名」，避免被误读为已可发布。
    assert "未配置代码签名" in content


def test_desktop_tree_has_no_auto_updater_code() -> None:
    offenders = []

    # 判定依据：整个 desktop/ 源码树不得出现 autoUpdater 字符串。
    for path in desktop_files():
        if "autoUpdater" in path.read_text(encoding="utf-8", errors="ignore"):
            offenders.append(str(path.relative_to(ROOT)))

    assert offenders == []


def test_readme_states_signing_is_not_accepted() -> None:
    content = read("desktop/README.md")

    # 判定依据：README 必须如实标注签名/公证尚未完成，属未验收项。
    assert "未验收" in content or "未签名" in content


def test_gitignore_ignores_desktop_build_outputs() -> None:
    entries = {
        line.strip()
        for line in read(".gitignore").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }

    assert "desktop/node_modules/" in entries
    assert "desktop/release/" in entries
    assert "desktop/web/" in entries
