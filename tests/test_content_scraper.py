from __future__ import annotations

from threading import Lock, Thread

import pytest
from fastapi.testclient import TestClient

from app import main as main_module
from app.audit.models import AuditAction
from app.audit.service import AuditService
from app.audit.store import InMemoryAuditStore
from app.content.scraper import (
    ScrapeDenied,
    ScrapeFailed,
    ScrapePolicy,
    ScrapeResponse,
    WebScraper,
)
from app.content.service import ContentService, ScrapeNotConfigured
from app.content.store import ContentStore
from app.domain import TaskStore, UserContext
from app.runtime.service import RuntimeService


client = TestClient(main_module.app)


def policy(**overrides) -> ScrapePolicy:
    values = {"allowed_domains": frozenset({"example.com"}), "user_agent": "TestBot/0.1"}
    values.update(overrides)
    return ScrapePolicy(**values)


def robots_allow(url: str) -> ScrapeResponse:
    return ScrapeResponse(status_code=404, content_type=None, text="", truncated=False)


def robots_disallow(url: str) -> ScrapeResponse:
    return ScrapeResponse(
        status_code=200,
        content_type="text/plain",
        text="User-agent: *\nDisallow: /\n",
        truncated=False,
    )


def robots_unavailable(url: str) -> ScrapeResponse:
    return ScrapeResponse(status_code=503, content_type=None, text="", truncated=False)


def robots_raises(url: str) -> ScrapeResponse:
    raise ScrapeFailed("robots 加载异常")


class FakeTransport:
    def __init__(self, response: ScrapeResponse) -> None:
        self.response = response
        self.calls: list[tuple[str, dict[str, str], float, int]] = []

    def __call__(self, url, headers, timeout_seconds, max_bytes) -> ScrapeResponse:
        self.calls.append((url, headers, timeout_seconds, max_bytes))
        return self.response


def html_response(text: str, *, status: int = 200, content_type="text/html; charset=utf-8", truncated=False):
    return ScrapeResponse(
        status_code=status, content_type=content_type, text=text, truncated=truncated,
    )


def make_scraper(response, *, policy_obj=None, robots_loader=robots_allow, clock=None, sleeper=None):
    kwargs = {}
    if clock is not None:
        kwargs["clock"] = clock
    if sleeper is not None:
        kwargs["sleeper"] = sleeper
    return WebScraper(
        policy_obj or policy(),
        transport=FakeTransport(response),
        robots_loader=robots_loader,
        **kwargs,
    )


def actor():
    return UserContext(tenant_id="t1", user_id="u1", role="employee")


def make_service(*, scraper=None, audit=None) -> ContentService:
    task_store = TaskStore()
    return ContentService(
        task_store, RuntimeService(task_store), ContentStore(), scraper=scraper, audit=audit,
    )


def scrape_headers():
    return {"X-Tenant-Id": "scrape-tenant", "X-User-Id": "scrape-user", "X-User-Role": "employee"}


# --- 策略校验 -------------------------------------------------------------


def test_scrape_policy_requires_non_empty_domains_and_valid_numbers():
    with pytest.raises(ValueError, match="白名单"):
        ScrapePolicy(allowed_domains=frozenset(), user_agent="Bot")
    with pytest.raises(ValueError, match="白名单"):
        ScrapePolicy(allowed_domains=frozenset({"   "}), user_agent="Bot")
    with pytest.raises(ValueError, match="超时"):
        ScrapePolicy(allowed_domains=frozenset({"example.com"}), user_agent="Bot", timeout_seconds=0)
    with pytest.raises(ValueError, match="最大字节"):
        ScrapePolicy(allowed_domains=frozenset({"example.com"}), user_agent="Bot", max_bytes=0)
    with pytest.raises(ValueError, match="限速"):
        ScrapePolicy(allowed_domains=frozenset({"example.com"}), user_agent="Bot", min_interval_seconds=-1)


def test_scrape_policy_normalizes_domains():
    value = ScrapePolicy(
        allowed_domains=frozenset({" Example.COM ", "other.com"}), user_agent="  Bot  ",
    )
    assert value.allowed_domains == frozenset({"example.com", "other.com"})
    assert value.user_agent == "Bot"


# --- fetch 顺序与 fail-closed --------------------------------------------


def test_fetch_rejects_non_http_scheme_and_userinfo():
    scraper = make_scraper(html_response("<html><body>ok</body></html>"))
    with pytest.raises(ScrapeDenied):
        scraper.fetch("ftp://example.com/a")
    with pytest.raises(ScrapeDenied):
        scraper.fetch("https://user:pass@example.com/a")


def test_fetch_enforces_whitelist_with_subdomains_and_similar_domains():
    scraper = make_scraper(html_response("<html><body>ok</body></html>"))
    document = scraper.fetch("https://sub.example.com/page")
    assert document.text == "ok"
    with pytest.raises(ScrapeDenied, match="白名单"):
        scraper.fetch("https://example.com.evil.com/page")
    with pytest.raises(ScrapeDenied, match="白名单"):
        scraper.fetch("https://evil.com/page")
    with pytest.raises(ScrapeDenied, match="白名单"):
        scraper.fetch("https://notexample.com/page")


def test_robots_allows_404_and_denies_5xx_error_and_disallow():
    assert make_scraper(html_response("<html><body>ok</body></html>")).fetch(
        "https://example.com/a"
    ).text == "ok"
    with pytest.raises(ScrapeDenied):
        make_scraper(html_response("x"), robots_loader=robots_unavailable).fetch(
            "https://example.com/a"
        )
    with pytest.raises(ScrapeDenied):
        make_scraper(html_response("x"), robots_loader=robots_raises).fetch(
            "https://example.com/a"
        )
    with pytest.raises(ScrapeDenied, match="robots.txt 不允许"):
        make_scraper(html_response("x"), robots_loader=robots_disallow).fetch(
            "https://example.com/a"
        )


def test_fetch_fails_on_non_2xx_and_unsupported_content_type():
    with pytest.raises(ScrapeFailed):
        make_scraper(html_response("boom", status=500)).fetch("https://example.com/a")
    with pytest.raises(ScrapeFailed):
        make_scraper(html_response('{"a":1}', content_type="application/json")).fetch(
            "https://example.com/a"
        )


def test_fetch_fails_when_body_is_empty():
    html = "<html><head><title>只有标题</title></head><body><script>x=1</script>   </body></html>"
    with pytest.raises(ScrapeFailed, match="未抽取到正文"):
        make_scraper(html_response(html)).fetch("https://example.com/a")


# --- 正文抽取 -------------------------------------------------------------


def test_fetch_extracts_title_text_and_strips_script_style():
    html = (
        "<html><head><title>T &amp;   T2</title><style>.a{color:red}</style></head>"
        "<body><script>var x=1;</script><noscript>ns</noscript>"
        "<p>Hello   world</p>\n<p>Second &lt;line&gt;</p></body></html>"
    )
    document = make_scraper(html_response(html)).fetch("https://example.com/a")
    assert document.title == "T & T2"
    assert document.text == "Hello world Second <line>"
    assert document.content_type == "text/html; charset=utf-8"
    assert document.url == "https://example.com/a"
    assert document.truncated is False


def test_fetch_reflects_transport_truncation_flag():
    document = make_scraper(
        html_response("<html><body>abc</body></html>", truncated=True)
    ).fetch("https://example.com/a")
    assert document.truncated is True


def test_default_transport_truncates_at_max_bytes(monkeypatch):
    import app.content.scraper as scraper_module

    captured = {}

    class FakeResponse:
        status_code = 200
        headers = {"content-type": "text/html; charset=utf-8"}
        encoding = "utf-8"

        def __init__(self, chunks):
            self._chunks = chunks

        def iter_bytes(self):
            yield from self._chunks

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return False

    def fake_stream(method, url, **kwargs):
        captured["method"] = method
        captured["url"] = url
        captured["follow_redirects"] = kwargs.get("follow_redirects")
        return FakeResponse([b"abcdefgh", b"ijkl"])

    monkeypatch.setattr(scraper_module.httpx, "stream", fake_stream)
    scraper = WebScraper(policy(max_bytes=5, min_interval_seconds=0), robots_loader=robots_allow)
    document = scraper.fetch("https://example.com/a")
    assert document.text == "abcde"
    assert document.truncated is True
    assert captured["method"] == "GET"
    assert captured["follow_redirects"] is False


def test_default_transport_rejects_redirects(monkeypatch):
    import app.content.scraper as scraper_module

    class FakeResponse:
        status_code = 302
        headers = {"location": "https://evil.com/x"}
        encoding = "utf-8"

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return False

        def iter_bytes(self):
            return iter(())

    monkeypatch.setattr(
        scraper_module.httpx, "stream",
        lambda method, url, **kwargs: FakeResponse(),
    )
    scraper = WebScraper(policy(min_interval_seconds=0), robots_loader=robots_allow)
    with pytest.raises(ScrapeFailed):
        scraper.fetch("https://example.com/a")


# --- 限速 -----------------------------------------------------------------


def test_rate_limit_waits_for_same_host_only():
    sleeps: list[float] = []
    clock = {"t": 100.0}

    def now() -> float:
        return clock["t"]

    def sleeper(seconds: float) -> None:
        sleeps.append(seconds)
        clock["t"] += seconds

    scraper = WebScraper(
        policy(allowed_domains=frozenset({"example.com", "other.com"}), min_interval_seconds=1.0),
        transport=FakeTransport(html_response("<html><body>ok</body></html>")),
        robots_loader=robots_allow,
        clock=now,
        sleeper=sleeper,
    )
    scraper.fetch("https://example.com/a")
    assert sleeps == []
    scraper.fetch("https://example.com/b")
    assert len(sleeps) == 1
    assert sleeps[0] == pytest.approx(1.0)
    scraper.fetch("https://other.com/a")
    assert len(sleeps) == 1


def test_rate_limit_is_thread_safe_per_host():
    sleeps: list[float] = []
    clock = {"t": 100.0}
    guard = Lock()

    def now() -> float:
        with guard:
            return clock["t"]

    def sleeper(seconds: float) -> None:
        with guard:
            sleeps.append(seconds)
            clock["t"] += seconds

    scraper = WebScraper(
        policy(allowed_domains=frozenset({"example.com", "other.com"}), min_interval_seconds=1.0),
        transport=FakeTransport(html_response("<html><body>ok</body></html>")),
        robots_loader=robots_allow,
        clock=now,
        sleeper=sleeper,
    )
    errors: list[Exception] = []

    def worker(url: str) -> None:
        try:
            scraper.fetch(url)
        except Exception as exc:  # pragma: no cover - 并发断言失败时用于定位
            errors.append(exc)

    threads = [Thread(target=worker, args=(f"https://example.com/{index}",)) for index in range(4)]
    threads += [Thread(target=worker, args=(f"https://other.com/{index}",)) for index in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert len(sleeps) == 6
    assert scraper._locks  # 每 host 一把锁，保证同域串行、跨域互不阻塞


# --- 服务层留痕 -----------------------------------------------------------


def test_service_records_audit_for_fetched_denied_and_failed():
    store = InMemoryAuditStore()
    audit = AuditService(store)
    service = make_service(
        scraper=make_scraper(html_response("<html><body>ok</body></html>")), audit=audit,
    )
    document = service.scrape_source(actor(), "https://example.com/a")
    assert document.text == "ok"
    assert store.list_recent("t1")[-1].action == AuditAction.CONTENT_SOURCE_SCRAPED
    assert store.list_recent("t1")[-1].detail == {"domain": "example.com", "status": "fetched"}

    with pytest.raises(ScrapeDenied):
        service.scrape_source(actor(), "https://evil.com/a")
    assert store.list_recent("t1")[-1].detail == {"domain": "evil.com", "status": "denied"}

    failing = make_service(
        scraper=make_scraper(html_response("boom", status=500)), audit=audit,
    )
    with pytest.raises(ScrapeFailed):
        failing.scrape_source(actor(), "https://example.com/a")
    assert store.list_recent("t1")[-1].detail == {"domain": "example.com", "status": "failed"}


def test_service_scrape_requires_configuration():
    service = make_service(scraper=None)
    with pytest.raises(ScrapeNotConfigured):
        service.scrape_source(actor(), "https://example.com/a")


# --- 接口 -----------------------------------------------------------------


def test_scrape_endpoint_returns_503_when_not_configured(monkeypatch):
    monkeypatch.setattr(main_module.content_service, "scraper", None)
    response = client.post(
        "/api/v1/content-sources/scrape",
        headers=scrape_headers(),
        json={"url": "https://example.com/a"},
    )
    assert response.status_code == 503
    assert "未配置抓取白名单" in response.json()["detail"]


def test_scrape_endpoint_returns_document(monkeypatch):
    monkeypatch.setattr(
        main_module.content_service,
        "scraper",
        make_scraper(html_response("<html><head><title>标题</title></head><body>正文</body></html>")),
    )
    response = client.post(
        "/api/v1/content-sources/scrape",
        headers=scrape_headers(),
        json={"url": "https://example.com/article"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["url"] == "https://example.com/article"
    assert body["title"] == "标题"
    assert body["text"] == "正文"
    assert body["truncated"] is False
    assert body["content_type"] == "text/html; charset=utf-8"
    assert body["fetched_at"]


def test_scrape_endpoint_maps_denied_and_failed(monkeypatch):
    monkeypatch.setattr(main_module.content_service, "scraper", make_scraper(html_response("x")))
    denied = client.post(
        "/api/v1/content-sources/scrape",
        headers=scrape_headers(),
        json={"url": "https://evil.com/a"},
    )
    assert denied.status_code == 403

    monkeypatch.setattr(
        main_module.content_service, "scraper", make_scraper(html_response("boom", status=500))
    )
    failed = client.post(
        "/api/v1/content-sources/scrape",
        headers=scrape_headers(),
        json={"url": "https://example.com/a"},
    )
    assert failed.status_code == 502
    assert failed.json()["detail"] == "抓取失败"


def test_scrape_endpoint_rejects_invalid_body():
    too_long = client.post(
        "/api/v1/content-sources/scrape",
        headers=scrape_headers(),
        json={"url": "https://example.com/" + "a" * 2048},
    )
    assert too_long.status_code == 422
    missing = client.post(
        "/api/v1/content-sources/scrape", headers=scrape_headers(), json={},
    )
    assert missing.status_code == 422
    extra = client.post(
        "/api/v1/content-sources/scrape",
        headers=scrape_headers(),
        json={"url": "https://example.com/a", "extra": 1},
    )
    assert extra.status_code == 422
