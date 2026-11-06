"""Wikipedia through the fetcher's rules (Phase 12), on a mock transport: no network."""

from __future__ import annotations

import httpx
import pytest

from lazis.providers.web import wikipedia
from lazis.providers.web.guard import EgressRefused
from tests.research_support import FakeWiki


def _fetcher(handler: httpx.MockTransport) -> wikipedia.Fetcher:
    return wikipedia.Fetcher(transport=handler)


def test_research_reads_the_top_pages_and_sends_only_the_query() -> None:
    wiki = FakeWiki()
    pages = wikipedia.research("Ankara nüfusu", wiki.fetcher())
    assert [p.title for p in pages] == ["Ankara", "Ankara Kalesi"]
    assert pages[0].url == "https://tr.wikipedia.org/wiki/Ankara" and pages[0].lang == "tr"
    assert "5,8 milyon" in pages[0].text
    first = wiki.requests[0]
    assert first.url.host == "tr.wikipedia.org" and first.url.params["srsearch"] == "Ankara nüfusu"
    assert first.headers["user-agent"] == wikipedia.USER_AGENT
    assert "cookie" not in first.headers
    assert all(r.url.scheme == "https" for r in wiki.requests)


def test_english_when_turkish_finds_nothing() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.host)
        if request.url.params.get("list") == "search":
            hits = [{"title": "Ankara"}] if request.url.host.startswith("en.") else []
            return httpx.Response(200, json={"query": {"search": hits}})
        return httpx.Response(
            200, json={"query": {"pages": [{"title": "Ankara", "extract": "Capital."}]}}
        )

    pages = wikipedia.research("Ankara", _fetcher(httpx.MockTransport(handler)))
    assert (
        seen[0].startswith("tr.")
        and pages[0].lang == "en"
        and pages[0].url.startswith("https://en.")
    )


def _refused(handler: httpx.MockTransport) -> str:
    with pytest.raises(EgressRefused) as caught:
        _fetcher(handler).get_json("https://tr.wikipedia.org/w/api.php")
    return caught.value.code


@pytest.mark.parametrize(
    ("location", "code"),
    [
        ("https://evil.example/steal", "url_host_not_allowed"),
        ("http://tr.wikipedia.org/w/api.php", "url_scheme"),
        ("https://127.0.0.1/admin", "url_ip_literal"),
        ("file:///etc/passwd", "url_scheme"),
    ],
)
def test_redirects_are_checked_at_every_hop(location: str, code: str) -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(302, headers={"location": location}))
    assert _refused(transport) == code


def test_a_redirect_loop_stops() -> None:
    transport = httpx.MockTransport(
        lambda r: httpx.Response(302, headers={"location": "https://en.wikipedia.org/w/api.php"})
    )
    assert _refused(transport) == "redirects"


def test_an_allowed_redirect_is_followed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "tr.wikipedia.org":
            return httpx.Response(301, headers={"location": "https://en.wikipedia.org/w/api.php"})
        return httpx.Response(200, json={"ok": 1})

    assert _fetcher(httpx.MockTransport(handler)).get_json(
        "https://tr.wikipedia.org/w/api.php"
    ) == {"ok": 1}


@pytest.mark.parametrize(
    ("response", "code"),
    [
        (httpx.Response(500, json={}), "http_status"),
        (httpx.Response(200, text="<html>x</html>", headers={"content-type": "text/html"}), "content_type"),
        (httpx.Response(200, content=b"{" + b" " * (wikipedia.MAX_RESPONSE_BYTES + 10) + b"}",
                        headers={"content-type": "application/json"}), "too_large"),
        (httpx.Response(200, content=b"not json", headers={"content-type": "application/json"}),
         "bad_response"),
    ],
)  # fmt: skip
def test_bad_responses(response: httpx.Response, code: str) -> None:
    assert _refused(httpx.MockTransport(lambda r: response)) == code


def test_network_errors_have_codes() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("slow", request=request)

    def refused(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    assert _refused(httpx.MockTransport(timeout)) == "timeout"
    assert _refused(httpx.MockTransport(refused)) == "network"


def test_the_deadline_holds() -> None:
    fetcher = wikipedia.Fetcher(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})),
                                deadline=0)  # fmt: skip
    with pytest.raises(EgressRefused) as caught:
        fetcher.get_json("https://tr.wikipedia.org/w/api.php")
    assert caught.value.code == "timeout"
