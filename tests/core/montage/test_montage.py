"""The plan held to the file, and subtitles placed on the finished clock."""

import pytest
from videokit import Cut

from core.montage import (
    MontagePlan,
    NothingToKeepError,
    PlanSegment,
    PlanText,
    SpokenWord,
    frame_every,
    lines_for,
    settle,
    srt,
    transcript_lines,
)

WORDS = (
    SpokenWord(text="Assalomu", start=1.0, end=1.6),
    SpokenWord(text="alaykum", start=1.7, end=2.3),
    SpokenWord(text="bugun", start=5.0, end=5.4),
    SpokenWord(text="chegirma", start=5.5, end=6.2),
)


def _plan(
    *segments: tuple[float, float], texts: list[PlanText] | None = None
) -> MontagePlan:
    return MontagePlan(
        segments=[PlanSegment(start=a, end=b) for a, b in segments],
        texts=texts or [],
        summary="-",
    )


def _settle(
    plan: MontagePlan, *, target: float = 30, source: float = 20
) -> list[tuple[float, float]]:
    settled = settle(
        plan=plan, source_seconds=source, target_seconds=target, words=WORDS
    )
    return [(cut.start, cut.end) for cut in settled.cuts]


def test_a_stretch_is_held_inside_the_file() -> None:
    assert _settle(_plan((15, 99))) == [(15, 20)]


def test_a_boundary_inside_a_word_moves_to_the_words_edge_with_room() -> None:
    # Snapped to 1.0-6.2, then a breath either side of the speech.
    assert _settle(_plan((1.3, 5.8))) == [(0.92, 6.38)]


def test_breath_room_stops_short_of_the_next_word() -> None:
    # Ends on "alaykum" at 2.3; "bugun" is far, so the full room is taken.
    # Starts on "bugun" at 5.0, but "alaykum" ended at 2.3 - room is free.
    assert _settle(_plan((1.0, 2.3))) == [(0.92, 2.48)]
    close = (
        SpokenWord(text="bir", start=1.0, end=1.5),
        SpokenWord(text="ikki", start=1.55, end=2.0),
    )
    settled = settle(
        plan=_plan((1.0, 1.5)), source_seconds=20, target_seconds=30, words=close
    )
    assert settled.cuts[0].end == 1.55


def test_a_stretch_that_carries_straight_on_is_one_cut() -> None:
    assert _settle(_plan((10, 12), (12.1, 14))) == [(10, 14)]


def test_a_jump_between_takes_of_one_shot_is_pushed_in() -> None:
    settled = settle(
        plan=_plan((10, 12), (13, 15), (3, 4.5)),
        source_seconds=20,
        target_seconds=30,
        words=WORDS,
    )

    # 10-12 then 13-15 jumps; going back to 3 is a different moment.
    assert [cut.zoom for cut in settled.cuts] == [1.0, 1.15, 1.0]


def test_close_framing_is_a_push_in() -> None:
    plan = MontagePlan(
        segments=[PlanSegment(start=10, end=12, framing="close")], summary="-"
    )

    settled = settle(plan=plan, source_seconds=20, target_seconds=30, words=())

    assert settled.cuts[0].zoom == 1.15


def test_two_stretches_that_meet_mid_word_are_one_cut() -> None:
    # 1.0-3.2 and 3.2-5.6 meet inside "ikki" - each snaps to its edges,
    # so they overlap by that word, which is not a repeat.
    words = (
        SpokenWord(text="bir", start=1.0, end=1.4),
        SpokenWord(text="ikki", start=3.0, end=3.5),
        SpokenWord(text="uch", start=5.0, end=5.6),
    )
    settled = settle(
        plan=_plan((1.0, 3.2), (3.2, 5.6)),
        source_seconds=20,
        target_seconds=30,
        words=words,
    )

    assert [(c.start, c.end) for c in settled.cuts] == [(0.92, 5.78)]


def test_a_dropped_flicker_joins_nothing_across_it() -> None:
    assert _settle(_plan((1.0, 2.3), (8, 8.3), (8.3, 9.5))) == [
        (0.92, 2.48),
        (8.3, 9.5),
    ]


def test_a_flicker_and_a_repeat_are_dropped() -> None:
    assert _settle(_plan((8, 8.3), (10, 14), (12, 16))) == [(10, 14)]


def test_order_is_the_plans_not_the_files() -> None:
    assert _settle(_plan((10, 12), (3, 4.5))) == [(10, 12), (3, 4.5)]


def test_the_video_is_held_near_the_asked_length() -> None:
    cuts = _settle(_plan((7, 12), (12.5, 19)), target=8)

    assert cuts == [(7, 12), (12.5, 16.7)]


def test_nothing_surviving_stops_the_montage() -> None:
    with pytest.raises(NothingToKeepError):
        _settle(_plan((19.9, 30)))


def test_text_past_the_end_is_dropped_and_long_text_is_shortened() -> None:
    plan = _plan(
        (10, 14),
        texts=[
            PlanText(text="Chegirma", at=1, seconds=8),
            PlanText(text="Kech", at=6, seconds=2),
        ],
    )

    settled = settle(plan=plan, source_seconds=20, target_seconds=30, words=WORDS)

    assert [(o.text, o.start, o.length) for o in settled.overlays] == [
        ("Chegirma", 1, 3)
    ]


def test_words_play_where_their_stretch_plays() -> None:
    cuts = (Cut(start=5, end=6.5), Cut(start=0.8, end=2.5))

    lines = lines_for(words=WORDS, cuts=cuts)

    assert [(line.text, line.start) for line in lines] == [
        ("bugun chegirma", 0.0),
        ("Assalomu alaykum", 1.7),
    ]


def test_hesitations_are_left_out_of_the_subtitles() -> None:
    words = (
        SpokenWord(text="Ee,", start=0.1, end=0.4),
        SpokenWord(text="narxi", start=0.5, end=0.9),
        SpokenWord(text="mmm", start=1.0, end=1.2),
        SpokenWord(text="arzon", start=1.3, end=1.7),
    )

    lines = lines_for(words=words, cuts=(Cut(start=0, end=2),))

    assert [line.text for line in lines] == ["narxi arzon"]


def test_a_word_from_a_dropped_stretch_is_not_shown() -> None:
    lines = lines_for(words=WORDS, cuts=(Cut(start=0, end=3),))

    assert "chegirma" not in " ".join(line.text for line in lines)


def test_srt_is_numbered_and_stamped() -> None:
    lines = lines_for(words=WORDS[:2], cuts=(Cut(start=0, end=3),))

    assert srt(lines) == "1\n00:00:01,000 --> 00:00:02,300\nAssalomu alaykum\n"


def test_the_transcript_is_shown_phrase_by_phrase_with_times() -> None:
    assert transcript_lines(WORDS) == (
        "[1.00-2.30] Assalomu alaykum\n[5.00-6.20] bugun chegirma"
    )
    assert "nothing is said" in transcript_lines(())


def test_long_files_get_their_stills_further_apart() -> None:
    assert frame_every(30) == 2.0
    assert frame_every(600) == 15.0


def test_a_stretch_framed_differently_stays_its_own_cut() -> None:
    plan = MontagePlan(
        segments=[
            PlanSegment(start=10, end=12),
            PlanSegment(start=12.1, end=14, framing="close"),
        ],
        summary="-",
    )

    settled = settle(plan=plan, source_seconds=20, target_seconds=30, words=())

    assert [(c.start, c.end, c.zoom) for c in settled.cuts] == [
        (10, 12, 1.0),
        (12, 14, 1.15),
    ]
