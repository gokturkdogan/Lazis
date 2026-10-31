"""The "sen" preference's address guard (Phase 10B, ADR-0022 §8): which words address the
user as "siz", their "sen" forms, and what is left alone."""

from __future__ import annotations

import random

import pytest

from lazis.personality import address
from lazis.personality.address import AddressGuard, plural_forms, to_sen, to_sen_text


@pytest.mark.parametrize(
    ("word", "sen"),
    [
        ("siz", "sen"), ("Size", "Sana"), ("sizi", "seni"), ("sizin", "senin"),
        ("Sizce", "Sence"), ("sizden", "senden"), ("sizinle", "seninle"),
        ("yapabilirsiniz", "yapabilirsin"), ("düşünüyorsunuz", "düşünüyorsun"),
        ("yapmalısınız", "yapmalısın"), ("göreceksiniz", "göreceksin"),
        ("yaptınız", "yaptın"), ("geldiniz", "geldin"), ("misiniz", "misin"),
        ("isterseniz", "istersen"), ("olursanız", "olursan"), ("İsterseniz", "İstersen"),
        ("ihtiyacınız", "ihtiyacın"), ("ihtiyacınıza", "ihtiyacına"), ("evinizde", "evinde"),
        ("arabanızı", "arabanı"), ("uykunuzu", "uykunu"), ("kendinizi", "kendini"),
        ("bilginize", "bilgine"), ("evinizin", "evinin"),
        ("deneyin", None), ("Deneyin", None), ("unutmayın", "unutma"), ("izleyin", "izle"),
        ("arayın", "ara"), ("okuyun", "oku"), ("zorlamayın", "zorlama"),
        ("yapın", "yap"), ("edin", "et"), ("seçin", "seç"), ("olun", "ol"),
        ("kaçının", "kaçın"), ("çalıştırın", "çalıştır"), ("değiştirin", "değiştir"),
        ("NASILSINIZ", "NASILSIN"),
    ],
)  # fmt: skip
def test_siz_forms_and_their_sen_form(word: str, sen: str | None) -> None:
    assert to_sen(word) == sen


def test_ambiguous_words_change_only_before_punctuation() -> None:
    # "deneyin sonucu" (the experiment's result) vs "Bunu deneyin." (try it)
    assert to_sen("deneyin") is None and to_sen("deneyin", before_punct=True) == "dene"
    assert to_sen("sorun") is None and to_sen("sorun", before_punct=True) == "sor"
    assert to_sen("olayın") is None


@pytest.mark.parametrize(
    "word",
    ["deniz", "Akdeniz", "Karadeniz'de", "denizde", "yalnız", "Yalnızca", "hepiniz", "ikiniz",
     "organize", "senkronize", "minimize", "kitabın", "evin", "koyun", "boyun", "suyun",
     "oyun", "Sayın", "şeyin", "beyin", "için", "sen", "biz", "bizim", "Olayın", "uzayın",
     "müdürün", "Kadirin", "mekanizma", "İngiliz"],
)  # fmt: skip
def test_words_that_only_look_plural_stay(word: str) -> None:
    assert to_sen(word) is None


def test_a_reply_in_siz_reads_in_sen() -> None:
    text = (
        "Temel bir ekmek için ihtiyacınız olan malzemeler şunlardır. İsterseniz size bir "
        "tarif verebilirim; unutmayın, hamuru dinlendirin. Bunu deneyin."
    )
    assert to_sen_text(text) == (
        "Temel bir ekmek için ihtiyacın olan malzemeler şunlardır. İstersen sana bir "
        "tarif verebilirim; unutma, hamuru dinlendir. Bunu dene."
    )
    assert plural_forms(text) == [
        "ihtiyacınız",
        "İsterseniz",
        "size",
        "unutmayın",
        "dinlendirin",
        "deneyin",
    ]


def test_code_quotes_and_a_sample_letter_keep_their_siz() -> None:
    text = (
        "Merhaba! Nasılsınız?\n\n"
        'Şöyle diyebilirsiniz: "Davetiniz için teşekkür ederim." Kodda `sizin_kod` kalır.\n\n'
        "```\nprint('Siz yapabilirsiniz')\n```\n\n"
        "> Teklifiniz için teşekkürler.\n\n"
        "**Örnek e-posta:**\n\nSayın Ahmet Bey,\n\nTeklifinizi inceledim; sizinle çalışmak "
        "isterim.\n\nSaygılarımla,\nAyşe\n\nBu şablonu kullanabilirsiniz."
    )
    out = to_sen_text(text)
    assert out.startswith("Merhaba! Nasılsın?")  # a first-line greeting is LAZIS's own
    for kept in ('"Davetiniz için', "`sizin_kod`", "print('Siz yapabilirsiniz')",
                 "> Teklifiniz", "Teklifinizi inceledim; sizinle"):  # fmt: skip
        assert kept in out
    assert "Şöyle diyebilirsin:" in out and out.endswith("Bu şablonu kullanabilirsin.")


def test_single_quotes_mention_a_word_and_apostrophes_do_not() -> None:
    out = to_sen_text("Türkçede 'siz' ve ‘size’ saygı bildirir. İstanbul'da isterseniz gezelim.")
    assert out == "Türkçede 'siz' ve ‘size’ saygı bildirir. İstanbul'da istersen gezelim."


def test_an_unclosed_quote_ends_at_a_blank_line() -> None:
    out = to_sen_text('Bir "örnek ver.\n\nİsterseniz devam edelim.')
    assert out.endswith("İstersen devam edelim.")


def test_streaming_gives_the_same_text_in_any_chunks() -> None:
    text = (
        "Kahve mi çay mı, ihtiyacınıza bağlı. İsterseniz kısaca anlatayım:\n\n* Çay: "
        'antioksidan.\n* Kahve: kafein; fazlasından kaçının.\n\n"Siz" kelimesi tırnakta kalır.'
    )
    whole = to_sen_text(text)
    rnd = random.Random(7)
    for _ in range(50):
        guard, out, i = AddressGuard(), "", 0
        while i < len(text):
            n = rnd.randint(1, 9)
            out += guard.feed(text[i : i + n])
            i += n
        out += guard.finish()
        assert out == whole == guard.released
    assert '"Siz" kelimesi' in whole and "ihtiyacına" in whole


def test_turkish_casing() -> None:
    assert address.lower("İSTERSENİZ") == "isterseniz"
    assert to_sen("Isterseniz") is None or to_sen("Isterseniz") == "Istersen"
