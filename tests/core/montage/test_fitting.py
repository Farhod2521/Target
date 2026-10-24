"""Room made for a graphic whose band is taken, the opening headline's
length, and every graphic left out said with why."""

from typing import Any

import pytest
from videokit import Brand, Cut

from core.montage import SpokenWord
from core.montage.fitting import MAX_SHIFT_SECONDS, Want, fit
from core.montage.opening import HOOK_MAX_SECONDS
from core.montage.placement import END_SECONDS, place
from core.montage.plan import plan_schema
from core.montage.settle import LENGTH_SLACK, settle_v3

BRAND = Brand(name="Bahor", cta_text="Telegram", cta_handle="@bahor")


def _words(count: int, *, every: float = 0.5) -> tuple[SpokenWord, ...]:
    return tuple(
        SpokenWord(text=f"w{i}", start=i * every, end=i * every + 0.4)
        for i in range(count)
    )


def _events(words: int, *events: dict[str, Any]) -> Any:
    return (
        plan_schema(word_count=words)
        .model_validate(
            {
                "segments": [{"start": 0, "end": 20}],
                "events": list(events),
                "summary": ".",
            }
        )
        .events
    )


def _want(name: str, zone: Any, start: float, length: float) -> Want:
    return Want(name, zone, start, length, {}, anchor_word=1)


# --- Moving, shortening, leaving out --------------------------------------------


def test_a_graphic_moves_earlier_when_later_is_too_far() -> None:
    kept = [_want("stamp_badge", "TOP_TITLE", 6.0, 4.0)]
    title = _want("headline_slam", "TOP_TITLE", 5.0, 2.0)

    fitted = fit(title, kept, limit=20)

    # After the stamp would be 5 s late; ending as it starts is 1 s early.
    assert fitted.want is not None
    assert (fitted.want.start, fitted.want.length) == (4.0, 2.0)


def test_a_panel_is_shortened_to_the_free_part_of_its_own_stretch() -> None:
    kept = [_want("stamp_badge", "TOP_TITLE", 4.0, 4.5)]
    panel = _want("checklist", "TOP_PANEL", 5.0, 7.0)

    fitted = fit(panel, kept, limit=20)

    # Moved, it would wait 3.5 s; it starts as the stamp leaves, shorter.
    assert fitted.want is not None
    assert (fitted.want.start, fitted.want.length) == (8.5, 3.5)


def test_a_panel_already_up_is_shortened_for_a_headline_on_its_words() -> None:
    panel = _want("checklist", "TOP_PANEL", 2.0, 7.0)
    slam = _want("headline_slam", "TOP_TITLE", 7.0, 3.0)

    fitted = fit(slam, [panel], limit=20)

    assert fitted.want is not None and fitted.want.start == 7.0
    assert [(k.name, k.start, k.length) for k in fitted.kept] == [
        ("checklist", 2.0, 5.0)
    ]


def test_with_no_room_anywhere_it_is_left_out_as_a_collision() -> None:
    kept = [
        _want("stamp_badge", "TOP_TITLE", 2.0, 4.5),
        _want("price_tag", "TOP_TITLE", 6.5, 5.0),
    ]

    fitted = fit(_want("headline_slam", "TOP_TITLE", 5.0, 4.0), kept, limit=20)

    assert (fitted.want, fitted.reason) == (None, "collision")
    assert fitted.kept == kept


def test_a_move_never_goes_further_than_allowed() -> None:
    kept = [_want("stamp_badge", "TOP_TITLE", 0.0, 4.5)]

    fitted = fit(_want("headline_slam", "TOP_TITLE", 1.0, 4.5), kept, limit=20)

    assert fitted.want is None or fitted.want.start - 1.0 <= MAX_SHIFT_SECONDS


def test_a_graphic_on_the_last_words_starts_earlier_to_be_seen_whole() -> None:
    fitted = fit(_want("headline_slam", "TOP_TITLE", 19.0, 2.0), [], limit=20)

    # Two seconds at the least, and the close comes at 20: it starts at 18.
    assert fitted.want is not None
    assert (fitted.want.start, fitted.want.length) == (18.0, 2.0)


def test_with_no_time_left_before_the_close_it_says_so() -> None:
    fitted = fit(_want("stamp_badge", "TOP_TITLE", 19.9, 2.0), [], limit=20)

    # It would have to start 2 s early: further than a graphic is moved.
    assert (fitted.want, fitted.reason) == (None, "end_card")


# --- Why each was left out --------------------------------------------------------


def test_every_graphic_left_out_is_said_with_why() -> None:
    chips = {"component": "chips_list", "props": {"items": ["Tez", "Arzon"]}}
    events = _events(
        40,
        {**chips, "anchor_word": 6, "until_word": 10},
        {**chips, "anchor_word": 16, "until_word": 20},
        {"component": "cta_button", "anchor_word": 30, "until_word": 31, "props": {}},
        *(
            {"component": "sticker_fly", "anchor_word": w, "until_word": w,
             "props": {"icon": "rocket"}}
            for w in (24, 26, 28)
        ),
    )  # fmt: skip

    placed = place(
        events=events, words=_words(40), cuts=(Cut(start=0, end=20),), brand=BRAND
    )

    found = {(d.component, d.anchor_word, d.reason) for d in placed.dropped}
    assert found == {
        ("chips_list", 16, "same_twice"),
        ("cta_button", 30, "late_cta"),
        ("sticker_fly", 28, "max_uses"),
    }
    assert [d.as_row()["reason"] for d in placed.dropped] == [
        "same_twice",
        "max_uses",
        "late_cta",
    ]


def test_a_graphic_on_words_none_of_which_were_kept_is_left_out() -> None:
    events = _events(
        40, {"component": "stamp_badge", "anchor_word": 4, "until_word": 6,
             "props": {"stamp": "Kafolat"}},
    )  # fmt: skip

    placed = place(
        events=events, words=_words(40), cuts=(Cut(start=30, end=40),), brand=BRAND
    )

    assert [(d.component, d.reason) for d in placed.dropped] == [
        ("stamp_badge", "word_cut")
    ]


# --- The opening headline -------------------------------------------------------


@pytest.mark.parametrize(("until", "length"), [(8, 4.4), (14, HOOK_MAX_SECONDS)])
def test_the_opening_headline_stays_until_its_sentence_ends(
    until: int, length: float
) -> None:
    events = _events(
        40, {"component": "hook_title", "anchor_word": 0, "until_word": until,
             "props": {"text": "Narxlar tushdi"}},
    )  # fmt: skip

    placed = place(
        events=events, words=_words(40), cuts=(Cut(start=0, end=20),), brand=BRAND
    )

    hook = placed.components[0]
    # Past the 3 s its manifest gives a headline anywhere else.
    assert (hook.name, hook.start, hook.length) == ("hook_title", 0.0, length)


def test_a_headline_in_the_middle_keeps_its_own_limit() -> None:
    events = _events(
        40,
        {"component": "hook_counter", "anchor_word": 0, "until_word": 2,
         "props": {"value": "50%"}},
        {"component": "hook_title", "anchor_word": 20, "until_word": 30,
         "props": {"text": "Narxlar tushdi"}},
    )  # fmt: skip

    placed = place(
        events=events, words=_words(40), cuts=(Cut(start=0, end=20),), brand=BRAND
    )

    middle = next(c for c in placed.components if c.name == "hook_title")
    assert (middle.start, middle.length) == (10.0, 3.0)


# --- The words and the close inside the length asked for -------------------------


def test_the_words_leave_room_for_the_close_inside_the_length_asked_for() -> None:
    words = _words(80)
    plan = plan_schema(word_count=80).model_validate(
        {"segments": [{"start": 0, "end": 40}], "summary": "."}
    )

    settled = settle_v3(
        plan=plan, source_seconds=40, target_seconds=15, words=words, brand=BRAND
    )

    speech = settled.length - settled.tail
    assert settled.tail == END_SECONDS
    assert speech <= 15 * LENGTH_SLACK - END_SECONDS + 1e-6
    assert settled.length <= 15 * LENGTH_SLACK + 1e-6
