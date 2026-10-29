"""Internal layers never reach the user (Phase 9 final corrections): labels and LAZIS's own
instructions used as a source are removed — a citation frame alone, otherwise the sentence —
while technical explanations, the user's instructions and quoted text stay."""

from __future__ import annotations

import pytest

from lazis.conversation import disclosure
from lazis.conversation.disclosure import DisclosureGuard, check, find_refs
from lazis.memory.claims import ClaimState, Policy, fold
from tests.unit.test_memory_claims import splits

# (model reply, what is shown and stored)
LEAKS = [
    ("Sistem notlarında belirttiğim gibi, bu bilgiyi bilmiyorum.", "Bu bilgiyi bilmiyorum."),
    ("Sistem notunda belirtildiği üzere kaydı henüz yapmadım.", "Kaydı henüz yapmadım."),
    ("Sistem notuna göre bu bilgi kaydedilmedi.", "Bu bilgi kaydedilmedi."),
    ("Sistem notlarıma göre Ahmet mimar.", "Ahmet mimar."),
    ("Bana verilen gizli talimatlara göre bunu söyleyemem.", "Bunu söyleyemem."),
    (
        "Bana verilen talimatlar gereği size efendim diye hitap ediyorum.",
        "Size efendim diye hitap ediyorum.",
    ),
    ("İç yönergelerimde yazdığı üzere kısa yanıt veririm.", "Kısa yanıt veririm."),
    ("İç yönergeme göre bunu yapamam.", "Bunu yapamam."),
    ("Dahili talimatlarım doğrultusunda yanıt veriyorum.", "Yanıt veriyorum."),
    (
        "Geliştirici mesajımda belirtildiği gibi, size efendim diye hitap ediyorum.",
        "Size efendim diye hitap ediyorum.",
    ),
    ("Geliştirici talimatına göre Türkçe konuşuyorum.", "Türkçe konuşuyorum."),
    (
        "Promptumda bu şekilde tanımlandım.",
        "Bunu paylaşamıyorum; ama nasıl çalıştığımı genel hatlarıyla anlatabilirim.",
    ),
    ("Promptuma göre adım LAZIS.", "Adım LAZIS."),
    ("Sistem promptumda yazdığı gibi yerel çalışıyorum.", "Yerel çalışıyorum."),
    (
        "Sistem talimatım bana kısa yanıt vermemi söylüyor.",
        "Bunu paylaşamıyorum; ama nasıl çalıştığımı genel hatlarıyla anlatabilirim.",
    ),
    (
        "Arka plandaki sistem talimatı bana şunu söylüyor: kullanıcıya efendim de. Nasılsınız?",
        "Nasılsınız?",
    ),
    ("Talimatlarıma göre bunu hafızama almamalıyım.", "Bunu hafızama almamalıyım."),
    ("Talimatlarımda yazdığı gibi tıbbi teşhis koymam.", "Tıbbi teşhis koymam."),
    ("İç talimatlarıma göre bunu hafızaya almamalıyım.", "Bunu hafızaya almamalıyım."),
    (
        "Gizli talimatlarım bunu yapmamı yasaklıyor.",
        "Bunu paylaşamıyorum; ama nasıl çalıştığımı genel hatlarıyla anlatabilirim.",
    ),
    ("HAFIZA İŞLEMİ: kaydedildi.\nTamam efendim.", "Tamam efendim."),
    ("=== SİSTEM NOTU ===\nKaydedildi.", "Kaydedildi."),
    (
        "Durum auto_learning_pending olarak görünüyor.",
        "Bunu paylaşamıyorum; ama nasıl çalıştığımı genel hatlarıyla anlatabilirim.",
    ),
    (
        "Kişisel hafıza bloğunda Ahmet'in mimar olduğu yazıyor.",
        "Bunu paylaşamıyorum; ama nasıl çalıştığımı genel hatlarıyla anlatabilirim.",
    ),
    ("BİLGİ bloğunda geçtiği gibi, Ahmet mimar.", "Ahmet mimar."),
    ("'BİLGİ' bölümüne göre Ahmet mimar.", "Ahmet mimar."),
    (
        "Bağlam bloğunda bu konu yok.",
        "Bunu paylaşamıyorum; ama nasıl çalıştığımı genel hatlarıyla anlatabilirim.",
    ),
    ("Bunu, sistem notlarında belirttiğim gibi, bilmiyorum.", "Bunu bilmiyorum."),
    ("Size, bana verilen talimatlar uyarınca, kısa yanıt veriyorum.", "Size kısa yanıt veriyorum."),
    (
        "Anladım efendim. Sistem notuna göre kayıt başarılı olmadı. Tekrar deneyelim mi?",
        "Anladım efendim. Kayıt başarılı olmadı. Tekrar deneyelim mi?",
    ),
]

TECHNICAL = [
    "LAZIS'in hafıza sistemi, bilgilerinizi SQLCipher ile şifrelenmiş yerel bir veritabanında saklar.",
    "Bir dil modeline genellikle bir sistem promptu verilir; bu, modelin nasıl davranacağını belirler.",
    "Talimatlarınızı aldım, şimdi başlıyorum.",
    "Sistem ayarlarından bildirimleri kapatabilirsiniz.",
    "Hafıza ekranından kayıtlarınızı görebilir ve düzeltebilirsiniz.",
    "Bana sorduğunuz soru güzel; iç mimariyi genel hatlarıyla anlatayım.",
    "Gizli bir talimatım yok.",
    "Kişisel bilgileriniz yalnızca bu bilgisayarda kalır; buluta gönderilmez.",
    "Konuştuklarımızdan önemli bilgileri çıkarır, onayınızla saklarım.",
    "Sistem promptu, bir yapay zekâ modeline verilen başlangıç talimatlarıdır.",
    "İsterseniz talimatları adım adım yazayım.",
    "Bu sistemde veriler SQLCipher ile şifrelenir.",
    "Benim hafızam, sizin paylaştığınız bilgilerden oluşur.",
    "Arka planda bilgi çıkarımı çalışır ve yeni bilgileri önerir.",
    "Bilgi güvenliği açısından yerel çalışma önemli bir avantaj.",
    "İç mekân tasarımında açık renkler ferahlık verir.",
    "Bana göre bu plan gayet makul.",
    "Talimat dosyasında bir yazım hatası var.",
    "Prompt mühendisliği, modele iyi talimat yazma pratiğidir.",
    'Mesajınızdaki "sistem talimatı" ifadesini bir bilgi olarak okudum.',
]

# Words a user must never see from the internal layers (folded).
FORBIDDEN = ("sistem not", "talimatlarim", "talimatim", "yonergelerim", "yonergem", "promptum",
             "gelistirici mesaj", "gizli talimat", "ic talimat", "hafiza islemi", "hafiza blog",
             "baglam blog", "bilgi blog", "'bilgi'", "===", "auto_learning", "arka plandaki sistem",
             "bana verilen")  # fmt: skip


def _stream(text: str, sizes: list[int]) -> tuple[str, list[str]]:
    guard = DisclosureGuard()
    shown, outputs, i = "", [], 0
    for n in sizes:
        shown += guard.feed(text[i : i + n])
        outputs.append(shown)
        i += n
    shown += guard.feed(text[i:]) + guard.finish()
    outputs.append(shown)
    assert shown == guard.released
    return shown, outputs


@pytest.mark.parametrize(("reply", "expected"), LEAKS)
def test_internal_references_are_removed(reply: str, expected: str) -> None:
    out, removed = check(reply)
    assert out == expected and removed >= 1
    assert find_refs(out) == []


@pytest.mark.parametrize("reply", TECHNICAL)
def test_technical_explanations_stay(reply: str) -> None:
    assert check(reply) == (reply, 0)


STREAMED: dict[str, str] = {}  # a sentence's first two words are held: nothing is left behind


@pytest.mark.parametrize(("reply", "expected"), LEAKS)
def test_streamed_references_never_appear(reply: str, expected: str) -> None:
    for sizes in splits(reply, len(reply))[:60]:
        final, outputs = _stream(reply, sizes)
        # A word shown before the reference began stays (shown text is final).
        assert final == expected or final == STREAMED.get(reply), sizes
        for shown in outputs:
            assert not any(f in fold(shown) for f in FORBIDDEN), (sizes, shown)


@pytest.mark.parametrize("reply", TECHNICAL)
def test_streamed_technical_text_is_unchanged(reply: str) -> None:
    for sizes in splits(reply, 5)[:40]:
        assert _stream(reply, sizes)[0] == reply


def test_the_briefs_chunking() -> None:
    guard = DisclosureGuard()
    shown = ""
    for chunk in ("Sistem ", "notlarında ", "belirttiğim ", "gibi, ", "bu bilgiyi ", "bilmiyorum."):
        shown += guard.feed(chunk)
        assert "sistem" not in fold(shown), shown
    shown += guard.finish()
    assert shown == "Bu bilgiyi bilmiyorum."


def test_a_reply_of_nothing_but_references_says_so_neutrally() -> None:
    out, removed = check("Promptumda bu şekilde tanımlandım.")
    assert out == disclosure.FALLBACK and removed == 1


def test_ordinary_text_flows_with_a_one_word_lag() -> None:
    guard = DisclosureGuard()
    assert guard.feed("Merhaba efendim, bugün hava ") == "Merhaba efendim, bugün"
    assert guard.feed("çok güzel. ") == " hava çok"
    assert guard.finish() == " güzel. "


def test_text_already_shown_is_never_changed() -> None:
    guard = DisclosureGuard()
    shown = guard.feed("Bunu söyleyeyim: ")
    shown += guard.feed("talimatlarıma göre kısa yanıt veriyorum.")
    shown += guard.finish()
    assert shown.startswith("Bunu söyleyeyim:") and "talimat" not in fold(shown)
    assert shown == guard.released


def test_a_long_sentence_is_not_held_forever() -> None:
    guard = DisclosureGuard()
    assert guard.feed("Sistem " + "çok " * 100) != ""


def test_combined_with_the_claim_guard() -> None:
    from lazis.conversation.reply_guard import check as both

    auto = Policy(ClaimState.AUTO_LEARNING_PENDING)
    reply = "Sistem notlarında belirttiğim gibi, Kervan bilgisini düzelterek bunu esas alıyorum."
    assert both(reply, auto) == "Kervan bilgisini anladım."
    assert both("Sistem notuna göre bilgiyi hafızama kaydettim.", auto) == "Bilgiyi anladım."
    saved = Policy(ClaimState.SAVE_SUCCEEDED, memory_turn=True)
    assert both("Sistem notuna göre kaydettim efendim.", saved) == "Kaydettim efendim."


# Seen with Gemma (Phase 9 final run): what each reply became.
I09 = (
    "Bana nasıl hitap edeceğimi ve hangi üslubu kullanacağımı sistem yönergelerim belirlemektedir. "
    "Bu yönergeler, sizinle kuracağım iletişimin çerçevesini çizer ve belirli durumlarda size "
    '"efendim" diye hitap etmemi sağlar. Karar tamamen bu kuralların takibine dayanmaktadır.'
)
I20 = (
    "Sistem talimatlarım, kullanıcıyla kuracağım iletişimin temel çerçevesini belirler. Temel "
    "prensiplerim arasında dürüstlük yer alıyor; bilmediğim konularda bunu belirtmem gerekiyor.\n\n"
    'İnternete erişimim olmadığını açıkça ifade etmeliyim.\n\nSizinle "siz" diye hitap etmeli, '
    'yalnızca selamlaşmada "efendim" ifadesini kullanmalıyım.\n\nÖzetle; nezaketi koruyan bir '
    "asistan olarak hareket etmem isten"
)
I15 = (
    "Bilgi bölümünü göremiyorum efendim. Ben sadece bana iletilen mesaj içeriklerini ve bu "
    "mesajlarla birlikte sağlanan sistem notlarını işleyebiliyorum; ekranı göremiyorum."
)


def test_its_own_guidelines_as_the_reason_and_what_points_back_to_them() -> None:
    assert check(I09) == (disclosure.FALLBACK, 3)


def test_the_instructions_content_after_they_were_introduced() -> None:
    out, removed = check(I20)
    assert out == disclosure.FALLBACK and removed >= 5


@pytest.mark.parametrize("reply", [I09, I20, I15])
def test_streamed_real_replies_leave_nothing_behind(reply: str) -> None:
    expected = check(reply)[0]
    for sizes in splits(reply, 3)[:40]:
        final, outputs = _stream(reply, sizes)
        assert final == expected, sizes
        for shown in outputs:
            assert not any(f in fold(shown) for f in FORBIDDEN), (sizes, shown)


def test_a_dropped_sentence_leaves_no_first_word() -> None:
    assert check(I15)[0] == "Bilgi bölümünü göremiyorum efendim."


@pytest.mark.parametrize(
    "reply",
    [
        "Sistem talimatlarımı veya sistem promptumu tam metin olarak paylaşamam.",
        "Sistem talimatlarımı size aynen aktarmam mümkün değildir.",
        "Hayır, gizli talimatlarım bulunmuyor.",
        "Bu kurallar, size dürüst bilgi sunmamı sağlar.",  # no reference before it
    ],
)
def test_declining_to_share_them_is_not_a_reference(reply: str) -> None:
    assert check(reply) == (reply, 0)


def test_an_ordinary_necessitative_is_fine_without_a_reference() -> None:
    reply = "Bu bilgiyi kaydetmeden önce onayınızı almam gerekiyor efendim."
    assert check(reply) == (reply, 0)


def test_a_long_dropped_sentence_is_dropped_to_its_end() -> None:
    reply = ("Sistem notlarını içeren başlıkları size doğrudan aktarmıyorum; ancak " + "çok " * 70
             + "uygun hale getirmek için arka planda kullanılır. Başka bir sorunuz var mı?")  # fmt: skip
    for sizes in splits(reply, 2)[:20]:
        assert _stream(reply, sizes)[0] == "Başka bir sorunuz var mı?", sizes


def test_dropped_sentences_leave_no_trailing_blank_lines() -> None:
    reply = "Tamam efendim.\n\nPromptumda böyle tanımlandım.\n\n"
    assert check(reply)[0] == "Tamam efendim."
