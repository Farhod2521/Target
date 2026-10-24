"""videokit: texts measured in the brand's font, and the checks before a render."""

import pytest
from videokit import (
    Brand,
    CaptionLine,
    CaptionWord,
    ComponentUse,
    Cut,
    EditSpec,
    build_edit,
)
from videokit.components import component, component_clip
from videokit.components.lettering import lettering
from videokit.components.render import brand_values
from videokit.fit import TextBox, fitted_px, lines_needed, packed, text_width
from videokit.layout import CORNER_LOGO_BOX, ZONES, safe_area
from videokit.preflight import FLOORS, preflight

SOURCE = "https://example.test/source.mp4"
BRAND = Brand(
    name="Chilonzor Fitnes",
    tagline="Kuch va sog'liq",
    cta_text="Yozing",
    cta_handle="@chilonzor_fitnes",
    cta_phone="+998 90 111 22 33",
)
END = 20.0


def _spec(*uses: ComponentUse, brand: Brand = BRAND, **extra: object) -> EditSpec:
    return EditSpec(
        source_url=SOURCE,
        cuts=(Cut(start=0, end=END),),
        resolution="1080",
        components=uses,
        brand=brand,
        **extra,  # type: ignore[arg-type]
    )


def _use(name: str, start: float, length: float, **props: object) -> ComponentUse:
    return ComponentUse(
        name=name,
        zone=component(name).zones[0],
        start=start,
        length=length,
        props=props,
    )


HOOK = _use("hook_title", 0.0, 2.0, text="Million dollarlik startap")
CLOSE = _use("cta_button", END - 2.7, 2.7)


def _kinds(spec: EditSpec) -> list[str]:
    return [p.kind for p in preflight(spec, build_edit(spec))]


# --- Measuring ---------------------------------------------------------------


def test_a_text_is_as_wide_as_the_font_draws_it() -> None:
    short = text_width("Salom", preset="modern", px=96)
    long = text_width("Salom dunyo", preset="modern", px=96)

    assert 0 < short < long
    # Half the size, half the width.
    assert text_width("Salom", preset="modern", px=48) == pytest.approx(short / 2, 0.05)


def test_a_long_headline_shrinks_before_it_wraps_past_its_lines() -> None:
    box = TextBox(selector=".t", px=96, min_px=64, width=876, lines=2)

    short = fitted_px("Narx 20%", box, preset="bold")
    long = fitted_px("Million dollarlik startapga qoshiling", box, preset="bold")

    assert short == 96
    assert long is not None and 64 <= long < 96


def test_a_word_wider_than_the_box_fits_nowhere() -> None:
    box = TextBox(selector=".t", px=96, min_px=64, width=300, lines=3)

    assert lines_needed("Yordamingizsizlarimizdan", box, preset="bold", px=64) is None
    assert fitted_px("Yordamingizsizlarimizdan", box, preset="bold") is None


def test_contacts_share_a_line_while_they_fit_and_split_when_not() -> None:
    box = TextBox(selector=".l2", px=40, min_px=32, width=680, lines=2)

    together = packed(
        ["@bahor", "+998 90 111 22 33"], box, preset="modern", joiner=" · "
    )
    apart = packed(
        ["@chilonzor_fitnes_markazi", "@chilonzor_fitnes_ig", "+998 90 111 22 33"],
        box,
        preset="modern",
        joiner=" · ",
    )

    assert together == (40, ("@bahor · +998 90 111 22 33",))
    assert apart is not None and len(apart[1]) == 2
    assert apart[1][-1].endswith("+998 90 111 22 33")


def test_the_button_writes_each_contact_line_at_its_measured_size() -> None:
    clip = component_clip(
        component("cta_button"),
        props={},
        brand=BRAND,
        zone="LOWER_THIRD",
        start=0,
        length=2,
        resolution="1080",
        aspect_ratio="9:16",
    )

    html, css = clip["asset"]["html"], clip["asset"]["css"]
    assert html.count('class="l2"') >= 1
    assert "+998 90 111 22 33" in html
    assert ".l2{font-size:" in css


def test_every_text_box_keeps_the_smallest_sizes_allowed() -> None:
    for key, floor in FLOORS.items():
        if key == "captions":
            continue
        name, value = key.split(".")
        box = dict(component(name).texts)[value]
        assert box.min_px >= floor, key


# --- The checks --------------------------------------------------------------


def test_a_clean_edit_has_no_problems() -> None:
    assert _kinds(_spec(HOOK, CLOSE)) == []


def test_a_headline_that_comes_late_is_a_problem() -> None:
    late = _use("hook_title", 1.0, 2.0, text="Million dollarlik")

    assert "late_hook" in _kinds(_spec(late, CLOSE))


def test_a_fade_up_from_black_is_a_problem() -> None:
    spec = _spec(HOOK, CLOSE)
    edit = build_edit(spec)
    footage = edit["timeline"]["tracks"][-1]["clips"]
    footage[0]["transition"] = {"in": "fade"}

    assert [p.kind for p in preflight(spec, edit)] == ["black_start"]


def test_a_text_too_long_for_its_box_is_a_problem() -> None:
    fits = _use("hook_title", 0.0, 2.0, text="Narxlar tushdi")
    word = _use("hook_title", 0.0, 2.0, text="Ш" * 40)

    assert (
        lettering(
            component("hook_title"), {**brand_values(BRAND), **fits.props}, brand=BRAND
        ).overflow
        == ()
    )
    assert "text_overflow" in _kinds(_spec(word, CLOSE))


def test_two_components_in_one_band_at_once_is_a_problem() -> None:
    bar = _use("lower_third", END - 3.0, 2.0)

    assert "zone_clash" in _kinds(_spec(HOOK, bar, CLOSE))


def test_a_blank_prop_is_a_problem() -> None:
    blank = _use("hook_title", 0.0, 2.0, text="   ")

    assert "empty_props" in _kinds(_spec(blank, CLOSE))


def test_a_video_that_ends_without_its_button_is_a_problem() -> None:
    assert "no_cta" in _kinds(_spec(HOOK))


def test_nothing_is_drawn_where_the_apps_put_their_buttons() -> None:
    area = safe_area("9:16")
    assert area == (0, 220, 940, 1500)
    assert ZONES["SUBTITLES"][1] <= area[3]
    left, top, right, _bottom = CORNER_LOGO_BOX
    assert left < 540 and top >= area[1] and right <= area[2]

    caption = CaptionLine(
        start=0.5, end=1.5, words=(CaptionWord(text="Salom", start=0.5, end=1.5),)
    )
    corner = _use("corner_logo", 2.0, 5.0, on_dark="1")
    logo = BRAND.model_copy(update={"logo": "data:image/png;base64,AA=="})
    assert _kinds(_spec(HOOK, corner, CLOSE, captions=(caption,), brand=logo)) == []


def test_a_wide_frame_has_no_app_buttons_to_keep_clear_of() -> None:
    assert safe_area("16:9") is None


def test_subtitle_words_are_spaced_by_one_fixed_gap() -> None:
    """The renderer drew the font's space wider on some lines than others;
    the words now sit apart by one gap, set in pixels."""
    words = tuple(
        CaptionWord(text=text, start=n * 0.3, end=n * 0.3 + 0.3)
        for n, text in enumerate(("Do'stlar,", "sizlarni", "har", "bittalarni"))
    )
    spec = _spec(HOOK, CLOSE, captions=(CaptionLine(start=0, end=1.2, words=words),))

    clip = build_edit(spec)["timeline"]["tracks"][-2]["clips"][0]
    html, css = clip["asset"]["html"], clip["asset"]["css"]

    assert "</span> <span" not in html
    assert "column-gap:23px" in css and "margin:0 .12em" not in css


def test_a_word_lit_by_its_colour_keeps_its_size() -> None:
    from videokit.karaoke import caption_colors

    words = (CaptionWord(text="Salom", start=0.0, end=0.5),)
    spec = _spec(HOOK, CLOSE, captions=(CaptionLine(start=0, end=0.5, words=words),))
    ink, lit = caption_colors(spec.brand)

    js = build_edit(spec)["timeline"]["tracks"][-2]["clips"][0]["asset"]["js"]

    assert ink != lit
    assert "scale:1," in js and "scale:1.1" not in js
