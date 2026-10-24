"""The closing card's own seconds after the last cut: silent footage under
it, counted in the video's length, and never left out for size."""

from videokit import Brand, ComponentUse, Cut, EditSpec, build_edit
from videokit.graphics import within_limit
from videokit.preflight import preflight

SOURCE = "https://example.test/source.mp4"
BRAND = Brand(name="Bahor", cta_text="Telegram", cta_handle="@bahor")
CLOSE = (
    ComponentUse(name="end_card", zone="FULL", start=10.0, length=3.0),
    ComponentUse(name="end_cta", zone="FULL", start=10.3, length=2.7),
)


def _spec(**more: object) -> EditSpec:
    given: dict[str, object] = {"components": CLOSE, **more}
    return EditSpec(
        source_url=SOURCE,
        cuts=(Cut(start=2, end=7), Cut(start=20, end=25, zoom=1.15)),
        brand=BRAND,
        tail=3.0,
        tail_from=25.0,
        **given,  # type: ignore[arg-type]
    )


def _footage(edit: dict[str, object]) -> list[dict[str, object]]:
    tracks = edit["timeline"]["tracks"]  # type: ignore[index]
    return next(
        t["clips"]
        for t in tracks
        if t["clips"][0]["asset"].get("src") == SOURCE  # type: ignore[index]
    )


def test_the_footage_carries_on_silently_under_the_close() -> None:
    clips = _footage(build_edit(_spec(motion="moving")))

    tail = clips[-1]
    assert tail["asset"] == {  # type: ignore[comparison-overlap]
        "type": "video",
        "src": SOURCE,
        "trim": 25.0,
        "volume": 0,
    }
    assert (tail["start"], tail["length"], tail["scale"]) == (10.0, 3.0, 1.15)
    # The video fades down at the very end, not where the words stop.
    assert tail["transition"] == {"out": "fade"}
    assert "out" not in clips[-2].get("transition", {})  # type: ignore[union-attr]


def test_the_close_is_part_of_the_length_and_of_the_check_for_a_button() -> None:
    spec = _spec()

    assert spec.length == 13.0
    assert not [p for p in preflight(spec, build_edit(spec)) if p.kind == "no_cta"]


def test_the_close_is_never_left_out_for_size() -> None:
    early = ComponentUse(name="stamp_badge", zone="TOP_TITLE", start=2.0, length=2.0,
                         props={"stamp": "Kafolat"})  # fmt: skip
    spec = _spec(components=(early, *CLOSE))

    smaller, dropped = within_limit(spec, limit=0, size=lambda s: len(s.components))

    assert dropped == (early,)
    assert smaller.components == CLOSE


def test_without_a_tail_the_video_ends_on_its_last_cut() -> None:
    spec = EditSpec(source_url=SOURCE, cuts=(Cut(start=0, end=5),))

    clips = _footage(build_edit(spec))

    assert spec.length == 5.0 and len(clips) == 1
