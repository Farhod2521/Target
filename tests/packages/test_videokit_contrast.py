"""videokit: words over light footage get a dark backing, and are checked."""

import io

from PIL import Image
from videokit import (
    Brand,
    CaptionLine,
    CaptionWord,
    ComponentUse,
    Cut,
    EditSpec,
    build_edit,
)
from videokit.brightness import region_light
from videokit.preflight import preflight
from videokit.preflight_contrast import needs_scrim

BRAND = Brand(name="Bahor", cta_text="Yozing", text="#ffffff")


def _still(top_grey: int, bottom_grey: int) -> bytes:
    image = Image.new("RGB", (360, 640), (bottom_grey,) * 3)
    image.paste((top_grey,) * 3, (0, 0, 360, 320))
    out = io.BytesIO()
    image.save(out, "JPEG", quality=95)
    return out.getvalue()


def _spec(**changes: object) -> EditSpec:
    hook = ComponentUse(
        name="hook_title", zone="TOP_TITLE", start=0, length=2, props={"text": "Salom"}
    )
    base = EditSpec(
        source_url="https://example.test/v.mp4",
        cuts=(Cut(start=0, end=10),),
        resolution="1080",
        brand=BRAND,
        components=(
            hook,
            ComponentUse(name="end_card", zone="FULL", start=7, length=3),
            ComponentUse(name="end_cta", zone="FULL", start=7.3, length=2.7),
        ),
    )
    return base.model_copy(update=changes)


def test_the_light_is_read_where_the_words_are() -> None:
    sky_over_dark = _still(top_grey=240, bottom_grey=20)

    assert region_light(sky_over_dark, (64, 240, 940, 500)) > 0.9  # type: ignore[operator]
    assert region_light(sky_over_dark, (140, 1280, 940, 1500)) < 0.1  # type: ignore[operator]


def test_white_words_need_a_backing_over_a_sky_but_not_over_a_jacket() -> None:
    assert needs_scrim("#ffffff", 0.94)
    assert not needs_scrim("#ffffff", 0.2)


def test_an_unbacked_headline_over_the_sky_stops_the_render() -> None:
    lit = _spec()
    bright = lit.model_copy(
        update={
            "components": (
                lit.components[0].model_copy(update={"backdrop": 0.95}),
                *lit.components[1:],
            )
        }
    )
    backed = bright.model_copy(
        update={
            "components": (
                bright.components[0].model_copy(update={"scrim": True}),
                *bright.components[1:],
            )
        }
    )

    assert "low_contrast" in [p.kind for p in preflight(bright, build_edit(bright))]
    assert "low_contrast" not in [p.kind for p in preflight(backed, build_edit(backed))]
    html = build_edit(backed)["timeline"]["tracks"][0]["clips"][0]["asset"]["html"]
    assert 'class="scrim"' in html


def test_a_backed_subtitle_line_is_drawn_on_its_backing() -> None:
    line = CaptionLine(
        start=0.5,
        end=1.5,
        words=(CaptionWord(text="Salom", start=0.5, end=1.5),),
        backdrop=0.95,
        scrim=True,
    )
    spec = _spec(captions=(line,))

    assert "low_contrast" not in [p.kind for p in preflight(spec, build_edit(spec))]
    clip = next(
        c
        for t in build_edit(spec)["timeline"]["tracks"]
        for c in t["clips"]
        if 'id="l0"' in c["asset"].get("html", "")
    )
    assert 'class="l sc"' in clip["asset"]["html"]
