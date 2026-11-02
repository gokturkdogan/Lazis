"""Phase 10B stabilization: a user message while background compaction runs (real Gemma).

    uv run --project core python evals/runners/p10s_compaction_turn.py --model gemma4:12b-it-qat

Production settings (the default 5 s idle delay, the production output length), the production
engine, throwaway encrypted profiles, synthetic data. A long conversation is seeded in the
database (past the compaction threshold), one real turn makes the engine schedule compaction.

Scenarios:

* **baseline** — the same long conversation, the message sent at once (no compaction yet);
* **during** — the message sent 1, 10 or 25 s into the running compaction;
* **writer** — a user who keeps writing, each message 6 s after the last reply (compaction has
  just started and is preempted every time); **writer30**, **writer60**: 30 s and 60 s after;
* **fast** — a user who writes right after each reply (never 5 s idle);
* **second** — a second message while the first reply is being generated;
* **close** — the app closes during compaction, then reopens.

Per turn: first token, stages, prompt tokens, whether compaction ran and was preempted. After each
scenario, from the database: every message exactly once and in order, every user message with
one completed reply, no reply left streaming; and whether compaction later completes.

Writes evals/reports/phase10/compaction_turn_<model>[_<label>].json.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from common import manifest
from p6_sessions import Profile, Recorder

from lazis.config.model import AppSection, LoggingSection, Settings, StorageSection
from lazis.conversation import TurnRequest
from lazis.conversation import repository as conv_repo
from lazis.errors import LlmBusyError
from lazis.ids import utc_now_iso
from lazis.memory import repository as memory_repo
from lazis.providers.llm.ollama import OllamaProvider

OUT = Path(__file__).resolve().parents[1] / "reports" / "phase10"
TURN_LIMIT_S = 420

SEED_Q = [
    "Evde sebze yetiştirmeye nasıl başlarım?", "Domates fideleri için en iyi toprak nedir?",
    "Balkonda hangi otlar kolay yetişir?", "Kompost yapmak için neler gerekir?",
    "Bitkileri ne sıklıkla sulamalıyım?", "Yaprak bitleriyle doğal yollarla nasıl başa çıkarım?",
    "Saksı boyutu bitkiyi nasıl etkiler?", "Kışın balkonda neler yetiştirilebilir?",
]  # fmt: skip
SEED_A = (
    "Toprağın havalanması ve su tutması dengede olmalı; saksının altında drenaj deliği bulunmalı, "
    "bitki güneş alan bir yere konmalı ve sulama toprağın üst katmanı kuruduğunda yapılmalı. "
    "Başlangıçta az sayıda ve dayanıklı türle başlamak, hataları görmeyi kolaylaştırır. Düzenli "
    "gözlem, yaprak rengi ve toprak nemi hakkında erken uyarı verir; gübre ölçülü kullanılmalı, "
    "çünkü fazlası kökleri yakabilir. Mevsim geçişlerinde bitkiyi rüzgârdan korumak ve budama "
    "ile hava akışını artırmak hastalık riskini azaltır. "
)
QUESTIONS = [
    "Fotosentez nasıl çalışır?", "Bulut bilişim nedir?", "Enflasyon neden olur?",
    "Gökyüzü neden mavidir?", "Stresle başa çıkmak için ne önerirsin?",
    "Kitap okuma alışkanlığı nasıl kazanılır?", "Tasarruf yapmaya nereden başlamalıyım?",
    "Yeni bir dil öğrenmeye nasıl başlamalıyım?", "SQL'de JOIN türleri nelerdir?",
    "İyi bir özgeçmişte neler olmalı?", "Sabah koşusu mu akşam koşusu mu daha iyi?",
    "Git'te rebase ile merge arasındaki fark ne?",
]  # fmt: skip


class Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.INFO)
        self.events: list[dict[str, Any]] = []

    def emit(self, record: logging.LogRecord) -> None:
        name = record.getMessage()
        if "compaction" in name:
            self.events.append({"t": time.monotonic(), "event": name,
                                **(getattr(record, "lazis_fields", None) or {})})  # fmt: skip


CAP = Capture()
logging.getLogger("lazis").addHandler(CAP)
logging.getLogger("lazis").setLevel(logging.INFO)


@dataclass
class P(Profile):
    def settings(self) -> Settings:  # production defaults for the conversation
        return Settings(
            app=AppSection(environment="test"),
            storage=StorageSection(data_dir=self.root / "data"),
            logging=LoggingSection(directory=self.root / "logs"),
        )


def seed(p: P, rounds: int = 11) -> None:
    """A long past conversation in the active session, past the compaction threshold."""
    assert p.session_id is not None

    def write(c: Any) -> None:
        with conv_repo.transaction(c):
            for i in range(rounds):
                for role, text in (("user", SEED_Q[i % len(SEED_Q)]), ("assistant", SEED_A * 3)):
                    conv_repo.insert_message(
                        c, conversation_id=p.session_id, role=role, content=text, status="complete",
                        now=utc_now_iso(), model=None if role == "user" else p.model,
                    )  # fmt: skip

    p.q(write)


async def turn(p: P, text: str) -> dict[str, Any]:
    assert p.engine is not None
    t0 = time.monotonic()
    job = p.engine.scheduler.background
    bg = None if job is None else {"kind": job.kind, "age_s": round(t0 - job.started_monotonic, 1)}
    h = await asyncio.wait_for(p.engine.begin_turn(
        TurnRequest(p.session_id, f"c-{secrets.token_hex(6)}", text, p.model)), TURN_LIMIT_S)  # fmt: skip
    stages: dict[str, int] = {}
    first: int | None = None
    reply: str | None = None
    errors: list[Any] = []

    async def drain() -> None:
        nonlocal first, reply
        async for e in p.engine.events(h):  # type: ignore[union-attr]
            now = round((time.monotonic() - t0) * 1000)
            if e["type"] == "status":
                stages.setdefault(e["stage"], now)
            elif e["type"] == "delta" and first is None:
                first = now
            elif e["type"] == "done":
                reply = e["message"]["content"]
            elif e["type"] == "error":
                errors.append(e.get("code"))

    timed_out = False
    try:
        await asyncio.wait_for(drain(), TURN_LIMIT_S)
    except TimeoutError:
        timed_out = True
    p.session_id = h.conversation.id
    last = dict(p.engine.last_turn or {})
    return {
        "user": text, "background_at_send": bg, "first_delta_ms": first, "stages": stages,
        "total_ms": round((time.monotonic() - t0) * 1000), "timed_out": timed_out,
        "errors": errors, "words": len((reply or "").split()), "reply": reply,
        **{k: last.get(k) for k in ("ttft_ms", "context_prep_ms", "runtime_ttft_ms", "prompt_tokens")},
    }  # fmt: skip


async def wait_compaction(p: P, limit: float = 120) -> float | None:
    """Until a compaction runs. Its start time, or None."""
    assert p.engine is not None
    t0 = time.monotonic()
    while time.monotonic() - t0 < limit:
        job = p.engine.scheduler.background
        if job is not None and job.kind == "compaction":
            return job.started_monotonic
        await asyncio.sleep(0.1)
    return None


async def settle(p: P, limit: float = 240) -> dict[str, Any]:
    """Until nothing runs or is queued: the time, and whether it did settle."""
    assert p.engine is not None
    t0 = time.monotonic()
    quiet = 0
    while time.monotonic() - t0 < limit:
        counts = p.q(memory_repo.job_counts)
        idle = not counts.get("queued") and not counts.get("running")
        if idle and p.engine.scheduler.background is None and not p.engine.is_busy():
            quiet += 1
            if quiet >= 40:  # 10 s with nothing running (the idle delay has passed)
                return {"settled": True, "s": round(time.monotonic() - t0 - 10, 1)}
        else:
            quiet = 0
        await asyncio.sleep(0.25)
    return {"settled": False, "s": limit}


def integrity(p: P, sent: list[str]) -> dict[str, Any]:
    """From the database: every message once and in order, every question answered."""

    def read(c: Any) -> dict[str, Any]:
        rows = c.execute(
            "SELECT seq, role, status, content FROM messages WHERE conversation_id = ? ORDER BY seq",
            (p.session_id,),
        ).fetchall()
        summaries = c.execute(
            "SELECT COUNT(*) FROM context_summaries WHERE conversation_id = ?", (p.session_id,)
        ).fetchone()[0]
        return {"rows": [tuple(r) for r in rows], "summaries": summaries}

    data = p.q(read)
    rows = data["rows"]
    seqs = [r[0] for r in rows]
    users = [r[3] for r in rows if r[1] == "user"]
    positions = [users.index(s) if s in users else -1 for s in sent]
    answered = True
    for i, r in enumerate(rows):
        if (
            r[1] == "user"
            and r[3] in sent
            and (
                i + 1 >= len(rows) or rows[i + 1][1] != "assistant" or rows[i + 1][2] != "complete"
            )
        ):
            answered = False
    return {
        "seq_increasing": seqs == sorted(set(seqs)),
        "each_sent_once": all(users.count(s) == 1 for s in sent),
        "order_kept": positions == sorted(positions) and -1 not in positions,
        "each_answered": answered,
        "none_streaming": not any(r[2] == "streaming" for r in rows),
        "messages": len(rows),
        "summaries": data["summaries"],
    }


def row(
    name: str, turns: list[dict[str, Any]], check: dict[str, Any], **extra: Any
) -> dict[str, Any]:
    out = {"scenario": name, "turns": turns, "integrity": check, **extra}
    print(json.dumps({"scenario": name, "first_delta_s": [round((t["first_delta_ms"] or 0) / 1000, 1) for t in turns],
                      "bg": [t["background_at_send"] for t in turns], "integrity": check,
                      **{k: v for k, v in extra.items() if k != "compactions"}}, ensure_ascii=False), flush=True)  # fmt: skip
    return out


async def setup(model: str, llm: Recorder) -> P:
    p = P(model, llm)
    await p.start()
    assert p.engine is not None
    session = await p.engine.start_new_session(model)
    p.session_id = session.id
    seed(p)
    return p


async def baseline(model: str, llm: Recorder) -> dict[str, Any]:
    """No compaction running: the message right after the previous reply."""
    p = await setup(model, llm)
    try:
        sent = QUESTIONS[:2]
        turns = [await turn(p, q) for q in sent]
        s = await settle(p)
        return row("baseline", turns, integrity(p, sent), settle=s)
    finally:
        await p.stop()
        p.remove()


async def during(model: str, llm: Recorder, offset: float) -> dict[str, Any]:
    p = await setup(model, llm)
    n0 = len(CAP.events)
    try:
        sent = QUESTIONS[:2]
        turns = [await turn(p, sent[0])]
        started = await wait_compaction(p)
        if started is not None:
            await asyncio.sleep(max(0.0, started + offset - time.monotonic()))
        turns.append(await turn(p, sent[1]))
        s = await settle(p)
        ev = [{k: v for k, v in e.items() if k != "t"} for e in CAP.events[n0:]]
        return row(f"during_{offset:g}s", turns, integrity(p, sent), settle=s, compaction_started=started is not None,
                   compactions=ev, completed=sum(e["event"] == "compaction.completed" for e in ev))  # fmt: skip
    finally:
        await p.stop()
        p.remove()


async def writer(
    model: str, llm: Recorder, wait: float, name: str, rounds: int = 12
) -> dict[str, Any]:
    p = await setup(model, llm)
    n0 = len(CAP.events)
    try:
        sent = QUESTIONS[:rounds]
        turns = []
        for q in sent:
            turns.append(await turn(p, q))
            await asyncio.sleep(wait)
        s = await settle(p)
        ev = [{k: v for k, v in e.items() if k != "t"} for e in CAP.events[n0:]]
        return row(name, turns, integrity(p, sent), settle=s, compactions=ev,
                   completed=sum(e["event"] == "compaction.completed" for e in ev))  # fmt: skip
    finally:
        await p.stop()
        p.remove()


async def second(model: str, llm: Recorder) -> dict[str, Any]:
    """A second message while the first reply is being generated: refused, nothing lost."""
    p = await setup(model, llm)
    try:
        assert p.engine is not None
        first_q, second_q = QUESTIONS[0], QUESTIONS[1]
        task = asyncio.create_task(turn(p, first_q))
        await asyncio.sleep(1.0)
        refused = False
        try:
            await p.engine.begin_turn(
                TurnRequest(p.session_id, f"c-{secrets.token_hex(6)}", second_q, p.model)
            )
        except LlmBusyError:
            refused = True
        t1 = await task
        t2 = await turn(p, second_q)  # the client sends it again
        s = await settle(p)
        return row(
            "second", [t1, t2], integrity(p, [first_q, second_q]), settle=s, second_refused=refused
        )
    finally:
        await p.stop()
        p.remove()


async def close(model: str, llm: Recorder) -> dict[str, Any]:
    """The app closes during compaction, then reopens: nothing lost, no hang."""
    p = await setup(model, llm)
    try:
        sent = QUESTIONS[:2]
        turns = [await turn(p, sent[0])]
        started = await wait_compaction(p)
        await asyncio.sleep(5)
        t0 = time.monotonic()
        await asyncio.wait_for(p.stop(), 60)
        closed_s = round(time.monotonic() - t0, 1)
        await p.start()
        turns.append(await turn(p, sent[1]))
        s = await settle(p)
        return row(
            "close",
            turns,
            integrity(p, sent),
            settle=s,
            closed_s=closed_s,
            compaction_started=started is not None,
        )
    finally:
        await p.stop()
        p.remove()


async def main_async(model: str, repeat: int, only: set[str] | None) -> dict[str, Any]:
    llm = Recorder(OllamaProvider(first_token_timeout=600, idle_timeout=120, max_duration=1200))
    rows: list[dict[str, Any]] = []

    async def guarded(name: str, coro: Any) -> None:
        try:
            rows.append(await asyncio.wait_for(coro, 1500))
        except Exception as exc:  # a hang or failure is a finding, not the end of the run
            rows.append({"scenario": name, "failed": f"{type(exc).__name__}: {exc}"[:300]})
            print(json.dumps(rows[-1], ensure_ascii=False), flush=True)

    def on(name: str) -> bool:
        return only is None or name in only

    for _ in range(repeat):
        if on("baseline"):
            await guarded("baseline", baseline(model, llm))
        if on("during"):
            for offset in (1.0, 10.0, 25.0):
                await guarded(f"during_{offset:g}s", during(model, llm, offset))
    if on("second"):
        await guarded("second", second(model, llm))
    if on("close"):
        await guarded("close", close(model, llm))
    if on("writer"):
        for _ in range(2):
            await guarded("writer", writer(model, llm, 6.0, "writer"))
    if on("fast"):
        await guarded("fast", writer(model, llm, 0.2, "fast"))
    for gap in (30, 60):
        if on(f"writer{gap}"):
            await guarded(f"writer{gap}", writer(model, llm, float(gap), f"writer{gap}"))
    await llm.inner.aclose()
    return {"model": model, "manifest": manifest(model), "rows": rows}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--only", default="")
    ap.add_argument("--label", default="")
    args = ap.parse_args()
    only = {x for x in args.only.split(",") if x} or None
    report = asyncio.run(main_async(args.model, args.repeat, only))
    OUT.mkdir(parents=True, exist_ok=True)
    name = re.sub(r"[:/]", "_", args.model)
    path = OUT / f"compaction_turn_{name}{'_' + args.label if args.label else ''}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n")
    print(path)


if __name__ == "__main__":
    main()
