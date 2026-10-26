"""A new picture, where the advert carrying a group has stopped being looked at.

The diagnosis decides that the advert is the problem - see
:mod:`core.agent.diagnosis` - whatever the group's price. This rule asks
for more before it proposes a swap: results that cost too much for what
the group was bought for, see :func:`core.agent.benchmark.results_are_poor`.
A swap replaces the advert and what it learned, and on a group bringing
results at the usual price that is a loss the cause alone does not justify
- the cause is said, in the waiting list, without the card. Where the
results are poor it turns that cause into the one change that answers it:
the advert carrying most of the group's money, shown again with a
different picture. **The words stay.** In a feed
the picture is what stops somebody scrolling; the sentence under it is read
by the people it already stopped, so new words in front of the same picture
change little and throw away what the advert had learned.

**Only on campaigns this product built**, and checked here rather than by
narrowing the account: the diagnosis compares every group with the whole
account, and handed half of it the cause it reached would not be the cause
printed on the card.

**Only a picture advert, and only a picture the account holds** - the one
new creative a swap can name without a download. A video, a promoted post
or a library with nothing new in it gets no proposal here; the waiting list
tells the owner to add a picture or a video instead - see
``apps.agent.selectors.notes``.
"""

from typing import Any, Final

from adskit import ExternalRef, Level

from core.agent.ad_facts import AdFacts, LibraryImage
from core.agent.benchmark import peers, results_are_poor
from core.agent.contracts import Finding, Policy
from core.agent.diagnosis import Diagnosis, diagnose
from core.agent.facts import AccountFacts, AdSetFacts
from core.agent.signals import leading_ads

REFRESH_AD = "refresh_ad"

# The cause a new picture answers here: people are shown the advert and do
# not click. Seen it too often is the morning's frequency message, with its
# own two buttons - a card beside it would say it twice. Every other cause is
# answered somewhere else - a form in the way is not fixed by a picture.
REFRESHED_CAUSES: Final = frozenset({"weak_creative"})

_LEVEL: Final[Level] = "ad"

# The creative kind a picture can be swapped on: a picture with a link. A
# video's frame and a promoted post are different creatives.
_PICTURE_KIND: Final = "link"

# What of the diagnosis rides along. The group's result and its price,
# because the promise is graded on them - see ``core.agent.promises`` - the
# figures that explain the price, and the cause, because the card says
# something different for a tired audience.
_EVIDENCE: Final = (
    "outcome",
    "results",
    "cost_minor",
    "account_cost_minor",
    "days",
    "spend_minor",
    "impressions",
    "link_clicks",
    "link_ctr_bp",
    "account_link_ctr_bp",
    "early_ctr_bp",
    "late_ctr_bp",
)


def refresh_ad(*, account: AccountFacts, policy: Policy) -> list[Finding]:
    """Propose a new picture for the busiest advert of every group it would help."""
    groups = {item.external_id: item for item in account.adsets if item.is_ours}
    found: list[Finding] = []
    for diagnosis in diagnose(account=account, policy=policy):
        item = groups.get(diagnosis.adset_id)
        if item is None or diagnosis.cause not in REFRESHED_CAUSES:
            continue
        if not results_are_poor(
            item=item, bench=peers(account.adsets, item, account.usual)
        ):
            continue
        ad = _busiest(item=item, policy=policy)
        if ad is None or ad.creative_kind != _PICTURE_KIND or not ad.image_hash:
            continue
        picture = fresh_picture(account=account, item=item)
        if picture is None:
            continue
        found.append(
            _finding(
                account=account,
                item=item,
                ad=ad,
                picture=picture,
                diagnosis=diagnosis,
            )
        )
    return found


def fresh_picture(*, account: AccountFacts, item: AdSetFacts) -> LibraryImage | None:
    """The newest picture the account holds that this group is not showing.

    Not one an advert beside it already carries: the whole group is what
    people have stopped looking at, so a picture from inside it is more of
    the same.
    """
    shown = {ad.image_hash for ad in item.ads if ad.image_hash}
    return next(
        (image for image in account.library if image.image_hash not in shown), None
    )


def _busiest(*, item: AdSetFacts, policy: Policy) -> AdFacts | None:
    """The delivering advert taking the most of the group's money.

    Among the ones carrying a real share of it - the adverts the diagnosis
    read the group's attention off. Changing one at two percent of the
    spend would change nothing the promise is graded on.
    """
    carrying = sorted(
        leading_ads(item, policy),
        key=lambda ad: (-int(ad.figures.spend_minor), ad.external_id),
    )
    return carrying[0] if carrying else None


def _finding(
    *,
    account: AccountFacts,
    item: AdSetFacts,
    ad: AdFacts,
    picture: LibraryImage,
    diagnosis: Diagnosis,
) -> Finding:
    """The proposal. ``weight`` is the group's spend: the result is its result."""
    spend = int(item.totals.spend_minor)
    evidence: dict[str, Any] = {
        key: diagnosis.evidence[key]
        for key in _EVIDENCE
        if diagnosis.evidence.get(key) is not None
    }
    evidence["cause"] = diagnosis.cause
    evidence["currency"] = account.currency
    evidence["picture_name"] = picture.name
    evidence["ad_spend_share_pct"] = (
        round(int(ad.figures.spend_minor) * 100 / spend) if spend else 0
    )
    return Finding(
        kind="new_picture",
        rule=REFRESH_AD,
        ref=ExternalRef(provider=account.provider, level=_LEVEL, id=ad.external_id),
        parent_id=item.external_id,
        weight=spend,
        evidence=evidence,
        payload={"asset_id": picture.asset_id, "image_hash": picture.image_hash},
    )


__all__ = ["REFRESHED_CAUSES", "REFRESH_AD", "fresh_picture", "refresh_ad"]
