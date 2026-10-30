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
from lazis.memory import (
    extraction,
    namesakes,
    policy,
    refine,
    registry,
    relations,
    resolver,
    service,
    text,
)
from lazis.memory import graphstore as gs
from lazis.memory import relationships as rels
from lazis.memory import repository as repo
from lazis.memory.extraction import Target
from lazis.memory.models import USER_ID, ApplyReport, Entity, EntityRef, Memory
from lazis.memory.service import Source
from lazis.storage.driver import Connection
from lazis.storage.repositories import write_audit
from lazis.storage.unit_of_work import UnitOfWork

Intent = Literal[
    "remember",
    "forget",
    "correct",
    "recall",
    "confirm",
    "decline",
    "same",
    "different",
    "choose",
]

# The header says what the note is to the model only; a label the model can quote back
# ("'HAFIZA İŞLEMİ' bildirimi varsa kaydedebilirim", Phase 7.1) is not in the persona any more.
NOTICE_START = "=== SİSTEM NOTU (kullanıcıya görünmez) ==="
NOTICE_END = "=== SİSTEM NOTU SONU ==="

_REMEMBER = re.compile(
    r"\b(unutma(?:yin|yiniz|yasin|man)?\b|unutmani istemiyorum|unutmamani (?:istiyorum|rica)"
    r"|hatirla(?:sana|yin|r misin|\b)|hatirlamani (?:istiyorum|rica)"
    r"|aklinda (?:tut|olsun|bulunsun)|aklinin bir kosesinde|bir kenara (?:yaz|not)"
    r"|kaydet(?!me(?:yin|yiniz|sin)?\b|ti|se[mk]\b|meli(?!sin))"
    r"|kaydeder misin|kaydedebilir|kaydedin\b|kayit et"
    r"|kayda (?:gecir|al)|kayit altina al|kaydini tut"
    r"|not (?:al|et|dus)\b|not (?:al|ed)(?:ir misin|abilir|ebilir|in|iniz|sana|sene)\b"
    r"|not etsene|hafizana|bunu bil\b)"
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
# Worded positively: naming the forbidden phrases primed them (measured with Gemma on 10
# statements: 3/10 replies claimed "not aldım" with the old wording, 1/10 with this one).
PENDING_NOTICE = (
    f"{NOTICE_START}\n"
    "Bu mesajdaki bilgiler henüz hafızaya yazılmadı (gerekirse sonra arka planda yazılır). "
    "Yanıtta yalnızca anladığını göster ve konuya devam et; kaydetmekten, not almaktan, "
    "öğrenmekten ya da hatırlayacağından söz etme.\n"
    f"{NOTICE_END}"
)
_QUESTION = re.compile(r"\?|\b(mi|mı|mu|mü|misin|mısın|musun|müsün|miyim|mıyım)\b")


def looks_like_statement(message: str) -> bool:
    """A message that may tell LAZIS something (not a question, not a one-word reply)."""
    return len(message.split()) >= 3 and not _QUESTION.search(text.casefold(message))


def contains_secret(message: str) -> bool:
    return policy.secret_kind(message) is not None


def detect(message: str, *, pending_confirmation: bool = False) -> Intent | None:
    """Stage 1: does this message look like a memory request? (Liberal: stage 2 decides.)
    Text the user quotes is not a request ("'Bunu not al' ifadesini İngilizceye çevir")."""
    folded = " ".join(text.words(extraction.users_own_words(message)))
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


# ----- what an explicit request owns (Phase 9.1) -------------------------------------------
# A remember / correct / forget request is carried out here, before the reply, and what it asks
# for is written only by it: failed, refused, cancelled, waiting or blocked, the same thing is not
# written afterwards by background learning. Learning reads the rest of the message.
REQUEST_INTENTS = frozenset({"remember", "correct", "forget"})
_SENTENCE = re.compile(r"(?<=[.!?;…])\s+|\n+")
_BARE_WORDS = frozenset(
    {"yanlis", "hatirliyorsun", "biliyorsun", "kaydettin", "anlamissin", "oyle", "degil",
     "hayir", "hafizandan", "bilgiyi", "bilgini", "bilgimi", "kaydi", "kaydini", "onu", "o"}
)  # fmt: skip


def _bare(sentence: str) -> bool:
    """A request with nothing of its own ("Bunu unutma.", "Yanlış hatırlıyorsun.", "Bunu
    sil."): what it is about is in the other sentences."""
    folded = " ".join(text.words(extraction.users_own_words(sentence)))
    for rx in (_REMEMBER, _FORGET, _CORRECT):
        folded = rx.sub(" ", folded)
    return not [w for w in folded.split() if w not in _CUE_WORDS and w not in _BARE_WORDS]


def learnable_part(message: str) -> str:
    """The part of a message background learning may read: all of it, unless the message is an
    explicit memory request — then the sentences the request covers are left out (all of them
    when a request sentence names nothing itself). Deterministic, from the user's words only,
    so it holds whatever order the request and learning run in."""
    if detect(message) not in REQUEST_INTENTS:
        return message
    sentences = [s for s in _SENTENCE.split(message.strip()) if s.strip()]
    kept: list[str] = []
    for s in sentences:
        if detect(s) in REQUEST_INTENTS:
            if _bare(s):
                return ""
            continue
        kept.append(s.strip())
    return " ".join(kept)


# "Az önce kaydettin mi?": answered from the database, not from what the reply believes.
_ASKS_SAVED = re.compile(
    r"\b(?:kaydettin|kaydedildi|kaydedebildin|not (?:aldin|ettin|edildi|alindi)|"
    r"hafizana (?:aldin|kaydettin|ekledin|yazdin|islendi)|aklinda tuttun|ekledin|"
    r"guncelledin|duzelttin|yazdin) (?:mi|mu)\b"
)


def asks_if_saved(message: str) -> bool:
    return bool(_ASKS_SAVED.search(" ".join(text.words(message))))


def saved_from(conn: Connection, message_ids: Sequence[str]) -> list[str]:
    """What the memory holds now that came from these messages (any status but deleted)."""
    found = [repo.get_memory(conn, i) for i in _from_messages(conn, message_ids)]
    return [m.content for m in found if m is not None and m.status != "retracted"]


def learning_waits(conn: Connection, message_ids: Sequence[str]) -> bool:
    """Background learning has not read one of these messages yet."""
    jobs = [repo.job_for_message(conn, mid) for mid in message_ids]
    return any(j is not None and j.status in ("queued", "deferred", "running") for j in jobs)


def saved_notice(lines: Sequence[str], *, waiting: bool = False) -> str:
    if not lines and waiting:
        body = [
            "Önceki mesajlardaki bilgiler henüz hafızaya yazılmadı (veritabanında yok; arka "
            "planda işlenmeyi bekliyor).",
            "'Evet' deme; henüz kaydedilmediğini kısaca söyle.",
        ]
        return "\n".join([NOTICE_START, *body, NOTICE_END])
    if lines:
        body = [
            "Önceki mesajlardan hafızada kayıtlı olanlar (veritabanından okundu):",
            *(f"- {_safe(x)}" for x in lines),
            "Yalnızca bunların kayıtlı olduğunu söyle; başka bir şeyi kaydettiğini söyleme.",
        ]
    else:
        body = [
            "Önceki mesajlardaki bilgilerden hiçbiri hafızaya yazılmadı (veritabanında yok).",
            "'Evet' deme; kaydedilmediğini açıkça ve kısaca söyle. İstersen kaydetmeyi yeniden "
            "denemeyi önerebilirsin.",
        ]
    return "\n".join([NOTICE_START, *body, NOTICE_END])


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


# remember: the same instruction as background learning (measured on the Phase 6 gold set),
# with the request stated. The command instruction above produced unusable items for plain
# requests (Phase 7.2: "Burak'ın düğünü haziranda" → predicate "device", nothing saved).
REMEMBER_NOTE = """\
Bu bir AÇIK KAYIT İSTEĞİ olabilir: kullanıcı bir bilgiyi hafızaya kaydetmemi istiyor ("bunu \
unutma", "not al", "kaydet", "aklında tut", "hatırla").
- action="remember": kaydedilmesini istediği bilgiyi aşağıdaki kurallarla items ve relations \
olarak çıkar. İstek kalıbı ("lütfen şunu not al", "bunu unutma") bilgi değildir; quote bilginin \
kendisinden alınır. Kural 2 burada yalnızca istek kalıbı için geçerlidir.
- action="none": mesaj aslında hafıza isteği değilse (metin ya da not hazırlatma, çeviri, bir \
uygulama ya da düğme hakkında konuşma); items ve relations boş."""


# "Ahmet'in doğum günü 5 Mayıs." → "Bunu unutma.": the request came after the message.
REMEMBER_PREVIOUS_NOTE = """\
Bu bir AÇIK KAYIT İSTEĞİDİR: kullanıcı aşağıdaki mesajını yazdıktan sonra "bunu unutma / not \
al / kaydet" diyerek bu mesajdaki bilgiyi hafızaya kaydetmemi istedi. action="remember"; \
mesajdaki kalıcı bilgiyi aşağıdaki kurallarla items ve relations olarak çıkar (kaydedilecek \
bilgi yoksa items boş)."""


def remember_instruction(message: str, ctx: Any, *, previous: bool = False) -> str:
    """``ctx``: :class:`lazis.memory.orchestrator.ExtractionContext` for this message;
    ``previous``: the message is the one before a bare "bunu unutma"."""
    return extraction.build_instruction(
        [Target("m1", "", message)],
        known=ctx.known,
        user_facts=ctx.user_facts,
        forgotten=ctx.forgotten,
        questions=ctx.questions,
        request_note=REMEMBER_PREVIOUS_NOTE if previous else REMEMBER_NOTE,
    )


def remember_schema() -> dict[str, Any]:
    base = extraction.schema()
    props = {"action": {"type": "string", "enum": ["none", "remember"]}, **base["properties"]}
    return {**base, "properties": props, "required": list(props)}


def parse_remember(raw: str) -> Command | None:
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(data, dict) or cast(dict[str, Any], data).get("action") not in (
        "none",
        "remember",
    ):
        return None
    items = extraction.parse(raw) or []
    action = cast(dict[str, Any], data)["action"]
    return Command(action=action, items=tuple(items),
                   relations=tuple(extraction.parse_relations(raw)))  # fmt: skip


_CUE_WORDS = frozenset(
    {"bunu", "sunu", "bu", "su", "bilgiyi", "bunlari", "lutfen", "efendim", "lazis", "de",
     "da", "ve", "tamam", "peki", "olur", "mu", "mi", "misin", "musun", "simdi", "hemen",
     "ileride", "istiyorum", "istemiyorum", "rica", "ederim", "ediyorum", "sakin"}
)  # fmt: skip


def cue_only(message: str) -> bool:
    """ "Bunu unutma." — a request whose content is the previous message."""
    folded = " ".join(text.words(message))
    rest = _REMEMBER.sub(" ", folded)
    return len([w for w in rest.split() if w not in _CUE_WORDS]) == 0


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
        "merged", "distinguished", "cancelled",
    ]  # fmt: skip
    lines: list[str] = field(default_factory=list[str])
    counts: dict[str, int] = field(default_factory=dict[str, int])

    def notice(self) -> str:
        body = {
            "saved": "Kaydedildi (hafızaya yazıldı):",
            "corrected": "Düzeltildi (eski bilgi geçmişte tutuluyor):",
            "forgotten": "Silindi (hafızadan, aramadan ve geçmiş sürümlerden kaldırıldı):",
            "confirm_needed": "Henüz silinmedi — kullanıcının onayı gerekiyor:",
            "ambiguous": "Henüz bir şey yapılmadı — hangisinin kastedildiği belirsiz:",
            "not_found": "Hafızada bununla eşleşen bir kayıt bulunamadı; hiçbir şey silinmedi.",
            "refused": "Kaydedilmedi:",
            "nothing": "Bu mesajda kaydedilecek ya da silinecek bir bilgi bulunamadı; hafıza "
            "değişmedi.",
            "failed": "Kayıt ya da silme şu anda yapılamadı (teknik bir sorun); hafıza değişmedi.",
            "declined": "Silme iptal edildi; hiçbir şey silinmedi.",
            "untrusted_model": "Şu anki yedek model hafızaya yazamaz; hafıza değişmedi. "
            "Kullanıcı ana modele dönebilir ya da Hafıza ekranını kullanabilir.",
            "secret_not_stored": "Bu mesajdaki gizli bilgi (şifre, anahtar, kart, IBAN ya da "
            "kimlik numarası) hafızaya kaydedilmedi ve kaydedilmeyecek (güvenlik kuralı).",
            "merged": "Birleştirildi (iki kayıt artık tek kişi; eski hâli geçmişte tutuluyor):",
            "distinguished": "Kaydedildi: bunlar farklı kişiler; bir daha karıştırılmayacak:",
            "cancelled": "Bekleyen kayıt kullanıcının isteğiyle iptal edildi; hiçbir şey "
            "kaydedilmedi.",
        }[self.kind]
        rules = {
            "saved": "Yalnızca bu bildirimde kaydedildiği yazanlar için 'kaydettim' de.",
            "corrected": "Düzelttiğini kısaca söyle.",
            "forgotten": "Unuttuğunu kısaca söyle ve şunu da ekle: sohbet geçmişindeki eski "
            "mesajlar ve yedekler bu işlemle silinmez (onlar ayrı tutulur). Silinen bilgiyi "
            "tekrar etme.",
            "confirm_needed": "Silmeden önce kullanıcıdan açıkça onay iste (evet/hayır).",
            "ambiguous": "Hangisini kastettiğini seçenekleri sayarak sor (ör. 'Hangi Ahmet'ten "
            "bahsediyorsunuz efendim? Komşunuz olan mı, iş arkadaşınız olan mı?').",
            "not_found": "Kayıt bulamadığını söyle; unuttum deme.",
            "refused": "Neden kaydedilmediğini kısaca açıkla; kaydettim ya da not aldım deme.",
            "nothing": "Kaydettim, not aldım, not ettim ya da unuttum deme; neyi kaydetmemi "
            "istediğini sorabilirsin.",
            "failed": "Kaydettim, not aldım ya da unuttum deme; bunu şu anda yapamadığını kısaca "
            "ve doğal bir dille söyle (ör. 'Bunu şu anda kaydedemedim efendim').",
            "declined": "Silmediğini söyle.",
            "untrusted_model": "Kaydettim, not aldım ya da unuttum deme.",
            "secret_not_stored": "Kaydettim ya da not aldım deme; gizli bilgiyi yanıtında tekrar "
            "etme. Gerekirse bunun için bir parola yöneticisi önerebilirsin.",
            "merged": "Birleştirdiğini kısaca söyle.",
            "distinguished": "Bunları ayrı kişiler olarak tuttuğunu kısaca söyle.",
            "cancelled": "Kaydetmediğini kısaca söyle.",
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
    if cmd.action == "remember" and not checked.accepted and cmd.items:
        # An explicit request is not dropped for a wrong predicate: the user's words (the
        # quote is still checked) are kept as a note about the same subject.
        notes = extraction.validate([{**i, "predicate": "note"} for i in cmd.items], [target])
        if notes.accepted:
            notes.dropped.update({f"as_note_{k}": v for k, v in checked.dropped.items()})
            checked = notes
    facts, from_items = extraction.relation_items(checked.accepted)
    found, rel_dropped = extraction.validate_relations(cmd.relations, [target], known)
    facts, _ = extraction.covered_by_relations(facts, [*from_items, *found])
    facts += extraction.facts_from_relations(facts, [*from_items, *found])
    rels_in = [*from_items, *found]
    facts, rels_in = refine.refine(facts, rels_in, {message_id: message}, {})
    # Namesakes the user states ("iki Ahmet: biri komşum, diğeri iş arkadaşım"): planned from
    # the user's words before anything is resolved (ADR-0018).
    facts, rel_all, _ = namesakes.plan(
        conn, message, facts, rels_in, message_id=message_id,
        kind="user_request", actor="user",
    )  # fmt: skip
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
        for e in rel_all
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
        labels = [question_text(i) for i in items if i is not None]
        if not lines:
            return Outcome("ambiguous", labels, {"inbox": len(labels)})
    if lines:
        # Corrected only when something that was there really changed (Phase 9: a "correct"
        # answer that only wrote a new note was reported as a correction).
        kind: Literal["saved", "corrected"] = (
            "corrected"
            if report.superseded or rel_report.retracted or rel_report.superseded
            else "saved"
        )
        return Outcome(kind, lines, {"saved": len(saved), **rel_report.counts()})
    refused = [_REFUSAL[r] for r in reasons if r in _REFUSAL]
    if refused:
        return Outcome("refused", refused, {"refused": sum(reasons.values())})
    if cmd.action == "remember" and (known_lines := _already_known(conn, message, message_id)):
        # "Bunu unutma." after the fact was learned in the background (or said before): it is
        # in the memory already — saying "kaydedemedim" would be false.
        return Outcome("saved", [f"{x} (zaten kayıtlıydı)" for x in known_lines], {"known": 1})
    if cmd.action == "remember" and (note := _users_words_as_note(conn, message, message_id,
                                                                    conversation_id)):  # fmt: skip
        # The model accepted the request but proposed nothing ("Aklında olsun, hafta sonu
        # annemlere gideceğim" read as a passing plan): the user asked, so their own words are
        # kept as a note — checked like any other item (quote, secrets, instructions).
        return Outcome("saved", note, {"saved": len(note), "as_note": 1})
    return Outcome("nothing")


def request_content(message: str) -> str:
    """The part of an explicit request that is not the request itself: after a colon, or the
    clauses without the cue ("Aklında olsun, hafta sonu annemlere gideceğim")."""
    if ":" in message:
        return message.split(":", 1)[1].strip(" .")
    if detect(message) != "remember":
        return message.strip(" .")  # the message before a bare "Bunu unutma."
    parts = [p for p in re.split(r"[,;]", message) if p.strip()]
    rest = [p for p in parts if detect(p) != "remember"]
    return ", ".join(x.strip() for x in rest).strip(" .") if len(rest) < len(parts) else ""


def _users_words_as_note(conn: Connection, message: str, message_id: str,
                         conversation_id: str) -> list[str]:  # fmt: skip
    content = request_content(message)
    if len(text.words(content)) < 2:
        return []
    item = {"message": "m1", "quote": content, "entity": "", "relation": "", "predicate": "note",
            "value": content, "statement": f"Kullanıcının notu: {content}.", "change": False,
            "replaces": "", "certain": True, "sensitive": "", "importance": 0.6}  # fmt: skip
    checked = extraction.validate([item], [Target("m1", message_id, message)])
    if not checked.accepted:
        return []
    report = service.apply_candidates(
        conn, [replace(e.candidate, origin="requested") for e in checked.accepted],
        source=Source("message", message_id, conversation_id), explicit=True, actor="user",
        kind="user_request",
    )  # fmt: skip
    saved = [m for m in (repo.get_memory(conn, i) for i in report.created + report.updated) if m]
    return [m.content for m in saved]


def _already_known(conn: Connection, message: str, message_id: str) -> list[str]:
    """Active records that already hold what an explicit request asks to keep: learned from this
    very message, or about a person it names with a value it states."""
    from lazis.memory import graph

    found = [m for m in (repo.get_memory(conn, i) for i in _from_messages(conn, [message_id]))
             if m is not None and m.status == "active"]  # fmt: skip
    if not found:
        folded = " ".join(text.words(message))
        subjects = {i for ids in graph.message_names(conn, message) for i in ids}
        for sid in subjects:
            for m in repo.memories_for_subject(conn, sid):
                v = " ".join(text.words(m.value))
                if m.status == "active" and v and v in folded:
                    found.append(m)
    return [m.content for m in found][:5]


def already_saved(conn: Connection, message: str, message_id: str) -> Outcome | None:
    """A bare "Bunu unutma." whose own step failed, about a message the memory already holds
    (learned before the request): "kaydedemedim" would be false (Phase 9.1)."""
    known = _already_known(conn, message, message_id)
    if not known:
        return None
    return Outcome("saved", [f"{x} (zaten kayıtlıydı)" for x in known], {"known": 1})


def question_text(item: Any) -> str:
    """A "which Ahmet?" inbox item as the notice line: the question and its options."""
    options = [str(o.get("label", "")) for o in item.payload.get("options", []) if o.get("label")]
    return f"{item.summary} (seçenekler: {'; '.join(options)})" if options else item.summary


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


def _subject(conn: Connection, name: str, relation: str,
             message: str = "") -> tuple[str, Entity | None, list[Entity]]:  # fmt: skip
    """('user'|'one'|'none'|'many', entity, namesakes) for a forget target. The relation
    counts only when the user wrote it (Phase 9.1: "Elif'in nerede yaşadığını unut" with the
    model's "sibling" made the only Elif "ambiguous")."""
    key = text.name_key(name)
    if not key or key in {"kullanici", "ben", "beni", "benim"}:
        return "user", None, []
    found = repo.find_entities(conn, key)
    if not found:
        return "none", None, []
    if relation and message and not extraction.relation_said(relation, message):
        relation = ""
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
    message: str = "",
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
    name = cmd.entity
    if message and name and not text.mentions_name(text.words(message), text.name_key(name)):
        name = ""  # not a name the user wrote ("kahve", "phone" from the model)
    if message and not name and (owner := _owner_named(message)):
        # "Elif'in telefonunu sil" with no entity from the model: Elif's, never the user's
        # (Phase 9.1) — not found when there is no Elif.
        name = owner
    who, ent, namesakes = _subject(conn, name, cmd.relation, message)
    if who == "none":
        return Outcome("not_found")
    if who == "many":
        return Outcome("ambiguous", [", ".join(_label(e) for e in namesakes)])
    subject_id = ent.id if ent is not None else None
    if message and cmd.scope != "entity":
        # The user's own words pick the record (Phase 9.1): the model often left the forget
        # fields empty ("Kahve bilgimi sil": 8 of 8 real runs found nothing).
        picked = forget_target(conn, message, subject_id, exclude=name)
        if picked is not None:
            return _forget_picked(conn, ent, picked)

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


# ----- what to forget, from the user's words (Phase 9.1) -----------------------------------
_FORGET_VERBS = re.compile(r"^(?:sil|unut|kaldir|cikar|temizle|hafizandan|hafizadan|kayitlarindan)")
_GENERIC = frozenset(
    {"bilgi", "bilgim", "bilgimi", "bilgiyi", "bilgisini", "bilgileri", "bilgilerimi",
     "bilgilerini", "bilgisi", "kayit", "kaydi", "kaydini", "kaydimi", "kayitlari", "kayitlarini",
     "hafiza", "hafizan", "hafizana", "hafizandaki", "tercih", "tercihim", "tercihimi",
     "tercihimle", "hakkinda", "hakkindaki", "hakkimdaki", "ilgili", "olan", "olani",
     "sey", "seyi", "seyleri", "konu", "konusu", "konusunu", "model", "modelim", "modelimi",
     "modelini", "lutfen", "artik", "simdi", "bunu", "sunu", "onu", "bu", "su", "o", "benim",
     "beni", "bana", "ben", "olarak", "tum", "tumunu", "butun", "hepsi", "hepsini", "tamamini",
     "ikisi", "ikisini", "efendim", "lazis", "rica", "ederim", "istiyorum", "misin", "musun",
     "bildigin", "bildiklerini", "bildigini", "her", "hersey", "herseyi"}
)  # fmt: skip
_ALL = frozenset({"tum", "tumunu", "butun", "hepsi", "hepsini", "tamamini", "ikisini", "ikisi"})
_OLD = frozenset({"eski", "eskiden", "onceki", "gecmis", "gecmisteki"})
_NOW = frozenset({"guncel", "simdiki", "mevcut", "yeni"})


_OWNER = re.compile(r"(?<![\w])([A-ZÇĞİÖŞÜ][\wçğıöşü]+)['’](?:n?[ıiuü]n|n?[ıiuü]nki)\b")


def _owner_named(message: str) -> str:
    """ "Elif'in", "Ahmet'in": the person whose thing it is (the first one named so)."""
    m = _OWNER.search(extraction.users_own_words(message))
    return m.group(1) if m else ""


@dataclass(frozen=True)
class Picked:
    kind: Literal["records", "topic", "ambiguous", "none"]
    memories: tuple[Memory, ...] = ()
    predicate: str = ""


def _same(w: str, t: str) -> bool:
    """Suffix-tolerant: "kahve" ~ "kahveyi", "isyerimle" ~ "isyeri", "telefon" ~ "telefonu"."""
    if len(w) < 3 or len(t) < 3:
        return False
    k = min(5, len(w), len(t))
    return w[:k] == t[:k] and (k >= 4 or w == t)


def forget_target(conn: Connection, message: str, subject_id: str | None, *,
                  exclude: str = "") -> Picked | None:  # fmt: skip
    """The records "Kahve bilgimi sil", "Telefon modelimi hafızandan kaldır", "Eski işyerimle
    ilgili bilgiyi sil" mean, from the user's words: a topic (the field itself: "telefon"),
    or the records whose value or sentence has the words ("kahve"). Several different records
    → ambiguous (the user is asked; nothing is deleted). None: the message names nothing
    (the model's answer decides, as before)."""
    names = set(text.words(exclude))
    words = [w for w in text.words(extraction.users_own_words(message))
             if not _FORGET_VERBS.match(w) and w not in names]  # fmt: skip
    old, now = bool(set(words) & _OLD), bool(set(words) & _NOW)
    every = bool(set(words) & _ALL)
    topic = [w for w in words if w not in _GENERIC and w not in _OLD and w not in _NOW
             and w not in text.STOP_WORDS and not w.isdigit()]  # fmt: skip
    if not topic:
        return None
    pool = repo.memories_for_subject(conn, subject_id, statuses=("active", "superseded"))
    if old:
        pool = [m for m in pool if m.status == "superseded"]
    elif now:
        pool = [m for m in pool if m.status == "active"]
    by_value: list[tuple[int, Memory]] = []
    by_topic: list[Memory] = []
    for m in pool:
        p = registry.get(m.predicate)
        field_words = text.words(f"{p.label} {registry.HINTS.get(m.predicate, '')}") if p else []
        own = [t for t in text.words(f"{m.value} {m.content}") if t != "kullanici"]
        score = sum(any(_same(w, t) for t in own) for w in topic)
        if score:
            by_value.append((score, m))
        elif any(_same(w, t) for w in topic for t in field_words):
            by_topic.append(m)
    if by_value:
        # "Şekersiz kahve bilgimi sil": the record with more of the words, not every coffee.
        best = max(n for n, _ in by_value)
        by_value = [(n, m) for n, m in by_value if n == best or every]
    if by_value:
        found = tuple(m for _, m in by_value)
        if len({m.value_key for m in found}) > 1 and not every:
            return Picked("ambiguous", found)
        return Picked("records", found)
    preds = {m.predicate for m in by_topic}
    if len(preds) > 1:
        return Picked("ambiguous", tuple(by_topic))
    if preds:
        pred = next(iter(preds))
        p = registry.get(pred)
        several = len({m.value_key for m in by_topic if m.status == "active"}) > 1
        if p is not None and p.cardinality == "multi" and several and not every:
            # "Ahmet'in iletişim bilgisini sil" with a number and an e-mail: which one?
            return Picked("ambiguous", tuple(by_topic))
        if old or now:  # "eski işyerim": the old value(s) only, not today's
            return Picked("records", tuple(by_topic), pred)
        return Picked("topic", tuple(by_topic), pred)
    return Picked("none")


def _forget_picked(conn: Connection, ent: Entity | None, picked: Picked) -> Outcome:
    if picked.kind == "none":
        return Outcome("not_found")
    if picked.kind == "ambiguous":
        # Never a guess: deleting the wrong record is worse than asking (Phase 9.1).
        return Outcome("ambiguous", [m.content for m in picked.memories],
                       {"options": len(picked.memories)})  # fmt: skip
    subject_id = ent.id if ent is not None else None
    if picked.kind == "topic":
        res = service.forget_topic(conn, subject_id, picked.predicate)
        p = registry.get(picked.predicate)
        who_label = _label(ent) if ent else "kullanıcı"
        return Outcome(
            "forgotten",
            [f"{who_label} — {p.label if p else picked.predicate} ({res.memories} kayıt, eski "
             "değerler dahil)"],
            {"forgotten": res.memories},
        )  # fmt: skip
    res = service.forget_memories(conn, [m.id for m in picked.memories])
    return Outcome("forgotten", [m.content for m in picked.memories], {"forgotten": res.memories})


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


# ----- "which Ahmet?" answered in chat (deterministic, no model; Phase 7.2) -------------------
QUESTION_MAX_AGE_S = 30 * 60  # an older open question is left to the memory screen
_ANSWER_FILLER = frozenset(
    {"olan", "o", "ki", "benim", "bizim", "efendim", "evet", "tabii", "tabi", "yani", "hani",
     "mi", "mu", "de", "da", "kastettim", "kastediyorum", "diyorum", "dedim", "tabiki", "elbette",
     "bahsediyorum", "bahsettim", "olani", "olanı", "in", "un", "nin", "nun", "ile", "su", "bu"}
)  # fmt: skip
# "Vazgeç", also after a "no" or "well" ("Hayır, vazgeç", "Tamam, boşver"; Phase 9).
_CANCEL = re.compile(
    r"^(?:(?:hayir|yok|tamam|peki|neyse|aslinda)\s+)?(?:vazgec|vazgectim|bosver|bos ver|iptal|"
    r"kaydetme|hicbiri|hic biri|ikisi de degil|hicbirine|unut gitsin)\b"
)
_MAX_ANSWER_WORDS = 7


def open_question(conn: Connection, conversation_id: str, *, now: str) -> Any | None:
    """The latest open "which X?" question of this conversation, if it is recent."""
    from datetime import datetime

    best = None
    for item in repo.list_inbox(conn, status="open", types=("ambiguous_entity",)):
        if item.conversation_id != conversation_id or not item.payload.get("options"):
            continue
        try:
            age = (
                datetime.fromisoformat(now) - datetime.fromisoformat(item.created_at)
            ).total_seconds()
        except ValueError:
            continue
        if age > QUESTION_MAX_AGE_S:
            continue
        if best is None or item.created_at > best.created_at:
            best = item
    return best


def _descriptors(conn: Connection, entity_id: str) -> tuple[set[str], set[str]]:
    """(relationship types to the user, folded words) that tell this namesake apart."""
    ent = repo.get_entity(conn, entity_id)
    if ent is None:
        return set(), set()
    types = {
        r.type
        for r in gs.relationships_between(conn, USER_ID, entity_id, statuses=("active", "planned"))
        if r.source_id == USER_ID
    }
    words: set[str] = set()
    for phrase in (ent.relation, ent.description):
        if phrase:
            words.update(text.words(phrase))
            if (k := relations.lexicon(phrase)) is not None:
                types.add(k)
    for m in repo.memories_for_subject(conn, entity_id):
        p = registry.get(m.predicate)
        if p is not None and p.cardinality == "single" and m.sensitivity != "sensitive":
            words.update(text.words(m.value))
    for t in types:
        if t in relations.TYPES:
            words.update(text.words(relations.TYPES[t].label))
    return types, words


def choice_for(conn: Connection, item: Any, message: str) -> str | None:
    """The option a short answer picks ("Komşum olan.", "öğretmen olan Mehmet"), "dismiss"
    for "vazgeç", "again" when it fits several, None when the message is not an answer."""
    words = text.words(message)
    if not words or len(words) > _MAX_ANSWER_WORDS:
        return None
    folded = " ".join(words)
    if _CANCEL.search(folded):
        return "dismiss"
    ent: dict[str, Any] = item.payload.get("candidate", {}).get("entity") or {}
    name_words = set(text.words(str(ent.get("name", ""))))
    content = [w for w in words if w not in _ANSWER_FILLER and w not in name_words]
    if not content:
        return None
    said_type = relations.lexicon(" ".join(content))
    fits: list[str] = []
    for opt in item.payload.get("options", []):
        oid = str(opt.get("id", ""))
        types, descr = _descriptors(conn, oid)
        stems = {text.stem_prefix(d) for d in descr}
        covered = all(
            any(text.stem_prefix(w) == s or w.startswith(s) or s.startswith(text.stem_prefix(w))
                for s in stems)
            for w in content
        )  # fmt: skip
        if (said_type is not None and said_type in types) or covered:
            fits.append(oid)
    if len(fits) == 1:
        return fits[0]
    return "again" if len(fits) > 1 else None


def choose(conn: Connection, item: Any, choice: str) -> Outcome:
    """Apply the answer to a "which X?" question (as the memory screen does)."""
    if choice == "again":
        return Outcome("ambiguous", [question_text(item)], {"inbox": 1})
    if choice == "dismiss":
        service.resolve_inbox(conn, item.id, "dismiss")
        return Outcome("cancelled", [], {"cancelled": 1})
    label = next((str(o.get("label")) for o in item.payload.get("options", [])
                  if str(o.get("id")) == choice), "")  # fmt: skip
    report = service.resolve_inbox(conn, item.id, choice)
    saved = [m for m in (repo.get_memory(conn, i) for i in report.created + report.updated) if m]
    lines = [m.content for m in saved]
    if not lines:
        statement = str(item.payload.get("candidate", {}).get("statement", ""))
        lines = [f"{statement} ({label})"] if statement else [label]
    return Outcome("saved", lines, {"saved": len(saved) or 1})


_REDIRECT = re.compile(
    r"^(?:hayir|yanlis|yok|degil)\b"
    r"|\b(?:digeri|digerinin|oburu|oburunun|oteki|yanlis kisi|o degil)\b"
)


def redirect_choice(
    conn: Connection, payload: dict[str, Any], chosen: str, message: str
) -> str | None:
    """Right after a "which Ahmet?" answer: "Hayır, iş arkadaşım olan." / "Diğeri." → the
    option the user meant instead, or None."""
    folded = " ".join(text.words(message))
    if not _REDIRECT.search(folded):
        return None
    others = [str(o.get("id")) for o in payload.get("options", []) if str(o.get("id")) != chosen]
    stripped = _REDIRECT.sub(" ", folded)
    pick = choice_for(conn, _Item(payload), stripped) if stripped.strip() else None
    if pick in others:
        return pick
    if pick is None and len(others) == 1 and re.search(r"\b(?:digeri|oburu|oteki)", folded):
        return others[0]
    return None


@dataclass(frozen=True)
class _Item:
    payload: dict[str, Any]


def redirect(conn: Connection, payload: dict[str, Any], wrong: str, right: str) -> Outcome:
    """Move a fact saved for the wrong namesake to the one the user meant (one change set for
    the removal, one for the new record; both in the history)."""
    if payload.get("target") == "relationship" or "predicate" not in payload.get("candidate", {}):
        return Outcome("nothing")
    c = service.candidate_from_json(payload["candidate"])
    key = text.fold(c.value).strip()
    old = [m.id for m in repo.memories_for_subject(conn, wrong)
           if m.predicate == c.predicate and text.fold(m.value).strip() == key]  # fmt: skip
    if old:
        service.forget_memories(conn, old)
    report = ApplyReport()
    now = utc_now_iso()
    with UnitOfWork(conn, kind="user_request", actor="user", summary="kişi düzeltmesi") as uow:
        service.apply_one(conn, uow, c, source=Source("confirmation", None, None), explicit=True,
                          report=report, now=now, forced_subject=(right,))  # fmt: skip
    labels = {str(o.get("id")): str(o.get("label")) for o in payload.get("options", [])}
    return Outcome(
        "corrected",
        [f"{c.statement} → {labels.get(right, '')} (önce yanlışlıkla {labels.get(wrong, '')} "
         "için kaydedilmişti; oradan kaldırıldı)"],
        {"saved": len(report.created + report.updated), "forgotten": len(old)},
    )  # fmt: skip


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
