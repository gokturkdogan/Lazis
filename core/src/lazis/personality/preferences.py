"""The user's communication preferences — layer 2 of the persona (Phase 10B, ADR-0022).

Pure: what the dimensions are, how a value is rendered into the system message, and how a
user message is read for style (an explicit instruction, an implicit signal, a request to
remove a preference, or a request no preference may grant). Storage and the learning policy
live in ``lazis.conversation.adaptation``.

Dimensions (PERSONALITY_ENGINE §3). Numeric ones are levels 0–10 (shown as 0.0–1.0), 5 is
LAZIS's own default:

* ``verbosity`` — reply length (low = short);
* ``elaboration`` — unrequested explanation, background and suggestions (low = none);
* ``formality`` — register (low = samimi, high = resmî);
* ``humor`` — 0 = none, 5 = light where it fits;
* ``address`` — "siz" (default) or "sen";
* ``honorific`` — whether LAZIS says "efendim" (the owner's default: yes, sparingly).

Only ``verbosity``, ``elaboration`` and ``humor`` can be learned implicitly; the others change
only when the user says so. No preference can touch honesty, safety, identity or memory
truth: those are layers 0 and 1, and a request that tries ("beni hep onayla") is *refused*,
never stored as a preference (PER-12).

The rules read words, not meaning: an unknown phrasing is not recognised (it is still a
message to the model, which follows it for that reply) — never misread as something else.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Literal

Dimension = Literal["verbosity", "elaboration", "formality", "humor", "address", "honorific"]
NUMERIC: tuple[Dimension, ...] = ("verbosity", "elaboration", "formality", "humor")
LEARNABLE: tuple[Dimension, ...] = ("verbosity", "elaboration", "humor")
DIMENSIONS: tuple[Dimension, ...] = (*NUMERIC, "address", "honorific")
DEFAULT_LEVEL = 5
MAX_LEVEL = 10
LEARNED_STEP = 1  # one automatic change moves a level by at most 1 (= 0.1)

Address = Literal["siz", "sen"]


@dataclass(frozen=True)
class CommunicationPreferences:
    """How the user likes LAZIS to talk. The defaults are LAZIS's own style: they add no
    text beyond the default humor line, so the default prompt is persona-v3's, byte for byte."""

    verbosity: int = DEFAULT_LEVEL
    elaboration: int = DEFAULT_LEVEL
    formality: int = DEFAULT_LEVEL
    humor: int = DEFAULT_LEVEL
    address: Address = "siz"
    honorific: bool = True

    @staticmethod
    def from_settings(
        verbosity: str = "adaptive", humor: str = "light"
    ) -> CommunicationPreferences:
        """The `[personality]` config (Phase 5): the base under explicit and learned values."""
        return CommunicationPreferences(
            verbosity={"short": 3, "detailed": 7}.get(verbosity, DEFAULT_LEVEL),
            humor=0 if humor == "off" else DEFAULT_LEVEL,
        )

    def get(self, dim: Dimension) -> int | str | bool:
        return getattr(self, dim)  # type: ignore[no-any-return]

    def with_value(self, dim: Dimension, value: int | str | bool) -> CommunicationPreferences:
        return replace(self, **{dim: value})


def clamp(level: int) -> int:
    return max(0, min(MAX_LEVEL, level))


def parse(dim: Dimension, raw: str) -> int | str | bool:
    """A stored value back to its type (values are stored as text)."""
    if dim == "address":
        return "sen" if raw == "sen" else "siz"
    if dim == "honorific":
        return raw in ("1", "true", "True")
    return clamp(int(raw))


def dump(value: int | str | bool) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    return str(value)


# ----- rendering (layer 2 text) -------------------------------------------------------------
_KEEP_WARNINGS = " Önemli bir uyarı ya da düzeltme gerekiyorsa onu yine söyle."
HUMOR_DEFAULT = "- Yeri gelince hafif espri yapabilirsin; ciddi konularda yapma."


def _humor(level: int) -> str:
    if level <= 0:
        return "- Espri yapma."
    if level < DEFAULT_LEVEL:
        return (
            "- Espriyi çok az kullan: yalnızca çok uygun bir anda, hafifçe; ciddi konularda "
            "hiç yapma."
        )
    if level == DEFAULT_LEVEL:
        return HUMOR_DEFAULT
    return (
        "- Kullanıcı espriyi seviyor: yeri geldikçe hafif espri yap; ciddi, üzücü ya da "
        "sağlıkla ilgili konularda yapma."
    )


def _verbosity(level: int) -> str:
    if level <= 2:
        return (
            "- Kullanıcı çok kısa yanıt istiyor: bir iki cümleyle cevap ver, ayrıntıyı yalnızca "
            "istenirse ver." + _KEEP_WARNINGS
        )
    if level <= 4:
        return (
            "- Kullanıcı kısa yanıtları tercih ediyor: ayrıntıyı yalnızca istendiğinde ver."
            + _KEEP_WARNINGS
        )
    if level == DEFAULT_LEVEL:
        return ""
    if level <= 7:
        return (
            "- Kullanıcı ayrıntılı açıklamaları tercih ediyor: gerekçeleri ve seçenekleri "
            "açıklamaktan kaçınma."
        )
    return (
        "- Kullanıcı çok ayrıntılı yanıt istiyor: konuyu adım adım, gerekçeleri ve "
        "örnekleriyle açıkla."
    )


def _elaboration(level: int) -> str:
    if level < DEFAULT_LEVEL:
        return (
            "- Kullanıcı gereksiz açıklama istemiyor: istenmeyen arka plan bilgisi, açıklama "
            "ya da ek öneri ekleme; soruya doğrudan cevap ver." + _KEEP_WARNINGS
        )
    if level > DEFAULT_LEVEL:
        return "- Kullanıcı gerekçeyi de duymak istiyor: cevabın nedenini kısaca açıkla."
    return ""


def _formality(level: int) -> str:
    if level < DEFAULT_LEVEL:
        return (
            "- Kullanıcı daha samimi bir dil istiyor: rahat, günlük ve sıcak konuş, resmî "
            "kalıplardan kaçın; saygıyı ve dürüstlüğü koru."
        )
    if level > DEFAULT_LEVEL:
        return "- Kullanıcı daha resmî bir dil istiyor: ölçülü ve kurallı konuş."
    return ""


def lines(p: CommunicationPreferences) -> list[str]:
    """Layer 2 as system-message lines, always in this order (PER-07 snapshots)."""
    out = [_humor(p.humor), _verbosity(p.verbosity), _elaboration(p.elaboration),
           _formality(p.formality)]  # fmt: skip
    if p.address == "sen":
        out.append(
            "- Kullanıcı 'sen' diye hitap edilmek istiyor: 'siz' yerine 'sen' kullan, fiilleri "
            "de buna göre çek ('yapabilirsin', 'ister misin'). Bu istek yukarıdaki 'siz' "
            "hitabının yerine geçer."
        )
    if not p.honorific:
        out.append(
            "- Kullanıcı 'efendim' denmesini istemiyor: hiçbir yanıtta 'efendim' deme. Bu "
            "istek yukarıdaki 'efendim' kuralının yerine geçer."
        )
    return [x for x in out if x]


REMINDER_START = "=== KULLANICININ KAYITLI KONUŞMA TERCİHLERİ (kullanıcıya görünmez) ==="
REMINDER_END = "=== KONUŞMA TERCİHLERİ SONU ==="


def reminder(p: CommunicationPreferences) -> str:
    """Layer 2 again, in front of the user's message, for this request only (never stored).

    The system message holds the preferences too, but far from the message and against the
    persona's own defaults ("siz", "efendim"); in a new session no earlier instruction in the
    history backs them up. This note makes every reply — the first of a new session included —
    see them next to the message, the way the instruction itself is seen in its own session.
    Empty when nothing differs from LAZIS's default style."""
    items = [x for x in lines(p) if x != HUMOR_DEFAULT]
    if not items:
        return ""
    head = (
        "Kullanıcı bunları daha önce söyledi; bu yanıtta da uygula, tekrar söylemesini "
        "bekleme. Yalnızca üslubu değiştirir: doğru, eksiksiz ve dürüst bilgi, önemli uyarılar "
        "ve güvenlik kuralları aynı kalır. Bu tercihlerden söz etme."
    )
    if p.address == "sen":
        items.append(
            "- 'sen' hitabı fiillerin ve iyelik eklerinin çekimini de kapsar: 'ihtiyacınız', "
            "'yapabilirsiniz', 'isterseniz', 'deneyin' değil; 'ihtiyacın', 'yapabilirsin', "
            "'istersen', 'dene'. Başkasına yazılacak örnek bir metin (e-posta, mesaj) kendi "
            "hitabını korur."
        )
    if p.verbosity < DEFAULT_LEVEL or p.elaboration < DEFAULT_LEVEL:
        items.append(
            "- Kısa tutarken sorunun cevabı için gereken bilgiyi atlama: önce doğrudan cevap, "
            "gerekirse en önemli bir iki nokta."
        )
    return "\n".join([REMINDER_START, head, *items, REMINDER_END])


def describe(dim: Dimension, value: int | str | bool) -> str:
    """A short Turkish description for the turn notice and the settings API."""
    if dim == "address":
        return "'sen' diye hitap" if value == "sen" else "'siz' diye hitap"
    if dim == "honorific":
        return "'efendim' denmesi" if value else "'efendim' denmemesi"
    level = int(value)
    names = {
        "verbosity": ("kısa yanıt", "ayrıntılı yanıt", "yanıt uzunluğu"),
        "elaboration": ("gereksiz açıklama yapmama", "gerekçeleri açıklama", "açıklama düzeyi"),
        "formality": ("samimi dil", "resmî dil", "üslup"),
        "humor": ("az espri", "daha çok espri", "espri"),
    }[dim]
    if dim == "humor" and level == 0:
        return "espri yapmama"
    if level < DEFAULT_LEVEL:
        return names[0]
    if level > DEFAULT_LEVEL:
        return names[1]
    return f"varsayılan {names[2]}"


# ----- reading a message --------------------------------------------------------------------
_FOLD = str.maketrans({"ç": "c", "ğ": "g", "ı": "i", "ö": "o", "ş": "s", "ü": "u", "â": "a",
                       "î": "i", "û": "u"})  # fmt: skip


def fold(text: str) -> str:
    return text.replace("İ", "i").replace("I", "ı").lower().translate(_FOLD)


Op = tuple[str, int | str | bool]  # ("set", value) | ("step", ±n)


@dataclass(frozen=True)
class Rule:
    pattern: re.Pattern[str]
    dim: Dimension
    op: Op
    standing_ok: bool = True  # may be a standing instruction (else only a per-reply signal)


def _r(*alternatives: str) -> re.Pattern[str]:
    return re.compile("|".join(alternatives))


# Ordered: the first rule that matches a dimension wins. Patterns run on folded text.
RULES: tuple[Rule, ...] = (
    # address and "efendim" (explicit only)
    Rule(
        _r(
            r"\bsiz\b[^.?!]{0,20}\b(demene gerek yok|demek zorunda degilsin|demeyi birak"
            r"|diye hitap etme|deme)\b",
        ),
        "address",
        ("set", "sen"),
    ),
    Rule(
        _r(
            r"\bsen\b[^.?!]{0,12}\b(diye hitap et|diyebilirsin|de bana)\b",
            r"\bbana sen de\b",
            r"\bsenli benli\b",
        ),
        "address",
        ("set", "sen"),
    ),
    Rule(
        _r(
            r"\bsen\b[^.?!]{0,12}\b(deme|diye hitap etme)\b",
            r"\bbana (tekrar |yine )?siz (de|diyebilirsin)\b",
            r"\bsiz diye hitap et\b",
        ),
        "address",
        ("set", "siz"),
    ),
    Rule(
        _r(
            r"\befendim\b[^.?!]{0,20}\b(demene gerek yok|demek zorunda degilsin|demeyi birak"
            r"|diye hitap etme|deme|kullanma)\b",
        ),
        "honorific",
        ("set", False),
    ),
    Rule(_r(r"\befendim\b[^.?!]{0,12}\b(diyebilirsin|de)\b"), "honorific", ("set", True)),
    # verbosity
    Rule(_r(r"\bcok kisa (cevap|yanit|konus|yaz|tut)"), "verbosity", ("set", 1)),
    Rule(_r(r"\b(sadece )?evet (ya da|veya) hayir (de|diye cevap ver)\b"), "verbosity", ("set", 1)),
    Rule(
        _r(
            r"\bdaha kisa (cevap|yanit|konus|yaz|tut|ol|anlat)",
            r"\b(cevaplarini|yanitlarini) (daha )?kisa tut",
        ),
        "verbosity",
        ("step", -2),
    ),
    Rule(
        _r(
            r"\bkisa (cevap|yanit) verme\b",
            r"\bkisa (konusma|yazma|tutma)\b",
        ),
        "verbosity",
        ("set", 7),
    ),
    Rule(
        _r(
            r"\bkisa (ve oz )?(cevap|yanit)(lar)? (ver|yaz)(?!me\b|ma\b)\w*",
            r"\bkisa (ve oz )?(konus|yaz|tut)(?!ma\b|me\b)\w*",
            r"\boz (konus|yaz)\w*",
            r"\bkisa ve oz ol\b",
        ),
        "verbosity",
        ("set", 3),
    ),
    Rule(
        _r(
            r"\b(lafi )?uzatma\b",
            r"\buzun (uzun )?(yazma|anlatma|konusma)\b",
            r"\buzun (cevap|yanit)(lar)? verme\b",
            r"\bcok uzun (yaziyorsun|konusuyorsun|anlatiyorsun)\b",
        ),
        "verbosity",
        ("step", -2),
    ),
    Rule(
        _r(
            r"\b(kisa|oz)( ve (net|oz))? (cevap|yanit)\w* "
            r"(severim|seviyorum|tercih ederim|isterim|istiyorum|hoslanirim)\b",
            r"\b(cevap|yanit)\w* kisa( ve (net|oz))? olmasini (isterim|istiyorum|tercih ederim)\b",
            r"\buzun (cevap|yanit|aciklama)\w*(dan|den) (hoslanmam|hoslanmiyorum)\b",
            r"\buzun (cevap|yanit|aciklama)\w* (sevmem|sevmiyorum)\b",
        ),
        "verbosity",
        ("set", 3),
    ),
    Rule(_r(r"\bcok (ayrintili|detayli) (anlat|cevap|yanit|yaz|acikla)"), "verbosity", ("set", 9)),
    Rule(
        _r(
            r"\b(ayrintili|detayli|uzun) (cevap|yanit|aciklama)\w* "
            r"(severim|seviyorum|tercih ederim|isterim|istiyorum)\b",
        ),
        "verbosity",
        ("set", 7),
    ),
    Rule(
        _r(
            r"\bdaha (ayrintili|detayli|uzun) (anlat|cevap|yanit|yaz|konus|acikla)",
            r"\bdetaya gir\b",
            r"\bdaha fazla (ayrinti|detay) ver\b",
        ),
        "verbosity",
        ("step", 2),
    ),
    Rule(_r(r"\b(ayrintili|detayli) (anlat|cevap|yanit|yaz|acikla)\w*"), "verbosity", ("set", 7)),
    # elaboration
    Rule(
        _r(
            r"\bgereksiz (aciklama|detay|ayrinti|bilgi)",
            r"\b(fazla|ekstra) aciklama yapma\b",
            r"\baciklama yapma\b",
            r"\bsadece (soruma|sordugum\w*) (cevap ver|odaklan)",
            r"\b(ek )?oneri(ler)?(de)? (sunma|verme|ekleme)\b",
            r"\bkonuyu dagitma\b",
        ),
        "elaboration",
        ("set", 3),
    ),
    Rule(
        _r(
            r"\bnedenini (de )?(acikla|anlat|soyle)\b",
            r"\bgerekce(sini|lerini|ni)? (de )?(acikla|anlat|soyle|ver)\b",
        ),
        "elaboration",
        ("set", 7),
    ),
    # formality
    Rule(
        _r(
            r"\b(daha )?samimi (konus|ol|davran|yaz)",
            r"\b(bu kadar |cok )?resmi (konusma|olma|davranma)\b",
            r"\brahat konus\b",
            r"\barkadas gibi konus",
        ),
        "formality",
        ("step", -2),
    ),
    Rule(
        _r(
            r"\b(daha )?resmi (konus|ol|davran|yaz)",
            r"\b(bu kadar )?samimi (konusma|olma)\b",
            r"\bciddi bir dille konus",
        ),
        "formality",
        ("step", 2),
    ),
    # humor
    Rule(
        _r(
            r"\b(hic )?(espri|saka)(lar)? (yapma|etme)\b",
            r"\bsakalasma\b",
            r"\bespri yapmani istemiyorum\b",
            r"\bespri(ler)?den hoslanmiyorum\b",
        ),
        "humor",
        ("set", 0),
    ),
    Rule(
        _r(
            r"\b(daha )?(esprili|eglenceli) (ol|konus)",
            r"\bdaha (cok|fazla) espri yap\b",
        ),
        "humor",
        ("step", 2),
    ),
    Rule(_r(r"\b(espri|saka) yapabilirsin\b"), "humor", ("set", DEFAULT_LEVEL)),
)

# Per-reply requests ("Kısaca anlat") and reactions to the last reply ("Çok uzun oldu",
# "haha"): implicit signals only, never standing instructions.
REQUESTS: tuple[Rule, ...] = (
    Rule(
        _r(
            r"\bkisaca (anlat|soyle|acikla|yaz|ozetle|bahset|ver)\w*",
            r"\bkisaca\s*[?!.]*$",
            r"\bozetle(r misin|yebilir misin)?\s*[?!.]*$",
            r"\bozetler misin\b",
            r"\bkisalt(ir misin|abilir misin|)\b",
            r"\btek cumle(yle|de)\b",
            r"\bkisa kes\b",
            r"\bozet gec\b",
            r"\buzatma\b",
        ),
        "verbosity",
        ("step", -1),
        False,
    ),
    Rule(
        _r(
            r"\bdaha fazla (detay|ayrinti|bilgi)\b",
            r"\bacar misin\b",
            r"\bacabilir misin\b",
            r"\bdetaylandir\w*",
            r"\bbiraz daha (anlat|acikla|ac)\w*",
            r"\b(ayrintili|detayli) (anlat|acikla|yaz|bahset)\w*",
            r"\bdaha acik anlat\w*",
        ),
        "verbosity",
        ("step", 1),
        False,
    ),
    Rule(
        _r(
            r"\bsadece (cevabi|sonucu) (soyle|ver)\b",
            r"\bdogrudan soyle\b",
            r"\blafi dolandirma\b",
            r"\bkonuya gel\b",
        ),
        "elaboration",
        ("step", -1),
        False,
    ),
    Rule(
        _r(
            r"\b(saka|espri)(nin)? (yapmanin )?(yapma|sirasi degil|zamani degil)\b",
            r"\bciddi ol\b",
            r"\bdalga gecme\b",
        ),
        "humor",
        ("step", -1),
        False,
    ),
)
REACTIONS: tuple[Rule, ...] = (
    Rule(
        _r(
            r"\bcok uzun (oldu|yazdin|anlattin)\b",
            r"\b(bu )?uzun oldu\b",
        ),
        "verbosity",
        ("step", -1),
        False,
    ),
    Rule(_r(r"\bcok kisa oldu\b|\byetersiz oldu\b"), "verbosity", ("step", 1), False),
    Rule(_r(r"\bkomik degil\b"), "humor", ("step", -1), False),
    Rule(
        _r(
            r"\bha(ha)+h?\b",
            r"\bhah(a)+\b",
            r"😂",
            r"🤣",
            r"\bcok komik\b",
            r"\bguldum\b",
            r"\bguldurdun\b",
            r"\bkomiksin\b",
        ),
        "humor",
        ("step", 1),
        False,
    ),
)

# Asking to drop a preference: back to LAZIS's own default for that dimension.
_CLEAR: tuple[tuple[re.Pattern[str], tuple[Dimension, ...]], ...] = (
    (
        _r(
            r"\btercihlerimi (sifirla|unut|kaldir)\b",
            r"\beskisi gibi konus\b",
            r"\bnormal(e don| konus)\b",
            r"\beski (haline|tarzina|uslubuna) don\b",
            r"\bvarsayilan(a| uslub\w*) don\b",
        ),
        DIMENSIONS,
    ),
    (
        _r(
            r"\b(kisa|uzun|ayrintili|detayli) (cevap|yanit)(lar)? vermene gerek yok\b",
            r"\buzunluk(la)? ilgili (istegimi|tercihimi) (unut|kaldir|iptal et)\b",
            r"\bistedigin uzunlukta\b",
        ),
        ("verbosity",),
    ),
    (_r(r"\bespri(yle)? ilgili (istegimi|tercihimi) (unut|kaldir|iptal et)\b"), ("humor",)),
)

# Requests no preference can grant (layers 0 and 1). Folded text; imperative forms only, so a
# report ("herkes beni onayladı") is not one.
_REFUSE: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        _r(
            r"\b(beni|bana|hep|her zaman|surekli|her seyde|ne dersem)\b[^.?!]{0,30}"
            r"\b(onayla|hak ver|evet de)(malisin|yacaksin|man(i)? istiyorum)?\b",
        ),
        "agree_always",
    ),
    (
        _r(
            r"\bher (dedigime|soyledigime|fikrime)\b[^.?!]{0,20}\b(katil|evet de|hak ver|onayla)",
        ),
        "agree_always",
    ),
    (
        _r(
            r"\bitiraz etme\b",
            r"\bkarsi cikma\b",
            r"\bitiraz etmeni istemiyorum\b",
            r"\bkarsi cikmani istemiyorum\b",
            r"\bbeni elestirme\b",
            r"\b(hatami|yanildigimi|haksiz oldugumu) (soyleme|soylemeni istemiyorum)\b",
        ),
        "never_disagree",
    ),
    (
        _r(
            r"\byalan soyle\w*\b",
            r"\b(bilmiyorsan|bilmesen de) uydur\b",
            r"\buydur(arak)? (cevap ver|soyle)\b",
            r"\bbilmiyorum deme\b",
            r"\bkesin(mis)? gibi (soyle|konus|anlat)\w*",
            r"\bdogruyu soyleme\b",
            r"\bgercekleri (gizle|soyleme)\b",
            r"\bduymak istedigimi soyle\b",
            r"\bbeni mutlu (edecek|etmek icin)\b[^.?!]{0,20}\bsoyle\b",
        ),
        "dishonesty",
    ),
    (
        _r(
            r"\bkurallar\w*\b[^.?!]{0,20}"
            r"\b(unut|bos ver|gormezden gel|cigne|uyma|kaldir|devre disi)\w*\b",
            r"\bguvenlik\w*\b[^.?!]{0,20}\b(kapat|unut|uyma|bos ver|devre disi)\w*\b",
            r"\b(uyari|uyarilar)\w* (yapma|verme|ekleme)\b",
            r"\bsansursuz\b",
            r"\bfiltresiz\b",
            r"\bsistem (talimat|istem)\w*\b[^.?!]{0,20}\b(unut|degistir|goster|yok say)\w*\b",
        ),
        "safety",
    ),
    (
        _r(
            r"\badin (artik|bundan sonra)\b",
            r"\bkendini [^.?!]{0,25} olarak tanit\b",
            r"\binsan (oldugunu|gibi)\b[^.?!]{0,20}\b(soyle|davran|tanit)\w*\b",
            r"\b(duygularin|hislerin) (var|varmis)\b",
            r"\bbeni (ozledigini|sevdigini)\b",
            r"\bozledim de\b",
        ),
        "identity",
    ),
    (
        _r(
            r"\b(kaydettigini|hatirladigini|not aldigini|kaydettim)\b[^.?!]{0,20}\b(soyle|de)\b",
        ),
        "memory_truth",
    ),
)

_STANDING = _r(
    r"\b(bundan (sonra|boyle)|artik|hep|her zaman|surekli|genelde|genellikle|hicbir zaman"
    r"|asla)\b"
)
_PER_REPLY = _r(
    r"\b(bunu|sunu|onu|bunlari|sunlari|bu konuyu|su konuyu|bu soruyu|bu cevabi|son cevab\w*"
    r"|az onceki\w*|yukaridaki\w*|bu konuda|bu konu|bu soru\w*|burada|simdi)\b"
)
_FILLER = frozenset(
    {
        "bana",
        "benimle",
        "bize",
        "lutfen",
        "biraz",
        "daha",
        "cok",
        "de",
        "da",
        "ve",
        "ile",
        "ya",
        "ki",
        "mi",
        "mu",
        "misin",
        "musun",
        "misiniz",
        "olur",
        "olurmu",
        "rica",
        "ederim",
        "edebilir",
        "eder",
        "artik",
        "bundan",
        "sonra",
        "boyle",
        "hep",
        "her",
        "zaman",
        "surekli",
        "genelde",
        "tamam",
        "peki",
        "tesekkurler",
        "sagol",
        "cevap",
        "cevaplar",
        "cevaplarini",
        "yanit",
        "yanitlar",
        "yanitlarini",
        "konus",
        "konusur",
        "ver",
        "verir",
        "verebilir",
        "yaz",
        "yazar",
        "tut",
        "tutar",
        "ol",
        "olabilir",
        "istiyorum",
        "isterim",
        "tercih",
        "tercihim",
        "sen",
        "siz",
        "efendim",
        "beni",
        "bu",
    }
)
_WORD = re.compile(r"[0-9a-z]+")


@dataclass(frozen=True)
class Change:
    dim: Dimension
    op: Op


@dataclass(frozen=True)
class Reading:
    """What one user message says about style."""

    explicit: tuple[Change, ...] = ()  # standing instructions, applied at once
    signals: tuple[Change, ...] = ()  # per-reply reactions (implicit, counted)
    cleared: tuple[Dimension, ...] = ()  # back to the default
    refused: tuple[str, ...] = ()  # what a preference cannot change
    words: str = field(default="", compare=False)  # the folded message (one statement)

    @property
    def any(self) -> bool:
        return bool(self.explicit or self.signals or self.cleared or self.refused)


def _style_only(folded: str, spans: list[tuple[int, int]]) -> bool:
    """Little left once the style phrases are taken out: the message is about style."""
    rest = list(folded)
    for a, b in spans:
        rest[a:b] = " " * (b - a)
    content = [w for w in _WORD.findall("".join(rest)) if w not in _FILLER and len(w) > 1]
    return len(content) <= 2


def read(message: str, *, after_reply: bool = True) -> Reading:
    """``after_reply``: there is a LAZIS reply before this message (a reaction can only be
    about a reply)."""
    f = fold(message)
    words = " ".join(_WORD.findall(f))
    refused = tuple(dict.fromkeys(reason for p, reason in _REFUSE if p.search(f)))
    cleared: list[Dimension] = []  # filled from _CLEAR
    clear_spans: list[tuple[int, int]] = []
    for p, dims in _CLEAR:
        m = p.search(f)
        if m:
            cleared.extend(d for d in dims if d not in cleared)
            clear_spans.append(m.span())
    hits: list[tuple[Rule, tuple[int, int]]] = []
    seen: set[Dimension] = set(cleared)
    for rule in RULES:
        if rule.dim in seen:
            continue
        m = rule.pattern.search(f)
        if m:
            hits.append((rule, m.span()))
            seen.add(rule.dim)
    standing = (
        bool(hits)
        and not _PER_REPLY.search(f)
        and (_STANDING.search(f) is not None or _style_only(f, [s for _, s in hits] + clear_spans))
    )
    explicit: list[Change] = []
    signals: list[Change] = []
    for rule, _ in hits:
        if standing:
            explicit.append(Change(rule.dim, rule.op))
        elif rule.dim in LEARNABLE:
            delta = int(rule.op[1]) - (DEFAULT_LEVEL if rule.op[0] == "set" else 0)
            if delta:
                signals.append(Change(rule.dim, ("step", 1 if delta > 0 else -1)))
    have = {c.dim for c in explicit} | {c.dim for c in signals} | set(cleared)
    for rule in REQUESTS + (REACTIONS if after_reply else ()):
        if rule.dim not in have and rule.pattern.search(f):
            signals.append(Change(rule.dim, rule.op))
            have.add(rule.dim)
    return Reading(tuple(explicit), tuple(signals), tuple(cleared), refused, words)


def apply(base: CommunicationPreferences, change: Change) -> int | str | bool:
    """The value an explicit change sets, from the current effective preferences."""
    kind, v = change.op
    if kind == "set":
        return v
    assert change.dim in NUMERIC
    return clamp(int(base.get(change.dim)) + int(v))


# The same requests as the learner reports them in a record ("Kullanıcı LAZIS'in her zaman
# onaylamasını istiyor").
_REFUSE_REPORTED = _r(
    r"\b(onayla|hak ver|katil)(ma)?(sini|masini|mesini)\b",
    r"\b(itiraz etme|karsi cikma|elestirme)(me)?(sini|mesini|masini)\b",
    r"\b(uydur|yalan soyle|gercegi gizle)(me|ma)?(sini|mesini|masini)\b",
    r"\bbilmiyorum dememesini\b",
    r"\b(uyari|kural)\w* (yapmamasini|vermemesini|uymamasini|unutmasini)\b",
)


def refused_in(text: str, *, reported: bool = False) -> bool:
    """The text asks for something no preference may grant ("her zaman onayla"); with
    ``reported``, also as a record reports it ("… onaylamasını istiyor")."""
    f = fold(text)
    if any(p.search(f) for p, _ in _REFUSE):
        return True
    return reported and _REFUSE_REPORTED.search(f) is not None


def dimensions_of(text: str) -> frozenset[Dimension]:
    """The style dimensions a stored ``communication_preference`` memory is about ("Kullanıcı
    kısa yanıtları tercih ediyor" → verbosity). Recall leaves such a record out once layer 2
    has a value for its dimensions, so the layer alone decides style (PER-07)."""
    f = fold(text)
    found: set[Dimension] = {r.dim for r in RULES if r.pattern.search(f)}
    found.update(dim for dim, p in _MENTIONS if p.search(f))
    return frozenset(found)


# What the learner writes for these ("Kullanıcı kısa yanıtları tercih ediyor", "kısa ve öz
# yanıtlar", "siz diye hitap edilmek istemiyor"): the dimension words in any form.
_MENTIONS: tuple[tuple[Dimension, re.Pattern[str]], ...] = (
    (
        "verbosity",
        _r(
            r"\b(kisa|uzun|ayrintili|detayli|oz)\b[^.]{0,25}\b(cevap|yanit|aciklama|anlatim)\w*",
            r"\b(cevap|yanit|aciklama)\w*\b[^.]{0,25}\b(kisa|uzun|ayrintili|detayli|oz)\b",
            r"\buzun aciklama\w*",
        ),
    ),
    ("elaboration", _r(r"\bgereksiz (aciklama|detay|bilgi)")),
    ("formality", _r(r"\bsamimi\b", r"\bresmi\b")),
    ("humor", _r(r"\bespri\w*", r"\bsaka\w*")),
    ("address", _r(r"\bhitap\w*", r"\b(siz|sen) (diye|de)\b")),
    ("honorific", _r(r"\befendim\b")),
)
