"""The sales figures as every screen is handed them.

One shape, so the CRM page, the dashboard and the expert board cannot
disagree: each metric is a cell - ``{"value": ..., "missing": ...}`` - with
the value, or the reason there is none. Money is in minor units of
``currency``, a percent and a ratio are numbers to two places, a time is
whole minutes.
"""

from datetime import date, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.ads.contract.expert import cell
from app.modules.crm.selectors.process import StageProcess
from app.modules.crm.selectors.stats import Stats
from core.metrics.catalogue.spec import MISSING_WORDS
from core.metrics.sales import SALES, Completeness, SalesFigures, answers


def metrics_out() -> list[dict[str, Any]]:
    """What each key is called and how its value reads."""
    return [
        {
            "key": metric.key,
            "label": metric.label,
            "hint": metric.hint,
            "unit": metric.unit,
            "lower_is_better": metric.lower_is_better,
        }
        for metric in SALES
    ]


def cells(figures: SalesFigures) -> dict[str, dict[str, Any]]:
    return {key: cell(answer) for key, answer in answers(figures).items()}


def completeness_out(found: Completeness) -> dict[str, Any]:
    return {
        "level": found.level,
        "handled_pct": found.handled_pct,
        "closed_pct": found.closed_pct,
        "open": found.open,
        "note": found.note,
    }


def summary_out(found: Stats) -> dict[str, Any]:
    """The period as a whole: what the dashboard and the expert board show."""
    total = found.totals
    return {
        "state": found.state,
        "currency": found.currency,
        "range": {
            "since": found.range.since.isoformat(),
            "until": found.range.until.isoformat(),
            "days": found.range.days,
        },
        "metrics": metrics_out(),
        "missing_words": MISSING_WORDS,
        "totals": cells(total),
        # The same number of days just before, counted the same way.
        "earlier": cells(found.earlier) if found.earlier is not None else None,
        # Customers typed onto the board by hand: their sales are real money
        # and no advert's, so they stand apart and are in no cell above.
        "direct": cells(found.direct),
        "completeness": completeness_out(found.completeness),
        "left_out": {
            # Sales in another currency on a day no rate is held for.
            "sales": total.unpriced,
            # Days whose spend no rate could price.
            "spend_days": total.spend_unpriced_days,
        },
    }


def pair_summary(
    db: Session, *, user: User, since: date, until: date, now: datetime
) -> dict[str, Any] | None:
    """The sales figures of the pair on screen for a range of days, for a
    screen outside the CRM. Nothing for a reader with no pair, or one who is
    not the owner: a manager is not shown what the advertising cost."""
    from app.modules.crm.selectors import viewer_for
    from app.modules.crm.selectors.stats import stats

    viewer = viewer_for(db, user=user)
    if viewer.pair is None or not viewer.is_owner:
        return None
    found = stats(
        db,
        viewer=viewer,
        since=since.isoformat(),
        until=until.isoformat(),
        now=now,
    )
    return summary_out(found)


def breakdown_out(db: Session, *, owner: User, found: Stats) -> dict[str, Any]:
    """The period cut by campaign, advert, manager and day."""
    from app.modules.ads.selectors import ad_labels
    from app.modules.ads.selectors.labels import campaign_names

    ads = ad_labels(db, owner=owner, external_ids=[key for key, _ in found.ads])
    campaigns = campaign_names(
        db, owner=owner, external_ids=[key for key, _ in found.campaigns]
    )
    return {
        "campaigns": [
            {"id": key, "name": campaigns.get(key, key), "cells": cells(tally)}
            for key, tally in found.campaigns
        ],
        "ads": [
            {
                "id": key,
                "name": ads[key].title if key in ads else key,
                "cells": cells(tally),
            }
            for key, tally in found.ads
        ],
        "managers": [
            {
                "user": {
                    "id": str(user.id),
                    "full_name": user.full_name,
                    "email": user.email,
                },
                "cells": cells(tally),
                "late": late,
            }
            for user, tally, late in found.managers
        ],
        "daily": [
            {"day": day.isoformat(), "cells": cells(tally)}
            for day, tally in zip(found.days, found.daily, strict=True)
        ],
    }


def process_out(rows: list[StageProcess]) -> list[dict[str, Any]]:
    """Each column of the board: the cards in it now and how long they stay."""
    return [
        {
            "stage": {
                "id": str(row.stage.id),
                "name": row.stage.name,
                "kind": row.stage.kind,
                "color": row.stage.color,
            },
            "now": row.now,
            "late": row.late,
            "waiting_min": row.waiting_min,
            "longest_wait_min": row.longest_wait_min,
            "stay_min": row.stay_min,
            "stays": len(row.stays),
            "approximate": row.approximate,
        }
        for row in rows
    ]


__all__ = [
    "breakdown_out",
    "cells",
    "completeness_out",
    "metrics_out",
    "pair_summary",
    "process_out",
    "summary_out",
]
