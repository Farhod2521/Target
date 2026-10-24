"""Components placed by words: kept, moved, held to their limits, never clashing."""

from typing import Any

import pytest
from pydantic import ValidationError
from videokit import Brand, Cut

from core.montage import SpokenWord
from core.montage.placement import nearest_kept, place, word_times
from core.montage.plan import plan_schema
from core.montage.settle import settle_v3

BRAND = Brand(name="Bahor", cta_text="Telegram", cta_handle="@bahor")


def _words(count: int, *, every: float = 0.5) -> tuple[SpokenWord, ...]:
    """``w0. w1 w2 ...`` - one word every ``every`` seconds, 0.4 s long."""
    return tuple(
        SpokenWord(
            text=f"w{i}." if i == 0 else f"w{i}", start=i * every, end=i * every + 0.4
        )
        for i in range(count)
    )


def _plan(words: int, *events: dict[str, Any], segments: list[dict[str, Any]]) -> Any:
    return plan_schema(word_count=words).model_validate(
        {"segments": segments, "events": list(events), "summary": "."}
    )


def _names(placed: Any) -> list[tuple[str, float, float]]:
    """What was placed, the progress line along the edge left out."""
    return [
        (c.name, c.start, c.length)
        for c in placed.components
        if c.name != "progress_bar"
    ]


def test_a_word_lands_where_it_plays_after_the_stretches_are_reordered() -> None:
    words = _words(40)
    cuts = (Cut(start=10, end=15), Cut(start=0, end=5))

    times = word_times(words, cuts)

    # Word 20 was said at 10 s; its stretch plays first.
    assert times[20] == (0.0, 0.4)
    # Word 0 was said at 0 s; its stretch plays second, from 5 s.
    assert times[0] == (5.0, 5.4)
    assert 12 not in times


def test_a_word_that_was_cut_gives_way_to_the_nearest_kept_one() -> None:
    times = {3: (0.0, 0.4), 7: (1.0, 1.4)}

    assert nearest_kept(5, times, 10) == 7  # a tie goes to the later word
    assert nearest_kept(4, times, 10) == 3
    assert nearest_kept(9, {}, 10) is None


def test_lengths_are_held_to_the_manifest() -> None:
    words = _words(40)
    plan = _plan(
        40,
        {"component": "cta_button", "anchor_word": 2, "until_word": 2, "props": {}},
        {"component": "chips_list", "anchor_word": 6, "until_word": 39,
         "props": {"items": ["Tez", "Arzon"]}},
        segments=[{"start": 0, "end": 20}],
    )  # fmt: skip

    placed = place(
        events=plan.events, words=words, cuts=(Cut(start=0, end=20),), brand=BRAND
    )

    found = {name: (start, length) for name, start, length in _names(placed)}
    assert found["cta_button"] == (1.0, 1.5)  # one word, stretched to the least
    assert found["chips_list"] == (3.0, 7.0)  # many words, cut to the most


def test_the_close_comes_after_the_last_word_and_a_graphic_may_stay_until_it() -> None:
    words = _words(40)
    plan = _plan(
        40,
        {"component": "stamp_badge", "anchor_word": 30, "until_word": 39,
         "props": {"stamp": "Kafolat"}},
        segments=[{"start": 0, "end": 20}],
    )  # fmt: skip

    placed = place(
        events=plan.events, words=words, cuts=(Cut(start=0, end=20),), brand=BRAND
    )

    # The words run 20 s; the card and its button play after them.
    assert ("end_card", 20.0, 3.0) in _names(placed)
    assert ("end_cta", 20.3, 2.7) in _names(placed)
    assert placed.tail == 3.0
    # The stamp is on its words to the end: nothing covers them any more.
    assert ("stamp_badge", 15.0, 4.5) in _names(placed)
    assert placed.dropped == ()


def test_no_call_to_action_means_no_button() -> None:
    placed = place(
        events=[],
        words=_words(40),
        cuts=(Cut(start=0, end=20),),
        brand=Brand(name="Bahor"),
    )

    assert "cta_button" not in [c.name for c in placed.components]
    assert "end_card" in [c.name for c in placed.components]


def test_without_a_planned_headline_the_first_sentence_becomes_one() -> None:
    words = (
        SpokenWord(text="Narxlar", start=0.2, end=0.6),
        SpokenWord(text="tushdi!", start=0.7, end=1.1),
        SpokenWord(text="Bugun", start=1.5, end=1.9),
    )

    placed = place(events=[], words=words, cuts=(Cut(start=0, end=2),), brand=BRAND)

    hook = placed.components[0]
    assert (hook.name, hook.props, hook.start, hook.length) == (
        "hook_title",
        {"text": "Narxlar tushdi!"},
        0.0,
        1.7,
    )


def test_two_components_in_one_band_take_turns_or_one_is_left_out() -> None:
    words = _words(40)
    plan = _plan(
        40,
        {
            "component": "stamp_badge",
            "anchor_word": 4,
            "until_word": 9,
            "props": {"stamp": "Kafolat"},
        },
        {
            "component": "chips_list",
            "anchor_word": 6,
            "until_word": 7,
            "props": {"items": ["Tez", "Arzon"]},
        },
        {
            "component": "checklist",
            "anchor_word": 8,
            "until_word": 9,
            "props": {"title": "Nega", "items": ["Tez", "Arzon"]},
        },
        segments=[{"start": 0, "end": 20}],
    )

    placed = place(
        events=plan.events, words=words, cuts=(Cut(start=0, end=20),), brand=BRAND
    )

    early = [
        item
        for item in _names(placed)
        if item[1] < 10 and item[0] not in ("hook_title", "lower_third")
    ]
    # The stamp holds the top 2.0-4.9. The chips would have to wait 1.9 s
    # for it - longer than a component is moved - and are left out; the
    # checklist waits 0.9 s and follows it.
    assert early == [("stamp_badge", 2.0, 2.9), ("checklist", 4.9, 3.0)]


def test_a_graphic_never_follows_one_of_its_own_kind() -> None:
    words = _words(40)
    chips = {"component": "chips_list", "props": {"items": ["Tez", "Arzon"]}}
    plan = _plan(
        40,
        {**chips, "anchor_word": 6, "until_word": 10},
        {**chips, "anchor_word": 16, "until_word": 20},
        {"component": "checklist", "anchor_word": 22, "until_word": 23,
         "props": {"title": "Nega", "items": ["Tez", "Arzon"]}},
        {**chips, "anchor_word": 28, "until_word": 29},
        segments=[{"start": 0, "end": 20}],
    )  # fmt: skip

    placed = place(
        events=plan.events, words=words, cuts=(Cut(start=0, end=20),), brand=BRAND
    )

    panels = [n for n, _, _ in _names(placed) if n in ("chips_list", "checklist")]
    assert panels == ["chips_list", "checklist", "chips_list"]


def test_a_panel_moves_the_footage_aside_for_exactly_its_time() -> None:
    words = _words(40)
    plan = _plan(
        40,
        {"component": "chips_list", "anchor_word": 10, "until_word": 15,
         "props": {"items": ["Tez", "Arzon"]}},
        segments=[{"start": 0, "end": 20, "layout": "split_top"}],
    )  # fmt: skip

    settled = settle_v3(
        plan=plan, source_seconds=20, target_seconds=30, words=words, brand=BRAND
    )

    chips = next(c for c in settled.components if c.name == "chips_list")
    assert [(s.start, s.end, s.layout) for s in settled.layouts] == [
        (chips.start, chips.start + chips.length, "split_top")
    ]
    assert [cut.enter for cut in settled.cuts] == ["none"]


def test_a_transition_keeps_a_stretch_that_carries_on_as_its_own_cut() -> None:
    plan = plan_schema(word_count=0).model_validate(
        {
            "segments": [
                {"start": 0.0, "end": 4.0},
                {"start": 4.0, "end": 8.0, "transition_in": "flash"},
            ],
            "summary": "-",
        }
    )

    settled = settle_v3(
        plan=plan, source_seconds=20, target_seconds=30, words=(), brand=Brand()
    )

    assert [(c.start, c.end, c.enter) for c in settled.cuts] == [
        (0.0, 4.0, "none"),
        (4.0, 8.0, "flash"),
    ]


def test_with_no_name_or_logo_nothing_is_drawn_empty() -> None:
    schema = plan_schema(word_count=40)
    plan = schema.model_validate(
        {
            "segments": [{"start": 0, "end": 20}],
            "events": [],
            "summary": "-",
        }
    )  # fmt: skip

    placed = place(
        events=plan.events,
        words=_words(40),
        cuts=(Cut(start=0, end=20),),
        brand=Brand(cta_text="Telegram", cta_handle="@b"),
    )

    names = [c.name for c in placed.components]
    assert "lower_third" not in names and "end_card" not in names
    # The closing button has its own words, so it still comes.
    assert "cta_button" in names


# --- The name bar, always ------------------------------------------------------


def _bare(brand: Brand, *, seconds: float = 20.0) -> list[tuple[str, float, float]]:
    words = tuple(
        SpokenWord(text=f"so'z{i}", start=i * 0.5, end=i * 0.5 + 0.4)
        for i in range(int(seconds * 2))
    )
    placed = place(
        events=[], words=words, cuts=[Cut(start=0.0, end=seconds)], brand=brand
    )
    return [(c.name, c.start, c.length) for c in placed.components]


def test_a_plan_without_a_name_bar_gets_one_early() -> None:
    names = _bare(Brand(name="Bahor", tagline="Gullar"))

    assert ("lower_third", 3.0, 4.0) in names


def test_the_name_bar_waits_for_its_band_to_be_free() -> None:
    """A button the planner put at 3-4.5 s holds the band; the bar comes
    after it, still inside the window."""
    words = tuple(
        SpokenWord(text=f"so'z{i}", start=i * 0.5, end=i * 0.5 + 0.4) for i in range(40)
    )
    plan = plan_schema(word_count=len(words)).model_validate(
        {"segments": [{"start": 0.0, "end": 20.0}],
         "events": [{"component": "cta_button", "anchor_word": 6, "until_word": 8,
                     "props": {}}],
         "summary": "."}
    )  # fmt: skip

    placed = place(
        events=plan.events,
        words=words,
        cuts=[Cut(start=0.0, end=20.0)],
        brand=Brand(name="Bahor", cta_text="Yozing"),
    )

    bar = [c for c in placed.components if c.name == "lower_third"]
    button = next(c for c in placed.components if c.name == "cta_button")
    assert len(bar) == 1
    assert bar[0].start >= button.start + button.length - 1e-6
    assert bar[0].start + bar[0].length <= 7.0 + 1e-6


def test_no_name_bar_where_there_is_no_room_or_nothing_to_show() -> None:
    assert not any(n == "lower_third" for n, _, _ in _bare(Brand(), seconds=20))
    assert not any(
        n == "lower_third" for n, _, _ in _bare(Brand(name="Bahor"), seconds=5)
    )


def test_a_name_the_logo_spells_is_the_logo_and_the_slogan() -> None:
    from videokit.components import component, component_clip

    brand = Brand(
        name="Osh Markazi", tagline="Har kuni issiq osh",
        logo="data:image/png;base64,T1NI", name_in_logo=True,
    )  # fmt: skip

    html = component_clip(
        component("lower_third"), props={}, brand=brand, zone="LOWER_THIRD",
        start=0, length=4, resolution="1080", aspect_ratio="9:16",
    )["asset"]["html"]  # fmt: skip

    assert 'class="solo"' in html and "Har kuni issiq osh" in html
    assert "Osh Markazi" not in html


def test_a_short_video_still_gets_its_whole_close_after_the_words() -> None:
    words = (SpokenWord(text="Salom!", start=0.2, end=0.8),)

    placed = place(events=[], words=words, cuts=(Cut(start=0, end=4),), brand=BRAND)

    names = [(c.name, c.start, c.length) for c in placed.components]
    assert ("end_card", 4.0, 3.0) in names
    assert ("end_cta", 4.3, 2.7) in names
    assert names[0][:2] == ("hook_title", 0.0)


def test_with_neither_card_nor_button_the_video_ends_on_its_last_word() -> None:
    placed = place(
        events=[], words=_words(10), cuts=(Cut(start=0, end=5),), brand=Brand()
    )

    assert placed.tail == 0.0
    assert not {"end_card", "end_cta", "cta_button"} & {
        c.name for c in placed.components
    }


# --- Beats -------------------------------------------------------------------


def test_a_beat_lands_on_its_word_or_the_nearest_one_kept() -> None:
    words = _words(40)
    plan = _plan(
        40,
        {"component": "chips_list", "anchor_word": 12, "until_word": 17,
         "props": {"items": ["Tez", "Arzon", "Yangi"]},
         "beats": {"items": [13, 9, 30]}},
        segments=[{"start": 0.0, "end": 3.9}, {"start": 5.0, "end": 8.9},
                  {"start": 10.0, "end": 13.9}],
    )  # fmt: skip

    settled = settle_v3(
        plan=plan, source_seconds=20.0, target_seconds=30, words=words, brand=BRAND
    )

    chips = next(c for c in settled.components if c.name == "chips_list")
    times = word_times(words, settled.cuts)
    # Word 9 was cut out: word 10, the nearest kept, stands in; word 30 is
    # past every cut, so the last word kept does.
    assert 9 not in times and 30 not in times
    assert chips.beats["items"] == [times[13][0], times[10][0], times[27][0]]


def test_a_plan_may_leave_beats_out_and_may_not_invent_them() -> None:
    schema = plan_schema(word_count=10)
    base = {"segments": [{"start": 0, "end": 4}], "summary": "."}
    bare = {"component": "chips_list", "anchor_word": 1, "until_word": 4,
            "props": {"items": ["Tez", "Arzon"]}}  # fmt: skip

    assert schema.model_validate({**base, "events": [bare]}).events[0].beats is None
    with pytest.raises(ValidationError):
        schema.model_validate(
            {**base, "events": [{**bare, "beats": {"items": [1, 12]}}]}
        )
    with pytest.raises(ValidationError):
        schema.model_validate(
            {**base, "events": [{"component": "cta_button", "anchor_word": 1,
                                 "until_word": 2, "props": {}, "beats": {}}]}
        )  # fmt: skip


def test_a_progress_line_runs_along_the_edge_until_the_end_card() -> None:
    words = _words(40)
    plan = _plan(40, segments=[{"start": 0.0, "end": 19.9}])

    settled = settle_v3(
        plan=plan, source_seconds=20.0, target_seconds=30, words=words, brand=BRAND
    )

    bar = next(c for c in settled.components if c.name == "progress_bar")
    card = next(c for c in settled.components if c.name == "end_card")
    assert (bar.zone, bar.start) == ("EDGE", 0.0)
    assert bar.start + bar.length == pytest.approx(card.start)


def test_a_sticker_makes_way_for_graphics_with_words_and_comes_twice_at_most() -> None:
    words = _words(40)
    plan = _plan(
        40,
        *({"component": "sticker_fly", "anchor_word": w, "until_word": w,
           "props": {"icon": "rocket"}} for w in (4, 12, 20)),
        {"component": "headline_slam", "anchor_word": 12, "until_word": 16,
         "props": {"pill": "Zo'r"}},
        segments=[{"start": 0.0, "end": 19.9}],
    )  # fmt: skip

    settled = settle_v3(
        plan=plan, source_seconds=20.0, target_seconds=30, words=words, brand=BRAND
    )

    stickers = [c for c in settled.components if c.name == "sticker_fly"]
    slam = next(c for c in settled.components if c.name == "headline_slam")
    assert len(stickers) == 2
    assert all(
        s.start + s.length <= slam.start + 1e-6 or s.start >= slam.start + slam.length
        for s in stickers
    )


def test_a_late_beat_is_seen_before_the_graphic_leaves() -> None:
    words = _words(40)
    plan = _plan(
        40,
        {"component": "headline_slam", "anchor_word": 10, "until_word": 11,
         "props": {"pill": "Zo'r"}, "beats": {"slam": 15}},
        segments=[{"start": 0, "end": 19.9}],
    )  # fmt: skip

    placed = place(
        events=plan.events, words=words, cuts=(Cut(start=0, end=20),), brand=BRAND
    )

    slam = next(c for c in placed.components if c.name == "headline_slam")
    assert slam.start + slam.length >= slam.beats["slam"] + 1.2 - 1e-6
