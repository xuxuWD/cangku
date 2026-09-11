"""手机伴侣 PWA 静态资产的契约校验。

本机不启动浏览器 / GUI，因此这里只做**静态文本断言**：
确认 manifest 合法、index.html 具备 PWA 必需元信息、Service Worker 不缓存任何 API 响应，
以及工程脚本与 .gitignore 就位。真实安装、离线与真机行为属于待验收项。
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PWA = ROOT / "companion-pwa"


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_manifest_is_valid_and_declares_required_fields() -> None:
    manifest = json.loads(read("companion-pwa/public/manifest.webmanifest"))

    assert manifest["name"]
    assert manifest["short_name"]
    assert manifest["start_url"]
    assert manifest["scope"]
    assert manifest["display"] == "standalone"
    assert manifest["theme_color"]
    assert manifest["lang"] == "zh-CN"


def test_manifest_declares_192_and_512_icons() -> None:
    manifest = json.loads(read("companion-pwa/public/manifest.webmanifest"))
    icons = manifest["icons"]

    assert len(icons) >= 2
    sizes = {icon["sizes"] for icon in icons}
    assert "192x192" in sizes
    assert "512x512" in sizes
    for icon in icons:
        assert icon["type"] == "image/svg+xml"


def test_icon_files_exist() -> None:
    assert (PWA / "public/icons/icon-192.svg").is_file()
    assert (PWA / "public/icons/icon-512.svg").is_file()


def test_index_html_has_pwa_metadata() -> None:
    html = read("companion-pwa/index.html")

    assert 'rel="manifest"' in html
    assert "theme-color" in html
    assert "viewport-fit=cover" in html
    assert 'lang="zh-CN"' in html
    assert "apple-touch-icon" in html


def test_service_worker_activates_and_takes_control() -> None:
    sw = read("companion-pwa/public/sw.js")

    assert "skipWaiting" in sw
    assert "clients.claim" in sw
    # 版本化缓存名，便于升级时清理旧缓存。
    assert "workbench-companion-v" in sw


def test_service_worker_never_caches_api_or_cross_origin_requests() -> None:
    sw = read("companion-pwa/public/sw.js")
    fetch_handler = sw.split("addEventListener('fetch'", 1)[1]

    # 判定依据：fetch 处理器必须在任何缓存写入之前对 /api/ 与跨源请求早退，
    # 且整个文件不存在 cache.put，fetch 处理器内不出现 cache.addAll / caches.open。
    assert "if (request.method !== 'GET') return" in fetch_handler
    assert "if (url.origin !== self.location.origin) return" in fetch_handler
    assert "if (url.pathname.startsWith('/api/')) return" in fetch_handler
    assert "/api/" in sw
    assert "cache.put" not in sw
    assert "cache.addAll" not in fetch_handler
    assert "caches.open" not in fetch_handler
    # 明确写出「绝不缓存」的注释，防止后续误改把 API 响应写进缓存。
    assert "绝不缓存" in sw


def test_package_scripts_cover_dev_build_test_preview() -> None:
    package = json.loads(read("companion-pwa/package.json"))
    scripts = package["scripts"]

    for name in ("dev", "build", "test", "preview"):
        assert name in scripts


def test_gitignore_ignores_companion_build_outputs() -> None:
    entries = {
        line.strip()
        for line in read(".gitignore").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }

    assert "companion-pwa/node_modules/" in entries
    assert "companion-pwa/dist/" in entries
