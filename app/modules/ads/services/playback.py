"""Where a video in the picker plays from, for the one person about to watch it.

Both kinds of address are signed CDN links that expire, so neither is kept as
the truth. A library video's address from the last library read is used while
it is still good for a while (read 2026-11-09: valid four to five days, served
as ``video/mp4`` with ``access-control-allow-origin: *`` and byte ranges, so a
``<video>`` plays it straight from Meta); past that, and for every Instagram
post, Meta is asked again. The answer is kept a short while so a preview
opened twice does not ask twice.
"""

import logging
import re
from datetime import UTC, datetime, timedelta
from typing import Final

from adskit.errors import ProviderError
from metaads.assets import MetaAssets

from app.common.cache import cache
from app.common.db import utcnow
from app.modules.ads.constants import MediaKind
from app.modules.ads.exceptions import (
    NoAdAccount,
    NotAVideo,
    VideoUnreadable,
    VideoWithheld,
)
from app.modules.ads.models import MediaAsset
from app.modules.ads.services.access import profile_token, token_for

logger = logging.getLogger(__name__)

PLAY_KEY: Final = "media-play:{asset}"
PLAY_SECONDS: Final = 30 * 60
# An address with less life than this left is asked for again.
PLAY_LEEWAY: Final = timedelta(hours=1)
# fbcdn's own expiry: ``oe=`` and the Unix time in hex.
_EXPIRES: Final = re.compile(r"[?&]oe=([0-9A-Fa-f]{6,10})(?:&|$)")


def play_address(asset: MediaAsset, *, now: datetime | None = None) -> str:
    """A fresh address to play this video from. Raises when there is none."""
    if not asset.is_video:
        raise NotAVideo
    key = PLAY_KEY.format(asset=asset.id)
    kept = cache.get(key)
    if isinstance(kept, str) and kept:
        return kept
    moment = now or utcnow()
    stored = asset.permalink_url if asset.kind == MediaKind.VIDEO else ""
    address = stored if _lasts(stored, now=moment) else _asked(asset)
    if not address:
        raise VideoWithheld
    cache.set(key, address, PLAY_SECONDS)
    return address


def expires_at(address: str) -> datetime | None:
    """When a signed CDN address stops working, if it says."""
    found = _EXPIRES.search(address)
    if found is None:
        return None
    return datetime.fromtimestamp(int(found.group(1), 16), tz=UTC)


def _lasts(address: str, *, now: datetime) -> bool:
    ends = expires_at(address)
    return ends is not None and ends - now > PLAY_LEEWAY


def _asked(asset: MediaAsset) -> str:
    assets = MetaAssets()
    try:
        if asset.kind == MediaKind.VIDEO:
            if asset.ad_account is None:
                raise NoAdAccount
            return assets.video_source(
                video_id=asset.external_id, token=token_for(ad_account=asset.ad_account)
            )
        return assets.instagram_source(
            media_id=asset.external_id, token=profile_token(asset)
        )
    except ProviderError as exc:
        logger.info(
            "video address unread",
            extra={"asset": asset.external_id, "kind": asset.kind, "error": str(exc)},
        )
        raise VideoUnreadable from exc


__all__ = ["PLAY_KEY", "expires_at", "play_address"]
