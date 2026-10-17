"""Conversation compaction: structured, evidence-checked summaries of older messages.

The model proposes summary items as JSON (schema-constrained). Code then verifies every item
against the *original* stored messages before anything reaches a prompt:

* every item must cite existing messages inside the summarized range;
* an item attributed to the user must cite a user message and carry a quote that occurs in
  one of the cited user messages (normalized, fuzzy ≥ 0.85) — LAZIS's own words are never
  evidence for what the user said, and invented details have no quote to match;
* an item attributed to LAZIS must cite an assistant message.

Items that fail are dropped and counted. Summaries are stored next to (never instead of)
the original messages and can be invalidated and rebuilt at any time.
"""

from __future__ import annotations

import difflib
import json
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

from lazis.conversation.context import TokenEstimator, message_cost
from lazis.conversation.models import CONTEXT_STATUSES, Message
from lazis.conversation.prompts import SECTIONS, SUMMARY_INSTRUCTIONS
from lazis.providers.llm.ports import ChatMessage

MAX_TEXT = 300
MAX_QUOTE = 240
FUZZY_THRESHOLD = 0.85


@dataclass(frozen=True)
class SplitPlan:
    """Compact messages ``[window_start, split_seq)``; keep ``split_seq…`` verbatim."""

    split_seq: int
    to_compact: tuple[Message, ...]


@dataclass(frozen=True)
class VerifiedSummary:
    content: dict[str, list[dict[str, Any]]]
    kept: int
    dropped: int
    rendered: str


def plan_split(
    window: Sequence[Message],
    *,
    estimator: TokenEstimator,
    keep_recent_tokens: int,
    keep_recent_messages: int,
) -> SplitPlan | None:
    """Choose where the verbatim tail starts. The tail holds at least ``keep_recent_messages``
    messages, about ``keep_recent_tokens`` tokens, and starts at a user message."""
    if len(window) <= keep_recent_messages:
        return None
    tokens = 0
    start = len(window)
    while start > 0:
        cost = message_cost(window[start - 1], estimator)
        count = len(window) - start
        if count >= keep_recent_messages and tokens + cost > keep_recent_tokens:
            break
        tokens += cost
        start -= 1
    # Start the tail at a user turn so the verbatim history keeps whole exchanges.
    while start > 0 and window[start].role != "user":
        start -= 1
    if start <= 0:
        return None
    to_compact = tuple(window[:start])
    if not any(m.status in CONTEXT_STATUSES for m in to_compact):
        return None
    return SplitPlan(split_seq=window[start].seq, to_compact=to_compact)


def chunk_messages(
    messages: Sequence[Message], *, estimator: TokenEstimator, max_tokens: int
) -> list[list[Message]]:
    """Split the messages to compact into chunks whose transcript fits ``max_tokens``."""
    chunks: list[list[Message]] = []
    current: list[Message] = []
    used = 0
    for message in messages:
        cost = estimator.message(transcript_line(message))
        if current and used + cost > max_tokens:
            chunks.append(current)
            current, used = [], 0
        current.append(message)
        used += cost
    if current:
        chunks.append(current)
    return chunks


def transcript_line(message: Message) -> str:
    who = "KULLANICI" if message.role == "user" else "LAZIS"
    note = f" {message.context_note}" if message.context_note else ""
    state = ""
    if message.status == "cancelled":
        state = " (yanıt yarıda kesildi)"
    elif message.status == "interrupted":
        state = " (yanıt yarım kaldı)"
    return f"#{message.seq} {who}{note}{state}: {message.content}"


def build_messages(
    previous: Mapping[str, Any] | None, messages: Sequence[Message]
) -> list[ChatMessage]:
    """The summarization request: fixed instructions, the previous summary's verified items
    (if any) and the transcript of the messages to fold in."""
    body: list[str] = []
    if previous:
        body.append(
            "Önceki özet (JSON; içindeki geçerli maddeleri koru ve güncelle):\n"
            + json.dumps(previous, ensure_ascii=False, sort_keys=True)
        )
    body.append("Özetlenecek yeni mesajlar:")
    body.extend(
        transcript_line(m)
        for m in messages
        if m.status in CONTEXT_STATUSES and m.role in ("user", "assistant")
    )
    return [ChatMessage("system", SUMMARY_INSTRUCTIONS), ChatMessage("user", "\n".join(body))]


def parse_summary(text: str) -> dict[str, Any] | None:
    """Parse the model's JSON. Output cut off at the token limit is salvaged: every *complete*
    item before the cut is kept (and still verified like any other); the rest is lost."""
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.MULTILINE)
    for candidate in (cleaned, _outer_object(text)):
        if candidate is None:
            continue
        try:
            data = json.loads(candidate)
        except ValueError:
            continue
        return cast(dict[str, Any], data) if isinstance(data, dict) else None
    return _salvage_truncated(cleaned)


def _outer_object(text: str) -> str | None:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    return None if match is None else match.group(0)


def _salvage_truncated(text: str) -> dict[str, Any] | None:
    start = text.find("{")
    if start < 0:
        return None
    body = text[start:]
    # Cut back to the last place where an item object closed, then close the open brackets.
    for end in range(len(body), 0, -1):
        if body[end - 1] != "}":
            continue
        prefix = body[:end]
        closing = _closers(prefix)
        if closing is None:
            continue
        try:
            data = json.loads(prefix + closing)
        except ValueError:
            continue
        if isinstance(data, dict):
            return cast(dict[str, Any], data)
    return None


def _closers(prefix: str) -> str | None:
    """The brackets needed to close ``prefix`` (None if it ends inside a string)."""
    stack: list[str] = []
    in_string = escaped = False
    for ch in prefix:
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch in "[{":
            stack.append("]" if ch == "[" else "}")
        elif ch in "]}":
            if not stack:
                return None
            stack.pop()
    if in_string:
        return None
    return "".join(reversed(stack))


# ----- verification --------------------------------------------------------------------
def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).replace("İ", "i").replace("I", "ı").lower()
    text = re.sub(r"[^\w\s]", " ", text)
    return " ".join(text.split())


def quote_in(quote: str, text: str) -> bool:
    q, t = normalize(quote), normalize(text)
    if not q:
        return False
    if q in t:
        return True
    if len(q) < 12 or len(t) < len(q) // 2:
        return False
    width = len(q)
    step = max(1, width // 6)
    best = 0.0
    for i in range(0, max(1, len(t) - width // 2), step):
        ratio = difflib.SequenceMatcher(None, q, t[i : i + width + width // 5]).ratio()
        best = max(best, ratio)
        if best >= FUZZY_THRESHOLD:
            return True
    return False


def _str(value: Any, limit: int) -> str:
    return value.strip()[:limit] if isinstance(value, str) else ""


def _refs(value: Any) -> list[int]:
    if not isinstance(value, list):
        return []
    out: set[int] = set()
    for item in cast(list[Any], value):
        if isinstance(item, bool):
            continue
        if isinstance(item, int):
            out.add(item)
        elif isinstance(item, str) and item.lstrip("#").isdigit():
            out.add(int(item.lstrip("#")))
    return sorted(out)


def verify_items(
    content: Mapping[str, Any], lookup: Mapping[int, Message], *, covered_to: int
) -> tuple[dict[str, list[dict[str, Any]]], int, int]:
    """Keep only items whose citations and quotes check out against the stored messages."""
    clean: dict[str, list[dict[str, Any]]] = {key: [] for key, _ in SECTIONS}
    kept = dropped = 0
    for key, _label in SECTIONS:
        raw = content.get(key, [])
        if not isinstance(raw, list):
            continue
        for entry in cast(list[Any], raw):
            item = _verify_one(key, entry, lookup, covered_to)
            if item is None:
                dropped += 1
            else:
                clean[key].append(item)
                kept += 1
    return clean, kept, dropped


def _verify_one(
    key: str, entry: Any, lookup: Mapping[int, Message], covered_to: int
) -> dict[str, Any] | None:
    if not isinstance(entry, dict):
        return None
    data = cast(dict[str, Any], entry)
    source = data.get("source")
    if source not in ("user", "assistant"):
        return None
    refs = [r for r in _refs(data.get("refs")) if 1 <= r <= covered_to and r in lookup]
    if not refs:
        return None
    quote = _str(data.get("quote"), MAX_QUOTE)
    cited = [lookup[r] for r in refs]
    role = "user" if source == "user" else "assistant"
    own = [m for m in cited if m.role == role]
    if not own:
        return None  # e.g. a LAZIS suggestion attributed to the user
    # A user item must quote a user message; a LAZIS item's quote (optional) must match too.
    if (source == "user" or quote) and not any(quote_in(quote, m.content) for m in own):
        return None
    item: dict[str, Any] = {
        "source": source,
        "refs": [m.seq for m in own] if source == "user" else refs,
        "quote": quote,
        "certain": data.get("certain") is True,
    }
    if key == "people":
        name = _str(data.get("name"), 80)
        if not name:
            return None
        item["name"] = name
        item["relation"] = _str(data.get("relation"), MAX_TEXT)
    else:
        text = _str(data.get("text"), MAX_TEXT)
        if not text:
            return None
        item["text"] = text
    if key == "decisions":
        item["current"] = data.get("current") is not False
    return item


# ----- rendering -----------------------------------------------------------------------
def _cite(item: Mapping[str, Any]) -> str:
    refs = cast(list[int], item.get("refs", []))
    return " [" + ", ".join(f"#{r}" for r in refs) + "]" if refs else ""


def _line(item: Mapping[str, Any]) -> str:
    if "name" in item:
        relation = str(item.get("relation") or "").strip()
        body = f"{item['name']}: {relation}" if relation else str(item["name"])
    else:
        body = str(item["text"])
    if not item.get("certain"):
        body += " (belirsiz)"
    return f"- {body}{_cite(item)}"


def render(content: Mapping[str, list[dict[str, Any]]], *, from_seq: int, to_seq: int) -> str:
    """Deterministic Turkish text for the prompt. LAZIS's own suggestions are listed apart
    from anything the user said, and replaced decisions are marked as no longer valid."""
    lines = [
        f"Konuşma özeti (#{from_seq}–#{to_seq} arası mesajlardan otomatik çıkarıldı; hatalı "
        "olabilir, orijinal mesajlar kayıtlı):"
    ]
    assistant: list[dict[str, Any]] = []
    for key, label in SECTIONS:
        items = content.get(key, [])
        user_items = [i for i in items if i.get("source") == "user"]
        assistant.extend(i for i in items if i.get("source") == "assistant")
        if key == "assistant_notes":
            continue
        if key == "decisions":
            current = [i for i in user_items if i.get("current", True)]
            old = [i for i in user_items if not i.get("current", True)]
            if current:
                lines.append("Kullanıcının kararları (güncel):")
                lines.extend(_line(i) for i in current)
            if old:
                lines.append("Değiştirilmiş eski kararlar (artık geçerli değil):")
                lines.extend(_line(i) for i in old)
            continue
        if user_items:
            lines.append(f"{label}:")
            lines.extend(_line(i) for i in user_items)
    if assistant:
        lines.append(
            "LAZIS'in önerileri ve çıkarımları (kullanıcı kabul etmedikçe kullanıcının görüşü "
            "ya da kararı değildir):"
        )
        lines.extend(_line(i) for i in assistant)
    if len(lines) == 1:
        lines.append("- (Bu bölümden kaydedilecek doğrulanmış bir bilgi çıkmadı.)")
    return "\n".join(lines)


def verify_and_render(
    raw: Mapping[str, Any],
    lookup: Mapping[int, Message],
    *,
    from_seq: int,
    to_seq: int,
) -> VerifiedSummary:
    clean, kept, dropped = verify_items(raw, lookup, covered_to=to_seq)
    return VerifiedSummary(
        content=clean,
        kept=kept,
        dropped=dropped,
        rendered=render(clean, from_seq=from_seq, to_seq=to_seq),
    )


def cited_seqs(content: Mapping[str, Any]) -> list[int]:
    seqs: set[int] = set()
    for key, _ in SECTIONS:
        raw = content.get(key, [])
        if isinstance(raw, list):
            for entry in cast(list[Any], raw):
                if isinstance(entry, dict):
                    seqs.update(_refs(cast(dict[str, Any], entry).get("refs")))
    return sorted(seqs)
