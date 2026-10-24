"""A new picture, where the advert carrying a group has stopped being looked at."""

from typing import Any, Final

from adskit import ExternalRef, Level

from core.agent.ad_facts import AdFacts, LibraryImage
from core.agent.contracts import Finding, Policy
from core.agent.diagnosis import Diagnosis, diagnose
from core.agent.facts import AccountFacts, AdSetFacts
from core.agent.signals import leading_ads

REFRESH_AD = "refresh_ad"

REFRESHED_CAUSES: Final = frozenset({"weak_creative", "worn_out"})

_LEVEL: Final[Level] = "ad"

_PICTURE_KIND: Final = "link"

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
    "late_frequency",
)


def refresh_ad(*, account: AccountFacts, policy: Policy) -> list[Finding]:
    """Propose a new picture for the busiest advert of every group it would help."""
    groups = {item.external_id: item for item in account.adsets if item.is_ours}
    found: list[Finding] = []
    for diagnosis in diagnose(account=account, policy=policy):
        item = groups.get(diagnosis.adset_id)
        if item is None or diagnosis.cause not in REFRESHED_CAUSES:
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
    """The newest picture the account holds that this group is not showing."""
    shown = {ad.image_hash for ad in item.ads if ad.image_hash}
    return next(
        (image for image in account.library if image.image_hash not in shown), None
    )


def _busiest(*, item: AdSetFacts, policy: Policy) -> AdFacts | None:
    """The delivering advert taking the most of the group's money."""
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
