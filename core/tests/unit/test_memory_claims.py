"""Truthful memory claims (Phase 7.1): the reply guard rewrites only claims the real memory
outcome does not support, never shows one while streaming, and leaves everything else alone.
"""

from __future__ import annotations

import random

import pytest

from lazis.memory.claims import ClaimGuard, ClaimState, Policy, check, find_claims, fold, state_for

AUTO = Policy(ClaimState.AUTO_LEARNING_PENDING)
NONE = Policy(ClaimState.NO_MEMORY_ACTION)
RECALLED = Policy(ClaimState.NO_MEMORY_ACTION, has_memory=True)
SAVED = Policy(ClaimState.SAVE_SUCCEEDED, memory_turn=True)
SAVE_FAILED = Policy(ClaimState.SAVE_FAILED, memory_turn=True)
SAVE_PENDING = Policy(ClaimState.SAVE_PENDING, memory_turn=True)
DELETED = Policy(ClaimState.DELETE_SUCCEEDED, memory_turn=True)
DELETE_FAILED = Policy(ClaimState.DELETE_FAILED, memory_turn=True)
DELETE_PENDING = Policy(ClaimState.DELETE_PENDING, memory_turn=True)
UPDATED = Policy(ClaimState.UPDATE_SUCCEEDED, memory_turn=True)
UPDATE_FAILED = Policy(ClaimState.UPDATE_FAILED, memory_turn=True)


def unauthorized(text: str, policy: Policy) -> list[str]:
    return [text[c.start : c.end] for c in find_claims(text, policy) if not policy.allows(c.kind)]


# ----- 1. claims after a statement (learning pending): reworded -------------------------------
REWORDED = [
    ("Not aldım.", "Anladım."),
    ("Not ettim.", "Anladım."),
    ("Kaydettim efendim.", "Anladım efendim."),
    ("Kaydettim.", "Anladım."),
    ("Bunu kaydettim.", "Bunu anladım."),
    ("Bunu hafızama kaydettim.", "Bunu anladım."),
    ("Hafızama kaydettim efendim.", "Anladım efendim."),
    ("Bu bilgiyi hafızama ekledim.", "Bu bilgiyi anladım."),
    ("Hafızama ekledim.", "Anladım."),
    ("Hafızama aldım.", "Anladım."),
    ("Aklımda tutacağım efendim.", "Anladım efendim."),
    ("Bunu aklımda tutacağım.", "Bunu anladım."),
    ("Hafızamda tutacağım.", "Anladım."),
    ("Bunu unutmayacağım.", "Bunu anladım."),
    ("Unutmayacağım efendim.", "Anladım efendim."),
    ("Artık hatırlayacağım.", "Artık anladım."),
    ("Bunu hatırlayacağım efendim.", "Bunu anladım efendim."),
    ("Bunu öğrendim efendim.", "Bunu anladım efendim."),
    ("Bilgi kaydedildi.", "Bilgi anlaşıldı."),
    ("Bu bilgi hafızama eklendi.", "Bu bilgi anlaşıldı."),
    ("Kaydediyorum efendim.", "Anladım efendim."),
    ("Not alıyorum.", "Anladım."),
    ("Bunu kaydedeceğim.", "Bunu anladım."),
    ("Kayıt altına aldım.", "Anladım."),
    ("Anladım ve not aldım.", "Anladım."),
    ("Tamam, not aldım.", "Tamam."),
    ("Tamam efendim, bunu not aldım.", "Tamam efendim, bunu anladım."),
    (
        "Anlaşıldı efendim. Ahmet'in kardeşi Mehmet olduğunu not ettim; başka bir konuda yardımcı olabilir miyim?",
        "Anlaşıldı efendim. Ahmet'in kardeşi Mehmet olduğunu anladım; başka bir konuda yardımcı olabilir miyim?",
    ),
    (
        "Ahmet’in kardeşinin Mehmet olduğunu hafızama kaydettim efendim. Mehmet’in mesleğini de biliyor muyuz?",
        "Ahmet’in kardeşinin Mehmet olduğunu anladım efendim. Mehmet’in mesleğini de biliyor muyuz?",
    ),
    (
        "Kervan Lojistik'te çalıştığınızı not ettim. Sizin için yapabileceğim bir şey var mı?",
        "Kervan Lojistik'te çalıştığınızı anladım. Sizin için yapabileceğim bir şey var mı?",
    ),
    (
        "Anlaşıldı efendim, bunu hafızama kaydettim ve Ahmet'e iyi dileklerimi iletirim.",
        "Anlaşıldı efendim, Ahmet'e iyi dileklerimi iletirim.",
    ),
    (
        "Sevgiliniz Ece ile yemeğe çıkacağınızı not ettim.",
        "Sevgiliniz Ece ile yemeğe çıkacağınızı anladım.",
    ),
    (
        "Murat'ın Pusula projesinde çalıştığını kaydettim.",
        "Murat'ın Pusula projesinde çalıştığını anladım.",
    ),
    (
        "Kuzeniniz Deniz'in aradığını not aldım efendim.",
        "Kuzeniniz Deniz'in aradığını anladım efendim.",
    ),
    ("Çocukluk arkadaşınız Ahmet'i hafızama ekledim.", "Çocukluk arkadaşınız Ahmet'i anladım."),
    ("Bunu kaydettik.", "Bunu anladım."),
    ("NOT ALDIM.", "Anladım."),
    ("Hafızama yazdım efendim.", "Anladım efendim."),
    ("Bunu notlarıma ekledim.", "Bunu anladım."),
    ("Bunu kayda geçirdim.", "Bunu anladım."),
    # Phase 7.1 real-model finding: possessive and record-noun forms.
    ("Notunuzu aldım; düğün haziranda olacak.", "Anladım; düğün haziranda olacak."),
    ("Notlarınızı aldım, teşekkürler.", "Anladım, teşekkürler."),
    ("Toplantının notunu aldım efendim.", "Toplantının bilgisini anladım efendim."),
    ("Ahmet'in doğum gününün kaydını aldım.", "Ahmet'in doğum gününün bilgisini anladım."),
    ("Bu notu aldım.", "Bu bilgiyi anladım."),
    ("Ahmet için bir kayıt oluşturdum.", "Ahmet için bunu anladım."),
    ("Bunu kayda aldım.", "Bunu anladım."),
    ("Kahve tercihinizi bilgilerime ekledim efendim.", "Kahve tercihinizi anladım efendim."),
    # Phase 9 real-model finding: the user's records as the place.
    (
        "Not aldım efendim. İstanbul'da yaşadığınızı bilgilerinize ekledim.",
        "Anladım efendim. İstanbul'da yaşadığınızı anladım.",
    ),
    ("Bunu kayıtlarınıza ekledim.", "Bunu anladım."),
    ("Bunu profilinize kaydettim.", "Bunu anladım."),
    # Phase 9 real-model finding (s08): what the user told, as the value or the object.
    (
        "Anlaşıldı efendim, tercihinizi sütlü kahve olarak güncelledim.",
        "Anlaşıldı efendim, tercihinizi sütlü kahve olarak anladım.",
    ),
    ("Adresinizi İzmir olarak düzelttim.", "Adresinizi İzmir olarak anladım."),
    ("Mesleğinizi değiştirdim.", "Mesleğinizi anladım."),
    ("Bunu listeme ekledim.", "Bunu anladım."),
    ("Toplantıyı ajandama yazdım.", "Toplantıyı anladım."),
    ("Anladım ve notunu aldım.", "Anladım."),
    ("Notumu aldım efendim.", "Anladım efendim."),
    (
        "Dişçi randevunuzun salı günü olduğunu not etmiş oldum.",
        "Dişçi randevunuzun salı günü olduğunu anladım.",
    ),
    ("Bu bilgiyi kaydetmiş oldum efendim.", "Bu bilgiyi anladım efendim."),
    ("Anladım efendim, notlarımı aldım.", "Anladım efendim."),
    ("Bu bilgiyi kayıtlarım arasına ekledim.", "Bu bilgiyi anladım."),
    ("Bunu hafızamın bir köşesine yazdım efendim.", "Bunu anladım efendim."),
    # A storage word further back in the sentence (real-model finding, two-Ahmet check).
    (
        "Not defterime Ahmet'in doğum gününün 5 Mayıs olduğunu ekledim.",
        "Ahmet'in doğum gününün 5 Mayıs olduğunu anladım.",
    ),
    (
        "Hafızama bu konuşmadan iki bilgi yazdım efendim.",
        "Bu konuşmadan iki bilgi anladım efendim.",
    ),
    (
        "Anlaşıldı, listeme yarınki toplantıyı da ekledim.",
        "Anlaşıldı, yarınki toplantıyı da anladım.",
    ),
    # Information as the object (Phase 9 real-model finding: said after a conflict was asked).
    (
        "Bilgiyi güncelledim efendim. Artık Pusula'da çalıştığınızı anladım.",
        "Bilgiyi anladım efendim. Artık Pusula'da çalıştığınızı anladım.",
    ),
    ("Bilgilerinizi güncelledim.", "Bilgilerinizi anladım."),
    ("İş yeri bilginizi güncelledim efendim.", "İş yeri bilginizi anladım efendim."),
    ("Bu bilgiyi sildim.", "Bu bilgiyi anladım."),
    ("Bilgi güncellendi.", "Bilgi anlaşıldı."),
    ("Kayıt güncellendi.", "Kayıt anlaşıldı."),
]


@pytest.mark.parametrize(("reply", "expected"), REWORDED)
def test_claims_after_a_statement_are_reworded(reply: str, expected: str) -> None:
    out, rewrites = check(reply, AUTO)
    assert out == expected
    assert rewrites and unauthorized(out, AUTO) == []


# ----- 2. not claims: untouched --------------------------------------------------------------
UNTOUCHED = [
    "Tercihinizi güncellememi isterseniz söyleyin.",
    "İsterseniz bunu bilgilerinize ekleyebilirim.",
    "Bilgileriniz güvende, cihazınızda şifreli tutuluyor.",
    "Anladım efendim.",
    "Anladım efendim, Ahmet'in kardeşi Mehmet.",
    "Bahsettiğiniz kişiyi anlıyorum.",
    "Bu konuşmada söylediklerinizi dikkate alacağım.",
    "Bunu kaydetmedim.",
    "Bunu henüz kaydetmedim.",
    "Bunu kaydedemedim.",
    "Hafızama kaydedemedim efendim.",
    "Bu bilgi kaydedilmedi.",
    "Not almadım.",
    "Bunu unutmadım.",
    "İsterseniz bunu hafızama kaydedebilirim.",
    "Dilerseniz not alabilirim.",
    "Kaydedeyim mi?",
    "Bunu hafızama kaydedeyim mi efendim?",
    "İsterseniz kaydederim.",
    "Kaydetmemi ister misiniz?",
    "Kaydettim mi?",
    "Bunu kaydettiniz mi?",
    "Kaydettiniz.",
    "Siz not aldınız.",
    "“Bunu hafızama kaydettim” ifadesini kullanmam doğru değildi.",
    '"Not aldım" demem yanlıştı.',
    "Hafızamda bu konuda bir bilgi yok.",
    "Hafızamda kayıtlı bir bilgi bulunmuyor.",
    "Daha önce kaydettiğimiz bir bilgi yok.",
    "Bir not defteri almanızı öneririm.",
    "Kayıt olmak için formu doldurun.",
    "Notunuzu aldım gibi bir şey söylemem gerekmez.",
    "Hatırlıyorum, Ahmet öğretmendi.",
    "Bunu hatırlıyor musunuz?",
    "Unutmayın, toplantı yarın saat onda.",
    "Gereksiz cümleyi sildim ve metni düzelttim.",
    "Paragrafı güncelledim, daha akıcı oldu.",
    "Bu kodda iki hatayı düzelttim.",
    "Bunu öğrenmek ister misiniz?",
    "Python'da bir sözlüğü sıralamak için sorted() kullanılır.",
    "Hafıza kartı fotoğraf makinesinde dolmuş olabilir.",
    "Bilgisayarınızın belleği 24 GB.",
    "Not: Bu sadece bir öneri.",
    "Kaydetmek isterseniz Hafıza ekranını kullanabilirsiniz.",
    "Kayıt defteri Windows'ta ayarları tutar.",
    "Ahmet bunu not etmiş.",
    "Mehmet de bunu öğrendi.",
    "Unutkanlık herkeste olur.",
    "Ahmet'in kardeşi Mehmet, eşi Zeynep.",
    "Sizi anlıyorum; zor bir gün geçirmişsiniz.",
    "Kaydedebileceğim bir bilgi göremedim.",
    "Bunu kaydetmeyeceğim, çünkü bir şifre içeriyor.",
    "Bu bilgiyi hafızama almadım.",
    "Notunuzu alabilirim.",
    "Not defterinizi aldınız mı?",
    "Toplantı notlarını aldınız mı?",
    "Not aldım gibi bir şey söylemem gerekmez.",
    "Kaydettim diye düşünmeyin, henüz bir şey yazılmadı.",
    "Listeme bakınca bugün üç işiniz var gibi görünüyor.",
    "Bir kayıt oluşturmak isterseniz söylemeniz yeterli.",
    "Ajandama bakarsanız toplantıyı eklediğinizi görürsünüz.",
    "Listeme göre yarın üç işiniz var.",
    "Bilgisayarınızı güncelledim.",
    "Paragraf güncellendi.",
    "Ahmet raporu güncelledi.",
    "Bu konuda bilgi vermek isterim.",
]


@pytest.mark.parametrize("reply", UNTOUCHED)
def test_ordinary_replies_are_untouched(reply: str) -> None:
    out, rewrites = check(reply, AUTO)
    assert out == reply and rewrites == []


# ----- 3. references to existing records ------------------------------------------------------
EXISTING = [
    (
        "Daha önce kaydettiğimiz bilgiye göre Ahmet öğretmen.",
        "Daha önce konuştuğumuz bilgiye göre Ahmet öğretmen.",
    ),
    ("Bu bilgi daha önce hafızama kaydedilmiş.", "Bu bilgi daha önce konuşmamızda geçmiş."),
    ("Hafızamdaki bilgiye göre Ahmet öğretmen.", "Konuşmamızdaki bilgiye göre Ahmet öğretmen."),
    (
        "Kaydettiğim bilgilere göre İzmir'de yaşıyorsunuz.",
        "Konuştuğumuz bilgilere göre İzmir'de yaşıyorsunuz.",
    ),
    (
        "Hafızamda Ahmet'in kardeşi olarak Mehmet var.",
        "Konuşmamızda Ahmet'in kardeşi olarak Mehmet var.",
    ),
]


@pytest.mark.parametrize(("reply", "without_memory"), EXISTING)
def test_references_need_a_recalled_record(reply: str, without_memory: str) -> None:
    assert check(reply, RECALLED)[0] == reply  # recall really brought memory: true
    assert check(reply, NONE)[0] == without_memory


# ----- 4. explicit requests: the real outcome decides ------------------------------------------
OUTCOMES = [
    (  # the real-model case: an explicit save the command step found nothing to store in
        SAVE_FAILED,
        "Anlaşıldı efendim. Notunuzu aldım; Burak'ın düğünü haziranda olacak.",
        "Anlaşıldı efendim. Kaydedemedim; Burak'ın düğünü haziranda olacak.",
    ),
    (SAVE_FAILED, "Ahmet'in kaydını aldım.", "Ahmet'in bilgisini kaydedemedim."),
    (SAVE_PENDING, "Toplantının notunu aldım.", "Toplantının bilgisini henüz kaydetmedim."),
    (SAVED, "Notunuzu aldım efendim.", "Notunuzu aldım efendim."),
    (  # the real-model case (Phase 7.2): a failed save
        SAVE_FAILED,
        "Bunu şu anda kaydedemedim efendim. Ancak randevunuzun salı olduğunu not etmiş oldum.",
        "Bunu şu anda kaydedemedim efendim. Ancak randevunuzun salı olduğunu kaydedemedim.",
    ),
    (  # the real-model case (Phase 7.2, 4th run): a save waiting for "which Mehmet?"
        SAVE_PENDING,
        "Anladım efendim, kayıtlarım arasına ekledim. Ancak hangi Mehmet?",
        "Anladım efendim, kayıtlarım arasına henüz kaydetmedim. Ancak hangi Mehmet?",
    ),
    (  # the real-model case: a save waiting for "which Çağla?"
        SAVE_PENDING,
        "Notumu aldım efendim. Bu doğum günü hangi Çağla'ya ait?",
        "Henüz kaydetmedim efendim. Bu doğum günü hangi Çağla'ya ait?",
    ),
    (  # the real-model case: two namesakes, the save waits for "which Ahmet?"
        SAVE_PENDING,
        "Not defterime Ahmet'in doğum gününün 5 Mayıs olduğunu ekledim.",
        "Not defterime Ahmet'in doğum gününün 5 Mayıs olduğunu henüz kaydetmedim.",
    ),
    (
        SAVE_FAILED,
        "Hafızama bu konuşmadan iki bilgi yazdım.",
        "Hafızama bu konuşmadan iki bilgi kaydedemedim.",
    ),
    (
        SAVED,
        "Not defterime Ahmet'in doğum gününü ekledim.",
        "Not defterime Ahmet'in doğum gününü ekledim.",
    ),
    (
        SAVED,
        "Kaydettim efendim. Ahmet’in kardeşi Mehmet.",
        "Kaydettim efendim. Ahmet’in kardeşi Mehmet.",
    ),
    (SAVED, "Bunu hafızama kaydettim.", "Bunu hafızama kaydettim."),
    (SAVED, "Not aldım efendim.", "Not aldım efendim."),
    (SAVED, "Selin'in kuzeniniz olduğunu kaydettim.", "Selin'in kuzeniniz olduğunu kaydettim."),
    (SAVE_FAILED, "Bunu hafızama kaydettim.", "Bunu hafızama kaydedemedim."),
    (SAVE_FAILED, "Kaydettim efendim.", "Kaydedemedim efendim."),
    (SAVE_FAILED, "Bilgi kaydedildi.", "Bilgi kaydedilemedi."),
    (
        SAVE_FAILED,
        "Bu bilgiyi şu anda hafızama kaydedemedim efendim.",
        "Bu bilgiyi şu anda hafızama kaydedemedim efendim.",
    ),
    (SAVE_PENDING, "Kaydettim efendim.", "Henüz kaydetmedim efendim."),
    (
        SAVE_PENDING,
        "Kaydetme işlemi henüz tamamlanmadı efendim.",
        "Kaydetme işlemi henüz tamamlanmadı efendim.",
    ),
    (
        DELETED,
        "Ahmet ile Mehmet arasındaki ilişkiyi hafızamdan sildim.",
        "Ahmet ile Mehmet arasındaki ilişkiyi hafızamdan sildim.",
    ),
    (DELETED, "Unuttum efendim.", "Unuttum efendim."),
    (
        DELETE_FAILED,
        "Ahmet'in mesleğini hafızamdan sildim.",
        "Ahmet'in mesleğini hafızamdan silmedim.",
    ),
    (DELETE_FAILED, "Bilgi silindi.", "Bilgi silinmedi."),
    (
        DELETE_PENDING,
        "Ahmet hakkındaki bilgileri sildim.",
        "Ahmet hakkındaki bilgileri henüz silmedim.",
    ),
    (
        DELETE_PENDING,
        "Onayınızı bekliyorum; henüz bir şey silmedim.",
        "Onayınızı bekliyorum; henüz bir şey silmedim.",
    ),
    (DELETE_PENDING, "Bunu kaydettim.", "Bunu henüz kaydetmedim."),
    (
        UPDATED,
        "Mehmet'in Ahmet'in kuzeni olduğunu güncelledim efendim.",
        "Mehmet'in Ahmet'in kuzeni olduğunu güncelledim efendim.",
    ),
    (
        UPDATED,
        "Düzelttim; Selin artık komşunuz olarak kayıtlı.",
        "Düzelttim; Selin artık komşunuz olarak kayıtlı.",
    ),
    (UPDATE_FAILED, "Mehmet'in mesleğini güncelledim.", "Mehmet'in mesleğini güncelleyemedim."),
    (UPDATE_FAILED, "Kaydı düzelttim.", "Kaydı güncelleyemedim."),
    (AUTO, "Mehmet'in mesleğini hafızamda güncelledim.", "Mehmet'in mesleğini anladım."),
]


@pytest.mark.parametrize(("policy", "reply", "expected"), OUTCOMES)
def test_explicit_requests_follow_the_real_outcome(
    policy: Policy, reply: str, expected: str
) -> None:
    out, _ = check(reply, policy)
    assert out == expected
    assert unauthorized(out, policy) == []


# ----- 5. the state comes from the real outcome --------------------------------------------
@pytest.mark.parametrize(
    ("intent", "outcome", "statement", "expected"),
    [
        (None, None, True, ClaimState.AUTO_LEARNING_PENDING),
        (None, None, False, ClaimState.NO_MEMORY_ACTION),
        ("recall", None, False, ClaimState.NO_MEMORY_ACTION),
        ("remember", "saved", True, ClaimState.SAVE_SUCCEEDED),
        ("remember", "failed", True, ClaimState.SAVE_FAILED),
        ("remember", "refused", True, ClaimState.SAVE_FAILED),
        ("remember", "nothing", True, ClaimState.SAVE_FAILED),
        ("remember", "untrusted_model", True, ClaimState.SAVE_FAILED),
        ("remember", "ambiguous", True, ClaimState.SAVE_PENDING),
        ("remember", "none", True, ClaimState.AUTO_LEARNING_PENDING),  # not a request after all
        ("secret", "secret_not_stored", True, ClaimState.SAVE_FAILED),
        ("correct", "corrected", True, ClaimState.UPDATE_SUCCEEDED),
        ("correct", "failed", True, ClaimState.UPDATE_FAILED),
        ("forget", "forgotten", False, ClaimState.DELETE_SUCCEEDED),
        ("forget", "confirm_needed", False, ClaimState.DELETE_PENDING),
        ("forget", "not_found", False, ClaimState.DELETE_FAILED),
        ("confirm", "forgotten", False, ClaimState.DELETE_SUCCEEDED),
        ("decline", "declined", False, ClaimState.DELETE_FAILED),
        ("same", "confirm_needed", False, ClaimState.SAVE_PENDING),
        ("different", "distinguished", False, ClaimState.UPDATE_SUCCEEDED),
    ],
)
def test_state_from_the_real_outcome(
    intent: str | None, outcome: str | None, statement: bool, expected: ClaimState
) -> None:
    assert state_for(intent, outcome, statement=statement, learning=True) == expected


def test_without_learning_a_statement_is_no_memory_action() -> None:
    assert state_for(None, None, statement=True, learning=False) == ClaimState.NO_MEMORY_ACTION
    # …and a save claim is still not true.
    assert check("Not aldım.", NONE)[0] == "Anladım."


# ----- 6. streaming: no claim in any intermediate output, same final text --------------------
FORBIDDEN = ("not aldim", "not ettim", "kaydettim", "hafizama", "unutmayacagim", "hatirlayacagim",
             "kaydedildi", "aklimda tut", "ogrendim", "kaydediyorum", "eklendi", "notunuzu aldim",
             "notlarinizi aldim", "notunu aldim", "kaydini aldim", "kayit olusturdum", "kayda aldim",
             "bilgilerime ekledim", "listeme ekledim", "ajandama yazdim", "bilgilerinize ekledim",
             "defterime", "hafizama bu", "listeme yarinki", "notumu aldim", "notlarimi aldim", "arasina ekledim",
             "kosesine yazdim", "etmis oldum", "kaydetmis oldum")  # fmt: skip


def stream(text: str, chunks: list[int], policy: Policy) -> tuple[str, list[str]]:
    guard = ClaimGuard(policy)
    shown, outputs, i = "", [], 0
    for n in chunks:
        shown += guard.feed(text[i : i + n])
        outputs.append(shown)
        i += n
    shown += guard.feed(text[i:])
    shown += guard.finish()
    outputs.append(shown)
    return shown, outputs


def splits(text: str, seed: int) -> list[list[int]]:
    rng = random.Random(seed)
    out = [[len(text)], [1] * len(text)]
    out += [[k] for k in range(1, len(text))]  # every two-part split
    for _ in range(20):
        sizes, left = [], len(text)
        while left > 0:
            n = min(left, rng.randint(1, 12))
            sizes.append(n)
            left -= n
        out.append(sizes)
    return out


@pytest.mark.parametrize(("reply", "expected"), REWORDED)
def test_streamed_claims_never_appear(reply: str, expected: str) -> None:
    for sizes in splits(reply, len(reply)):
        final, outputs = stream(reply, sizes, AUTO)
        assert final == expected, sizes
        for shown in outputs:
            folded = fold(shown)
            assert not any(f in folded for f in FORBIDDEN), (sizes, shown)
            assert unauthorized(shown, AUTO) == [], (sizes, shown)


@pytest.mark.parametrize(
    "chunks",
    [["Not aldım."], ["Not", " aldım."], ["N", "ot al", "dım."], ["Not ald", "ım."],
     ["Hafızama", " kaydettim."], ["Kay", "dettim."], ["Bunu", " unutmayacağım."]],
)  # fmt: skip
def test_the_briefs_chunkings(chunks: list[str]) -> None:
    guard = ClaimGuard(AUTO)
    shown = ""
    for c in chunks:
        shown += guard.feed(c)
        assert unauthorized(shown, AUTO) == [] and not any(f in fold(shown) for f in FORBIDDEN)
    shown += guard.finish()
    assert unauthorized(shown, AUTO) == []
    assert shown in ("Anladım.", "Bunu anladım.")


@pytest.mark.parametrize("reply", UNTOUCHED[:30])
def test_streamed_ordinary_text_is_unchanged(reply: str) -> None:
    for sizes in splits(reply, 7)[:40]:
        assert stream(reply, sizes, AUTO)[0] == reply


def test_ordinary_text_flows_with_a_one_word_lag() -> None:
    guard = ClaimGuard(AUTO)
    shown = guard.feed("Merhaba efendim, bugün hava ")
    assert shown == "Merhaba efendim, bugün"  # the last word may still grow or be a connector
    shown += guard.feed("çok güzel. ")
    assert shown == "Merhaba efendim, bugün hava çok"
    shown += guard.finish()
    assert shown == "Merhaba efendim, bugün hava çok güzel. "


def test_a_long_sentence_is_not_held_forever() -> None:
    guard = ClaimGuard(AUTO)
    long = "Not defterinizde " + "çok " * 100
    shown = guard.feed(long)
    assert len(shown) > 0  # decided at a word boundary after MAX_HOLD characters


def test_a_claim_cannot_straddle_the_long_sentence_cut() -> None:
    for pad in range(40, 53):  # the cut falls just before, inside and after "not aldım"
        reply = (
            "Not defterinizde " + "çok " * pad + "güzel şeyler var ve bunları not aldım efendim."
        )
        out, shown = stream(reply, [5] * (len(reply) // 5 + 1), AUTO)
        assert all("not aldim" not in fold(s) for s in shown), pad
        assert out.endswith("ve bunları anladım efendim.") or out.endswith("anladım efendim."), out


def test_successful_explicit_saves_stream_unchanged() -> None:
    reply = "Kaydettim efendim. Ahmet’in kardeşi Mehmet."
    for sizes in splits(reply, 3):
        assert stream(reply, sizes, SAVED)[0] == reply
