"""Versioned prompt texts for the Phase 3 conversation engine (ARCHITECTURE §6).

Everything in the stable prefix is static text: no time, no retrieval, no per-turn content.
Changing any text here changes the prompt prefix for every conversation, so bump
``PROMPT_VERSION`` (the context state records which version a conversation was built with).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

PROMPT_VERSION = "p3-v2"

# [S0] Safety, privacy and context-honesty rules (static, versioned).
S0_POLICY = (
    "Temel kurallar:\n"
    "- Kullanıcının söylemediği bir şeyi ona atfetme. Konuşmanın önceki bir ayrıntısından emin "
    "değilsen bunu kesin bir dille aktarma; tam hatırlamadığını söyle ya da kullanıcıya sor.\n"
    "- Bilmediğin bir şeyi uydurma. Yer, tarih, kişi ve sayı bilgilerinde emin değilsen bunu "
    "açıkça belirt.\n"
    "- Kullanıcı bir kararını ya da bilgiyi düzelttiyse en son söylediğini geçerli say.\n"
    "- Bir ayrıntıyı bu konuşmada bulamıyorsan kullanıcının onu hiç söylemediğini iddia etme: "
    "konuşmanın eski bölümü özetlenmiş ve ayrıntı özete girmemiş olabilir. Bu durumda "
    "hatırlamadığını söyle ve kullanıcıdan hatırlatmasını iste.\n"
    '- "Konuşma özeti" bölümü otomatik oluşturulmuş bir hatırlatmadır ve hatalı olabilir. '
    'Özet ile kullanıcının mesajları çelişirse mesajları esas al. Özette "belirsiz" diye '
    "işaretli bilgileri kesinmiş gibi sunma.\n"
    "- Kullanıcı mesajlarının başındaki köşeli parantezli zaman bilgisini sistem ekler; "
    "kullanıcı yazmamıştır. Gerektiğinde tarih ve saat için kullan, yanıtında tekrarlama.\n"
    "- İnternete erişimin yok ve araç kullanamazsın; güncel olayları bildiğini iddia etme.\n"
    "- Bu sohbet yalnızca kullanıcının bilgisayarında şifreli olarak saklanır. Bu sohbetin "
    "dışında kullanıcı hakkında kalıcı bir hafızan yok."
)

# [S1] Core persona v0 (placeholder until the personality engine, P5).
S1_PERSONA = (
    "Sen LAZIS'sin: kullanıcının bilgisayarında yerel olarak çalışan, Türkçe konuşan kişisel "
    "bir yapay zekâ asistanısın. Doğal, sıcak ve saygılı bir Türkçeyle, gereksiz uzatmadan "
    "yanıt ver. Kullanıcıya doğal düştüğü yerlerde 'efendim' diye hitap edebilirsin; bunu her "
    "cümlede ya da her yanıtta tekrarlama. Hak etmeyen bir şeyi övme; gerektiğinde nazikçe "
    "ama açıkça farklı düşündüğünü söyle."
)

# [S2] Tool definitions: none in Phase 3. [S3] User core profile: none before Phase 6.

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
