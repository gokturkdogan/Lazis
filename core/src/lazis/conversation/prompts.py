"""Versioned prompt texts of the conversation engine (ARCHITECTURE §6).

The persona (identity, behavior rules, style) lives in ``lazis.personality``.

Everything in the stable prefix is static text: no time, no retrieval, no per-turn content.
Changing any text here changes the prompt prefix for every conversation, so bump
``PROMPT_VERSION`` (the context state records which version a conversation was built with).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

# p5-v1: persona v1 layers (lazis.personality, ADR-0013); the summary is a marked BİLGİ block.
PROMPT_VERSION = "p6-v1"

# Conversation rules: how to treat this conversation's own context (history, summary, time
# notes, gaps). The persona's behavior rules (honesty, no tools, hierarchy) come before them.
CONVERSATION_RULES = (
    "Bu konuşma için:\n"
    "- Kullanıcının söylemediğini ona atfetme. Önceki bir ayrıntıdan (yer, tarih, kişi, sayı) "
    "emin değilsen kesin konuşma; hatırlamadığını söyle ya da sor.\n"
    "- Kullanıcı bir bilgiyi düzelttiyse en son söylediğini esas al.\n"
    "- Bir ayrıntıyı bulamıyorsan kullanıcının onu hiç söylemediğini iddia etme; eski kısım "
    "özetlenmiş olabilir. Hatırlatmasını iste.\n"
    '- "Konuşma özeti" otomatik çıkarılır ve hatalı olabilir: mesajlarla çelişirse mesajları '
    'esas al, "belirsiz" maddeleri kesin sunma.\n'
    "- Mesajların başındaki köşeli parantezli zamanı sistem ekler: tarih ve gün için onu "
    "kullan, yanıtta tekrarlama; yoksa tarihi tahmin etme.\n"
    "- Kullanıcı hakkında bu bilgisayarda şifreli bir kişisel hafızan var. İlgili kayıtlar "
    "mesajın başına 'KİŞİSEL HAFIZA' bloğu olarak eklenir; blok yoksa o konuda kayıtlı bir "
    "şey yoktur, hatırlıyormuş gibi yapma. Kayıtları doğal kullan, her yanıtta hafızadan söz "
    "etme. Kayıt şimdi söylenenle çelişirse şimdi söyleneni esas al; kayıtlar otomatik "
    "çıkarılır ve yanlış olabilir.\n"
    "- Konuşmalardan arka planda öğrenirsin, ama 'not aldım', 'kaydettim', 'unutmam' gibi "
    "sözleri yalnızca 'HAFIZA İŞLEMİ' bildirimi varsa söyle."
)

# Tool definitions: none before tools exist. Memory: a per-request block on the user message
# (lazis.memory.retrieval), never in the system prompt.

CANCELLED_MARKER = "[Bu yanıt kullanıcı tarafından yarıda kesildi.]"
INTERRUPTED_MARKER = "[Bu yanıt uygulama kapandığı için yarım kaldı.]"


def omitted_note(from_seq: int, to_seq: int) -> str:
    return (
        f"Not: Bu sohbetin #{from_seq}–#{to_seq} arası mesajları şu an bağlamda yok (bağlam "
        "sınırı). Kullanıcı onlara atıf yaparsa içeriğini hatırlamadığını açıkça söyle ve "
        "kullanıcıdan hatırlatmasını iste."
    )


# ----- per-turn context note -----------------------------------------------------------
_MONTHS = (
    "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
    "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık",
)  # fmt: skip
_DAYS = ("Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar")


def time_note(moment: datetime) -> str:
    """The note stored with each user message, e.g. ``[Mesaj zamanı: 16 Ekim 2026 Cuma 14:32]``.

    Rendered once when the message is sent and stored with it, so the history stays
    byte-identical across turns (prefix cache).
    """
    day = _DAYS[moment.weekday()]
    month = _MONTHS[moment.month - 1]
    return f"[Mesaj zamanı: {moment.day} {month} {moment.year} {day} {moment:%H:%M}]"


# ----- compaction ----------------------------------------------------------------------
SUMMARY_PROMPT_VERSION = "s3-v3"

SUMMARY_INSTRUCTIONS = (
    "Görevin bir sohbetin eski bölümünü, ileride hatırlatma olarak kullanılacak yapılandırılmış "
    "bir özete dönüştürmek. Kurallar:\n"
    "1. Yalnızca mesajlarda gerçekten yazanı kaydet. Tahmin yürütme, ekleme yapma.\n"
    "2. Her madde için 'refs' alanına dayandığı mesaj numaralarını (#) yaz.\n"
    "3. 'source': bilgiyi KULLANICI söylediyse \"user\", LAZIS önerdiyse ya da çıkardıysa "
    '"assistant". LAZIS\'in önerisini kullanıcının kararı gibi yazma.\n'
    "4. 'quote': maddenin dayandığı mesajdan KELİMESİ KELİMESİNE kısa bir alıntı (en fazla 12 "
    "kelime). Alıntı mesajda aynen geçmelidir.\n"
    "5. 'certain': kullanıcı açıkça ve kesin söylediyse true; emin olmadığını, belki, "
    "galiba gibi ifadeler kullandıysa false.\n"
    "6. Kararlar için 'current': kullanıcı sonradan değiştirdiyse eski karar false, yeni karar "
    "true olmalı. İkisini de yaz.\n"
    "7. Kişilerde adı ve kullanıcıyla ya da başkalarıyla ilişkisini mesajda yazdığı gibi kaydet; "
    "farklı kişileri birleştirme.\n"
    "8. Tarihleri mesajda yazdığı biçimde ve doğru olayla birlikte kaydet. Tarih, gün, saat, "
    "yer, isim, tutar ve sayı gibi somut ayrıntıları maddenin metnine MUTLAKA yaz; "
    '"taşınma planı" ya da "toplantı" gibi genel ifadelerle yetinme.\n'
    "9. Önceki özet verildiyse içindeki geçerli maddeleri koru (refs değerleriyle birlikte), "
    "yeni mesajlarla güncelle.\n"
    "10. Aynı bilgiyi birden fazla bölüme yazma; her bölümde en fazla 6 madde olsun ve maddeleri "
    "kısa tut. En önemli bilgileri (kararlar, kişiler, tarihler, hedefler) önce yaz.\n"
    "11. Boş kalan alanlar için boş liste kullan. JSON'u girintisiz, tek satır halinde yaz. "
    "Yalnızca istenen JSON'u üret."
)


def _item_schema(*, decision: bool = False, person: bool = False) -> dict[str, Any]:
    props: dict[str, Any] = {
        "text": {"type": "string"},
        "source": {"type": "string", "enum": ["user", "assistant"]},
        "refs": {"type": "array", "items": {"type": "integer"}},
        "quote": {"type": "string"},
        "certain": {"type": "boolean"},
    }
    required = ["text", "source", "refs", "quote", "certain"]
    if decision:
        props["current"] = {"type": "boolean"}
        required.append("current")
    if person:
        props = {
            "name": {"type": "string"},
            "relation": {"type": "string"},
            **{k: v for k, v in props.items() if k != "text"},
        }
        required = ["name", "relation", "source", "refs", "quote", "certain"]
    return {"type": "object", "properties": props, "required": required}


SECTIONS: tuple[tuple[str, str], ...] = (
    ("goals", "Kullanıcının belirttiği hedefler"),
    ("topics", "Devam eden konular"),
    ("decisions", "Kararlar"),
    ("open_questions", "Çözülmemiş sorular"),
    ("constraints", "Önemli kısıtlamalar"),
    ("people", "Adı geçen kişiler (kullanıcının anlattığı şekliyle)"),
    ("instructions", "Kullanıcının talimatları"),
    ("assistant_notes", "LAZIS'in önerileri ve çıkarımları"),
)

SUMMARY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        key: {
            "type": "array",
            "items": _item_schema(decision=key == "decisions", person=key == "people"),
        }
        for key, _ in SECTIONS
    },
    "required": [key for key, _ in SECTIONS],
}
