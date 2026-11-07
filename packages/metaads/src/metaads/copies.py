"""TZ 2: copies Meta makes itself, ``POST /{id}/copies``.

A copy keeps every setting the mirror does not hold - placements, bidding,
the creative as Meta stores it - which is why it is asked of Meta rather
than rebuilt here. One call may carry an object's ads with it, but only a
few: "the total number of children ads to copy should not exceed 3 for a
synchronous call". A bigger tree is copied a level at a time by the caller.
"""

from typing import Any, Final, Literal

from metaads.client import GraphClient
from metaads.writing import fake_id, is_dry_run_id, post_object

# Meta's documented ceiling for a deep copy answered in the same call.
SYNC_DEEP_COPY_ADS: Final = 3

StatusOption = Literal["ACTIVE", "PAUSED", "INHERITED_FROM_SOURCE"]
PAUSED: Final[StatusOption] = "PAUSED"
ACTIVE: Final[StatusOption] = "ACTIVE"
INHERITED: Final[StatusOption] = "INHERITED_FROM_SOURCE"


def _rename(suffix: str) -> dict[str, str]:
    """The copy alone takes the suffix; what it carries keeps its names."""
    if not suffix:
        return {"rename_strategy": "NO_RENAME"}
    return {"rename_strategy": "ONLY_TOP_LEVEL_RENAME", "rename_suffix": suffix}


def copy_campaign(
    *,
    campaign_id: str,
    suffix: str,
    token: str,
    client: GraphClient | None = None,
    dry_run: bool = True,
) -> str:
    """The campaign alone, paused; its groups are copied into it one by one."""
    if dry_run or is_dry_run_id(campaign_id):
        return fake_id("campaign")
    answer = post_object(
        path=f"{campaign_id}/copies",
        data={
            "deep_copy": False,
            "status_option": PAUSED,
            "rename_options": _rename(suffix),
        },
        token=token,
        client=client,
    )
    return str(answer["copied_campaign_id"])


def copy_adset(
    *,
    adset_id: str,
    campaign_id: str = "",
    deep_copy: bool,
    status: StatusOption,
    suffix: str = "",
    token: str,
    client: GraphClient | None = None,
    dry_run: bool = True,
) -> str:
    """One group, into ``campaign_id`` (its own when empty), with its ads if asked."""
    if dry_run or is_dry_run_id(adset_id):
        return fake_id("adset")
    answer = post_object(
        path=f"{adset_id}/copies",
        data={
            "campaign_id": campaign_id,
            "deep_copy": deep_copy,
            "status_option": status,
            "rename_options": _rename(suffix),
        },
        token=token,
        client=client,
    )
    return str(answer["copied_adset_id"])


def copy_ad(
    *,
    ad_id: str,
    adset_id: str = "",
    status: StatusOption,
    suffix: str = "",
    creative: dict[str, Any] | None = None,
    token: str,
    client: GraphClient | None = None,
    dry_run: bool = True,
) -> str:
    """One advert, into ``adset_id`` (its own when empty).

    ``creative`` is Meta's ``creative_parameters``: left out, the copy runs
    an identical creative; given, its top-level fields replace the original's
    in a creative this call makes.
    """
    if dry_run or is_dry_run_id(ad_id):
        return fake_id("ad")
    answer = post_object(
        path=f"{ad_id}/copies",
        data={
            "adset_id": adset_id,
            "status_option": status,
            "rename_options": _rename(suffix),
            "creative_parameters": creative or None,
        },
        token=token,
        client=client,
    )
    return str(answer["copied_ad_id"])


__all__ = [
    "ACTIVE",
    "INHERITED",
    "PAUSED",
    "SYNC_DEEP_COPY_ADS",
    "StatusOption",
    "copy_ad",
    "copy_adset",
    "copy_campaign",
]
