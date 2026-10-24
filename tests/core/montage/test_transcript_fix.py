"""The transcript put right where it misheard the brand: times kept,
bad fixes dropped, every change written down."""

from core.montage import SpokenWord
from core.montage.transcript_fix import Fix, apply_fixes, doubts, indexed_words

WORDS = (
    SpokenWord(text="Biz", start=0.5, end=0.7),
    SpokenWord(text="yaqinda", start=0.8, end=1.2),
    SpokenWord(text="targetologiya", start=1.3, end=2.0),
    SpokenWord(text="degan", start=2.1, end=2.4),
    SpokenWord(text="startap.", start=2.5, end=3.0),
)


def test_one_word_heard_for_two_is_split_by_length() -> None:
    fixed, diff = apply_fixes(WORDS, [Fix(first=2, last=2, text="Targetolog AI")])

    assert [w.text for w in fixed] == [
        "Biz", "yaqinda", "Targetolog", "AI", "degan", "startap.",
    ]  # fmt: skip
    # 0.7 s shared 10 letters to 2: the second word starts at 1.3 + 0.583.
    assert (fixed[2].start, fixed[2].end) == (1.3, 1.883)
    assert (fixed[3].start, fixed[3].end) == (1.883, 2.0)
    # Everything else keeps its time to the millisecond.
    assert fixed[:2] == WORDS[:2] and fixed[4:] == WORDS[3:]
    assert diff == [
        {
            "at": 2,
            "kind": "brand",
            "was": [["targetologiya", 1.3, 2.0]],
            "now": [["Targetolog", 1.3, 1.883], ["AI", 1.883, 2.0]],
        }
    ]


def test_two_words_heard_for_one_are_joined_and_the_full_stop_kept() -> None:
    fixed, _diff = apply_fixes(WORDS, [Fix(first=3, last=4, text="Dastur")])

    assert [w.text for w in fixed][-1] == "Dastur."
    assert (fixed[-1].start, fixed[-1].end) == (2.1, 3.0)


def test_a_fix_that_is_out_of_range_crossing_or_empty_is_dropped() -> None:
    fixes = [
        Fix(first=4, last=9, text="x"),  # past the end
        Fix(first=1, last=2, text="yaqinda Targetolog"),
        Fix(first=2, last=3, text="crosses the one before"),
        Fix(first=0, last=0, text="Biz"),  # changes nothing
        Fix(first=3, last=3, text="bir ikki uch tort besh olti"),  # too many
    ]

    fixed, diff = apply_fixes(WORDS, fixes)

    assert [d["at"] for d in diff] == [1]
    assert [w.text for w in fixed][1:3] == ["yaqinda", "Targetolog"]


def test_no_fixes_change_nothing() -> None:
    assert apply_fixes(WORDS, []) == (WORDS, [])


def test_the_prompt_numbers_every_word() -> None:
    assert indexed_words(WORDS).splitlines()[2] == "#2 targetologiya"


def test_an_ordinary_word_misheard_is_respelled() -> None:
    words = (
        SpokenWord(text="Sizning", start=0.0, end=0.4),
        SpokenWord(text="yordamiylasiz", start=0.5, end=1.2),
        SpokenWord(text="qiyin.", start=1.3, end=1.7),
    )

    fixed, diff = apply_fixes(
        words, [Fix(first=1, last=1, text="yordamingizsiz", kind="word")]
    )

    assert [w.text for w in fixed] == ["Sizning", "yordamingizsiz", "qiyin."]
    assert diff[0]["kind"] == "word"


def test_a_fix_that_would_change_the_meaning_is_not_made() -> None:
    words = (
        SpokenWord(text="Bu", start=0.0, end=0.2),
        SpokenWord(text="ishlaydi", start=0.3, end=0.8),
        SpokenWord(text="yaxshi.", start=0.9, end=1.3),
    )
    fixes = [
        # A "not" put in, however alike it is spelled.
        Fix(first=1, last=1, text="ishlamaydi", kind="word"),
        # Another word entirely.
        Fix(first=2, last=2, text="yomon.", kind="word"),
    ]

    fixed, diff = apply_fixes(words, fixes)

    assert fixed == words and diff == []


def test_an_unsure_fix_is_not_made() -> None:
    unsure = Fix(first=2, last=2, text="Targetolog AI", confidence="low")

    fixed, diff = apply_fixes(WORDS, [unsure])

    assert fixed == WORDS and diff == []


def test_a_medium_guess_is_listed_not_made() -> None:
    words = (
        SpokenWord(text="bo'lish", start=0.0, end=0.4),
        SpokenWord(text="ekanlari", start=0.5, end=0.9),
        SpokenWord(text="imkoniyati", start=1.0, end=1.5),
    )
    guess = Fix(
        first=1,
        last=2,
        text="ekanligi imkoniyati",
        kind="word",
        confidence="medium",
        note="no sense in context",
    )
    hunch = Fix(first=0, last=0, text="bo'lishi", kind="word", confidence="low")

    fixed, diff = apply_fixes(words, [guess, hunch])

    assert fixed == words and diff == []
    assert doubts(words, [guess, hunch]) == [
        {
            "at": 1,
            "time": 0.5,
            "heard": "ekanlari imkoniyati",
            "guess": "ekanligi imkoniyati",
            "note": "no sense in context",
        }
    ]


def test_a_sure_fix_the_guard_refused_is_listed_for_a_person() -> None:
    words = (SpokenWord(text="ishlaydi", start=0.0, end=0.5),)
    flip = Fix(first=0, last=0, text="ishlamaydi", kind="word")

    assert doubts(words, [flip])[0]["note"] == "changes the meaning"
