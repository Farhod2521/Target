"""An advert is a video when people see one, whatever shape its creative took."""

from types import SimpleNamespace

from app.modules.ads.selectors.creatives import ad_format


def _creative(**fields: object) -> SimpleNamespace:
    base = {"is_video": False, "kind": "", "video_id": ""}
    return SimpleNamespace(**{**base, **fields})


def test_a_boosted_video_post_is_a_video() -> None:
    assert ad_format(_creative(kind="post", is_video=True)) == "video"


def test_a_row_the_sync_has_not_reached_falls_back_to_its_shape() -> None:
    assert ad_format(_creative(kind="video")) == "video"
    assert ad_format(_creative(kind="", video_id="77")) == "video"


def test_a_picture_and_a_missing_creative_are_images() -> None:
    assert ad_format(_creative(kind="link")) == "image"
    assert ad_format(None) == "image"
