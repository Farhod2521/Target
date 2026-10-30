"""What unfolds under a list row: the groups and their adverts, with their figures."""

from typing import Any, Final

from sqlalchemy.orm import Session

from app.common.contract import money
from app.modules.accounts.models import User
from app.modules.ads.contract.listing import figures_of
from app.modules.ads.contract.words import controls_of, last_action_of, status_of

# An advert that shows an existing page post: its words are changed on the network.
POST_KINDS: Final = frozenset({"post", "page_post", "existing_post", "boost"})
# The figures beside each advert are the last week's.
TREE_PERIOD: Final = "7"


def ad_item(ad: Any, *, position: int, chips: Any, currency: str) -> dict[str, Any]:
    content = getattr(ad, "content", None)
    figures = figures_of(chips, currency=currency, provider=ad.provider)
    kind = getattr(content, "kind", "") or ""
    return {
        "id": str(ad.id),
        "external_id": ad.external_id,
        "position": position,
        "format": "video" if kind == "video" else "image",
        "name": ad.name or None,
        "thumb": getattr(content, "thumbnail_url", "") or None,
        "headline": getattr(content, "headline", "") or None,
        "text": getattr(content, "message", "") or ad.name,
        "description": getattr(content, "description", "") or None,
        "cta": getattr(content, "call_to_action", "") or None,
        "link": getattr(content, "link_url", "") or None,
        "status": status_of(ad),
        "results": figures["results"] if figures else 0,
        "unit_cost": figures["unit_cost"] if figures else None,
        "spent": figures["spent"] if figures else None,
        "controls": controls_of(
            getattr(ad, "controls", None), early_hours=getattr(ad, "early_hours", 0)
        ),
        "is_last": bool(getattr(ad, "is_last", False)),
        "deleting": bool(getattr(ad, "deleting", False)) or None,
        "can_swap": kind not in POST_KINDS,
    }


def ad_figures(db: Session, *, owner: User, campaign: Any) -> dict[str, Any]:
    """Each advert's chips for the last week, by its network id."""
    from app.modules.metrics.routers import resolve_range
    from app.modules.metrics.selectors.dashboard import cabinet_today
    from app.modules.metrics.selectors.panel import ad_chips

    today = cabinet_today(db, owner=owner, account=campaign.ad_account)
    chosen = resolve_range(period=TREE_PERIOD, start=None, end=None, today=today)
    return {
        row.ad_id: row
        for row in ad_chips(db, owner=owner, campaign=campaign, date_range=chosen)
    }


def campaign_tree(groups: list[Any], *, chips: dict[str, Any]) -> dict[str, Any]:
    """Every group with its adverts, numbered across the campaign."""
    position = 0
    out = []
    for group in groups:
        currency = group.currency or group.campaign.ad_account.currency
        ads = []
        for ad in getattr(group, "fold_ads", group.ads):
            position += 1
            ads.append(
                ad_item(
                    ad,
                    position=position,
                    chips=chips.get(ad.external_id),
                    currency=currency,
                )
            )
        controls = getattr(group, "controls", None)
        out.append(
            {
                "external_id": group.external_id,
                "name": group.name,
                "status": status_of(group, learning=bool(group.is_learning)),
                "daily_budget": money(
                    group.daily_budget_minor, currency, provider=group.provider
                ),
                "min_budget": money(
                    controls.floor_minor if controls is not None else None,
                    currency,
                    provider=group.provider,
                ),
                "controls": controls_of(
                    controls, early_hours=getattr(group, "early_hours", 0)
                ),
                "is_last": bool(getattr(group, "is_last", False)),
                "deleting": bool(getattr(group, "deleting", False)) or None,
                "last_action": last_action_of(getattr(group, "last_action", None)),
                "ads": ads,
            }
        )
    return {"split": len(groups) > 1, "groups": out}


__all__ = ["POST_KINDS", "ad_figures", "ad_item", "campaign_tree"]
