"""Indirect memory claims (Phase 9 final corrections): a converb that claims what its main verb
claims ("Kervan bilgisini düzelterek bunu esas alıyorum", seen with Gemma), adopting a value
("esas alıyorum", "güncel tutacağım"), in every memory state — and what must stay untouched."""

from __future__ import annotations

import pytest

from lazis.memory.claims import ClaimGuard, ClaimState, Policy, check, fold, rewrite_sentence
from tests.unit.test_memory_claims import splits, stream, unauthorized


def _p(state: ClaimState) -> Policy:
    return Policy(state, memory_turn=state not in (ClaimState.AUTO_LEARNING_PENDING,
                                                   ClaimState.NO_MEMORY_ACTION))  # fmt: skip


AUTO = _p(ClaimState.AUTO_LEARNING_PENDING)
NONE = _p(ClaimState.NO_MEMORY_ACTION)

# (state, model reply, what is shown and stored)
INDIRECT = [
    (AUTO, "Kervan bilgisini düzelterek bunu esas alıyorum.", "Kervan bilgisini anladım."),
    (
        AUTO,
        "Kervan bilgisini düzelterek bunu esas alıyorum efendim.",
        "Kervan bilgisini anladım efendim.",
    ),
    (AUTO, "Bilgiyi düzelterek bunu esas alıyorum.", "Bilgiyi anladım."),
    (AUTO, "Önceki bilgiyi kaldırıp yenisini kullanacağım.", "Önceki bilgiyi anladım."),
    (AUTO, "Bunu hafızamda güncel tutacağım.", "Bunu anladım."),
    (AUTO, "Bilgilerinizi güncelleyerek Atlas'ı esas aldım.", "Bilgilerinizi anladım."),
    (AUTO, "Eski bilgiyi silip yerine Atlas'ı yazdım.", "Eski bilgiyi anladım."),
    (AUTO, "İş yeri bilginizi düzeltip Atlas olarak kaydediyorum.", "İş yeri bilginizi anladım."),
    (AUTO, "Hafızama ekleyerek bundan sonra bunu hatırlayacağım.", "Anladım."),
    (AUTO, "Bundan sonra Atlas'ı esas alacağım.", "Bundan sonra Atlas'ı anladım."),
    (AUTO, "Artık Atlas Yazılım'ı esas alıyorum.", "Artık Atlas Yazılım'ı anladım."),
    (AUTO, "Bundan sonra bunu dikkate alacağım.", "Bundan sonra bunu anladım."),
    (AUTO, "Bilginizi güncelledikten sonra Atlas'ı kullanıyorum.", "Bilginizi anladım."),
    (AUTO, "Kayıtlarımı düzelterek Atlas'ı temel aldım.", "Kayıtlarımı anladım."),
    (AUTO, "Bu bilgiyi kalıcı olarak saklıyorum.", "Bu bilgiyi anladım."),
    (AUTO, "Bilgileri birleştirip tek kayıt hâline getirdim.", "Bilgileri anladım."),
    (
        AUTO,
        "Peki efendim, Kervan bilgisini düzelterek Atlas'ı esas alıyorum.",
        "Peki efendim, Kervan bilgisini anladım.",
    ),
    (AUTO, "Anladım, bilgiyi güncelleyip Atlas'ı esas aldım.", "Anladım."),
    # A failure, a pending or cancelled request: the truth, in the claim's place.
    (
        _p(ClaimState.SAVE_FAILED),
        "Bilgiyi kaydederek not defterime işliyorum.",
        "Bilgiyi kaydedemedim.",
    ),
    (
        _p(ClaimState.SAVE_FAILED),
        "Bunu hafızama ekleyip saklıyorum.",
        "Bunu hafızama kaydedemedim.",
    ),
    (
        _p(ClaimState.UPDATE_FAILED),
        "Bilgiyi düzelterek Atlas'ı esas aldım.",
        "Bilgiyi güncelleyemedim.",
    ),
    (
        _p(ClaimState.UPDATE_FAILED),
        "Kervan bilgisini güncelleyerek değiştirdim.",
        "Kervan bilgisini güncelleyemedim.",
    ),
    (
        _p(ClaimState.SAVE_PENDING),
        "Bilgiyi kaydedip hafızama ekliyorum.",
        "Bilgiyi henüz kaydetmedim.",
    ),
    (_p(ClaimState.SAVE_CANCELLED), "Bunu kaydederek hafızama aldım.", "Bunu kaydetmedim."),
    (
        _p(ClaimState.DELETE_PENDING),
        "Ahmet bilgilerini silerek hafızamdan çıkardım.",
        "Ahmet bilgilerini henüz silmedim.",
    ),
    (_p(ClaimState.DELETE_FAILED), "Bilgiyi silip kaldırdım.", "Bilgiyi silmedim."),
]


@pytest.mark.parametrize(("policy", "reply", "expected"), INDIRECT)
def test_indirect_claims_are_reworded(policy: Policy, reply: str, expected: str) -> None:
    out, rewrites = check(reply, policy)
    assert out == expected
    assert rewrites and unauthorized(out, policy) == []


DONE = [
    (_p(ClaimState.UPDATE_SUCCEEDED), "Kervan bilgisini düzelterek Atlas'ı esas aldım."),
    (_p(ClaimState.SAVE_SUCCEEDED), "Bilgiyi kaydederek hafızama ekledim."),
    (_p(ClaimState.DELETE_SUCCEEDED), "Bilgiyi silerek hafızamdan çıkardım."),
]


@pytest.mark.parametrize(("policy", "reply"), DONE)
def test_a_real_operation_may_be_told_indirectly_too(policy: Policy, reply: str) -> None:
    assert check(reply, policy) == (reply, [])


# Not claims: questions, offers, conditions, explanations, other tasks, this conversation only.
UNTOUCHED = [
    (NONE, "Bilgileri nasıl güncelliyorsun?"),
    (NONE, "Bilgiyi güncellememi isterseniz bunu yapabiliriz."),
    (AUTO, "Bilgiyi güncellememi isterseniz bunu yapabiliriz."),
    (AUTO, "Kervan bilgisini düzeltmemi ister misiniz?"),
    (AUTO, "Bilgiyi düzelterek kaydetmemi ister misiniz?"),
    (AUTO, "Bilgiyi düzeltip kaydedebilirim; ister misiniz?"),
    (AUTO, "Bilgiyi silmeden önce onayınızı almam gerekiyor."),
    (NONE, "Bu hesapta 2024 verilerini esas alıyorum."),
    (NONE, "Hafıza ekranında bilgileri düzelterek güncelleyebilirsiniz."),
    (NONE, "LAZIS, bilgileri sizin onayınızla güncelleyerek saklar."),
    (AUTO, "Bu konuşmada söylediklerinizi dikkate alacağım."),
    (AUTO, "Kodu düzelterek tekrar çalıştırdım."),
    (AUTO, "Paragrafı düzeltip daha akıcı hale getirdim."),
    (NONE, "Bilgileri düzelterek kaydetmek için Hafıza ekranını kullanabilirsiniz."),
    (AUTO, "Bilgiyi düzelterek tekrar sorayım mı?"),
    (AUTO, "Kervan mı Atlas mı, hangisi güncel?"),
    (NONE, "Bilgilerinizi güncellerken her zaman onayınızı isterim."),
    (
        AUTO,
        "Önceki bilgiyle çelişen bir ifade var. Hangisinin güncel olduğunu netleştirebilir "
        "miyiz efendim?",
    ),
    (AUTO, "Bunu kalıcı olarak kaydetmemi ister misiniz efendim?"),
    (AUTO, "Söylediğiniz bilgiyi anladım efendim."),
    (
        NONE,
        "Hafızam, sizin paylaştığınız bilgileri yerel ve şifreli bir veritabanında tutar; "
        "bir bilgi değişirse önce size sorarım.",
    ),
    (NONE, "Bilgilerinizi Hafıza ekranından silebilir ya da düzeltebilirsiniz."),
]


@pytest.mark.parametrize(("policy", "reply"), UNTOUCHED)
def test_explanations_and_offers_are_untouched(policy: Policy, reply: str) -> None:
    assert check(reply, policy) == (reply, [])


STREAMED = {"Anladım, bilgiyi güncelleyip Atlas'ı esas aldım.": "Anladım, bilgiyi anladım."}


@pytest.mark.parametrize(("policy", "reply", "expected"), INDIRECT)
def test_streamed_indirect_claims_never_appear(policy: Policy, reply: str, expected: str) -> None:
    for sizes in splits(reply, len(reply))[:60]:
        final, outputs = stream(reply, sizes, policy)
        # Once "Anladım, " was shown the connector cannot go: the claim is reworded instead.
        assert final == expected or final == STREAMED.get(reply), sizes
        for shown in outputs:
            assert unauthorized(shown, policy) == [], (sizes, shown)
            # Nothing of the claim's words was shown before the decision.
            assert "esas al" not in fold(shown) or "esas al" in fold(expected)
            assert "duzelterek" not in fold(shown) and "kaldirip" not in fold(shown)


def test_the_briefs_chunking_of_the_kervan_reply() -> None:
    guard = ClaimGuard(AUTO)
    shown = ""
    for chunk in ("Bilgiyi ", "düzelterek ", "bunu esas ", "alıyorum."):
        shown += guard.feed(chunk)
        assert "duzelt" not in fold(shown) and "esas" not in fold(shown), shown
    shown += guard.finish()
    assert shown == guard.released == "Bilgiyi anladım."


@pytest.mark.parametrize(("policy", "reply"), UNTOUCHED)
def test_streamed_explanations_are_unchanged(policy: Policy, reply: str) -> None:
    for sizes in splits(reply, 11)[:40]:
        assert stream(reply, sizes, policy)[0] == reply


def test_a_claim_the_rewording_leaves_takes_the_rest_of_the_sentence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fail closed: whatever the rewording produced is checked again (here a broken table
    rewords a claim into another claim)."""
    from lazis.memory import claims

    failed = _p(ClaimState.SAVE_FAILED)
    monkeypatch.setitem(claims._REPLACEMENT, (ClaimState.SAVE_FAILED, "save"), "kaydettim")
    out, rewrites = rewrite_sentence("Peki, bunu hafızama kaydettim efendim.", failed)
    assert out == "Peki, bunu kaydedemedim."
    assert unauthorized(out, failed) == [] and len(rewrites) == 2
