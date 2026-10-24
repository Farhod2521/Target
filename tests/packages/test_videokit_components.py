"""videokit components: the registry's rules, the clips, tracks and layouts."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from videokit import (
    Brand,
    CaptionLine,
    CaptionWord,
    ComponentUse,
    Cut,
    EditSpec,
    LayoutSpan,
    build_edit,
    edit_bytes,
)
from videokit.components import (
    ComponentError,
    component,
    component_clip,
    components,
    fill,
)
from videokit.components.registry import FOLDER, _read
from videokit.components.rules import check
from videokit.graphics import pieces, within_limit
from videokit.icons import ICONS, icon_svg
from videokit.layout import PLACEABLE, zone_box
from videokit.motion_tokens import prelude
from videokit.preflight import preflight

SOURCE = "https://example.test/source.mp4"
BRAND = Brand(name="Bahor", tagline="Gullar", cta_text="Telegram", cta_handle="@bahor")


def test_every_folder_is_a_component_that_keeps_the_rules() -> None:
    found = components()

    assert set(found) >= {
        "hook_title",
        "chips_list",
        "lower_third",
        "cta_button",
        "end_card",
    }
    for item in found.values():
        assert item.description
        assert set(item.zones) <= PLACEABLE
        assert 0 < item.min_seconds <= item.max_seconds
        assert item.props_model().model_validate(item.example)


@pytest.mark.parametrize(
    ("js", "css", "html"),
    [
        ("setTimeout(()=>{},10)", "", ""),
        ("requestAnimationFrame(f)", "", ""),
        ("const t=Date.now()", "", ""),
        ("", ".a{background:url(https://x.test/a.png)}", ""),
        ("", "", "<canvas></canvas>"),
        ("", "", '<script src="https://x.test/a.js"></script>'),
        ("", ".a{font-size:2em}", ""),
        ("", ".a{text-transform:uppercase}", ""),
        ("", ".a{backdrop-filter:blur(8px)}", ""),
    ],
)
def test_a_component_that_breaks_a_rule_is_refused(
    js: str, css: str, html: str
) -> None:
    with pytest.raises(ComponentError):
        check("broken", html=html, css=css, js=js)


def test_a_manifest_must_name_its_own_folder(tmp_path: Path) -> None:
    folder = tmp_path / "odd"
    folder.mkdir()
    (folder / "manifest.json").write_text('{"name": "other"}')

    with pytest.raises(ComponentError):
        _read(folder)


def test_text_is_always_escaped_and_lists_repeat() -> None:
    html = fill(
        "<b>{{ title }}</b>{{#items}}<i>{{ . }}</i>{{/items}}{{#none}}x{{/none}}",
        {"title": "<script>", "items": ["a&b", "\\1"], "none": ""},
    )

    assert html == "<b>&lt;script&gt;</b><i>a&amp;b</i><i>\\1</i>"


def test_props_are_held_to_the_manifest_limits() -> None:
    model = component("chips_list").props_model()

    with pytest.raises(ValidationError):
        model.model_validate({"items": ["only one"]})
    with pytest.raises(ValidationError):
        model.model_validate({"items": ["a" * 40, "b"]})
    with pytest.raises(ValidationError):
        model.model_validate({"items": ["ok", "fine"], "colour": "red"})
    assert model.model_validate({"items": ["Tez", "Arzon"]})


def test_a_clip_sits_over_its_zone_with_the_brand_and_the_font() -> None:
    clip = component_clip(
        component("hook_title"),
        props={"text": "Narx 20% arzon"},
        brand=BRAND,
        zone="TOP_TITLE",
        start=0.5,
        length=2.0,
        resolution="1080",
        aspect_ratio="9:16",
    )

    assert clip["asset"]["type"] == "html5"
    assert (clip["start"], clip["length"]) == (0.5, 2.0)
    assert {k: clip[k] for k in ("width", "height", "offset")} == {
        "width": 1080,
        "height": 500,
        "offset": {"x": 0, "y": 0.2552},
    }
    css = clip["asset"]["css"]
    assert "@font-face" in css and "--accent:#ffd400" in css
    assert clip["asset"]["js"].startswith('const P={"text": "Narx 20% arzon"')


def test_a_component_is_refused_outside_its_zones() -> None:
    with pytest.raises(ComponentError):
        component_clip(
            component("hook_title"),
            props={"text": "Salom"},
            brand=BRAND,
            zone="LOWER_THIRD",
            start=0,
            length=2,
            resolution="1080",
            aspect_ratio="9:16",
        )


def test_the_subtitle_band_never_meets_a_component_band() -> None:
    subtitles = zone_box("SUBTITLES", "1080", "9:16")
    lower = zone_box("LOWER_THIRD", "1080", "9:16")

    lower_bottom = (0.5 - lower["offset"]["y"]) * 1920 + lower["height"] / 2
    subtitles_top = (0.5 - subtitles["offset"]["y"]) * 1920 - subtitles["height"] / 2
    assert lower_bottom <= subtitles_top + 1


def test_components_at_the_same_time_get_their_own_tracks_backdrops_lowest() -> None:
    spec = EditSpec(
        source_url=SOURCE,
        cuts=(Cut(start=0, end=10),),
        brand=BRAND,
        components=(
            ComponentUse(name="end_card", zone="FULL", start=7, length=3),
            ComponentUse(name="cta_button", zone="LOWER_THIRD", start=7, length=3),
            ComponentUse(
                name="hook_title", zone="TOP_TITLE", start=0, length=2,
                props={"text": "Salom"},
            ),
            ComponentUse(name="lower_third", zone="LOWER_THIRD", start=2.5, length=3),
        ),
    )  # fmt: skip

    tracks = build_edit(spec)["timeline"]["tracks"]

    starts = [[clip["start"] for clip in track["clips"]] for track in tracks]
    # The button fits after the lower third; the end card lies under both.
    assert starts[:2] == [[0, 2.5, 7], [7]]
    assert 'class="e"' in tracks[1]["clips"][0]["asset"]["html"]
    assert tracks[-1]["clips"][0]["asset"]["type"] == "video"
    assert edit_bytes(build_edit(spec)) < 150_000


def test_a_split_moves_the_footage_down_for_exactly_its_stretch() -> None:
    spec = EditSpec(
        source_url=SOURCE,
        cuts=(Cut(start=10, end=14, zoom=1.15), Cut(start=20, end=23)),
        layouts=(LayoutSpan(start=2, end=5, layout="split_top"),),
    )

    footage = build_edit(spec)["timeline"]["tracks"][-1]["clips"]

    assert [
        (c["start"], c["length"], c["asset"]["trim"], "offset" in c, c.get("scale"))
        for c in footage
    ] == [
        (0, 2, 10, False, 1.15),
        (2, 2, 12, True, 1.15),
        (4, 1, 20, True, None),
        (5, 2, 21, False, None),
    ]
    assert "transition" not in footage[0]
    assert footage[-1]["transition"] == {"out": "fade"}


def test_pieces_merge_neighbours_with_the_same_layout() -> None:
    spans = (LayoutSpan(start=1, end=2, layout="full"),)

    assert pieces(0, 3, spans) == [(0, 3, "full")]


def test_subtitles_drop_lower_while_the_footage_is_split() -> None:
    def line(start: float) -> CaptionLine:
        return CaptionLine(
            start=start,
            end=start + 1,
            words=(CaptionWord(text="Salom", start=start, end=start + 1),),
        )

    spec = EditSpec(
        source_url=SOURCE,
        cuts=(Cut(start=0, end=10),),
        layouts=(LayoutSpan(start=2, end=5, layout="split_top"),),
        captions=(line(0.5), line(3.0), line(6.0)),
    )

    clips = build_edit(spec)["timeline"]["tracks"][0]["clips"]

    # One clip over both bands; the split line sits lower inside it.
    assert len(clips) == 1
    html = clips[0]["asset"]["html"]
    tops = [int(part.split("px")[0]) for part in html.split('style="top:')[1:]]
    assert tops[0] == tops[2] < tops[1]


def test_a_panel_left_out_for_size_takes_its_split_screen_with_it() -> None:
    spec = EditSpec(
        source_url=SOURCE,
        cuts=(Cut(start=0, end=10),),
        components=(
            ComponentUse(name="chips_list", zone="TOP_PANEL", start=2, length=3),
        ),
        layouts=(LayoutSpan(start=2, end=5, layout="split_top"),),
    )

    smaller, dropped = within_limit(
        spec, limit=0, size=lambda s: len(s.components) + len(s.layouts)
    )

    assert [use.name for use in dropped] == ["chips_list"]
    assert (smaller.components, smaller.layouts) == ((), ())


# --- Beats and capitals --------------------------------------------------------


def test_beats_reach_the_timeline_by_the_clips_clock_and_inside_it() -> None:
    clip = component_clip(
        component("chips_list"),
        props={"items": ["Tez", "Arzon", "Yangi"]},
        brand=BRAND,
        zone="TOP_PANEL",
        start=10.0,
        length=4.0,
        resolution="1080",
        aspect_ratio="9:16",
        beats={"items": [9.0, 11.25, 20.0]},
    )

    # Before the clip: at once; inside: by its clock; past its exit: just
    # before it.
    assert '"beats": {"items": [0.05, 1.25, 3.65]}' in clip["asset"]["js"]


def test_a_beat_may_not_share_a_name_with_a_text_prop(tmp_path: Path) -> None:
    folder = tmp_path / "chips_list"
    folder.mkdir()
    source = component("chips_list")
    manifest = json.loads(
        (FOLDER / "chips_list" / "manifest.json").read_text(encoding="utf-8")
    )
    manifest["beats"] = {"title": "the title lands"}
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    for name, text in (
        ("template.html", source.html),
        ("style.css", source.css),
        ("timeline.js", source.js),
    ):
        (folder / name).write_text(text, encoding="utf-8")

    with pytest.raises(ComponentError, match="beats"):
        _read(folder)


def test_a_clip_carries_the_shared_motion_it_uses_and_no_more() -> None:
    js = component_clip(
        component("chips_list"),
        props={"items": ["Tez", "Arzon"]},
        brand=BRAND,
        zone="TOP_PANEL",
        start=0,
        length=4,
        resolution="1080",
        aspect_ratio="9:16",
    )["asset"]["js"]

    assert js.startswith("const P=")
    assert "const M={" in js and "const pop=" in js
    assert "const slam=" not in js and "const typeIn=" not in js
    assert prelude("tl.to('.a',{x:1});") == ""


def test_every_icon_is_an_inline_drawing_in_the_brands_colour() -> None:
    for name in ICONS:
        drawing = icon_svg(name)

        assert drawing.startswith("<svg viewBox=") and drawing.endswith("</svg>")
        assert "currentColor" in drawing
        assert "http" not in drawing and "<script" not in drawing


def test_an_icon_is_drawn_where_the_template_asks_and_text_stays_escaped() -> None:
    html = fill(
        "<i>{{{ icon }}}</i><b>{{ label }}</b>",
        {"icon": "star", "label": "<b>"},
        drawings={"icon": icon_svg("star")},
    )

    assert html == f"<i>{icon_svg('star')}</i><b>&lt;b&gt;</b>"


def test_capitals_come_from_the_props_and_a_repeated_icon_is_drawn_once() -> None:
    clip = component_clip(
        component("headline_slam"),
        props={"line": "Sizning yordamingizsiz", "pill": "imkonsiz"},
        brand=BRAND,
        zone="TOP_TITLE",
        start=0,
        length=3,
        resolution="1080",
        aspect_ratio="9:16",
    )["asset"]

    assert ">IMKONSIZ<" in clip["html"] and "imkonsiz" not in clip["js"]
    assert clip["html"].count('<symbol id="i-sparkle"') == 1
    assert clip["html"].count('<use href="#i-sparkle"/>') == 4


def test_a_long_clip_seen_in_stretches_clashes_only_where_it_is_seen() -> None:
    corner = ComponentUse(
        name="corner_logo", zone="CORNER", start=0.0, length=10.0,
        props={"on_dark": "1"}, beats={"shows": [0.0, 2.0, 6.0, 10.0]},
    )  # fmt: skip
    headline = ComponentUse(
        name="hook_title", zone="TOP_TITLE", start=2.5, length=3.0,
        props={"text": "Salom dunyo"},
    )  # fmt: skip
    spec = EditSpec(
        source_url=SOURCE,
        cuts=(Cut(start=0, end=10),),
        brand=BRAND.model_copy(update={"logo": "data:image/png;base64,T1dO"}),
        components=(corner, headline),
    )

    assert not [p for p in preflight(spec, build_edit(spec)) if p.kind == "zone_clash"]
