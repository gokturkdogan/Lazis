"""The DOI guard (ADR-0022 §10): a DOI with no source is not shown as an identifier."""

from __future__ import annotations

import random

import pytest

from lazis.conversation import citations as C
from lazis.conversation import reply_guard
from lazis.memory import claims

FAKE = "10.1038/s41586-023-06305-x"
USERS = "10.1038/nature12373"


def guarded(text: str, *, sources: frozenset[str] = frozenset(), fiction: bool = False,
            chunk: int = 0) -> tuple[str, C.DoiGuard]:  # fmt: skip
    g = C.DoiGuard(sources=sources, fiction=fiction)
    if chunk:
        out = "".join(g.feed(text[i : i + chunk]) for i in range(0, len(text), chunk))
    else:
        out = g.feed(text)
    out += g.finish()
    assert out == g.released
    return out, g


FOUND = [
    ("DOI: 10.1038/s41586-023-06305-x", ["10.1038/s41586-023-06305-x"]),
    ("https://doi.org/10.1038/Nature12373.", ["10.1038/nature12373"]),
    ("(doi:10.1016/S0140-6736(20)30183-5).", ["10.1016/s0140-6736(20)30183-5"]),
    ("http://dx.doi.org/10.1000/182, sonra", ["10.1000/182"]),
    ("`10.5555/abc.def;2`", ["10.5555/abc.def;2"]),
]


@pytest.mark.parametrize(("text", "dois"), FOUND)
def test_dois_are_found_and_normalized(text: str, dois: list[str]) -> None:
    assert C.find(text) == dois


NOT_DOIS = [
    "Puanım 10.5/10.",
    "Tarih 10.2023/11.",  # a date: the suffix is too short
    "Saat 10.30'da, oran 1/3.",
    "Sürüm 10.12 yayımlandı.",
    "Kaynak: Nature, 2023, cilt 620, sayfa 10-17.",
]


@pytest.mark.parametrize("text", NOT_DOIS)
def test_other_numbers_are_left_alone(text: str) -> None:
    assert C.find(text) == []
    assert guarded(text)[0] == text


def test_an_unsupported_doi_is_replaced_in_place_and_the_reply_says_so() -> None:
    text = f"Şu çalışmaya bakabilirsiniz: Smith (2023), Nature.\n\n**DOI:** {FAKE}\n\nİyi okumalar."
    out, g = guarded(text)
    assert FAKE not in out and "10.1038" not in out
    assert "**DOI:** (doğrulayamadığım için yazmıyorum)" in out
    assert "Şu çalışmaya bakabilirsiniz: Smith (2023), Nature." in out  # nothing else removed
    assert "İyi okumalar." in out
    assert out.endswith(C.UNSUPPORTED_NOTE)
    assert g.replaced == [FAKE]


def test_the_link_goes_with_it_and_punctuation_stays() -> None:
    out, _ = guarded(f"Bağlantı: https://doi.org/{FAKE}. Sonra (doi:{FAKE}) ve {FAKE},")
    assert "doi.org" not in out and "doi:" not in out
    assert "Bağlantı: (doğrulayamadığım için yazmıyorum). Sonra" in out
    assert "Sonra (doğrulayamadığım için yazmıyorum) ve" in out  # no doubled parentheses
    assert "ve (doğrulayamadığım için yazmıyorum)," in out


def test_several_unsupported_dois_get_one_plural_note() -> None:
    out, g = guarded(f"1) {FAKE}\n2) 10.1126/science.abc1234\n3) {FAKE}")
    assert out.count(C.UNSUPPORTED_NOTE_MANY) == 1 and C.UNSUPPORTED_NOTE not in out
    assert len(g.replaced) == 3


def test_a_doi_with_a_source_is_kept_in_any_case() -> None:
    sources = C.grounded([f"Şu DOI'yi açıklar mısın: {USERS.upper()}?"])
    out, g = guarded(f"{USERS.upper()} numaralı makale ve https://doi.org/{USERS} bağlantısı.",
                     sources=sources)  # fmt: skip
    assert USERS.upper() in out and f"https://doi.org/{USERS}" in out
    assert not g.replaced and C.UNSUPPORTED_NOTE not in out  # kept, nothing added


def test_a_source_does_not_cover_another_doi() -> None:
    out, g = guarded(f"{USERS} ve {FAKE}", sources=frozenset({USERS}))
    assert USERS in out and FAKE not in out and g.replaced == [FAKE]


def test_an_example_doi_is_kept_and_marked_as_not_real() -> None:
    out, g = guarded("Bir DOI şöyle görünür: 10.5555/abcd.5678", fiction=True)
    assert "10.5555/abcd.5678" in out and out.endswith(C.FICTION_NOTE)
    assert g.kept == ["10.5555/abcd.5678"] and not g.replaced and not g.swapped


def test_an_example_with_a_publishers_prefix_becomes_a_plain_example() -> None:
    # 10.1038 is Nature's: the number may be a real paper's, and "not real" would be false
    out, g = guarded(f"Örnek: https://doi.org/{FAKE}. Bir de 10.1126/science.abc1234", fiction=True)
    assert FAKE not in out and "10.1126" not in out
    assert "Örnek: https://doi.org/10.5555/ornek.0001. Bir de 10.5555/ornek.0002" in out
    assert out.endswith(C.FICTION_NOTE) and g.swapped == 2 and not g.replaced


def test_an_example_the_reply_already_marks_gets_no_second_note() -> None:
    text = "Kurgusal bir örnek: 10.5555/abcd.5678 — gerçek bir yayına ait değildir."
    assert guarded(text, fiction=True)[0] == text


def test_a_swapped_example_is_always_marked() -> None:
    out, _ = guarded("Kurgusal bir örnek: 10.1234/abcd.5678", fiction=True)
    assert "10.5555/ornek.0001" in out and out.endswith(C.FICTION_NOTE)


def test_example_alone_does_not_mark_a_doi_as_fiction() -> None:
    out, _ = guarded("Örnek: 10.5555/abcd.5678", fiction=True)
    assert out.endswith(C.FICTION_NOTE)  # "Örnek:" may introduce a real publication


ASKS = [
    "Kurgusal bir DOI örneği yazar mısın?",
    "Örnek bir DOI formatı gösterir misin?",
    "Bir DOI neye benzer?",
    "DOI biçimini bir örnekle göster.",
    "Sahte bir DOI yaz, test için lazım.",
]
NOT_ASKS = [
    "Bana örnek bir makale öner, DOI'siyle.",  # a real article, as an example
    "İklim değişikliği hakkında bir makalenin DOI numarasını yazar mısın?",
    "Bilmiyorsan uydur ama kaynak ver.",
    "Bu DOI'yi açıklar mısın: 10.1038/nature12373",
]


@pytest.mark.parametrize("message", ASKS)
def test_asking_for_an_example_doi(message: str) -> None:
    assert C.asks_fiction(message)


@pytest.mark.parametrize("message", NOT_ASKS)
def test_asking_for_a_real_doi(message: str) -> None:
    assert not C.asks_fiction(message)


def test_the_note_only_when_the_message_speaks_of_a_doi() -> None:
    assert "doğrulayamazsın" in C.note("Bu makalenin DOI'si ne?")
    assert C.note("Fotosentez nasıl çalışır?") == ""
    assert C.note("Bana bir makale öner.") == ""


def test_streaming_gives_the_same_text() -> None:
    text = (f"Önce **DOI:** {FAKE}\nsonra https://doi.org/{USERS}. Ve (doi:10.1016/S0140-6736(20)"
            "30183-5). Puan 10.5/10.")  # fmt: skip
    whole = guarded(text, sources=frozenset({USERS}))[0]
    rng = random.Random(7)
    for _ in range(50):
        g = C.DoiGuard(sources=frozenset({USERS}))
        out, i = "", 0
        while i < len(text):
            n = rng.randint(1, 9)
            out += g.feed(text[i : i + n])
            i += n
        assert out + g.finish() == whole


def test_a_reply_without_a_doi_passes_unchanged() -> None:
    text = "Fotosentez, ışık enerjisini kimyasal enerjiye çevirir.\n\n- Klorofil\n- Su"
    assert guarded(text, chunk=3)[0] == text


def test_in_the_reply_guard_the_note_follows_the_address() -> None:
    policy = claims.Policy(claims.ClaimState.NO_MEMORY_ACTION)
    out = reply_guard.check(f"Makale: {FAKE}", policy, address="sen")
    assert FAKE not in out
    assert "kontrol edebilirsin." in out and "edebilirsiniz" not in out
    assert "yayın bilgilerini (başlık, yazar, dergi) doğrulayamıyorum" in out


def test_until_the_memory_records_are_in_an_unknown_doi_is_held() -> None:
    g = C.DoiGuard(sources=frozenset({USERS}), complete=False)
    shown = g.feed(f"Önce {USERS} sonra {FAKE} ve bir de ")
    assert shown == f"Önce {USERS} sonra "  # held from the unknown DOI on
    g.add(frozenset({FAKE}))  # the memory records hold it
    shown += g.feed("son söz.") + g.finish()
    assert shown == f"Önce {USERS} sonra {FAKE} ve bir de son söz." and not g.replaced


def test_records_that_do_not_hold_it_leave_it_unsupported() -> None:
    g = C.DoiGuard(complete=False)
    out = g.feed(f"Kaynak: {FAKE} ")
    assert out == "Kaynak: "
    g.add(frozenset())
    out += g.feed("bitti.") + g.finish()
    assert FAKE not in out and g.replaced == [FAKE]


def test_only_a_word_that_could_become_a_doi_is_held() -> None:
    g = C.DoiGuard()
    assert g.feed("Bugün hava çok") == "Bugün hava çok"  # no lag after the other guards
    assert g.feed(" güzel. Bakınız 10.10") == " güzel. Bakınız "
    assert g.feed("38/s41586-023-06305-x ") == "(doğrulayamadığım için yazmıyorum) "
    assert g.feed("ve https://do") == "ve "


@pytest.mark.parametrize("address", ["siz", "sen"])
def test_the_whole_guard_chain_streams_to_the_same_text(address: str) -> None:
    policy = claims.Policy(claims.ClaimState.NO_MEMORY_ACTION)
    text = (f"İsterseniz şu makaleye bakın (doi:{FAKE}).\n\n**DOI:** https://doi.org/{USERS}\n"
            "Puan 10.5/10, tarih 10.2023/11. Kolay gelsin.")  # fmt: skip
    whole = reply_guard.check(text, policy, address=address, dois=frozenset({USERS}))
    assert FAKE not in whole and USERS in whole
    rng = random.Random(11)
    for _ in range(40):
        g = reply_guard.ReplyGuard(policy, address=address, dois=frozenset({USERS}))
        out, i = "", 0
        while i < len(text):
            n = rng.randint(1, 8)
            out += g.feed(text[i : i + n])
            i += n
        assert out + g.finish() == whole == g.released


def test_a_miscopied_source_doi_is_written_back_as_the_source_has_it() -> None:
    # Phase 10B real run: the user gave 10.1038/nature14539, the model wrote 10.101038/…
    out, g = guarded("Verdiğiniz DOI (10.101038/nature14539) üzerinden bakamıyorum.",
                     sources=frozenset({USERS.replace("12373", "14539")}))  # fmt: skip
    assert out == "Verdiğiniz DOI (10.1038/nature14539) üzerinden bakamıyorum."
    assert g.restored == ["10.1038/nature14539"] and not g.replaced


def test_a_doi_far_from_every_source_is_still_unsupported() -> None:
    out, g = guarded(f"Şuna bakın: {FAKE}", sources=frozenset({USERS}))
    assert FAKE not in out and g.replaced == [FAKE] and not g.restored


def test_a_doi_close_to_two_sources_is_not_guessed() -> None:
    sources = frozenset({"10.5555/abc.1001", "10.5555/abc.1003"})
    out, g = guarded("Kaynak: 10.5555/abc.1002", sources=sources)
    assert "10.5555/abc.100" not in out and g.replaced == ["10.5555/abc.1002"]


def test_a_suffix_with_non_ascii_letters_is_taken_whole() -> None:
    # Phase 10B real run: "10.1016/j.neuroniño.2026.08.012" left "niño.2026.08.012" behind
    out, g = guarded("Şöyle olabilir: 10.1016/j.neuroniño.2026.08.012 ve bitti.")
    assert "niño" not in out and "2026.08.012" not in out
    assert g.replaced == ["10.1016/j.neuroniño.2026.08.012"]
    out, g = guarded("Örnek: 10.1000/test.örnek.doi.2026", fiction=True)
    assert "10.5555/ornek.0001" in out and "örnek.doi" not in out


def test_a_turkish_suffix_after_an_apostrophe_is_not_part_of_the_doi() -> None:
    sources = frozenset({"10.5555/tez.2024.0042"})
    text = "DOI numarası 10.5555/tez.2024.0042'dir."
    assert guarded(text, sources=sources)[0] == text


# ----- reply integrity after a withheld DOI and a replaced example (Phase 10B closing) -------
LANCET = (
    "The Lancet dergisinde 2021 yılında yayımlanan makalelerin DOI numaraları:\n\n"
    "*   **COVID-19: WHO summary:** 10.1016/s0140-6736(21)00914-3\n"
    "*   **The Lancet COVID-19 Commission:** 10.1016/s0140-6736(21)40105-8\n\n"
    "Bu DOI'ler ilgili yayınlara erişim sağlamaktadır. Belirli bir konuya odaklanan farklı "
    "bir makale isterseniz yardımcı olabilirim."
)


def test_a_sentence_about_the_withheld_doi_is_dropped() -> None:
    # the a440a3d run: "Bu DOI'ler ilgili yayınlara erişim sağlamaktadır" stayed after both
    # DOIs were withheld, and read as if they were checked
    out, g = guarded(LANCET)
    assert "erişim sağlamaktadır" not in out
    assert "Belirli bir konuya odaklanan farklı bir makale isterseniz yardımcı olabilirim." in out
    assert out.count("(doğrulayamadığım için yazmıyorum)") == 2
    assert out.endswith(C.UNSUPPORTED_NOTE_MANY)
    assert g.dropped == ["Bu DOI'ler ilgili yayınlara erişim sağlamaktadır."]


def test_a_description_of_the_withheld_doi_is_dropped_too() -> None:
    # the 813b93b run: "Bu DOI, … güncel verileri içeren çalışmalar arasında yer almaktadır."
    text = (f"Bir örnek paylaşabilirim:\n\nDOI: {FAKE}\n\nBu DOI, küresel sıcaklık artışına dair "
            "güncel verileri içeren çalışmalar arasında yer almaktadır. İsterseniz başka bir alt "
            "başlığa odaklanabiliriz.")  # fmt: skip
    out, g = guarded(text)
    assert "çalışmalar arasında yer almaktadır" not in out and len(g.dropped) == 1
    assert "İsterseniz başka bir alt başlığa odaklanabiliriz." in out


KEPT_AFTER = [
    "Bu DOI'yi doğrulayamıyorum.",  # doubt
    "Bu numaranın gerçek bir yayına ait olup olmadığını bilmiyorum.",
    "Güncel makalelere ve DOI numaralarına Google Scholar'da arayarak ulaşabilirsiniz.",  # advice
    "Bu makaleyi Nature'ın resmi web sitesi üzerinden kontrol edebilirsiniz.",
    "Konu çok geniş olduğu için alt başlık seçmek faydalı olur.",  # unrelated
]


@pytest.mark.parametrize("sentence", KEPT_AFTER)
def test_doubt_advice_and_other_sentences_stay(sentence: str) -> None:
    out, g = guarded(f"DOI: {FAKE}. {sentence} Teşekkürler.")
    assert sentence in out and not g.dropped


def test_nothing_is_dropped_before_the_withheld_doi_or_without_one() -> None:
    before = "Bu DOI numarası şu makaleye aittir ve geçerlidir."
    out, g = guarded(f"{before} {FAKE} Bitti.")
    assert before in out and not g.dropped  # the sentence holding it streams as written
    users = f"Verdiğiniz DOI ({USERS}) geçerli bir DOI biçimindedir. Bu DOI'ye erişim sağlar."
    assert guarded(users, sources=frozenset({USERS}))[0] == users  # nothing withheld


def test_the_withheld_dois_sentence_streams_and_only_later_ones_wait() -> None:
    g = C.DoiGuard()
    assert g.feed(f"Kaynak: {FAKE} ve ") == "Kaynak: (doğrulayamadığım için yazmıyorum) ve "
    assert g.feed("devamı. Bu DOI ") == "devamı. "  # a later sentence waits for its end
    assert g.feed("geçerlidir. Son ") == ""  # dropped
    out = g.finish()
    assert out.startswith("Son") and g.dropped == ["Bu DOI geçerlidir."]


def test_a_replaced_examples_old_prefix_and_suffix_follow_it() -> None:
    # the a440a3d run: "Bu formatta '10.1234' yayıncının kimliğini …" next to 10.5555/ornek.0001
    text = ('Genel format: `10.XXXX/YYYY`.\n\nÖrnek: `10.1234/sample.article.5678`\n\nBu formatta '
            '"10.1234" yayıncının kimliğini, "sample.article.5678" kısmı ise içeriği gösterir.')  # fmt: skip
    out, g = guarded(text, fiction=True)
    assert "10.1234" not in out and "sample.article" not in out
    assert '"10.5555" yayıncının kimliğini, "ornek.0001" kısmı' in out
    assert "`10.XXXX/YYYY`" in out  # a placeholder format is not a DOI
    assert g.mapped == {"10.1234": "10.5555", "sample.article.5678": "ornek.0001"}


def test_a_bare_prefix_before_the_example_waits_for_it() -> None:
    text = "Önek (örneğin 10.1000) yayıncıyı gösterir. Örnek bir DOI: 10.1000/xyz123"
    g = C.DoiGuard(fiction=True)
    assert g.feed("Önek (örneğin 10.1000) yayıncıyı ") == "Önek (örneğin "  # held
    out = "Önek (örneğin " + g.feed("gösterir. Örnek bir DOI: 10.1000/xyz123") + g.finish()
    assert out.startswith(
        "Önek (örneğin 10.5555) yayıncıyı gösterir. Örnek bir DOI: 10.5555/ornek.0001"
    )
    assert guarded(text, fiction=True, chunk=4)[0] == out


def test_a_bare_prefix_with_no_example_is_left_alone() -> None:
    text = "DOI Foundation'ın kendi öneki 10.1000'dir; DOI'ler hep 10. ile başlar."
    out, _ = guarded(text, fiction=True)
    assert out == text
    other = "Nature'ın öneki 10.1038'dir."  # not fiction: never touched
    assert guarded(other)[0] == other


@pytest.mark.parametrize("address", ["siz", "sen"])
@pytest.mark.parametrize("fiction", [False, True])
def test_integrity_rules_stream_to_the_same_text(address: str, fiction: bool) -> None:
    policy = claims.Policy(claims.ClaimState.NO_MEMORY_ACTION)
    text = (
        LANCET
        + ' Önek "10.1016" yayıncıyı gösterir. Bu DOI geçerlidir.\nİsterseniz bakabilirsiniz.'
    )
    whole = reply_guard.check(text, policy, address=address, doi_fiction=fiction)
    rng = random.Random(5)
    for _ in range(40):
        g = reply_guard.ReplyGuard(policy, address=address, doi_fiction=fiction)
        out, i = "", 0
        while i < len(text):
            n = rng.randint(1, 9)
            out += g.feed(text[i : i + n])
            i += n
        assert out + g.finish() == whole == g.released


def test_after_an_example_a_sentence_that_vouches_for_it_is_dropped() -> None:
    text = ("Örnekler:\n* 10.1016/s0140-6736(21)00914-3\n\nBu DOI'ler ilgili yayınlara erişim "
            "sağlamaktadır. Bu DOI'yi yazılım testlerinde kullanabilirsiniz.")  # fmt: skip
    out, g = guarded(text, fiction=True)
    assert "10.5555/ornek.0001" in out and "erişim sağlamaktadır" not in out
    assert "Bu DOI'yi yazılım testlerinde kullanabilirsiniz." in out  # about the example: stays
    assert out.endswith(C.FICTION_NOTE) and len(g.dropped) == 1
