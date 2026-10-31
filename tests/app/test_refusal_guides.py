"""What a refused change says: the cause, then what to do, never a guess at waiting."""

from types import SimpleNamespace

import pytest
from metaads import creatives

from app.modules.ads.constants import PostRoute
from app.modules.ads.selectors.failures import GUIDES, SENTENCES, guide_of
from app.modules.ads.selectors.variants import post_route

WAITED = {"temporary", "read"}


def test_a_refusal_with_no_name_still_says_what_to_do() -> None:
    cause, steps = guide_of("refused")

    assert "pastda" not in cause
    assert steps


@pytest.mark.parametrize("code", sorted(GUIDES))
def test_every_guide_is_a_sentence_of_the_screen(code: str) -> None:
    assert code in SENTENCES
    assert guide_of(code)[0] and guide_of(code)[1]


@pytest.mark.parametrize("code", sorted(set(GUIDES) - WAITED))
def test_only_a_passing_fault_is_told_to_wait(code: str) -> None:
    assert "kuting" not in " ".join(guide_of(code)[1]).replace(
        "O'rganish tugashini kuting", ""
    )


def _post(*, carousel: bool, text: str = "Izoh") -> SimpleNamespace:
    return SimpleNamespace(
        media_asset=SimpleNamespace(kind="ig_image", is_carousel=carousel, name="Izoh"),
        headline="",
        description="",
        primary_text=text,
    )


def _going(*, form: bool = False, phone: bool = False) -> SimpleNamespace:
    return SimpleNamespace(needs_lead_form=form, needs_phone=phone)


def test_an_album_behind_a_lead_form_becomes_a_new_carousel() -> None:
    route = post_route(variant=_post(carousel=True), built=_going(form=True))  # type: ignore[arg-type]

    assert route == PostRoute.COPIED_FOR_CAROUSEL


def test_an_album_elsewhere_keeps_its_likes() -> None:
    route = post_route(variant=_post(carousel=True), built=_going())  # type: ignore[arg-type]

    assert route == PostRoute.PROMOTED


def test_a_single_picture_behind_a_lead_form_keeps_its_likes() -> None:
    route = post_route(variant=_post(carousel=False), built=_going(form=True))  # type: ignore[arg-type]

    assert route == PostRoute.PROMOTED


def test_every_route_has_its_note() -> None:
    assert PostRoute.COPIED_FOR_CAROUSEL.label


@pytest.mark.parametrize(
    ("media_type", "expected"), [("CAROUSEL_ALBUM", True), ("IMAGE", False)]
)
def test_an_album_is_told_from_a_picture(media_type: str, expected: bool) -> None:
    found = creatives._instagram(
        {
            "id": "1",
            "media_type": media_type,
            "media_product_type": "FEED",
            "media_url": "https://x/y.jpg",
        }
    )

    assert found is not None
    assert found.is_carousel is expected
