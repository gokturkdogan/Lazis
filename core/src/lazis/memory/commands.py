"""Explicit memory requests in chat: "bunu unutma", "Ahmet'in mesleğini unut", "yanlış
hatırlıyorsun", "hakkımda ne biliyorsun?" (MEMORY_ARCHITECTURE P6.8).

Two stages, so ordinary messages pay nothing:

1. ``detect``: a Turkish cue lexicon on the folded message (microseconds). Most messages stop
   here. "Ne biliyorsun?" style questions need no model: they only widen recall.
2. For remember / forget / correct cues, the engine asks the model once, synchronously and on
   the cached prefix, what exactly is meant (``instruction`` + ``schema``), then executes it
   here — before the reply is generated. The reply gets a HAFIZA İŞLEMİ notice describing
   what really happened, so LAZIS says "Kaydettim" only after the write committed, and never
   "Unuttum" before the delete.

Deleting everything about a person is destructive: it waits for the user's confirmation
(an inbox item, answered in chat — "evet" — or in the memory screen).
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import Any, Literal, cast

from lazis.ids import utc_now_iso
from lazis.memory import extraction, policy, registry, relations, resolver, service, text
from lazis.memory import graphstore as gs
from lazis.memory import relationships as rels
from lazis.memory import repository as repo
from lazis.memory.extraction import Target
from lazis.memory.models import USER_ID, Entity, EntityRef, Memory, RelCandidate
from lazis.memory.service import Source
from lazis.storage.driver import Connection
from lazis.storage.repositories import write_audit
from lazis.storage.unit_of_work import UnitOfWork

Intent = Literal[
    "remember", "forget", "correct", "recall", "confirm", "decline", "same", "different"
]

NOTICE_START = "=== HAFIZA İŞLEMİ ==="
NOTICE_END = "=== HAFIZA İŞLEMİ SONU ==="

_REMEMBER = re.compile(
    r"\b(unutma(?:yin|yasin|man)?\b|hatirla(?:sana|r misin|\b)|aklinda (?:tut|olsun)|"
    r"kaydet|kayit et|not (?:al|et)\b|hafizana|bunu bil\b)"
)
_FORGET = re.compile(
    r"\b(unut(?:\b|ur mu|abilir|mani|sana|un\b)|hafizandan|kaydini sil|kayitlarini sil|"
    r"\bsil\b|silebilir|siler misin|silin\b)"
)
_CORRECT = re.compile(
    r"\b(yanlis (?:hatirliyorsun|biliyorsun|kaydettin|anlamissin)|oyle degil|duzelt)"
)
_RECALL = re.compile(
    r"\b((?:hakkimda|benimle ilgili|hakkinda) (?:ne|neler) (?:biliyorsun|hatirliyorsun|kaydettin)|"
    r"(?:ne|neler) (?:biliyorsun|hatirliyorsun) (?:benim|hakkimda)|hafizanda ne)"
)
# "Bu iki Ahmet aynı kişi" / "Ahmet ile Memo aynı kişi" — not a question ("aynı kişi mi?").
_SAME = re.compile(
    r"\b(ayni (?:kisi|insan|kisiler|adam|kadin)|ikisi (?:de )?ayni|tek (?:bir )?kisi)\b"
    r"(?! (?:degil|mi|mu|midir|misiniz)\b)"
)
_DIFFERENT = re.compile(
    r"\b(farkli (?:kisi|insan|kisiler|insanlar)|ayni kisi(?:ler)? degil|baska (?:biri|bir kisi)|"
    r"ayri (?:kisi|kisiler|insanlar))\b(?! (?:mi|mu|midir)\b)"
)
_CONFIRM = re.compile(r"^\s*(evet|onayliyorum|onayla|tamam,? sil|sil gitsin|eminim)\b")
_DECLINE = re.compile(r"^\s*(hayir|vazgec|silme|iptal)\b")


# For a statement without a memory request: background learning happens after the reply, so
# at reply time nothing has been written ("not ettim" would be a claim before the fact).
PENDING_NOTICE = (
    f"{NOTICE_START}\n"
    "Henüz hiçbir şey kaydedilmedi; 'not ettim', 'kaydettim', 'öğrendim' deme.\n"
    f"{NOTICE_END}"
)
_QUESTION = re.compile(r"\?|\b(mi|mı|mu|mü|misin|mısın|musun|müsün|miyim|mıyım)\b")


def looks_like_statement(message: str) -> bool:
    """A message that may tell LAZIS something (not a question, not a one-word reply)."""
    return len(message.split()) >= 3 and not _QUESTION.search(text.casefold(message))


def contains_secret(message: str) -> bool:
    return policy.secret_kind(message) is not None


def detect(message: str, *, pending_confirmation: bool = False) -> Intent | None:
    """Stage 1: does this message look like a memory request? (Liberal: stage 2 decides.)"""
    folded = " ".join(text.words(message))
    if pending_confirmation:
        if _CONFIRM.search(folded):
            return "confirm"
        if _DECLINE.search(folded):
            return "decline"
    if _RECALL.search(folded):
        return "recall"
    if _DIFFERENT.search(folded):
        return "different"
    if _SAME.search(folded):
        return "same"
    if _CORRECT.search(folded) or _denies_relation(folded.split()):
        return "correct"
    # "unutma" (remember) is checked before "unut" (forget).
    if _REMEMBER.search(folded):
        return "remember"
    if _FORGET.search(folded):
        return "forget"
    return None


def _denies_relation(words: Sequence[str]) -> bool:
    """ "Ahmet benim kuzenim değil", "Ahmet ile Mehmet kardeş değil", "evli değiller"."""
    for i in range(len(words) - 1):
        m = relations.match_at(words, i)
        head = (m[1] if m else 1) if m or words[i] in ("akraba", "evli") else 0
        nxt = words[i + head + 1] if i + head + 1 < len(words) else ""
        if (
            head
            and i + head < len(words)
            and words[i + head].startswith("degil")
            and not words[i + head].startswith(("degilmi", "degil mi"))
            and not re.fullmatch(r"m[iu](?:dir|dur|ydi|ydu|sin|sun|yim|yum)?", nxt)
        ):
            return True
    return False


# ----- stage 2: what exactly ------------------------------------------------------------
RULES = """\
[LAZIS İÇ GÖREVİ — bu bir kullanıcı mesajı değildir. Yanıt yazma, yalnızca JSON üret.]

Kullanıcının son mesajı LAZIS'in kişisel hafızasıyla ilgili bir istek olabilir. Ne istediğini \
belirle:
- action="remember": bir bilgiyi kaydetmemi istiyor ("bunu unutma", "kaydet", "aklında tut").
- action="correct": hafızadaki bir bilginin yanlış olduğunu söyleyip doğrusunu veriyor.
- action="forget": bir bilgiyi unutmamı/silmemi istiyor.
- action="none": hafıza isteği değil ("dosyayı sil", "unuttum", sıradan sohbet).

remember/correct için items: kaydedilecek bilgiler (alanlar aşağıda). Her öğe kullanıcının \
mesajından birebir kısa bir alıntı (quote) içermeli. correct için change=true. Şifre, PIN, \
API anahtarı, kart/IBAN/kimlik numarası ASLA items'a yazılmaz.
relations: ilişki bilgileri (kim kimin nesi), kullanıcının açıkça söylediği kadarıyla. Kaynak \
kullanıcı ise source boş. "Ahmet kuzenim değil", "Ahmet ile Mehmet kardeş değil" → negated=true \
(action=correct). "Ahmet çocukluk arkadaşım değil, iş arkadaşım" → eskisi için negated=true, \
yenisi için correction=true. "Artık birlikte çalışmıyoruz" gibi bitişlerde change=true, \
status="ended". Örnek: "Kemal aslında Sibel'in ağabeyi değil, kuzeni." → iki öğe: \
{source:"Sibel", type:"sibling", target:"Kemal", negated:true} ve {source:"Sibel", \
type:"cousin", target:"Kemal", correction:true} (kullanıcı bu ilişkinin ucu değil). \
Zincirden ilişki türetme. Alanlar: message ("m1"), quote, source, \
source_relation, source_kind, type, target, target_relation, target_kind, negated, correction, \
change, status, certain, time, statement.
forget için: forget_scope = "last" (az önce söylediğim bu bilgi: "bunu unut"), "fact" (belirli \
bir bilgi), "topic" (bir kişinin/kullanıcının belirli bir konusu: "Ahmet'in mesleği"), "entity" \
(bir kişi/proje hakkındaki her şey), "relation" (iki kişi arasındaki ilişki: "Ahmet ile \
Mehmet arasındaki ilişkiyi unut"; forget_other: diğer kişi, kullanıcı ise boş; forget_type: \
ilişki türü ya da tümü için boş). forget_entity: kişi/proje adı (kullanıcının kendisi ise \
boş), forget_relation: ilişkisi (biliniyorsa), forget_predicate: konu (yüklem anahtarı ya da \
boş), forget_value: unutulacak değer (biliniyorsa).
Öğe alanları: message (her zaman "m1"), quote, entity, relation, predicate, value, statement \
(tek cümle, üçüncü şahıs), change, replaces, certain, sensitive, importance.
JSON'u tek satırda, girintisiz yaz."""


def instruction(message: str) -> str:
    return "\n".join(
        [
            RULES,
            "",
            extraction.predicates_for_prompt(),
            "İlişki türleri (type):",
            relations.describe_for_prompt(),
            "",
            "Kullanıcının son mesajı:",
            f"[m1] «{message[: extraction.MAX_TARGET_CHARS]}»",
        ]
    )


def schema() -> dict[str, Any]:
    item = extraction.schema()["properties"]["items"]
    s: dict[str, Any] = {"type": "string"}
    props: dict[str, Any] = {
        "action": {"type": "string", "enum": ["none", "remember", "correct", "forget"]},
        "items": item,
        "relations": extraction.schema()["properties"]["relations"],
        "forget_scope": {
            "type": "string",
            "enum": ["", "last", "fact", "topic", "entity", "relation"],
        },
        "forget_entity": s,
        "forget_relation": s,
        "forget_predicate": {"type": "string", "enum": ["", *registry.keys()]},
        "forget_value": s,
        "forget_other": s,
        "forget_type": {"type": "string", "enum": ["", *relations.KEYS]},
    }
    return {"type": "object", "properties": props, "required": list(props),
            "additionalProperties": False}  # fmt: skip


@dataclass(frozen=True)
class Command:
    action: Literal["none", "remember", "correct", "forget"]
    items: tuple[dict[str, Any], ...] = ()
    scope: str = ""
    entity: str = ""
    relation: str = ""
    predicate: str = ""
    value: str = ""
    relations: tuple[dict[str, Any], ...] = ()
    other: str = ""
    rel_type: str = ""


def parse(raw: str) -> Command | None:
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    d = cast(dict[str, Any], data)
    action = d.get("action")
    if action not in ("none", "remember", "correct", "forget"):
        return None
    items = d.get("items")

    def s(key: str) -> str:
        v = d.get(key)
        return v.strip()[:120] if isinstance(v, str) else ""

    return Command(
        action=cast(Any, action),
        items=tuple(cast(dict[str, Any], i) for i in cast(list[Any], items) if isinstance(i, dict))
        if isinstance(items, list)
        else (),
        scope=s("forget_scope"),
        entity=s("forget_entity"),
        relation=s("forget_relation"),
        predicate=s("forget_predicate"),
        value=s("forget_value"),
        relations=tuple(extraction.parse_relations(raw)),
        other=s("forget_other"),
        rel_type=s("forget_type") if s("forget_type") in relations.TYPES else "",
    )


# ----- outcomes -------------------------------------------------------------------------
@dataclass
class Outcome:
    """What really happened, for the HAFIZA İŞLEMİ notice (and diagnostics: counts only)."""

    kind: Literal[
        "saved", "corrected", "forgotten", "confirm_needed", "ambiguous", "not_found",
        "refused", "nothing", "failed", "declined", "untrusted_model", "secret_not_stored",
        "merged", "distinguished",
    ]  # fmt: skip
    lines: list[str] = field(default_factory=list[str])
    counts: dict[str, int] = field(default_factory=dict[str, int])

    def notice(self) -> str:
        body = {
            "saved": "Kaydedildi (veritabanına yazıldı):",
            "corrected": "Düzeltildi (eski bilgi geçmişte tutuluyor):",
            "forgotten": "Silindi (hafızadan, aramadan ve geçmiş sürümlerden kaldırıldı):",
            "confirm_needed": "Henüz silinmedi — kullanıcının onayı gerekiyor:",
            "ambiguous": "Henüz bir şey yapılmadı — hangisinin kastedildiği belirsiz:",
            "not_found": "Hafızada bununla eşleşen bir kayıt bulunamadı; hiçbir şey silinmedi.",
            "refused": "Kaydedilmedi:",
            "nothing": "Bu mesajda kaydedilecek ya da silinecek bir bilgi bulunamadı; hafıza "
            "değişmedi.",
            "failed": "Hafıza işlemi teknik bir hata nedeniyle yapılamadı; hafıza değişmedi.",
            "declined": "Silme iptal edildi; hiçbir şey silinmedi.",
            "untrusted_model": "Şu anki yedek model hafızaya yazamaz; hafıza değişmedi. "
            "Kullanıcı ana modele dönebilir ya da Hafıza ekranını kullanabilir.",
            "secret_not_stored": "Bu mesajdaki gizli bilgi (şifre, anahtar, kart, IBAN ya da "
            "kimlik numarası) hafızaya kaydedilmedi ve kaydedilmeyecek (güvenlik kuralı).",
            "merged": "Birleştirildi (iki kayıt artık tek kişi; eski hâli geçmişte tutuluyor):",
            "distinguished": "Kaydedildi: bunlar farklı kişiler; bir daha karıştırılmayacak:",
        }[self.kind]
        rules = {
            "saved": "Yalnızca bu bildirimde kaydedildiği yazanlar için 'kaydettim' de.",
            "corrected": "Düzelttiğini kısaca söyle.",
            "forgotten": "Unuttuğunu kısaca söyle ve şunu da ekle: sohbet geçmişindeki eski "
            "mesajlar ve yedekler bu işlemle silinmez (onlar ayrı tutulur). Silinen bilgiyi "
            "tekrar etme.",
            "confirm_needed": "Silmeden önce kullanıcıdan açıkça onay iste (evet/hayır).",
            "ambiguous": "Hangisini kastettiğini sor.",
            "not_found": "Kayıt bulamadığını söyle; unuttum deme.",
            "refused": "Neden kaydedilmediğini kısaca açıkla; kaydettim ya da not aldım deme.",
            "nothing": "Kaydettim, not aldım, not ettim ya da unuttum deme; neyi kaydetmemi "
            "istediğini sorabilirsin.",
            "failed": "Kaydettim, not aldım ya da unuttum deme; işlemin yapılamadığını söyle.",
            "declined": "Silmediğini söyle.",
            "untrusted_model": "Kaydettim, not aldım ya da unuttum deme.",
            "secret_not_stored": "Kaydettim ya da not aldım deme; gizli bilgiyi yanıtında tekrar "
            "etme. Gerekirse bunun için bir parola yöneticisi önerebilirsin.",
            "merged": "Birleştirdiğini kısaca söyle.",
            "distinguished": "Bunları ayrı kişiler olarak tuttuğunu kısaca söyle.",
        }[self.kind]
        lines = [NOTICE_START, body, *(f"- {_safe(x)}" for x in self.lines), rules, NOTICE_END]
        return "\n".join(lines)


_REFUSAL = {
    "secret": "şifre, anahtar, kart, IBAN ya da kimlik numarası genel hafızada tutulmaz "
    "(güvenlik kuralı)",
    "instruction_like": "kural ya da kimlik değiştirmeye yönelik metinler hafızaya bilgi "
    "olarak alınmaz",
    "quote_not_found": "bilgi mesajda açıkça yer almıyor",
}


def _safe(s: str) -> str:
    return s.replace("===", "=").replace("\n", " ").strip()


# ----- execution (database thread) --------------------------------------------------------
def apply_items(
    conn: Connection,
    cmd: Command,
    *,
    message_id: str,
    message: str,
    conversation_id: str,
) -> Outcome:
    """remember / correct: validated like extraction (the quote must be in this message),
    then written as an explicit request (sensitive allowed, secrets never)."""
    target = Target("m1", message_id, message)
    from lazis.memory.orchestrator import extraction_context

    known = extraction_context(conn, [target]).known
    checked = extraction.validate(cmd.items, [target])
    facts, from_items = extraction.relation_items(checked.accepted)
    found, rel_dropped = extraction.validate_relations(cmd.relations, [target], known)
    stated = extraction.stated_correction(message)
    if stated:
        # "X aslında Y'nin A'sı değil, B'si": the user's grammar says exactly what changes;
        # it replaces whatever the model proposed for the same pair.
        pairs = {(text.name_key(o) if o else "", text.name_key(x)) for o, _, _, x in stated}
        found = [
            f for f in found
            if (text.name_key(f.candidate.source.name) if f.candidate.source else "",
                text.name_key(f.candidate.target.name)) not in pairs
            and (text.name_key(f.candidate.target.name),
                 text.name_key(f.candidate.source.name) if f.candidate.source else "") not in pairs
        ]  # fmt: skip
        for owner, old, new, who in stated:
            src = EntityRef(owner) if owner else None
            for key, neg in ((old, True), (new, False)):
                found.append(extraction.ExtractedRel(message_id, RelCandidate(
                    type=key, source=src, target=EntityRef(who), quote=message[:160],
                    negated=neg, correction=not neg)))  # fmt: skip
    facts, _ = extraction.covered_by_relations(facts, [*from_items, *found])
    facts += extraction.facts_from_relations(facts, [*from_items, *found])
    checked = replace(checked, accepted=facts)
    candidates = [
        replace(
            e.candidate, origin="requested", change=e.candidate.change or cmd.action == "correct"
        )
        for e in checked.accepted
    ]
    report = service.apply_candidates(
        conn,
        candidates,
        source=Source("message", message_id, conversation_id),
        explicit=True,
        actor="user",
        kind="user_request",
    )
    rel_cands = [
        replace(e.candidate, origin="requested",
                correction=e.candidate.correction or (cmd.action == "correct"
                                                      and not e.candidate.negated))
        for e in [*from_items, *found]
    ]  # fmt: skip
    rel_report = rels.apply_relations(
        conn,
        rel_cands,
        source=Source("message", message_id, conversation_id),
        explicit=True,
        actor="user",
        kind="user_request",
    )
    saved = [m for m in (repo.get_memory(conn, i) for i in report.created + report.updated) if m]
    lines = [m.content for m in saved] + _relation_lines(conn, rel_report)
    reasons = {**checked.dropped, **report.dropped, **rel_dropped, **rel_report.dropped}
    inbox = report.inbox + rel_report.inbox
    if inbox:
        items = [repo.get_inbox(conn, i) for i in inbox]
        labels = [i.summary for i in items if i is not None]
        if not lines:
            return Outcome("ambiguous", labels, {"inbox": len(labels)})
    if lines:
        kind: Literal["saved", "corrected"] = (
            "corrected"
            if cmd.action == "correct" or rel_report.retracted or rel_report.superseded
            else "saved"
        )
        return Outcome(kind, lines, {"saved": len(saved), **rel_report.counts()})
    refused = [_REFUSAL[r] for r in reasons if r in _REFUSAL]
    if refused:
        return Outcome("refused", refused, {"refused": sum(reasons.values())})
    return Outcome("nothing")


def _relation_lines(conn: Connection, report: rels.RelReport) -> list[str]:
    """What really changed in the graph, in the notice's words."""
    out: list[str] = []

    def text_of(rel_id: str) -> str | None:
        r = gs.get_relationship(conn, rel_id)
        return None if r is None else rels.statement_for(conn, r.source_id, r.type, r.target_id)

    for rid in report.created + report.updated:
        if (t := text_of(rid)) is not None:
            out.append(t)
    for rid in report.retracted:
        if (t := text_of(rid)) is not None:
            out.append(f"artık geçerli değil (geri alındı): {t}")
    for rid in report.superseded + report.ended:
        if (t := text_of(rid)) is not None:
            out.append(f"eski bilgi geçmişe alındı: {t}")
    return out


def _subject(conn: Connection, name: str, relation: str) -> tuple[str, Entity | None, list[Entity]]:
    """('user'|'one'|'none'|'many', entity, namesakes) for a forget target."""
    key = text.name_key(name)
    if not key or key in {"kullanici", "ben", "beni", "benim"}:
        return "user", None, []
    found = repo.find_entities(conn, key)
    if not found:
        return "none", None, []
    res = resolver.resolve(EntityRef(name, found[0].kind, relation or None), found)
    if res.kind == "existing" and res.entity_id is not None:
        return "one", repo.get_entity(conn, res.entity_id), []
    return "many", None, found


def _label(e: Entity) -> str:
    return f"{e.name} ({e.relation})" if e.relation else e.name


def _matching(memories: Sequence[Memory], value: str) -> list[Memory]:
    if not value:
        return list(memories)
    key = text.fold(value)
    return [
        m
        for m in memories
        if key in m.value_key
        or key in text.fold(m.content)
        or text.similarity(value, m.value) >= 0.5
    ]


def forget(
    conn: Connection,
    cmd: Command,
    *,
    conversation_id: str,
    recent_user_message_ids: Sequence[str],
) -> Outcome:
    statuses = ("active", "superseded", "retracted")
    if cmd.scope == "last":
        ids = _from_messages(conn, recent_user_message_ids)
        if not ids:
            _skip_jobs(conn, recent_user_message_ids)
            return Outcome("not_found")
        found = [m for m in (repo.get_memory(conn, i) for i in ids) if m is not None]
        res = service.forget_memories(conn, [m.id for m in found])
        _skip_jobs(conn, recent_user_message_ids)
        return Outcome("forgotten", [m.content for m in found], {"forgotten": res.memories})

    if cmd.scope == "relation":
        return _forget_relation(conn, cmd)
    who, ent, namesakes = _subject(conn, cmd.entity, cmd.relation)
    if who == "none":
        return Outcome("not_found")
    if who == "many":
        return Outcome("ambiguous", [", ".join(_label(e) for e in namesakes)])
    subject_id = ent.id if ent is not None else None

    if cmd.scope == "entity" and ent is not None:
        count = len(repo.memories_for_subject(conn, ent.id, statuses=statuses))
        now = utc_now_iso()
        with UnitOfWork(conn, kind="review_action", actor="user", summary="onay") as _:
            repo.insert_inbox(
                conn,
                type="destructive",
                summary=f"{_label(ent)} hakkındaki {count} kaydın silinmesi",
                payload={"entity_id": ent.id, "count": count},
                now=now,
                conversation_id=conversation_id,
            )
        return Outcome(
            "confirm_needed",
            [f"{_label(ent)} hakkındaki tüm kayıtlar ({count} kayıt) ve kişi kaydının kendisi"],
            {"inbox": 1, "pending": count},
        )

    # A named topic ("Ahmet'in mesleği") means every value of it, past ones included — even
    # when the model also quoted the current value.
    if cmd.predicate and cmd.scope in ("topic", "fact", ""):
        found = repo.memories_for_subject(
            conn, subject_id, predicate=cmd.predicate, statuses=statuses
        )
        if not found:
            return Outcome("not_found")
        res = service.forget_topic(conn, subject_id, cmd.predicate)
        p = registry.get(cmd.predicate)
        who_label = _label(ent) if ent else "kullanıcı"
        return Outcome(
            "forgotten",
            [f"{who_label} — {p.label if p else cmd.predicate} ({res.memories} kayıt, eski "
             "değerler dahil)"],
            {"forgotten": res.memories},
        )  # fmt: skip

    pool = repo.memories_for_subject(
        conn, subject_id, predicate=cmd.predicate or None, statuses=statuses
    )
    found = _matching(pool, cmd.value)
    if not found or (not cmd.value and not cmd.predicate):
        return Outcome("not_found")
    res = service.forget_memories(conn, [m.id for m in found])
    return Outcome("forgotten", [m.content for m in found], {"forgotten": res.memories})


def _end_ids(conn: Connection, name: str, relation: str) -> list[str] | None:
    """Candidate ids for one end of a relationship to forget (None: nobody by that name)."""
    who, ent, namesakes = _subject(conn, name, relation)
    if who == "none":
        return None
    if who == "user":
        return [USER_ID]
    return [ent.id] if ent is not None else [e.id for e in namesakes]


def _forget_relation(conn: Connection, cmd: Command) -> Outcome:
    ends_a = _end_ids(conn, cmd.entity, cmd.relation)
    ends_b = _end_ids(conn, cmd.other, "")
    if ends_a is None or ends_b is None:
        return Outcome("not_found")
    # Two namesakes: the pair meant is the one that has a relationship ("Ahmet ile Mehmet
    # arasındaki ilişki" — the Ahmet linked to Mehmet). Still several: ask.
    pairs = [(x, y) for x in ends_a for y in ends_b if x != y
             and gs.relationships_between(conn, x, y)]  # fmt: skip
    if not pairs:
        return Outcome("not_found")
    if len(pairs) > 1:
        names = [e for e in (repo.get_entity(conn, i) for p in pairs for i in p) if e is not None]
        return Outcome("ambiguous", [", ".join(dict.fromkeys(_label(e) for e in names))])
    a, b = pairs[0]
    found = gs.relationships_between(conn, a, b)
    if cmd.rel_type:
        wanted = set(relations.answers(cmd.rel_type))
        inverse = relations.reading_from_target(cmd.rel_type)
        found = [r for r in found if r.type in wanted or r.type == inverse]
    if not found:
        return Outcome("not_found")
    lines = [rels.statement_for(conn, r.source_id, r.type, r.target_id) for r in found]
    if cmd.rel_type:
        res = rels.forget_relationships(conn, [r.id for r in found])
    else:  # every relationship between the two, and none is learned again
        res = rels.forget_pair(conn, a, b)
    return Outcome("forgotten", lines, {"forgotten_relations": res.relationships})


def _from_messages(conn: Connection, message_ids: Sequence[str]) -> list[str]:
    if not message_ids:
        return []
    marks = ",".join("?" * len(message_ids))
    rows = conn.execute(
        f"SELECT DISTINCT memory_id FROM memory_evidence WHERE source_ref IN ({marks})",  # noqa: S608
        tuple(message_ids),
    ).fetchall()
    return [str(r[0]) for r in rows]


def _skip_jobs(conn: Connection, message_ids: Sequence[str]) -> None:
    """ "Bunu unut" before the background job ran: it must not learn it afterwards."""
    now = utc_now_iso()
    for mid in message_ids:
        job = repo.job_for_message(conn, mid)
        if job is not None and job.status in ("queued", "deferred", "running"):
            repo.set_job(conn, job.id, status="skipped", now=now, error="forgotten_on_request")


def skip_job(conn: Connection, message_id: str) -> None:
    """The request was carried out synchronously; its background job has nothing to add."""
    _skip_jobs(conn, [message_id])


def pending_confirmation(conn: Connection, conversation_id: str) -> str | None:
    for item in repo.list_inbox(conn, status="open", types=("destructive",)):
        if item.conversation_id == conversation_id:
            return item.id
    return None


def confirm(conn: Connection, item_id: str) -> Outcome:
    item = repo.get_inbox(conn, item_id)
    if item is None or item.status != "open":
        return Outcome("not_found")
    if item.payload.get("action") == "merge":
        return _merge(conn, item_id, str(item.payload["keep"]), str(item.payload["merge"]))
    entity_id = str(item.payload.get("entity_id", ""))
    ent = repo.get_entity(conn, entity_id)
    if ent is None:
        repo.resolve_inbox(conn, item_id, status="dismissed", resolution="gone", now=utc_now_iso())
        return Outcome("not_found")
    label = _label(ent)
    res = service.forget_entity(conn, entity_id)  # also removes inbox items about the entity
    if repo.get_inbox(conn, item_id) is not None:
        repo.resolve_inbox(
            conn, item_id, status="resolved", resolution="confirmed", now=utc_now_iso()
        )
    return Outcome(
        "forgotten",
        [f"{label} hakkındaki {res.memories} kayıt ve kişi kaydı"],
        {"forgotten": res.memories, "entities": res.entities},
    )


def decline(conn: Connection, item_id: str) -> Outcome:
    if repo.get_inbox(conn, item_id) is not None:
        repo.resolve_inbox(
            conn, item_id, status="dismissed", resolution="declined", now=utc_now_iso()
        )
    return Outcome("declined")


# ----- identity: "aynı kişi" / "farklı kişiler" (deterministic, no model) -----------------------
def _pair(conn: Connection, message: str) -> tuple[Entity, Entity] | list[Entity] | None:
    """The two records a same/different statement is about: one name with exactly two
    namesakes ("bu iki Ahmet"), or two names. A list: too many candidates (ask)."""
    from lazis.memory import graph

    names = [e for e in graph.message_names(conn, message) if e]
    ents = [[x for x in (repo.get_entity(conn, i) for i in ids) if x] for ids in names]
    if len(ents) == 1 and len(ents[0]) == 2:
        a, b = ents[0]
        return a, b
    if len(ents) == 1 and len(ents[0]) > 2:
        return ents[0]
    if len(ents) >= 2:
        firsts = [group for group in ents if group][:2]
        if len(firsts) == 2 and len(firsts[0]) == 1 and len(firsts[1]) == 1:
            a, b = firsts[0][0], firsts[1][0]
            return None if a.id == b.id else (a, b)
        return [e for group in firsts for e in group]
    return None


def identity(
    conn: Connection, intent: Intent, message: str, *, conversation_id: str
) -> Outcome | None:
    """None: no pair of stored records in the message (not an identity statement for us)."""
    pair = _pair(conn, message)
    if pair is None:
        return None
    if isinstance(pair, list):
        return Outcome("ambiguous", [", ".join(_label(e) for e in pair)])
    a, b = sorted(pair, key=lambda e: e.created_at)
    if intent == "different":
        now = utc_now_iso()
        with UnitOfWork(conn, kind="user_request", actor="user", summary="farklı kişiler") as uow:
            gs.add_distinction(conn, a.id, b.id, now)
            write_audit(conn, category="memory", action="distinguish", outcome="success",
                        actor="user", change_set_id=uow.change_set_id,
                        target_refs=[a.id, b.id])  # fmt: skip
        return Outcome("distinguished", [f"{_label(a)} ≠ {_label(b)}"], {"distinctions": 1})
    if gs.are_distinct(conn, a.id, b.id):
        return Outcome("refused", [f"{_label(a)} ve {_label(b)} daha önce farklı kişiler olarak "
                                   "işaretlendi; birleştirmek için önce bunu Hafıza ekranından "
                                   "kaldırmak gerekir"])  # fmt: skip
    now = utc_now_iso()
    with UnitOfWork(conn, kind="review_action", actor="user", summary="onay") as _:
        repo.insert_inbox(
            conn,
            type="destructive",
            summary=f"{_label(a)} ile {_label(b)} tek kişi olarak birleştirilsin mi?",
            payload={"action": "merge", "keep": a.id, "merge": b.id},
            now=now,
            conversation_id=conversation_id,
        )
    return Outcome(
        "confirm_needed",
        [f"{_label(a)} ile {_label(b)} birleştirilecek (bilgileri ve ilişkileri tek kişide "
         "toplanır)"],
        {"inbox": 1},
    )  # fmt: skip


def _merge(conn: Connection, item_id: str, keep: str, other: str) -> Outcome:
    a, b = repo.get_entity(conn, keep), repo.get_entity(conn, other)
    now = utc_now_iso()
    if a is None or b is None or a.status != "active" or b.status != "active":
        repo.resolve_inbox(conn, item_id, status="dismissed", resolution="gone", now=now)
        return Outcome("not_found")
    try:
        service.merge_entities(conn, a.id, b.id)
    except ValueError as exc:
        repo.resolve_inbox(conn, item_id, status="dismissed", resolution="refused", now=now)
        return Outcome("refused", [str(exc)])
    repo.resolve_inbox(conn, item_id, status="resolved", resolution="confirmed", now=now)
    return Outcome("merged", [f"{_label(a)} + {_label(b)} → {a.name}"], {"merged": 1})
