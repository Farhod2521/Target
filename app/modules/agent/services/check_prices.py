"""Tonight's price rises (TZ 1): raise new ones, close the eased and the gone."""

from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.agent.constants import PriceAnswer
from app.modules.agent.models import PriceAlert
from app.modules.agent.selectors.frequency import newest_ads
from app.modules.agent.selectors.price_rise import (
    Advert,
    Judged,
    cost_after,
    judged_groups,
)
from app.modules.audit.constants import EventName
from app.modules.audit.services import emit
from core.agent.price_rise import Figures, Usual, causes, eased, risen, times

# TZ 1.6: one message a group in 72 hours; «Kuzataman» keeps it quiet as long.
QUIET: Final = timedelta(hours=72)
AFTER: Final = timedelta(days=7)


def check_prices(db: Session, *, owner: User, now: datetime) -> list[PriceAlert]:
    """Write tonight's price rises. Returns the rows raised tonight. Commits."""
    judged = {item.adset_id: item for item in judged_groups(db, owner=owner, now=now)}
    open_rows = {
        row.adset_external_id: row
        for row in db.scalars(
            select(PriceAlert).where(
                PriceAlert.owner_id == owner.id, PriceAlert.closed_at.is_(None)
            )
        )
    }
    newest = newest_ads(db, owner=owner, adset_ids=list(open_rows))
    raised: list[PriceAlert] = []
    for adset_id, row in open_rows.items():
        added = newest.get(adset_id)
        if added is not None and added > row.created_at:
            # TZ 2.3: a creative added starts the group again.
            if not row.answer:
                row.answer, row.answered_at = PriceAnswer.CREATIVE_ADDED, now
            row.closed_at = now
        elif adset_id not in judged:
            # Stopped, or delivering nothing: nothing left to warn about.
            row.closed_at = now
    for adset_id, found in judged.items():
        current = open_rows.get(adset_id)
        if current is not None and current.closed_at is not None:
            continue
        made = _one(db, owner=owner, found=found, row=current, now=now)
        if made is not None:
            raised.append(made)
    db.commit()
    _price_after(db, owner=owner, now=now)
    return raised


def _one(
    db: Session, *, owner: User, found: Judged, row: PriceAlert | None, now: datetime
) -> PriceAlert | None:
    """One group: close it, raise it, or leave it."""
    usual = found.usual
    if usual is None or found.excepted:
        return None
    if row is not None:
        if eased(_figures_of(found, row.ad_external_id), usual):
            row.closed_at = now
            return None
        quiet_until = max(
            row.created_at + QUIET,
            (row.answered_at + QUIET)
            if row.answer == PriceAnswer.WATCHING and row.answered_at
            else row.created_at,
        )
        if now < quiet_until:
            return None
    target = _target(found, usual)
    if target is None:
        return None
    if row is not None:
        row.closed_at = now
        db.flush()
    advert, figures = target
    made = PriceAlert(
        owner_id=owner.id,
        provider=found.account.provider,
        ad_account_id=found.account.id,
        adset_external_id=found.adset_id,
        ad_external_id=advert.ad_id if advert is not None else "",
        name=(advert.name if advert is not None else "") or found.name,
        result_kind=found.key,
        currency=found.account.currency,
        spend_minor=figures.spend_minor,
        results=figures.results,
        cost_minor=round(figures.cost) if figures.cost is not None else None,
        cost_usual_minor=round(usual.cost),
        times=round(times(figures, usual) * 100),
        baseline_source=usual.source,
        baseline_adverts=usual.adverts,
        causes=_causes(figures, usual, currency=found.account.currency),
    )
    db.add(made)
    db.flush()
    emit(
        db,
        owner_id=owner.id,
        name=EventName.PRICE_ALERTED,
        aggregate_type="adset",
        aggregate_id=made.adset_external_id,
        payload={"times": made.times, "source": made.baseline_source},
    )
    return made


def _target(found: Judged, usual: Usual) -> tuple[Advert | None, Figures] | None:
    """TZ 1.3: the advert that rose most - or the group, when it rose as a whole."""
    adverts = [
        advert
        for advert in found.adverts
        if advert.live and advert.now.spend_minor and risen(advert.now, usual)
    ]
    if adverts:
        worst = max(adverts, key=lambda advert: times(advert.now, usual))
        return worst, worst.now
    return (None, found.now) if risen(found.now, usual) else None


def _figures_of(found: Judged, ad_id: str) -> Figures:
    for advert in found.adverts:
        if ad_id and advert.ad_id == ad_id:
            return advert.now
    return found.now


def _causes(figures: Figures, usual: Usual, *, currency: str) -> list[dict[str, Any]]:
    """The causes as stored (TZ 1.7) - with the CTR beside one cause that is
    not the CTR, as TZ 1.5's sample shows it."""
    found = [asdict(cause) | {"currency": currency} for cause in causes(figures, usual)]
    keys = {cause["key"] for cause in found}
    ctr_now, ctr_usual = figures.value("ctr"), usual.steps.get("ctr")
    alone = len(found) == 1 and not keys & {"ranking", "ctr"}
    if alone and ctr_now is not None and ctr_usual:
        found.append(
            {
                "key": "ctr",
                "now": ctr_now,
                "usual": ctr_usual,
                "ratio": ctr_now / ctr_usual,
                "context": True,
            }
        )
    return found


def _price_after(db: Session, *, owner: User, now: datetime) -> None:
    """TZ 1.7: a week after each answer, what one result cost since."""
    a = PriceAlert
    rows = db.scalars(
        select(a).where(
            a.owner_id == owner.id,
            a.answered_at <= now - AFTER,
            a.answered_at >= now - AFTER * 4,
            a.cost_after_7d_minor.is_(None),
        )
    ).all()
    for row in rows:
        assert row.answered_at is not None
        account = row.ad_account
        since = row.answered_at.astimezone(account.tzinfo()).date()
        row.cost_after_7d_minor = cost_after(
            db,
            owner=owner,
            account=account,
            adset_id=row.adset_external_id,
            since=since,
            until=since + AFTER - timedelta(days=1),
        )
    db.commit()


__all__ = ["check_prices"]
