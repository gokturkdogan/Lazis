"""The backend's side of the research helper: one request over its Unix socket (Phase 12).

Blocking, with a deadline; run it off the event loop. The backend's own network guard allows
Unix sockets and its OS profile allows exactly this one path, so nothing else is reachable.
"""

from __future__ import annotations

import json
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import cast

TIMEOUT_SECONDS = 30.0
MAX_REPLY_BYTES = 200_000


@dataclass(frozen=True)
class WebPage:
    title: str
    url: str
    lang: str
    text: str


class ResearchUnavailable(Exception):
    """Research could not be done. ``code`` names why (safe to show and to log)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class ResearchClient:
    def __init__(self, socket_path: Path | str, *, timeout: float = TIMEOUT_SECONDS) -> None:
        self.socket_path = str(socket_path)
        self.timeout = timeout

    def _call(self, request: dict[str, str]) -> dict[str, object]:
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
                conn.settimeout(self.timeout)
                conn.connect(self.socket_path)
                conn.sendall(json.dumps(request, ensure_ascii=False).encode() + b"\n")
                data = bytearray()
                while b"\n" not in data:
                    chunk = conn.recv(65536)
                    if not chunk:
                        break
                    data += chunk
                    if len(data) > MAX_REPLY_BYTES:
                        raise ResearchUnavailable("bad_response")
        except TimeoutError:
            raise ResearchUnavailable("timeout") from None
        except (FileNotFoundError, ConnectionRefusedError):
            raise ResearchUnavailable("helper_unavailable") from None
        except OSError:
            raise ResearchUnavailable("helper_unavailable") from None
        try:
            reply = json.loads(bytes(data).split(b"\n", 1)[0])
        except ValueError:
            raise ResearchUnavailable("bad_response") from None
        if not isinstance(reply, dict):
            raise ResearchUnavailable("bad_response")
        return {str(k): v for k, v in cast(dict[object, object], reply).items()}

    def research(self, query: str) -> list[WebPage]:
        reply = self._call({"op": "research", "query": query})
        if reply.get("ok") is not True:
            raise ResearchUnavailable(str(reply.get("code") or "network"))
        pages = reply.get("pages")
        out: list[WebPage] = []
        for item in cast(list[object], pages) if isinstance(pages, list) else []:
            if not isinstance(item, dict):
                continue
            p = cast(dict[str, object], item)
            values = [p.get(k) for k in ("title", "url", "lang", "text")]
            if all(isinstance(v, str) for v in values):
                title, url, lang, text = (str(v) for v in values)
                out.append(WebPage(title, url, lang, text))
        return out
