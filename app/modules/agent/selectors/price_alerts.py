"""The price rises waiting for an answer, and the frequency level said with each."""

from collections.abc import Collection
from datetime import timedelta
from typing import Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.agent.models import FrequencyAlert, PriceAlert

# TZ 6.5.6: a frequency level raised the same night as the price rise of
# the same group is said in one message with it.
SAME_NIGHT: Final = timedelta(hours=24)


def price_alerts_to_show(
    db: Session, *, owner: User, hidden_adsets: Collection[str] = ()
) -> list[PriceAlert]:
    """Open price rises with no answer yet, dearest first."""
    a = PriceAlert
    rows = db.scalars(
        select(a).where(
            a.owner_id == owner.id,
            a.closed_at.is_(None),
            a.answer == "",
            a.adset_external_id.not_in(list(hidden_adsets)),
        )
    )
    return sorted(rows, key=lambda row: (-row.times, row.created_at))


def merged_frequency(db: Session, *, row: PriceAlert) -> FrequencyAlert | None:
    """The same group's frequency level raised the same night, still open."""
    f = FrequencyAlert
    return db.scalar(
        select(f)
        .where(
            f.owner_id == row.owner_id,
            f.adset_external_id == row.adset_external_id,
            f.closed_at.is_(None),
            f.eased_at.is_(None),
            f.created_at >= row.created_at - SAME_NIGHT,
            f.created_at <= row.created_at + SAME_NIGHT,
        )
        .order_by(f.created_at.desc())
        .limit(1)
    )


def merged_frequencies(
    db: Session, *, rows: list[PriceAlert]
) -> dict[str, FrequencyAlert]:
    """``{group: its frequency level said with its price rise}``."""
    found: dict[str, FrequencyAlert] = {}
    for row in rows:
        level = merged_frequency(db, row=row)
        if level is not None:
            found[row.adset_external_id] = level
    return found


def price_creative_target(db: Session, *, owner: User, row: PriceAlert) -> str:
    """The advert whose copy window opens: the one that rose, or a delivering
    one of the group (TZ 2.3)."""
    from app.modules.agent.selectors.frequency import creative_target

    return row.ad_external_id or creative_target(
        db, owner=owner, adset_id=row.adset_external_id
    )


__all__ = [
    "merged_frequencies",
    "merged_frequency",
    "price_alerts_to_show",
    "price_creative_target",
]
