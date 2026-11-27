"""The pairs a daily report says nothing of: nothing of theirs can run now.

A pair whose ad account the network stopped, or whose every advert is
switched off, has no day to report: a message of yesterday's figures reads as
"your adverts are running", and the owner was already told what stopped them.
Such a pair leaves the day's message altogether - its money with it - and a
day with no other pair is not sent.

Judged as things stand when the message is written, not as they stood on the
day it is about: the message is read now.

**Off needs proof.** A pair nothing was ever mirrored of is left in: no row
says its adverts are off.
"""

from collections import defaultdict
from dataclasses import replace
from typing import Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.ads.constants import NOT_LIVE, Delivery
from app.modules.ads.models import Ad, AdSet
from app.modules.chat.selectors.day_tables import DayPairs, day_pairs
from app.modules.integrations.models import AdAccount
from app.modules.integrations.selectors.standing import stopped_kind
from core.chat.day_report import DayBook

# What an advert shows nobody under: switched off here or above, finished, or
# refused by the network's review.
DARK: Final[frozenset[str]] = NOT_LIVE | frozenset({Delivery.REJECTED})


def dark_pairs(db: Session, *, owner: User, pairs: DayPairs) -> frozenset[str]:
    """The keys of the pairs whose account is stopped or whose adverts are
    all off."""
    stopped = _stopped_accounts(db, owner=owner)
    groups = _groups_by_pair(pairs)
    lit = _lit_groups(db, owner=owner, ids=frozenset(pairs.of))
    dark = set()
    for pair in pairs.names:
        if pairs.account_ids.get(pair, "") in stopped:
            dark.add(pair)
            continue
        own = groups.get(pair)
        if own and not own & lit:
            dark.add(pair)
    return frozenset(dark)


def without_dark(db: Session, *, owner: User, book: DayBook) -> DayBook:
    """The day's book less its dark pairs, totals counted again. A week keeps
    every pair: it is an account of what the week cost."""
    from app.modules.chat.selectors.daily import _totals

    if book.weekly or not book.reports:
        return book
    dark = dark_pairs(db, owner=owner, pairs=day_pairs(db, owner=owner, pages={}))
    kept = tuple(report for report in book.reports if report.pair not in dark)
    if len(kept) == len(book.reports):
        return book
    return replace(
        book,
        reports=kept,
        totals=_totals(kept),
        dark=tuple(report.title for report in book.reports if report.pair in dark),
    )


def _stopped_accounts(db: Session, *, owner: User) -> frozenset[str]:
    accounts = db.scalars(select(AdAccount).where(AdAccount.owner_id == owner.id))
    return frozenset(
        account.external_id for account in accounts if stopped_kind(account) is not None
    )


def _groups_by_pair(pairs: DayPairs) -> dict[str, set[str]]:
    groups: dict[str, set[str]] = defaultdict(set)
    for adset_id, pair in pairs.of.items():
        groups[pair].add(adset_id)
    return groups


def _lit_groups(db: Session, *, owner: User, ids: frozenset[str]) -> frozenset[str]:
    """The ad groups something may still be shown from: the group is on, and
    so is at least one of its adverts - or none of them was mirrored."""
    if not ids:
        return frozenset()
    on = {
        row.id: row.external_id
        for row in db.execute(
            select(AdSet.id, AdSet.external_id).where(
                AdSet.owner_id == owner.id,
                AdSet.external_id.in_(ids),
                AdSet.delivery.notin_(DARK),
            )
        )
    }
    if not on:
        return frozenset()
    adverts: dict[object, bool] = {}
    for adset_id, delivery in db.execute(
        select(Ad.adset_id, Ad.delivery).where(Ad.adset_id.in_(on))
    ):
        adverts[adset_id] = adverts.get(adset_id, False) or str(delivery) not in DARK
    return frozenset(
        external_id for pk, external_id in on.items() if adverts.get(pk, True)
    )


__all__ = ["DARK", "dark_pairs", "without_dark"]
