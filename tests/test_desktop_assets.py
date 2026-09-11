"""Windows 桌面端（Electron 安全壳）静态资产的契约校验。

本机没有 Electron 运行时、没有代码签名证书，也无法启动 GUI，因此这里只做
**静态文本断言**：确认壳工程具备安全基线、打包配置就位、自动更新按配置 fail-closed 启用。
真实安装包构建、代码签名、公证与干净电脑测试（宪法 2.5）均属于未验收项；
自动更新的「旧版→新版」实跑同样属于未验收项。
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


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


def test_package_json_pins_all_dependencies() -> None:
    package = json.loads(read("desktop/package.json"))

    # 判定依据：自动更新依赖必须精确锁定（不得用 ^ / ~ / latest），
    # 且升级渠道来自 electron-updater 这一条运行时依赖。
    assert package["dependencies"]["electron-updater"] == "6.8.9"
    for name, version in package["dependencies"].items():
        assert re.fullmatch(r"\d+\.\d+\.\d+", version), f"{name} 未精确锁版本：{version}"
    for name, version in package["devDependencies"].items():
        assert re.fullmatch(r"\d+\.\d+\.\d+", version), f"{name} 未精确锁版本：{version}"


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

    # 判定依据：自动更新的发布源必须由环境变量注入，不得写死地址或密钥。
    assert "publish:" in content
    assert "provider: generic" in content
    assert "${env.WORKBENCH_DESKTOP_UPDATE_URL}" in content


def test_config_module_resolves_update_options_fail_closed() -> None:
    content = read("desktop/src/config.cjs")

    # 判定依据：更新策略必须在纯函数里解析，且 fail-closed 依赖 HTTPS 与频道白名单；
    # 未配置更新源时必须能返回关闭状态。
    for expected in (
        "resolveUpdateOptions",
        "UPDATE_CHANNELS",
        "enabled: false",
        "parsed.protocol !== 'https:'",
    ):
        assert expected in content, f"config.cjs 缺少更新策略项 {expected}"


def test_main_process_wires_auto_update_fail_closed() -> None:
    content = read("desktop/src/main.cjs")

    # 判定依据：主进程必须按配置启用自动更新——未启用时早退且不加载依赖，
    # 启用时延迟 require 并在 electron-updater 上设置源/频道/下载策略。
    assert "setupAutoUpdate" in content
    assert "if (!UPDATE_OPTIONS.enabled)" in content
    assert "require('electron-updater')" in content
    assert "autoUpdater.setFeedURL" in content
    assert "autoUpdater.checkForUpdates" in content
    assert "autoUpdater.autoDownload" in content
    # 更新失败不得让应用崩溃：必须有错误处理分支。
    assert "自动更新失败" in content

    # 判定依据：自动更新不得改动任何渲染进程安全策略。
    assert "nodeIntegration: true" not in content
    assert "contextIsolation: false" not in content


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
