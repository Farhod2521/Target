"""Targetolog mode: the account as Ads Manager shows it, every level in one answer.

The browser asked two endpoints per campaign for this (2 + 2N calls); the
rows come from the list's own filters and every level's figures here.
"""

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.common.contract import money
from app.modules.accounts.models import User
from app.modules.ads import selectors
from app.modules.ads.contract.listing import (
    ListAsk,
    campaign_list,
    figures_of,
    figures_range,
)
from app.modules.ads.contract.words import controls_of, status_of


def _reach(chips: Any) -> dict[str, int]:
    found = {chip.key: chip.value for chip in chips.chips} if chips is not None else {}
    return {
        "impressions": int(found.get("impressions") or 0),
        "reach": int(found.get("reach") or 0),
        "clicks": int(found.get("link_clicks") or found.get("clicks") or 0),
    }


def manager(db: Session, *, owner: User, ask: ListAsk) -> dict[str, Any]:
    from app.modules.metrics.selectors.panel import (
        ad_chips,
        campaign_chips,
        group_chips,
    )

    listed = campaign_list(db, owner=owner, ask=ask)
    out: dict[str, list[dict[str, Any]]] = {"campaigns": [], "adsets": [], "ads": []}
    for row in listed["campaigns"]:
        campaign = selectors.campaign_detail(
            db, owner=owner, campaign_id=uuid.UUID(row["id"])
        )
        if campaign is None:
            continue
        selectors.with_controls(db, owner=owner, campaign=campaign)
        chosen, _ = figures_range(db, owner=owner, account=campaign.ad_account, ask=ask)
        at_campaign = campaign.daily_budget_minor is not None
        budget_at = "campaign" if at_campaign else "adset"
        base = {
            "campaign_id": row["id"],
            "campaign_external_id": row["external_id"],
            "kind": row["kind"],
            "network": row["network"],
        }
        own = next(
            iter(
                campaign_chips(
                    db,
                    owner=owner,
                    campaigns=[campaign],
                    date_range=chosen,
                    account=campaign.ad_account,
                )
            ),
            None,
        )
        out["campaigns"].append(
            base
            | {
                "level": "campaign",
                "id": row["external_id"],
                "adset_external_id": None,
                "name": row["name"],
                "status": row["status"],
                "budget": row["daily_budget"] if at_campaign else None,
                "budget_at": budget_at,
                "results": row["metrics"]["results"] if row["metrics"] else 0,
                "unit_cost": row["metrics"]["unit_cost"] if row["metrics"] else None,
                "spent": row["metrics"]["spent"] if row["metrics"] else None,
                **_reach(own),
                "controls": row["controls"],
                "problem": row["problem"],
            }
        )
        groups = list(campaign.adsets)
        by_group = {
            found.campaign_id: found
            for found in group_chips(
                db,
                owner=owner,
                adsets=groups,
                date_range=chosen,
                tzinfo=campaign.ad_account.tzinfo(),
            )
        }
        by_ad = {
            found.ad_id: found
            for found in ad_chips(db, owner=owner, campaign=campaign, date_range=chosen)
        }
        ads = selectors.with_content(
            db, owner=owner, ads=[ad for group in groups for ad in group.ads]
        )
        for group in groups:
            currency = group.currency or campaign.ad_account.currency
            chips = by_group.get(group.external_id)
            figures = figures_of(chips, currency=currency, provider=group.provider)
            shared = base | {
                "adset_external_id": group.external_id,
                "budget_at": budget_at,
            }
            out["adsets"].append(
                shared
                | {
                    "level": "adset",
                    "id": group.external_id,
                    "name": group.name,
                    "status": status_of(group, learning=bool(group.is_learning)),
                    "budget": money(
                        group.daily_budget_minor, currency, provider=group.provider
                    ),
                    "results": figures["results"] if figures else 0,
                    "unit_cost": figures["unit_cost"] if figures else None,
                    "spent": figures["spent"] if figures else None,
                    **_reach(chips),
                    "controls": controls_of(
                        getattr(group, "controls", None),
                        early_hours=getattr(group, "early_hours", 0),
                    ),
                    "problem": getattr(group, "issue_summary", "") or None,
                }
            )
            for ad in (row for row in ads if row.adset_id == group.id):
                chips = by_ad.get(ad.external_id)
                figures = figures_of(chips, currency=currency, provider=ad.provider)
                content = getattr(ad, "content", None)
                out["ads"].append(
                    shared
                    | {
                        "level": "ad",
                        "id": ad.external_id,
                        "name": getattr(content, "headline", "") or ad.name,
                        "status": status_of(ad),
                        "budget": None,
                        "results": figures["results"] if figures else 0,
                        "unit_cost": figures["unit_cost"] if figures else None,
                        "spent": figures["spent"] if figures else None,
                        **_reach(chips),
                        "controls": controls_of(
                            getattr(ad, "controls", None),
                            early_hours=getattr(ad, "early_hours", 0),
                        ),
                        "problem": getattr(ad, "issue_summary", "") or None,
                    }
                )
    return out


__all__ = ["manager"]
