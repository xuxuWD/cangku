"""手机伴侣 PWA 静态资产的契约校验。

本机不启动浏览器 / GUI，因此这里只做**静态文本断言**：
确认 manifest 合法且声明了位图图标（含 maskable）、位图尺寸与声明一致、
index.html 具备 PWA 必需元信息、Service Worker 不缓存任何 API 响应，
以及工程脚本与 .gitignore 就位。真实安装、离线与真机行为属于待验收项。
"""

import json
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PWA = ROOT / "companion-pwa"


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def png_size(path: Path) -> tuple[int, int]:
    """读取 PNG 的 IHDR，返回 (宽, 高)，不依赖任何图像库。"""
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", f"{path.name} 不是合法 PNG"
    assert data[12:16] == b"IHDR", f"{path.name} 缺少 IHDR"
    width, height = struct.unpack(">II", data[16:24])
    return width, height


def test_manifest_is_valid_and_declares_required_fields() -> None:
    manifest = json.loads(read("companion-pwa/public/manifest.webmanifest"))

    assert manifest["name"]
    assert manifest["short_name"]
    assert manifest["start_url"]
    assert manifest["scope"]
    assert manifest["display"] == "standalone"
    assert manifest["theme_color"]
    assert manifest["lang"] == "zh-CN"


def test_manifest_declares_png_icons_with_192_512_and_maskable() -> None:
    manifest = json.loads(read("companion-pwa/public/manifest.webmanifest"))
    icons = manifest["icons"]

    # 判定依据：真机安装（尤其 Android maskable）要求位图；SVG 仅作 favicon 保留，
    # 不再作为 manifest 图标，避免平台忽略 SVG 导致图标缺失。
    assert len(icons) >= 3
    for icon in icons:
        assert icon["type"] == "image/png"

    by_size = {(icon["sizes"], icon["purpose"]) for icon in icons}
    assert ("192x192", "any") in by_size
    assert ("512x512", "any") in by_size
    assert ("512x512", "maskable") in by_size


def test_icon_files_exist() -> None:
    # SVG 作为浏览器 favicon 保留；manifest 使用的是位图 PNG。
    assert (PWA / "public/icons/icon-192.svg").is_file()
    assert (PWA / "public/icons/icon-512.svg").is_file()
    for name in ("icon-192.png", "icon-512.png", "icon-maskable-512.png", "apple-touch-icon.png"):
        assert (PWA / "public/icons" / name).is_file(), f"缺少位图图标 {name}"


def test_bitmap_icons_match_manifest_dimensions() -> None:
    # 判定依据：PNG 的实际像素尺寸必须与 manifest / apple-touch-icon 声明的尺寸一致，
    # 否则平台会按错误尺寸渲染或直接拒用。
    expected = {
        "icon-192.png": (192, 192),
        "icon-512.png": (512, 512),
        "icon-maskable-512.png": (512, 512),
        "apple-touch-icon.png": (180, 180),
    }
    for name, size in expected.items():
        assert png_size(PWA / "public/icons" / name) == size, f"{name} 尺寸不符"


def test_index_html_has_pwa_metadata() -> None:
    html = read("companion-pwa/index.html")

    assert 'rel="manifest"' in html
    assert "theme-color" in html
    assert "viewport-fit=cover" in html
    assert 'lang="zh-CN"' in html
    assert 'rel="apple-touch-icon"' in html
    # 判定依据：iOS 的 apple-touch-icon 必须指向位图 PNG。
    assert "apple-touch-icon.png" in html


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
