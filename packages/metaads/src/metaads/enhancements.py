"""Meta's own changes to an advert, every one of them turned down.

Advantage+ creative lets Meta crop a picture, brighten it, rewrite the
words, translate them, animate a still and lay music under a video. Each is
a feature a caller may opt out of, and a creative that names none of them
is left to Meta's defaults - which the documentation does not list, beyond
saying ``adapt_to_placement`` defaults to on. So every creative this
package makes names every feature and says no to each.

**Why no, always.** The diagnosis reads a video's opening and middle - the
hook and the hold - and a video Meta re-cut is not the video those numbers
describe. And a sentence written in Uzbek and then "optimised" or
translated by Meta is not the sentence the owner approved.

**The list is data.** Meta adds features between versions. When the API
version moves, the feature list in the get-started guide is read again and
any new key is added here; nothing else changes.

**Music is not one of them.** The guide says music is "implemented with the
``asset_feed_spec`` parameter" and that to opt out one passes
``asset_feed_spec.audios`` empty. The guide does not say whether a creative
carrying ``asset_feed_spec`` beside its story is then read as an asset-feed
creative, or whether every creative kind accepts every feature. So a
refusal is answered by sending the creative again with less, and the fact
is logged: the advert is made either way, and the log says which choice
did not travel - see :func:`post_creative`.

**Read back afterwards.** The guide's own advice: "to confirm the final
configuration, use a GET request". Any feature that came back switched on
is logged - the evidence that the list here is behind Meta's.

https://developers.facebook.com/documentation/ads-commerce/marketing-api/creative/advantage-creative/get-started
"""

import logging
from collections.abc import Mapping
from typing import Any, Final

from metaads.client import GraphClient
from metaads.errors import MetaAPIError, MetaAuthError, MetaError, MetaTemporaryError
from metaads.writing import graph_client, id_of, post_object

logger = logging.getLogger(__name__)

# Every Advantage+ creative feature the get-started guide lists, v26.0.
# ``standard_enhancements`` is not here: deprecated since v22.0, still
# returned on a read but no longer applied.
FEATURES: Final[tuple[str, ...]] = (
    "adapt_to_placement",
    "add_text_overlay",
    "creative_stickers",
    "description_automation",
    "enhance_cta",
    "image_animation",
    "image_background_gen",
    "image_brightness_and_contrast",
    "image_templates",
    "image_text_translation",
    "image_touchups",
    "image_uncrop",
    "inline_comment",
    "media_type_automation",
    "pac_relaxation",
    "product_extensions",
    "reveal_details_over_time",
    "text_optimizations",
    "text_translation",
    "translate_voiceover",
    "video_auto_crop",
    "video_filtering",
    "video_uncrop",
)

OPT_OUT: Final = "OPT_OUT"
FEATURES_KEY: Final = "degrees_of_freedom_spec"
MUSIC_KEY: Final = "asset_feed_spec"
# What the read-back asks for: the two blocks this module sends.
READ_FIELDS: Final = f"{FEATURES_KEY},{MUSIC_KEY}"


def opted_out() -> dict[str, Any]:
    """The two blocks every new creative carries, fresh each call."""
    return {
        FEATURES_KEY: {
            "creative_features_spec": {
                name: {"enroll_status": OPT_OUT} for name in FEATURES
            }
        },
        MUSIC_KEY: {"audios": []},
    }


def still_on(row: Mapping[str, Any]) -> list[str]:
    """The features a creative read back holds switched on, in list order.

    Only an explicit ``OPT_IN`` counts. A feature the read leaves out is
    not evidence of anything: Meta answers with the features it knows of,
    and ``standard_enhancements`` comes back after it stopped applying.
    """
    block = row.get(FEATURES_KEY) or {}
    features = (
        block.get("creative_features_spec") if isinstance(block, Mapping) else None
    )
    if not isinstance(features, Mapping):
        return []
    found = []
    for name, value in features.items():
        if isinstance(value, Mapping) and value.get("enroll_status") == "OPT_IN":
            found.append(str(name))
    return found


def post_creative(
    *,
    account_id: str,
    data: dict[str, Any],
    token: str,
    client: GraphClient | None = None,
) -> str:
    """Create one creative with every Meta change refused; answer its id.

    ``data`` is everything else the creative carries. The two blocks are
    added here, so no caller can make a creative without them.

    A refusal is answered by sending the creative again with less: first
    without the music block, then without either. Meta's refusals do not
    always name the field ("Invalid parameter"), so the fallback does not
    wait to be told which block it was. The last attempt is the creative
    exactly as it was sent before these blocks existed, so its refusal - the
    one raised - is the one the creative would have had anyway.
    """
    full = opted_out()
    attempts = (full, {FEATURES_KEY: full[FEATURES_KEY]}, {})
    for number, choices in enumerate(attempts):
        try:
            payload = post_object(
                path=f"{account_id}/adcreatives",
                data=data | choices,
                token=token,
                client=client,
            )
        except (MetaTemporaryError, MetaAuthError):
            # Not a refusal of what was sent: the same call later, or
            # with another token, would be made exactly as it is.
            raise
        except MetaAPIError as exc:
            if number == len(attempts) - 1:
                raise
            logger.warning(
                "creative refused with %s, sending again with less: %s",
                sorted(choices),
                exc,
            )
            continue
        created = id_of(payload)
        if number:
            logger.warning(
                "creative %s made without %s",
                created,
                sorted(set(full) - set(choices)),
            )
        if choices:
            _check(created, token=token, client=client)
        return created
    raise AssertionError("unreachable: the last attempt returns or raises")


def _check(creative_id: str, *, token: str, client: GraphClient | None) -> None:
    """Log any feature the new creative holds switched on. Never raises:
    the creative is made, and a failed read is not a reason to unmake it."""
    try:
        with graph_client(client, token) as graph:
            row = graph.get(creative_id, fields=READ_FIELDS)
    except MetaError as exc:
        logger.warning("creative %s read back failed: %s", creative_id, exc)
        return
    on = still_on(row)
    if on:
        logger.warning("creative %s still holds Meta changes: %s", creative_id, on)


__all__ = [
    "FEATURES",
    "FEATURES_KEY",
    "MUSIC_KEY",
    "OPT_OUT",
    "opted_out",
    "post_creative",
    "still_on",
]
