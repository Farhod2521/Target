"""The ready answers for Meta's errors as the assistant finds them: by a
code, by the words people use, and never by a word every answer has."""

from app.modules.ads.contract.launch.failures import guide_for, guides
from app.modules.ads.contract.launch.words import LaunchErrorCode
from app.modules.assistant.selectors.help import (
    _asked,
    _guides,
    _launches,
    _troubles,
    ranked,
)
from app.modules.chat.selectors.lookups.common import ready_fix


def _found(query: str) -> list[str]:
    shelves = [*_launches(), *_troubles(), *_guides()]
    return [item.problem for item in ranked(shelves, wanted=_asked(query))]


def test_every_refused_creation_has_a_ready_answer_with_steps() -> None:
    from typing import get_args

    known = {guide.code for guide in guides()}
    assert known == set(get_args(LaunchErrorCode)) - {"other"}
    for guide in guides():
        assert guide.title and guide.cause and guide.steps, guide.code
        # Written without the sheet's own figures: nothing left unfilled.
        assert "  " not in " ".join(guide.steps), guide.code


def test_a_code_finds_its_own_answer_and_nothing_else() -> None:
    assert _found("page_terms") == ["Sahifa Meta'ning lid shartlarini qabul qilmagan"]
    # An alias the worker writes is the same answer.
    assert _found("token_expired") == ["Facebook bilan ulanish uzilgan"]
    # Meta's own number.
    assert _found("1885316") == ["Reklama akkaunti faol emas"]


def test_the_words_people_use_find_the_answer() -> None:
    assert _found("lid shartlari qabul qilinmagan")[0].startswith(
        "Sahifa Meta'ning lid"
    )
    assert _found("byudjet kam ekan") == ["Kunlik byudjet Meta minimumidan kam"]
    assert "Facebook bilan ulanish uzilgan" in _found("Meta ulanishi uzilgan")
    refused = _found("reklama rad etildi")
    assert refused and all(problem.startswith("Sabab") for problem in refused[:4])
    # In Russian too: the answers are Uzbek, the words for them are not only.
    assert _found("реклама отклонена")


def test_a_word_every_answer_has_finds_nothing() -> None:
    assert _found("reklama") == []
    assert _found("reklama qanday beriladi") == []
    assert _found("salom") == []


def test_an_unknown_code_keeps_what_meta_wrote() -> None:
    guide = guide_for("never_seen", detail="Something Meta said")
    assert guide.code == "other" and guide.cause == "Something Meta said"
    assert guide.steps


def test_a_ready_fix_has_no_below_to_point_at() -> None:
    block = ready_fix(
        code="x", cause="Sabab", steps=("Pastda Meta yozgan qoidani o'qing.",)
    )
    assert block == [
        "## Ready fix: x",
        "Cause: Sabab",
        "1. Meta yozgan qoidani o'qing.",
    ]


def test_a_request_says_its_purpose_and_not_the_conversation() -> None:
    from app.modules.assistant.services.buttons import ticket_text

    text = ticket_text(
        question="Menga operator yordami kerak.",
        summary="«Bahor» kampaniyasi ko'rsatilayotganini tekshirib bering.",
        checked=["Tarif «Pro»: faol"],
    )
    assert text.splitlines() == [
        "🤖 AI chatdan zayavka",
        "",
        "Maqsad: «Bahor» kampaniyasi ko'rsatilayotganini tekshirib bering.",
        "",
        "Tekshirilgan:",
        "• Tarif «Pro»: faol",
    ]
    # No purpose written: the client's own words are it.
    bare = ticket_text(question="Operator kerak", summary="", checked=[])
    assert bare.endswith("Maqsad: Operator kerak")
