"""A fake Wikipedia behind the real research helper, on a real Unix socket (Phase 12 tests).
Nothing here touches the network: httpx.MockTransport answers every request."""

from __future__ import annotations

import json
import shutil
import tempfile
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from lazis.providers.web import helper, wikipedia

ARTICLES = {
    "Ankara": "Ankara, Türkiye'nin başkentidir.\n\nNüfusu yaklaşık 5,8 milyondur.",
    "Ankara Kalesi": "Ankara Kalesi şehrin en eski yapılarından biridir.",
}


@dataclass
class FakeWiki:
    articles: dict[str, str] = field(default_factory=lambda: dict(ARTICLES))
    requests: list[httpx.Request] = field(default_factory=list[httpx.Request])

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        params = request.url.params
        if params.get("list") == "search":
            hits = [{"title": t} for t in self.articles if params["srsearch"].split()[0] in t]
            body: object = {"query": {"search": hits}}
        else:
            title = params["titles"]
            body = {"query": {"pages": [{"title": title, "extract": self.articles.get(title, "")}]}}
        return httpx.Response(200, json=body)

    def fetcher(self) -> wikipedia.Fetcher:
        return wikipedia.Fetcher(transport=httpx.MockTransport(self.handler))


@contextmanager
def running_helper(
    fetcher_factory: Callable[[], wikipedia.Fetcher],
) -> Iterator[Path]:
    root = Path(tempfile.mkdtemp(prefix="lzr-", dir="/private/tmp"))
    path = root / "helper.sock"
    stop, ready = threading.Event(), threading.Event()
    thread = threading.Thread(
        target=helper.serve,
        args=(str(path),),
        kwargs={"fetcher_factory": fetcher_factory, "stop": stop, "ready": ready.set},
        daemon=True,
    )
    thread.start()
    assert ready.wait(5)
    try:
        yield path
    finally:
        stop.set()
        thread.join(5)
        shutil.rmtree(root, ignore_errors=True)


def as_json(r: httpx.Request) -> dict[str, str]:
    return json.loads(json.dumps(dict(r.url.params)))
