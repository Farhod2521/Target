"""Subtitles word by word, and which words are left out of them."""

import pytest
from videokit import Cut

from core.montage import SpokenWord, lines_for
from core.montage.fillers import for_prompt, is_filler, normal

OKINA = chr(0x02BB)


def _words(*items: tuple[str, float, float]) -> tuple[SpokenWord, ...]:
    return tuple(SpokenWord(text=t, start=s, end=e) for t, s, e in items)


def test_each_word_keeps_its_own_time_on_the_finished_clock() -> None:
    words = _words(("Salom", 1.0, 1.4), ("do'stlar", 1.5, 2.0), ("Narxi", 8.0, 8.3))

    cuts = (Cut(start=7.5, end=9), Cut(start=0.8, end=2.2))

    lines = lines_for(words=words, cuts=cuts)

    # The later stretch plays first; its word starts 0.5 s in.
    assert [(w.text, w.start, w.end) for w in lines[0].words] == [("Narxi", 0.5, 0.8)]
    # The second stretch starts at 1.5 s of the finished video.
    assert [(w.text, w.start, w.end) for w in lines[1].words] == [
        ("Salom", 1.7, 2.1),
        ("do'stlar", 2.2, 2.7),
    ]
    assert (lines[1].start, lines[1].text) == (1.7, "Salom do'stlar")


def test_fillers_are_heard_but_not_read() -> None:
    words = _words(
        ("Ee,", 0.0, 0.3),
        (f"xo{OKINA}sh,", 0.4, 0.7),
        ("haligi", 0.8, 1.0),
        ("bugun", 1.1, 1.4),
        ("chegirma", 1.5, 2.0),
    )

    lines = lines_for(words=words, cuts=(Cut(start=0, end=3),))

    assert [line.text for line in lines] == ["bugun chegirma"]


@pytest.mark.parametrize(
    ("pause", "following", "dropped"),
    [
        (0.1, "bu", False),  # "endi bu startapni" needs its "endi"
        (0.6, "bilasizmi", True),  # a pause after it: thinking aloud
        (0.1, "endi", True),  # said twice
    ],
)
def test_a_soft_filler_goes_only_when_it_hangs(
    pause: float, following: str, dropped: bool
) -> None:
    assert is_filler("Endi", pause_after=pause, next_text=following) is dropped


def test_the_prompt_and_the_subtitles_share_one_list() -> None:
    shown = for_prompt()

    for word in ("ee", "mmm", "xo'sh", "anaqa", "haligi", "vot", "nu"):
        assert f'"{word}"' in shown
        assert normal(word) == word
        assert is_filler(word, pause_after=0)
