from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from threading import Lock
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx


ALLOWED_CONTENT_TYPES = frozenset({"text/html", "text/plain", "application/xhtml+xml"})


class ScrapeDenied(ValueError):
    """抓取被策略拒绝（白名单、robots、地址非法等）。"""


class ScrapeFailed(RuntimeError):
    """抓取过程中目标不可用或内容不可用。"""


@dataclass(frozen=True)
class ScrapePolicy:
    allowed_domains: frozenset[str]
    user_agent: str
    timeout_seconds: float = 10.0
    max_bytes: int = 2_000_000
    min_interval_seconds: float = 1.0

    def __post_init__(self) -> None:
        domains = frozenset(item.strip().lower() for item in self.allowed_domains if item and item.strip())
        if not domains:
            raise ValueError("抓取白名单不能为空")
        if not self.user_agent or not self.user_agent.strip():
            raise ValueError("User-Agent 不能为空")
        if self.timeout_seconds <= 0:
            raise ValueError("超时时间必须大于 0")
        if self.max_bytes <= 0:
            raise ValueError("最大字节数必须大于 0")
        if self.min_interval_seconds < 0:
            raise ValueError("限速间隔不能为负数")
        object.__setattr__(self, "allowed_domains", domains)
        object.__setattr__(self, "user_agent", self.user_agent.strip())


@dataclass(frozen=True)
class ScrapedDocument:
    url: str
    title: str | None
    text: str
    truncated: bool
    content_type: str | None
    fetched_at: datetime


@dataclass(frozen=True)
class ScrapeResponse:
    status_code: int
    content_type: str | None
    text: str
    truncated: bool


ScrapeTransport = Callable[[str, dict[str, str], float, int], ScrapeResponse]


def _default_transport(
    url: str, headers: dict[str, str], timeout_seconds: float, max_bytes: int
) -> ScrapeResponse:
    """默认传输层：只读、显式禁止重定向、按 max_bytes 提前中断。"""
    with httpx.stream(
        "GET", url, headers=headers, timeout=timeout_seconds, follow_redirects=False
    ) as response:
        status_code = response.status_code
        content_type = response.headers.get("content-type")
        if 300 <= status_code < 400:
            raise ScrapeFailed("目标地址发生重定向，已拒绝跳转")
        if status_code < 200 or status_code >= 300:
            return ScrapeResponse(
                status_code=status_code, content_type=content_type, text="", truncated=False
            )
        chunks: list[bytes] = []
        total = 0
        truncated = False
        for chunk in response.iter_bytes():
            if total >= max_bytes:
                truncated = True
                break
            remaining = max_bytes - total
            if len(chunk) > remaining:
                chunks.append(chunk[:remaining])
                total = max_bytes
                truncated = True
                break
            chunks.append(chunk)
            total += len(chunk)
        encoding = getattr(response, "encoding", None) or "utf-8"
        text = b"".join(chunks).decode(encoding, errors="replace")
        return ScrapeResponse(
            status_code=status_code, content_type=content_type, text=text, truncated=truncated
        )


class _TextExtractor(HTMLParser):
    """提取 <title> 与正文文本；跳过 script/style/noscript，实体反转义，折叠空白。"""

    _SKIP_TAGS = frozenset({"script", "style", "noscript"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._in_title = False
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
        elif tag == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP_TAGS:
            if self._skip_depth:
                self._skip_depth -= 1
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._in_title:
            self.title_parts.append(data)
        else:
            self.text_parts.append(data)


def _extract_text(html: str) -> tuple[str, str | None]:
    extractor = _TextExtractor()
    extractor.feed(html)
    extractor.close()
    text = " ".join("".join(extractor.text_parts).split())
    title = " ".join("".join(extractor.title_parts).split()) or None
    return text, title


class WebScraper:
    def __init__(
        self,
        policy: ScrapePolicy,
        *,
        transport: ScrapeTransport | None = None,
        robots_loader: Callable[[str], ScrapeResponse] | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.policy = policy
        self._transport = transport or _default_transport
        self.robots_loader = robots_loader or self._load_robots_from_transport
        self._clock = clock
        self._sleeper = sleeper
        self._lock = Lock()
        self._locks: dict[str, Lock] = {}
        self._last_fetch: dict[str, float] = {}

    def _headers(self) -> dict[str, str]:
        return {
            "User-Agent": self.policy.user_agent,
            "Accept": "text/html,text/plain;q=0.9,*/*;q=0.1",
        }

    def _load_robots_from_transport(self, robots_url: str) -> ScrapeResponse:
        return self._transport(
            robots_url, self._headers(), self.policy.timeout_seconds, self.policy.max_bytes
        )

    def _domain_allowed(self, host: str) -> bool:
        return any(
            host == domain or host.endswith("." + domain) for domain in self.policy.allowed_domains
        )

    def _ensure_robots_allowed(self, scheme: str, host: str, port: int | None, url: str) -> None:
        authority = host if port in (None, 80, 443) else f"{host}:{port}"
        robots_url = f"{scheme}://{authority}/robots.txt"
        try:
            response = self.robots_loader(robots_url)
        except ScrapeFailed as exc:
            raise ScrapeDenied("robots.txt 加载失败，已按 fail-closed 拒绝抓取") from exc
        except Exception as exc:  # noqa: BLE001 - 任何加载异常都按 fail-closed 拒绝
            raise ScrapeDenied("robots.txt 加载异常，已按 fail-closed 拒绝抓取") from exc
        if 400 <= response.status_code < 500:
            return
        if response.status_code < 200 or response.status_code >= 500:
            raise ScrapeDenied("robots.txt 不可用，已按 fail-closed 拒绝抓取")
        parser = RobotFileParser()
        parser.parse(response.text.splitlines())
        if not parser.can_fetch(self.policy.user_agent, url):
            raise ScrapeDenied("robots.txt 不允许抓取该地址")

    def _host_lock(self, host: str) -> Lock:
        with self._lock:
            lock = self._locks.get(host)
            if lock is None:
                lock = Lock()
                self._locks[host] = lock
            return lock

    def _throttle(self, host: str) -> None:
        if self.policy.min_interval_seconds <= 0:
            return
        with self._host_lock(host):
            last = self._last_fetch.get(host)
            if last is not None:
                wait = self.policy.min_interval_seconds - (self._clock() - last)
                if wait > 0:
                    self._sleeper(wait)
            self._last_fetch[host] = self._clock()

    @staticmethod
    def _content_type_allowed(content_type: str | None) -> bool:
        if not content_type:
            return False
        base = content_type.split(";", 1)[0].strip().lower()
        return base in ALLOWED_CONTENT_TYPES

    def fetch(self, url: str) -> ScrapedDocument:
        parsed = urlparse(url)
        scheme = (parsed.scheme or "").lower()
        if scheme not in {"http", "https"}:
            raise ScrapeDenied("仅支持 http 或 https 地址")
        if "@" in parsed.netloc:
            raise ScrapeDenied("地址不得包含用户信息")
        host = (parsed.hostname or "").lower()
        if not host or not self._domain_allowed(host):
            raise ScrapeDenied("该域名不在抓取白名单内")
        self._ensure_robots_allowed(scheme, host, parsed.port, url)
        self._throttle(host)
        response = self._transport(
            url, self._headers(), self.policy.timeout_seconds, self.policy.max_bytes
        )
        if response.status_code < 200 or response.status_code >= 300:
            raise ScrapeFailed("目标地址返回非 2xx 状态码")
        if not self._content_type_allowed(response.content_type):
            raise ScrapeFailed("目标地址内容类型不受支持")
        text, title = _extract_text(response.text)
        if not text:
            raise ScrapeFailed("未抽取到正文")
        return ScrapedDocument(
            url=url,
            title=title,
            text=text,
            truncated=response.truncated,
            content_type=response.content_type,
            fetched_at=datetime.now(UTC),
        )
