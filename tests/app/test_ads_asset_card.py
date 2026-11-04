"""A library square carries where its post opens, and only a post has one."""

import pytest

from app.modules.ads.constants import MediaKind
from app.modules.ads.models import MediaAsset
from app.modules.ads.selectors.cards import asset_card


@pytest.mark.parametrize(
    ("kind", "link", "shown"),
    [
        (MediaKind.IG_IMAGE, "https://www.instagram.com/p/abc/", True),
        (MediaKind.IG_VIDEO, "https://www.instagram.com/reel/abc/", True),
        (MediaKind.POST, "https://www.facebook.com/1/posts/2", True),
        (MediaKind.VIDEO, "https://video.xx.fbcdn.net/v/file.mp4", False),
        (MediaKind.IMAGE, "https://scontent.xx.fbcdn.net/file.jpg", False),
    ],
)
def test_only_a_post_carries_its_link(kind: str, link: str, shown: bool) -> None:
    card = asset_card(MediaAsset(kind=kind, permalink_url=link))

    assert card is not None
    assert card["permalink_url"] == (link if shown else "")
