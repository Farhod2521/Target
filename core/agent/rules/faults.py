"""Adverts the provider has stopped, and the fix each one can be given.

Not a measurement, like the rules about money and attention: a fault is a
fact the provider reported, and it needs no window, no learning to finish
and no days with spend - see :func:`core.agent.facts.troubled`, which the
group-level twin of this module rests on.

**A fault becomes a proposal only where there is a fix to press.** The fix
is decided here, from the facts, and never by the model: the model explains
the proposal, it does not choose what gets written to somebody's account.

Three faults are handled here.

**A page the adverts send people to does not open.** Nothing on the
account fixes a website, so the fix offered is the one that stops the
money: the group is switched off until the page is back. Any campaign, like
every stop - a stop is the owner's own protection and never a rewrite.

**A refused advert** gets new words - but only when the refusal is about
the words: see :mod:`core.agent.refusal_cause`. New words for a refusal
about the picture, the page, the product or the account change the advert
and leave it refused. Those refusals are told to the owner with their cause
and are not proposed as new words.

**A picture the provider cannot show** gets a picture the account holds. It
is recognised three ways, because each alone misses a case. The picture is
not one the account holds - which is how another account's picture, listed
on this account's library edge, reaches an advert and fails it once
delivery starts. The provider's own summary says the picture is the
problem, for a picture the account did hold and lost. Or the advert was
refused under a policy, and the refusal is about the picture.
"""

from typing import Final

from adskit import ExternalRef

from core.agent.ad_facts import AdFacts, LibraryImage
from core.agent.contracts import Finding, Policy
from core.agent.facts import AccountFacts, AdSetFacts, switched_off
from core.agent.refusal_cause import refusal_cause

BROKEN_PICTURE: Final = "broken_picture"
REFUSED_AD: Final = "refused_ad"
SITE_DOWN: Final = "site_down"

# The creative kinds whose words can be written again: a picture with a
# link, and a video. A promoted post keeps its words on the post.
_REWRITABLE_KINDS: Final = ("link", "video")

# How much of the provider's refusal rides on the proposal, for the words
# to be written against and for the assistant to explain.
_REFUSAL_CHARS: Final = 500

# The one delivery state a stop is proposed for.
_ACTIVE: Final = "active"

# The creative kind a picture can be swapped on: a picture and a link. A
# video's frame and a promoted post are different creatives.
_PICTURE_KIND: Final = "link"

# How the provider's own summary names a picture fault, lowercased. Read
# only for an advert it has already stopped, and only to decide which fix
# fits - never to decide that something is wrong.
_PICTURE_WORDS: Final = ("image",)


def broken_picture(*, account: AccountFacts, policy: Policy) -> list[Finding]:
    """Every stopped advert whose picture is the fault, with one to replace it.

    Not inside a group or campaign the owner switched off: the provider keeps
    calling a refused advert refused there, and a fix for it would be a fix
    for something nobody is running.
    """
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
    """Every advert refused over its words, proposed as a new one with new words.

    The words themselves are written after the rules - see
    ``apps.agent.services.write_ad_copy`` - and a refusal they cannot be
    written for is not proposed at all. A refusal about anything else is
    not this rule's: see the module.
    """
    found: list[Finding] = []
    for item in account.adsets:
        if switched_off(item):
            continue
        for ad in item.ads:
            if not ad.is_faulted or not ad.refusal:
                continue
            if ad.creative_kind not in _REWRITABLE_KINDS:
                continue
            if refusal_cause(ad.refusal) != "words":
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
    """Every delivering group whose adverts send people to a page that is down.

    Spend is the weight, as for every stop: the money that is leaving for
    a page nobody can open.
    """
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
    if any(word in summary for word in _PICTURE_WORDS):
        return True
    return bool(ad.refusal) and refusal_cause(ad.refusal) == "picture"


def _replacement(
    *,
    account: AccountFacts,
    item: AdSetFacts,
    ad: AdFacts,
    own: dict[str, LibraryImage],
) -> LibraryImage | None:
    """The picture this advert is given instead, or nothing to offer.

    A picture a delivering advert beside it already shows, first in its own
    group and then in its campaign: it is a picture the owner already chose
    for this offer. Failing that, the newest picture the account holds.
    """
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
    """The proposal. ``weight`` is what the group is set to spend a day.

    A stopped advert has usually spent nothing, so its spend would rank it
    below every improvement. What it stands to lose is the group's money
    not reaching anybody, and the daily budget is that figure.
    """
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
