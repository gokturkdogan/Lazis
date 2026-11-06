"""Search and page text from Wikipedia (Phase 12, first provider).

Wikipedia's public API needs no key and no account, is free and is meant for programs. Turkish
first, English when Turkish finds nothing. One research request makes at most two searches and
three page reads, within one deadline. Every request goes through :func:`.guard.check_url`
(redirects included, re-checked per hop), with no cookies, a fixed User-Agent that names the
program but nobody, connect/read timeouts and a size cap on every response.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, cast
from urllib.parse import quote, urljoin

import httpx

from lazis.providers.web.guard import ALLOWED_HOSTS, EgressRefused, check_url

USER_AGENT = "LAZIS/0.1 (local personal assistant)"
MAX_RESPONSE_BYTES = 2_000_000
MAX_PAGE_CHARS = 20_000
MAX_REDIRECTS = 3
MAX_RESULTS = 3
MAX_PAGES = 3
DEADLINE_SECONDS = 20.0
LANGS = ("tr", "en")


@dataclass(frozen=True)
class Page:
    title: str
    url: str
    lang: str
    text: str


class Fetcher:
    """GET JSON from allowlisted hosts. ``transport`` is for tests (no network)."""

    def __init__(
        self,
        transport: httpx.BaseTransport | None = None,
        *,
        hosts: frozenset[str] = ALLOWED_HOSTS,
        deadline: float = DEADLINE_SECONDS,
    ) -> None:
        self._transport = transport
        self._hosts = hosts
        self._until = time.monotonic() + deadline

    def _left(self) -> float:
        left = self._until - time.monotonic()
        if left <= 0:
            raise EgressRefused("timeout")
        return left

    def get_json(self, url: str, params: dict[str, str] | None = None) -> Any:
        timeout = httpx.Timeout(min(10.0, self._left()), connect=min(5.0, self._left()))
        with httpx.Client(
            transport=self._transport,
            timeout=timeout,
            follow_redirects=False,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            trust_env=False,  # no proxy or netrc from the environment
        ) as client:
            for _ in range(MAX_REDIRECTS + 1):
                check_url(url, self._hosts)
                request = client.build_request("GET", url, params=params)
                check_url(str(request.url), self._hosts)
                try:
                    response = client.send(request, stream=True)
                except httpx.TimeoutException:
                    raise EgressRefused("timeout") from None
                except httpx.HTTPError:
                    raise EgressRefused("network") from None
                try:
                    if response.is_redirect:
                        url, params = urljoin(str(request.url), response.headers["location"]), None
                        continue
                    if response.status_code != 200:
                        raise EgressRefused("http_status")
                    kind = response.headers.get("content-type", "").split(";", 1)[0].strip()
                    if kind != "application/json":
                        raise EgressRefused("content_type")
                    body = bytearray()
                    try:
                        for chunk in response.iter_bytes():
                            body += chunk
                            if len(body) > MAX_RESPONSE_BYTES:
                                raise EgressRefused("too_large")
                            self._left()
                    except httpx.TimeoutException:
                        raise EgressRefused("timeout") from None
                    except httpx.HTTPError:
                        raise EgressRefused("network") from None
                finally:
                    response.close()
                try:
                    return json.loads(bytes(body))
                except ValueError:
                    raise EgressRefused("bad_response") from None
            raise EgressRefused("redirects")


def _api(lang: str) -> str:
    return f"https://{lang}.wikipedia.org/w/api.php"


def _page_url(lang: str, title: str) -> str:
    return f"https://{lang}.wikipedia.org/wiki/{quote(title.replace(' ', '_'), safe='')}"


def _records(data: object, *path: str) -> list[dict[str, object]]:
    """The list of objects at ``path`` in a JSON reply; empty when the shape is unexpected."""
    node: object = data
    for key in path:
        node = cast(dict[str, object], node).get(key) if isinstance(node, dict) else None
    items = cast(list[object], node) if isinstance(node, list) else []
    return [cast(dict[str, object], x) for x in items if isinstance(x, dict)]


def search(fetcher: Fetcher, lang: str, query: str, limit: int = MAX_RESULTS) -> list[str]:
    """Titles of the best matching articles."""
    data = fetcher.get_json(
        _api(lang),
        {"action": "query", "list": "search", "srsearch": query, "srlimit": str(limit),
         "srprop": "", "format": "json", "formatversion": "2", "utf8": "1"},
    )  # fmt: skip
    titles = [h.get("title") for h in _records(data, "query", "search")]
    return [t for t in titles if isinstance(t, str) and t][:limit]


def page(fetcher: Fetcher, lang: str, title: str) -> Page | None:
    """The plain text of one article (no HTML is parsed)."""
    data = fetcher.get_json(
        _api(lang),
        {"action": "query", "prop": "extracts", "explaintext": "1", "exsectionformat": "plain",
         "redirects": "1", "titles": title, "format": "json", "formatversion": "2"},
    )  # fmt: skip
    for p in _records(data, "query", "pages"):
        extract, real = p.get("extract"), p.get("title")
        if isinstance(extract, str) and extract:
            name = real if isinstance(real, str) and real else title
            return Page(name, _page_url(lang, name), lang, extract[:MAX_PAGE_CHARS])
    return None


def research(query: str, fetcher: Fetcher) -> list[Page]:
    """Search Turkish Wikipedia, then English if nothing was found; read the top pages."""
    for lang in LANGS:
        titles = search(fetcher, lang, query)
        if not titles:
            continue
        pages = [p for t in titles[:MAX_PAGES] if (p := page(fetcher, lang, t)) is not None]
        if pages:
            return pages
    return []
