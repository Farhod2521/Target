"""Adverts the provider has stopped, and the fix each one can be given."""

from typing import Final

from adskit import ExternalRef

from core.agent.ad_facts import AdFacts, LibraryImage
from core.agent.contracts import Finding, Policy
from core.agent.facts import AccountFacts, AdSetFacts, switched_off

BROKEN_PICTURE: Final = "broken_picture"
REFUSED_AD: Final = "refused_ad"
SITE_DOWN: Final = "site_down"

_REWRITABLE_KINDS: Final = ("link", "video")

_REFUSAL_CHARS: Final = 500

_ACTIVE: Final = "active"

_PICTURE_KIND: Final = "link"

_PICTURE_WORDS: Final = ("image",)


def broken_picture(*, account: AccountFacts, policy: Policy) -> list[Finding]:
    """Every stopped advert whose picture is the fault, with one to replace it."""
    own = {image.image_hash: image for image in account.library}
    found: list[Finding] = []
    for item in account.adsets:
        if switched_off(item):
            continue
        for ad in item.ads:
            if not _picture_is_broken(ad=ad, own=own):
                continue
            replacement = _replacement(account=account, item=item, ad=ad, own=own)
            if replacement is None:
                continue
            found.append(
                _finding(account=account, item=item, ad=ad, replacement=replacement)
            )
    return found


def refused_ad(*, account: AccountFacts, policy: Policy) -> list[Finding]:
    """Every advert refused under a policy, proposed as a new one with new words."""
    found: list[Finding] = []
    for item in account.adsets:
        if switched_off(item):
            continue
        for ad in item.ads:
            if not ad.is_faulted or not ad.refusal:
                continue
            if ad.creative_kind not in _REWRITABLE_KINDS:
                continue
            found.append(
                Finding(
                    kind="new_ad",
                    rule=REFUSED_AD,
                    ref=ExternalRef(
                        provider=account.provider, level="ad", id=ad.external_id
                    ),
                    parent_id=item.external_id,
                    weight=item.daily_budget_minor or 0,
                    evidence={
                        "cause": "refused",
                        "refusal": ad.refusal[:_REFUSAL_CHARS],
                        "delivery": ad.delivery,
                    },
                )
            )
    return found


def site_down(*, account: AccountFacts, policy: Policy) -> list[Finding]:
    """Every delivering group whose adverts send people to a page that is down."""
    return [
        Finding(
            kind="pause",
            rule=SITE_DOWN,
            ref=ExternalRef(
                provider=account.provider, level="adset", id=item.external_id
            ),
            weight=max(item.totals.spend_minor, item.daily_budget_minor or 0),
            evidence={
                "down_url": item.landing.down_urls[0],
                "days": item.days_with_spend,
                "spend_minor": item.totals.spend_minor,
                "currency": account.currency,
            },
        )
        for item in account.adsets
        if item.delivery == _ACTIVE and item.landing.down_urls
    ]


def _picture_is_broken(*, ad: AdFacts, own: dict[str, LibraryImage]) -> bool:
    if not ad.is_faulted or ad.creative_kind != _PICTURE_KIND or not ad.image_hash:
        return False
    if ad.image_hash not in own:
        return True
    summary = ad.issue_summary.lower()
    return any(word in summary for word in _PICTURE_WORDS)


def _replacement(
    *,
    account: AccountFacts,
    item: AdSetFacts,
    ad: AdFacts,
    own: dict[str, LibraryImage],
) -> LibraryImage | None:
    """The picture this advert is given instead, or nothing to offer."""
    for pool in (item.ads, _campaign_ads(account=account, item=item)):
        for other in pool:
            if (
                other.external_id != ad.external_id
                and other.is_active
                and other.image_hash in own
                and other.image_hash != ad.image_hash
            ):
                return own[other.image_hash]
    return next(
        (image for image in account.library if image.image_hash != ad.image_hash),
        None,
    )


def _campaign_ads(*, account: AccountFacts, item: AdSetFacts) -> tuple[AdFacts, ...]:
    return tuple(
        ad
        for group in account.in_campaign(item.campaign_external_id)
        if group.external_id != item.external_id
        for ad in group.ads
    )


def _finding(
    *,
    account: AccountFacts,
    item: AdSetFacts,
    ad: AdFacts,
    replacement: LibraryImage,
) -> Finding:
    """The proposal. ``weight`` is what the group is set to spend a day."""
    return Finding(
        kind="new_picture",
        rule=BROKEN_PICTURE,
        ref=ExternalRef(provider=account.provider, level="ad", id=ad.external_id),
        parent_id=item.external_id,
        weight=item.daily_budget_minor or 0,
        evidence={
            "picture_name": replacement.name,
            "delivery": ad.delivery,
            "issue_codes": list(ad.issue_codes),
        },
        payload={
            "asset_id": replacement.asset_id,
            "image_hash": replacement.image_hash,
        },
    )


__all__ = [
    "BROKEN_PICTURE",
    "REFUSED_AD",
    "SITE_DOWN",
    "broken_picture",
    "refused_ad",
    "site_down",
]
