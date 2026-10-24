"""An Uzbek ending heard apart from the brand's word is joined back on."""

from core.montage import SpokenWord
from core.montage.suffixes import joined_endings

TERMS = ("Bahor kafesi", "Meta", "Targetolog AI")


def _words(*items: tuple[str, float, float]) -> tuple[SpokenWord, ...]:
    return tuple(SpokenWord(text=t, start=s, end=e) for t, s, e in items)


def test_an_ending_said_straight_after_a_brand_word_joins_it() -> None:
    words = _words(("biz", 0.0, 0.3), ("Meta", 0.4, 0.7), ("dan", 0.72, 0.9),
                   ("ruxsat", 1.0, 1.4))  # fmt: skip

    joined, diff = joined_endings(words, TERMS)

    assert [w.text for w in joined] == ["biz", "Metadan", "ruxsat"]
    assert (joined[1].start, joined[1].end) == (0.4, 0.9)
    assert diff == [
        {
            "at": 1,
            "kind": "ending",
            "was": [["Meta", 0.4, 0.7], ["dan", 0.72, 0.9]],
            "now": [["Metadan", 0.4, 0.9]],
        }
    ]


def test_the_last_word_of_a_longer_name_takes_its_ending() -> None:
    words = _words(("kafesi", 0.0, 0.4), ("ning", 0.42, 0.6), ("AI", 1.0, 1.2),
                   ("ga.", 1.21, 1.4))  # fmt: skip

    joined, _diff = joined_endings(words, TERMS)

    assert [w.text for w in joined] == ["kafesining", "AIga."]


def test_a_pause_or_an_ordinary_word_keeps_them_apart() -> None:
    words = _words(
        ("Meta", 0.0, 0.3),
        ("dan", 0.6, 0.8),  # a pause
        ("uy", 1.0, 1.2),
        ("da", 1.21, 1.3),  # not the brand's
        ("Meta,", 2.0, 2.3),
        ("ga", 2.31, 2.4),
    )  # a comma between

    joined, diff = joined_endings(words, TERMS)

    assert [w.text for w in joined] == ["Meta", "dan", "uy", "da", "Meta,", "ga"]
    assert diff == []
