"""The expert dashboard of the page on screen, every number the catalogue's.

Headline metrics against the range before, the days, the funnel, each goal
apart, the campaigns against their goal, the adverts past their norms, the
audience cuts and what the CRM told Meta.
"""

from collections import defaultdict
from dataclasses import asdict
from datetime import timedelta
from typing import Any, Final

from fastapi.encoders import jsonable_encoder
from metaads.insights import ATTRIBUTION_ASKED
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.ads.contract.expert import cell
from app.modules.metrics.constants import EVERY_ACCOUNT, RANGE_MAX_DAYS, MetricLevel
from app.modules.metrics.ranges import Range
from app.modules.metrics.selectors.dashboard import cabinet_today, page_segments
from app.modules.metrics.selectors.expert import (
    differing_attribution,
    figures_by,
    figures_by_day,
    last_read_on,
    outcome_of_adsets,
    whole_account_people,
)
from app.modules.metrics.selectors.lead_quality import lead_quality
from app.modules.metrics.selectors.scope import PageCampaigns
from core.metrics import movement
from core.metrics.catalogue import BY_KEY, Answer, Figures, Setting, add_up, compute
from core.metrics.catalogue.board import TROUBLED_ADS, funnel, ranked, troubles
from core.metrics.outcomes import Outcome

HEADLINE: Final[tuple[str, ...]] = (
    "spend",
    "results",
    "cost_per_result",
    "cpql",
    "roas",
    "cpm",
    "ctr",
    "cpc",
    "frequency",
    "reach",
)
# What the chart may draw: the figures a single day adds up to.
CHARTED: Final[tuple[str, ...]] = (
    "spend",
    "results",
    "cost_per_result",
    "impressions",
    "cpm",
    "link_clicks",
    "ctr",
    "cpc",
    "leads",
    "qualified",
    "cpql",
    "purchases_site",
    "roas",
)
BY_GOAL: Final[tuple[str, ...]] = ("spend", "results", "cost_per_result", "roas")


def _setting(outcomes: set[Outcome], level: str = MetricLevel.CAMPAIGN) -> Setting:
    return Setting(
        level=level,  # type: ignore[arg-type]
        outcome=next(iter(outcomes)) if len(outcomes) == 1 else "lead",
        mixed=len(outcomes) > 1,
    )


def _headline(now: Figures, before: Figures | None, setting: Setting) -> list[Any]:
    found = []
    for key in HEADLINE:
        metric = BY_KEY[key]
        answer = compute(key, now, setting)
        was = compute(key, before, setting) if before is not None else Answer()
        moved = movement(
            now=_number(answer),
            before=_number(was),
            lower_is_better=metric.lower_is_better,
        )
        found.append(
            {
                "key": key,
                "now": cell(answer),
                "before": cell(was),
                "change": asdict(moved),
            }
        )
    return found


def _number(answer: Answer) -> float | None:
    if not answer.known or isinstance(answer.value, str):
        return None
    return float(answer.value)  # type: ignore[arg-type]


def expert_board(
    db: Session, *, owner: User, page: PageCampaigns, chosen: Range
) -> dict[str, Any]:
    from app.modules.ads.selectors import campaigns_for

    campaigns = (
        campaigns_for(db, owner=owner, external_ids=page.ids) if page.ids else []
    )
    accounts = list(
        {campaign.ad_account_id: campaign.ad_account for campaign in campaigns}.values()
    ) or list(page.accounts)
    comparable = chosen.days * 2 <= RANGE_MAX_DAYS
    before = (
        Range(
            since=chosen.since - timedelta(days=chosen.days),
            until=chosen.since - timedelta(days=1),
            key="before",
        )
        if comparable
        else None
    )
    rows: list[tuple[str, Figures, Setting]] = []
    earlier: list[Figures] = []
    ads: list[tuple[Any, Any, Figures, Setting]] = []
    currencies: set[str] = set()
    whole: list[Any] = []
    whole_before: list[Any] = []
    by_account: dict[Any, list[Any]] = defaultdict(list)
    for campaign in campaigns:
        by_account[campaign.ad_account].append(campaign)
    for account, members in by_account.items():
        currencies.add(account.currency)
        ids = [campaign.external_id for campaign in members]
        now = figures_by(
            db,
            owner=owner,
            account=account,
            level=MetricLevel.CAMPAIGN,
            ids=ids,
            date_range=chosen,
        )
        was = (
            figures_by(
                db,
                owner=owner,
                account=account,
                level=MetricLevel.CAMPAIGN,
                ids=ids,
                date_range=before,
            )
            if before is not None
            else {}
        )
        whole.append(
            whole_account_people(
                db,
                owner=owner,
                account=account,
                level=MetricLevel.CAMPAIGN,
                ids=ids,
                date_range=chosen,
            )
        )
        if before is not None:
            whole_before.append(
                whole_account_people(
                    db,
                    owner=owner,
                    account=account,
                    level=MetricLevel.CAMPAIGN,
                    ids=ids,
                    date_range=before,
                )
            )
        ad_rows = {
            ad.external_id: (campaign, ad, group)
            for campaign in members
            for group in campaign.adsets
            for ad in group.ads
        }
        ad_figures = figures_by(
            db,
            owner=owner,
            account=account,
            level=MetricLevel.AD,
            ids=list(ad_rows),
            date_range=chosen,
        )
        for campaign in members:
            outcome = outcome_of_adsets(campaign.adsets)
            setting = Setting(level="campaign", outcome=outcome)
            rows.append(
                (
                    campaign.external_id,
                    now.get(campaign.external_id, Figures()),
                    setting,
                )
            )
            if campaign.external_id in was:
                earlier.append(was[campaign.external_id])
        for external_id, (campaign, ad, group) in ad_rows.items():
            ads.append(
                (
                    campaign,
                    ad,
                    ad_figures.get(external_id, Figures()),
                    Setting(level="ad", outcome=outcome_of_adsets([group])),
                )
            )
    outcomes = {setting.outcome for _, _, setting in rows}
    setting = _setting(outcomes)
    # One account's alone: two accounts may reach the same person.
    people = whole[0] if len(whole) == 1 else None
    total = add_up(
        [figures for _, figures, _ in rows],
        currencies=len(currencies),
        reach=people.reach if people else None,
        unique_link_clicks=people.unique_link_clicks if people else None,
    )
    was_people = whole_before[0] if len(whole_before) == 1 else None
    previous = (
        add_up(
            earlier,
            currencies=len(currencies),
            reach=was_people.reach if was_people else None,
            unique_link_clicks=was_people.unique_link_clicks if was_people else None,
        )
        if before is not None
        else None
    )
    names = {campaign.external_id: campaign.name for campaign in campaigns}
    goals = _goals(rows, currencies=len(currencies))
    best, worst = ranked(
        rows, totals={goal: figures for goal, figures in goals.items()}
    )
    today = cabinet_today(db, owner=owner, account=page.home)
    segments, _ = (
        page_segments(
            db,
            owner=owner,
            today=today,
            currency=page.currency,
            rows_of=EVERY_ACCOUNT,
            scope=page.condition,
            account=page.home,
            campaign_ids=page.ids,
        )
        if page.home is not None
        else ((), {})
    )
    days = figures_by_day(
        db, owner=owner, accounts=accounts, campaign_ids=page.ids, date_range=chosen
    )
    return {
        "range": {"since": chosen.since, "until": chosen.until, "days": chosen.days},
        "before": (
            {"since": before.since, "until": before.until}
            if before is not None
            else None
        ),
        "currency": next(iter(currencies))
        if len(currencies) == 1
        else (page.currency or None),
        "synced_at": last_read_on(db, accounts=accounts),
        "attribution": {
            "asked": ATTRIBUTION_ASKED,
            "differs": differing_attribution(
                db, accounts=accounts, since=chosen.since, until=chosen.until
            ),
        },
        "headline": _headline(total, previous, setting),
        "series": {
            "keys": list(CHARTED),
            "days": [
                {
                    "day": day,
                    "cells": {
                        key: cell(compute(key, figures, setting)) for key in CHARTED
                    },
                }
                for day, figures in sorted(days.items())
            ],
        },
        "funnel": [
            {
                "key": step.key,
                "label": step.label,
                "count": cell(step.count),
                "rate": cell(step.rate) if step.rate is not None else None,
            }
            for step in funnel(total, setting)
        ],
        "goals": [
            {
                "outcome": goal,
                "campaigns": sum(1 for _, _, s in rows if s.outcome == goal),
                "cells": {
                    key: cell(
                        compute(key, figures, Setting(level="campaign", outcome=goal))
                    )
                    for key in BY_GOAL
                },
            }
            for goal, figures in goals.items()
        ],
        "best": [_ranked(row, names) for row in best],
        "worst": [_ranked(row, names) for row in worst],
        "troubled": _troubled(ads),
        "segments": jsonable_encoder(segments),
        "lead_quality": jsonable_encoder(
            lead_quality(
                db, owner=owner, page=page, since=chosen.since, until=chosen.until
            )
        ),
    }


def _goals(
    rows: list[tuple[str, Figures, Setting]], *, currencies: int
) -> dict[Outcome, Figures]:
    grouped: dict[Outcome, list[Figures]] = defaultdict(list)
    for _, figures, setting in rows:
        grouped[setting.outcome].append(figures)
    return {
        goal: add_up(members, currencies=currencies)
        for goal, members in grouped.items()
    }


def _ranked(row: Any, names: dict[str, str]) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": names.get(row.id, row.id),
        "outcome": row.outcome,
        "cost": cell(row.cost),
        "index": row.index,
    }


def _troubled(ads: list[tuple[Any, Any, Figures, Setting]]) -> list[dict[str, Any]]:
    found = []
    for campaign, ad, figures, setting in sorted(
        ads, key=lambda one: -int(one[2].spend_minor)
    ):
        problems = troubles(figures, setting)
        if not problems:
            continue
        found.append(
            {
                "id": ad.external_id,
                "name": ad.name,
                "campaign": campaign.name,
                "spend": cell(compute("spend", figures, setting)),
                "problems": [
                    {
                        "key": one.key,
                        "label": BY_KEY[one.key].label,
                        "value": float(one.value)
                        if not isinstance(one.value, str)
                        else one.value,
                        "norm": one.norm,
                    }
                    for one in problems
                ],
            }
        )
        if len(found) == TROUBLED_ADS:
            break
    return found


__all__ = ["CHARTED", "HEADLINE", "expert_board"]
