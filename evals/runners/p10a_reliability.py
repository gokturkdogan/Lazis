"""Phase 10A on the real runtime: memory and preference reliability (production engine,
synthetic data, throwaway encrypted profiles).

    uv run --project core python evals/runners/p10a_reliability.py --model gemma4:12b-it-qat
    uv run --project core python evals/runners/p10a_reliability.py --model gemma4:12b-it-qat \
        --only n1,f1 --repeat 1 --label try

Groups:

* **N — namesakes said with certainty**: the reply after a message that does not say which
  Ahmet (Phase 7 sessions 3.ask, Phase 9.1 namesakes a2, Phase 6 B4, three Ahmets), and two
  controls where it is settled (nothing may be dropped there).
* **F — forgotten things from the chat history**: a forgotten relationship (Phase 7 6.ask),
  the user's own value, another person's value; a control where the user brings it up.
* **G — the proactive gate** on the database a real conversation left behind, and on the
  conversation summary the real model wrote after forgetting.
* **S — preference signals** from records real learning wrote: the same preference in other
  words (Phase 9 r01), the same words again, three statements in three sessions.

Per turn: the model's raw reply, the shown (= stored) reply, the guard's count, the memory
block, the request outcome, the database afterwards. The checks below are independent word
checks written for these scenarios (not the guard's code); every reply is also read by hand.
Writes evals/reports/phase10/reliability_<model>[_<label>].json.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from common import manifest
from p6_sessions import Profile, Recorder, Report, has

from lazis.config.model import (
    AppSection,
    ConversationSection,
    LoggingSection,
    ModelsSection,
    Settings,
    StorageSection,
)
from lazis.conversation import repository as conv_repo
from lazis.memory import proactive, signals, text
from lazis.memory import repository as memory_repo
from lazis.memory.models import CURRENT
from lazis.providers.llm.ollama import OllamaProvider
from lazis.providers.llm.ports import ChatRequest, StreamEvent, TextDelta

OUT = Path(__file__).resolve().parents[1] / "reports" / "phase10"
_SENT = re.compile(r"[^.!?;\n]+[.!?;]*")
_COND = re.compile(r"(eger|\bise\b|saniz\b|seniz\b|yorsa|ysa\b|yse\b|isterseniz|kastediyorsa)")


class RawRecorder(Recorder):
    """Also keeps the raw text of the last reply stream (before the output guards)."""

    def __init__(self, inner: OllamaProvider) -> None:
        super().__init__(inner)
        self.raw = ""

    async def stream(self, request: ChatRequest) -> AsyncIterator[StreamEvent]:
        reply = request.options.response_format is None and request.options.max_tokens > 1
        if reply:
            self.raw = ""
        async for ev in super().stream(request):
            if reply and isinstance(ev, TextDelta) and ev.kind == "content":
                self.raw += ev.text
            yield ev


@dataclass
class SmallWindow(Profile):
    """Compaction can run after a few turns (group G)."""

    def settings(self) -> Settings:
        return Settings(
            app=AppSection(environment="test"),
            storage=StorageSection(data_dir=self.root / "data"),
            logging=LoggingSection(directory=self.root / "logs"),
            models=ModelsSection(max_output_tokens=300),
            conversation=ConversationSection(
                idle_compaction_delay_s=3600.0, keep_recent_tokens=256, keep_recent_messages=2
            ),
        )


@dataclass
class Run:
    llm: RawRecorder
    report: Report
    repeat: int
    rows: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])


def sentences(reply: str | None) -> list[str]:
    return [s.strip() for s in _SENT.findall(reply or "") if s.strip()]


def declarative(s: str) -> bool:
    return not s.rstrip(" \"'»”)").endswith("?") and not _COND.search(text.fold(s))


def picks_one(reply: str | None, topic: tuple[str, ...], labels: tuple[str, ...]) -> list[str]:
    """Declarative sentences with the topic and exactly one of the namesakes' labels."""
    out = []
    for s in sentences(reply):
        if declarative(s) and has(s, *topic) and sum(has(s, lab) for lab in labels) == 1:
            out.append(s)
    return out


def unlabeled(reply: str | None, fact: tuple[str, ...], label: tuple[str, ...]) -> list[str]:
    """Declarative sentences stating the stored fact without the label that says whose."""
    return [s for s in sentences(reply) if declarative(s) and has(s, *fact) and not has(s, *label)]


async def say(p: Profile, run: Run, scenario: str, step: str, message: str,
              checks: Callable[[dict[str, Any]], dict[str, bool]] | None = None) -> dict[str, Any]:  # fmt: skip
    t = await p.say(message)
    assert p.engine is not None
    last = dict(p.engine.last_turn or {})
    t["raw_reply"] = run.llm.raw
    t["people_removed"] = last.get("people_sentences_removed")
    t["first_shown_ms"] = last.get("first_shown_ms")
    t["runtime_ttft_ms"] = last.get("runtime_ttft_ms")
    t["shown_equals_stored"] = _stored_last(p) == t["reply"]
    c = {"shown_is_stored": t["shown_equals_stored"], **(checks(t) if checks else {})}
    run.report.turn(scenario, step, t, c)
    return t


def _stored_last(p: Profile) -> str | None:
    def read(c: Any) -> str | None:
        assert p.session_id is not None
        msgs = conv_repo.messages_between(c, p.session_id, 1)
        return next((m.content for m in reversed(msgs) if m.role == "assistant"), None)

    return p.q(read)


def facts_about(p: Profile, value: str) -> list[dict[str, Any]]:
    return [m for m in p.memories("active") if has(m["value"] + " " + m["content"], value)]


async def scenario(run: Run, name: str, body: Callable[[Profile, str], Awaitable[None]],
                   *, profile: type[Profile] = Profile, repeat: int | None = None) -> None:  # fmt: skip
    for i in range(repeat or run.repeat):
        p = profile("", run.llm)  # model set below
        p.model = MODEL[0]
        try:
            await p.start()
            await body(p, f"{name}#{i + 1}")
        finally:
            await p.stop()
            p.remove()


MODEL: list[str] = [""]
FRIEND, PARTNER = ("çocukluk arkadaş",), ("iş ortağ",)
NEIGHBOR, COLLEAGUE, COUSIN = ("komşu",), ("iş arkadaş",), ("kuzen",)


# ----- N: namesakes ---------------------------------------------------------------------------
async def n1(p: Profile, s: str) -> None:
    run = RUN[0]
    await say(p, run, s, "1", "Çocukluk arkadaşım Ahmet öğretmen.")
    await say(p, run, s, "2", "Ahmet'in kardeşi Mehmet.")
    await say(p, run, s, "3", "İş ortağımın adı da Ahmet.")
    await say(p, run, s, "ask", "Ahmet'in kardeşi kim?", lambda t: {
        "no_certain_answer": not unlabeled(t["reply"], ("Mehmet",), FRIEND),
        "asks_which": "?" in (t["reply"] or "") and has(t["reply"], "hangi", "hangisi", " mi", " mı"),
    })  # fmt: skip


async def n2(p: Profile, s: str) -> None:
    run = RUN[0]
    await say(p, run, s, "1", "İki Ahmet tanıyorum: biri komşum, diğeri iş arkadaşım.")
    t = await say(p, run, s, "news", "Ahmet emekli oldu.", lambda t: {
        "no_pick": not picks_one(t["reply"], ("emekli",), (*NEIGHBOR, *COLLEAGUE)),
    })  # fmt: skip
    run.report.state(s, "db", {"written_to_nobody": not facts_about(p, "emekli")},
                     {"facts": facts_about(p, "emekli"), "reply": t["reply"]})  # fmt: skip


async def n3(p: Profile, s: str) -> None:
    run = RUN[0]
    await say(p, run, s, "1", "Komşum Ahmet mimar.")
    await say(p, run, s, "2", "İş arkadaşım Ahmet muhasebeci.")
    await say(p, run, s, "ask", "Ahmet ne iş yapıyor?", lambda t: {
        "mimar_labeled": not unlabeled(t["reply"], ("mimar",), NEIGHBOR),
        "muhasebeci_labeled": not unlabeled(t["reply"], ("muhasebeci",), COLLEAGUE),
    })  # fmt: skip


async def n4(p: Profile, s: str) -> None:
    run = RUN[0]
    await say(p, run, s, "1", "Çocukluk arkadaşım Ahmet öğretmen.")
    await say(p, run, s, "2", "İş ortağım da Ahmet, o avukat.")
    t = await say(p, run, s, "news", "Ahmet bugün aradı, satranç kulübüne yazılmış.", lambda t: {
        "no_pick": not picks_one(t["reply"], ("satranç",), (*FRIEND, *PARTNER)),
    })  # fmt: skip
    run.report.state(s, "db", {"not_attached": not facts_about(p, "satranç")},
                     {"facts": facts_about(p, "satranç"), "reply": t["reply"]})  # fmt: skip


async def n5(p: Profile, s: str) -> None:
    run = RUN[0]
    await say(p, run, s, "1", "Üç Ahmet tanıyorum: biri komşum, biri kuzenim, biri iş arkadaşım.")
    t = await say(p, run, s, "news", "Ahmet yarın İzmir'e taşınıyor.", lambda t: {
        "no_pick": not picks_one(t["reply"], ("İzmir",), (*NEIGHBOR, *COUSIN, *COLLEAGUE)),
    })  # fmt: skip
    run.report.state(s, "db", {"not_attached": not [m for m in facts_about(p, "İzmir")
                                                    if m["about"] == "Ahmet"]},
                     {"facts": facts_about(p, "İzmir")})  # fmt: skip


async def n6(p: Profile, s: str) -> None:
    """Control: the message says which one — the answer stays."""
    run = RUN[0]
    await say(p, run, s, "1", "İki Ahmet tanıyorum: biri komşum, diğeri iş arkadaşım.")
    await say(p, run, s, "news", "Komşum Ahmet emekli oldu.", lambda t: {
        "nothing_dropped": not t["people_removed"],
    })  # fmt: skip


async def n7(p: Profile, s: str) -> None:
    """Control: one Ahmet — the answer stays."""
    run = RUN[0]
    await say(p, run, s, "1", "Arkadaşım Ahmet'in kardeşi Mehmet.")
    await say(p, run, s, "ask", "Ahmet'in kardeşi kim?", lambda t: {
        "answers": has(t["reply"], "Mehmet"), "nothing_dropped": not t["people_removed"],
    })  # fmt: skip


# ----- F: forgotten ---------------------------------------------------------------------------
async def f1(p: Profile, s: str) -> None:
    run = RUN[0]
    await say(p, run, s, "1", "Çocukluk arkadaşım Ahmet.")
    await say(p, run, s, "2", "Ahmet'in kuzeni Mehmet.")
    t = await say(p, run, s, "forget", "Ahmet ile Mehmet arasındaki ilişkiyi unut.")
    await say(p, run, s, "ask", "Mehmet, Ahmet'in neyi oluyor?", lambda t: {
        "no_old_relation": not has(t["reply"], "kuzen"),
    })  # fmt: skip
    run.report.state(s, "db", {"forgotten": t["outcome"] == "forgotten",
                               "no_link": not _linked(p, "Ahmet", "Mehmet")})  # fmt: skip


async def f2(p: Profile, s: str) -> None:
    run = RUN[0]
    await say(p, run, s, "1", "Kervan Lojistik'te çalışıyorum.")
    t = await say(p, run, s, "forget", "Çalıştığım yeri unut.")
    await say(p, run, s, "ask", "Nerede çalıştığımı hatırlıyor musun?", lambda t: {
        "no_old_value": not has(t["reply"], "Kervan"),
    })  # fmt: skip
    run.report.state(s, "db", {"forgotten": t["outcome"] == "forgotten",
                               "gone": not facts_about(p, "Kervan")})  # fmt: skip


async def f3(p: Profile, s: str) -> None:
    run = RUN[0]
    await say(p, run, s, "1", "Arkadaşım Selin veteriner.")
    t = await say(p, run, s, "forget", "Selin'in mesleğini unut.")
    await say(p, run, s, "ask", "Selin ne iş yapıyordu?", lambda t: {
        "no_old_value": not has(t["reply"], "veteriner"),
    })  # fmt: skip
    run.report.state(s, "db", {"forgotten": t["outcome"] == "forgotten",
                               "gone": not facts_about(p, "veteriner")})  # fmt: skip


async def f4(p: Profile, s: str) -> None:
    """Control: the user brings the forgotten value up again — answering it is fine."""
    run = RUN[0]
    await say(p, run, s, "1", "Kervan Lojistik'te çalışıyorum.")
    await say(p, run, s, "forget", "Çalıştığım yeri unut.")
    await say(p, run, s, "again", "Kervan Lojistik'ten ayrıldım, artık serbest çalışıyorum.",
              lambda t: {"nothing_dropped": not t["people_removed"]})  # fmt: skip


def _linked(p: Profile, a: str, b: str) -> bool:
    def read(c: Any) -> bool:
        for x in memory_repo.find_entities(c, text.name_key(a)):
            for y in memory_repo.find_entities(c, text.name_key(b)):
                if memory_repo_rel(c, x.id, y.id):
                    return True
        return False

    return p.q(read)


def memory_repo_rel(c: Any, a: str, b: str) -> bool:
    from lazis.memory import graphstore as gs

    return bool(gs.relationships_between(c, a, b, statuses=CURRENT))


# ----- G: the gate ----------------------------------------------------------------------------
async def g1(p: Profile, s: str) -> None:
    run = RUN[0]
    for i, m in enumerate([
        "Kervan Lojistik'te çalışıyorum.", "Hedefim gelecek yıl maraton koşmak.",
        "Komşum Ahmet emekli oldu.", "İş arkadaşım Ahmet muhasebeci.",
        "Komşum Ahmet'in kuzeni Mehmet.", "Hafta sonu kızım Defne'nin doğum günü var.",
    ]):  # fmt: skip
        await say(p, run, s, f"say{i + 1}", m)
    await say(p, run, s, "forget1", "Çalıştığım yeri unut.")
    await say(p, run, s, "forget2", "Komşum Ahmet ile Mehmet arasındaki ilişkiyi unut.")
    await say(p, run, s, "pad", "Bugün biraz yorgunum ama iyiyim.")
    assert p.engine is not None and p.session_id is not None
    compacted = await p.engine.compact_now(p.session_id)
    sid = p.session_id

    def read(c: Any) -> dict[str, Any]:
        gate = proactive.load(c)
        mems = memory_repo.list_memories(c, limit=500)
        rels = [r for e in memory_repo.list_entities(c) for r in
                memory_repo_rels_of(c, e.id)]  # fmt: skip
        summaries = conv_repo.list_summaries(c, sid)
        names = {e.id: e.name for e in memory_repo.list_entities(c)}
        names["user"] = "user"
        return {
            "memories": [{"value": m.value, "predicate": m.predicate, "about": names.get(m.subject_id or "user"),
                          "verdict": gate.memory(m)} for m in mems],  # fmt: skip
            "relationships": [{"s": names.get(r.source_id), "type": r.type, "t": names.get(r.target_id),
                               "verdict": gate.relationship(r)} for r in dict((r.id, r) for r in rels).values()],  # fmt: skip
            "needs_label": sorted(names[i] for i in gate.needs_label_ids),
            "summaries": [x.rendered for x in summaries],
            "cleaned": [gate.clean_text(x.rendered) for x in summaries],
        }

    d = p.q(read)
    usable_text = " ".join(c[0] for c in d["cleaned"])
    usable_values = " ".join(m["value"] for m in d["memories"] if m["verdict"] is None)
    run.report.state(s, "gate", {
        "compacted": bool(compacted) and bool(d["summaries"]),
        "no_forgotten_value_usable": not has(usable_values, "Kervan"),
        "no_forgotten_in_summary": not has(usable_text, "Kervan") and not has(usable_text, "kuzen"),
        "no_forgotten_relation_usable": not any(r["type"] == "cousin" and r["verdict"] is None
                                                for r in d["relationships"]),
        "ahmets_need_label": d["needs_label"].count("Ahmet") >= 2,
    }, d)  # fmt: skip


def memory_repo_rels_of(c: Any, eid: str) -> list[Any]:
    from lazis.memory import graphstore as gs

    return gs.relationships_of(c, eid)


# ----- S: signals -----------------------------------------------------------------------------
def _tally(p: Profile, predicates: tuple[str, ...]) -> dict[str, Any]:
    def read(c: Any) -> dict[str, Any]:
        ids = [m.id for m in memory_repo.list_memories(c, limit=500) if m.predicate in predicates]
        found = signals.from_records(c, {"pref": ids})
        t = signals.tally(found).get("pref")
        return {"records": len(ids), "messages": t.messages if t else 0,
                "sessions": t.sessions if t else 0, "enough": bool(t and t.enough)}  # fmt: skip

    return p.q(read)


PREFS = ("communication_preference", "work_preference", "preference", "likes", "habit")


async def s1(p: Profile, s: str) -> None:
    run = RUN[0]
    for i, m in enumerate(["Ben sabah çalışmayı seviyorum.", "En verimli olduğum saatler sabah.",
                           "Önemli işlerimi genellikle sabah yaparım."]):  # fmt: skip
        await say(p, run, s, f"say{i + 1}", m)
    t = _tally(p, PREFS)
    run.report.state(s, "tally", {"one_session_not_enough": not t["enough"],
                                  "messages_le_3": t["messages"] <= 3}, {**t, "memories": p.memories("active")})  # fmt: skip


async def s2(p: Profile, s: str) -> None:
    run = RUN[0]
    await say(p, run, s, "say1", "Kısa yanıtları severim.")
    await say(p, run, s, "say2", "Kısa yanıtları severim.")
    await p.clean_session()
    await say(p, run, s, "say3", "Kısa yanıtları severim.")
    t = _tally(p, PREFS)
    run.report.state(s, "tally", {"same_words_one_statement": t["messages"] <= 1,
                                  "not_enough": not t["enough"]}, {**t, "memories": p.memories("active")})  # fmt: skip


async def s3(p: Profile, s: str) -> None:
    run = RUN[0]
    for i, m in enumerate(["Kısa yanıtları severim.", "Uzun açıklamalardan hoşlanmam.",
                           "Bana hep kısa ve öz cevaplar ver."]):  # fmt: skip
        if i:
            await p.clean_session()
        await say(p, run, s, f"say{i + 1}", m)
    t = _tally(p, PREFS)
    run.report.state(s, "tally", {"messages_le_3": t["messages"] <= 3,
                                  "sessions_le_3": t["sessions"] <= 3}, {**t, "memories": p.memories("active")})  # fmt: skip


RUN: list[Run] = []
GROUPS: dict[str, tuple[Callable[[Profile, str], Awaitable[None]], type[Profile], int | None]] = {
    "n1": (n1, Profile, None), "n2": (n2, Profile, None), "n3": (n3, Profile, None),
    "n4": (n4, Profile, None), "n5": (n5, Profile, None), "n6": (n6, Profile, None),
    "n7": (n7, Profile, None), "f1": (f1, Profile, None), "f2": (f2, Profile, None),
    "f3": (f3, Profile, None), "f4": (f4, Profile, None), "g1": (g1, SmallWindow, 2),
    "s1": (s1, Profile, 1), "s2": (s2, Profile, 1), "s3": (s3, Profile, 1),
}  # fmt: skip


async def main_async(model: str, only: set[str] | None, repeat: int) -> dict[str, Any]:
    MODEL[0] = model
    llm = RawRecorder(OllamaProvider(first_token_timeout=600, idle_timeout=120, max_duration=1200))
    RUN.append(Run(llm, Report(), repeat))
    for name, (fn, profile, n) in GROUPS.items():
        if only and name not in only:
            continue
        await scenario(RUN[0], name, fn, profile=profile, repeat=None if n is None else min(n, repeat))
    await llm.inner.aclose()
    steps = RUN[0].report.steps
    checks = [v for st in steps for v in st["checks"].values()]
    return {"model": model, "manifest": manifest(model),
            "summary": {"checks": len(checks), "passed": sum(checks),
                        "failed": [f"{st['scenario']}/{st['step']}:{k}" for st in steps
                                   for k, v in st["checks"].items() if not v],
                        "guard_dropped_turns": sum(1 for st in steps if st.get("people_removed"))},
            "steps": steps}  # fmt: skip


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--only", default="")
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--label", default="")
    args = ap.parse_args()
    only = {s.strip() for s in args.only.split(",") if s.strip()} or None
    report = asyncio.run(main_async(args.model, only, args.repeat))
    OUT.mkdir(parents=True, exist_ok=True)
    name = args.model.replace(":", "_").replace("/", "_")
    path = OUT / f"reliability_{name}{'_' + args.label if args.label else ''}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str) + "\n")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=1))
    print(path)


if __name__ == "__main__":
    main()
