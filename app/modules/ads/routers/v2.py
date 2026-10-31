"""Version 2 of the campaign screens' figures; everything else stays in version 1."""

import uuid
from datetime import date
from typing import Any

from fastapi import APIRouter, Query

from app.api.deps import CurrentUser, Db
from app.modules.ads import selectors
from app.modules.ads.contract.figures_v2 import (
    campaign_list_v2,
    detail_v2,
    manager_v2,
    tree_range,
    tree_results_v2,
)
from app.modules.ads.contract.listing import ListAsk
from app.modules.ads.contract.shapes import CampaignTree
from app.modules.ads.contract.shapes_v2 import (
    CampaignDetailV2,
    CampaignListV2,
    ManagerDataV2,
)
from app.modules.ads.contract.tree import campaign_tree
from app.modules.ads.routers import _detail, _groups, _pick
from app.modules.metrics.ranges import Range

router = APIRouter(prefix="/campaigns", tags=["campaigns v2"])

PERIODS = ("today", "7d", "30d", "90d", "custom")


def _ask(
    period: str | None,
    status: str | None,
    source: str | None,
    network: str,
    since: date | None,
    until: date | None,
    started: str = "",
) -> ListAsk:
    return ListAsk(
        period=_pick(period, PERIODS, "7d"),
        status=_pick(status, ("running", "paused", "all"), "all"),
        source=_pick(source, ("all", "here", "network", "other_account"), "all"),
        network=network or "all",
        since=since,
        until=until,
        started=started,
    )


def _ad_chips(
    db: Db, user: CurrentUser, campaign: Any, chosen: Range
) -> dict[str, Any]:
    from app.modules.metrics.selectors.panel import ad_chips

    return {
        row.ad_id: row
        for row in ad_chips(db, owner=user, campaign=campaign, date_range=chosen)
    }


@router.get("", response_model=CampaignListV2)
def campaign_list(
    db: Db,
    user: CurrentUser,
    period: str | None = Query(None),
    status: str | None = Query(None),
    source: str | None = Query(None),
    network: str = Query("all"),
    since: date | None = Query(None),
    until: date | None = Query(None),
    started: str = Query(""),
) -> dict[str, Any]:
    """The list, with an event campaign's result and a kind that matches it."""
    ask = _ask(period, status, source, network, since, until, started)
    return campaign_list_v2(db, owner=user, ask=ask)


@router.get("/manager", response_model=ManagerDataV2)
def campaign_manager(
    db: Db,
    user: CurrentUser,
    period: str | None = Query(None),
    status: str | None = Query(None),
    source: str | None = Query(None),
    network: str = Query("all"),
    since: date | None = Query(None),
    until: date | None = Query(None),
) -> dict[str, Any]:
    """Every level with link clicks, and `reach: null` where it was not counted."""
    ask = _ask(period, status, source, network, since, until)
    return manager_v2(db, owner=user, ask=ask)


@router.get("/{campaign_id}/tree", response_model=CampaignTree)
def campaign_tree_v2(
    campaign_id: uuid.UUID,
    db: Db,
    user: CurrentUser,
    period: str | None = Query(None),
    since: date | None = Query(None),
    until: date | None = Query(None),
) -> dict[str, Any]:
    """Groups and adverts with the figures of the period the list shows."""
    campaign = _detail(db, user, campaign_id)
    selectors.with_controls(db, owner=user, campaign=campaign)
    ask = _ask(period, None, None, "all", since, until)
    chosen = tree_range(db, owner=user, campaign=campaign, ask=ask)
    tree = campaign_tree(
        _groups(db, user, campaign), chips=_ad_chips(db, user, campaign, chosen)
    )
    return tree_results_v2(
        db, owner=user, campaign=campaign, tree=tree, date_range=chosen
    )


@router.get("/{campaign_id}", response_model=CampaignDetailV2)
def campaign_detail(
    campaign_id: uuid.UUID,
    db: Db,
    user: CurrentUser,
    period: str | None = Query(None),
    since: date | None = Query(None),
    until: date | None = Query(None),
) -> dict[str, Any]:
    """One campaign's page; its adverts' figures follow the period asked."""
    from app.modules.ads.contract.detail import campaign_detail as detail

    campaign = _detail(db, user, campaign_id)
    selectors.with_controls(db, owner=user, campaign=campaign)
    selectors.with_tree_badge(campaign=campaign)
    campaign.settings = selectors.row_settings(campaign=campaign)
    ask = _ask(period, None, None, "all", since, until)
    chosen = tree_range(db, owner=user, campaign=campaign, ask=ask)
    answer = detail(
        db,
        owner=user,
        campaign=campaign,
        groups=_groups(db, user, campaign),
        history=selectors.campaign_history(db, owner=user, campaign=campaign),
        chips=_ad_chips(db, user, campaign, chosen),
    )
    return detail_v2(
        db, owner=user, campaign=campaign, answer=answer, date_range=chosen
    )


__all__ = ["router"]
