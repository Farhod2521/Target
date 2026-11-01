"""The boundaries one day's reports are drawn within: the pairs, their money,
and the causes the night's diagnosis wrote. The figures themselves are read in
:mod:`app.modules.chat.selectors.day_figures`."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from typing import Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.money import format_minor
from app.modules.accounts.models import User
from app.modules.ads.models import AdSet, Campaign
from app.modules.agent.causes import cause_label, cause_line
from app.modules.agent.constants import DiagnosisCause
from app.modules.agent.models import AdSetDiagnosis
from app.modules.agent.selectors.policy import diagnoses


@dataclass(frozen=True, slots=True)
class DayPairs:
    """``{ad group: pair key}``, and every chosen pair's page and account.

    ``names``, ``accounts``, ``pages`` and ``account_ids`` hold every chosen
    pair, whether it advertised or not: the page's name, the account's name,
    the page's id and the account's. A group whose page was guessed is filed
    under the pair the screens draw it on: the cabinet counts it there too.
    """

    of: dict[str, str] = field(default_factory=dict)
    names: dict[str, str] = field(default_factory=dict)
    accounts: dict[str, str] = field(default_factory=dict)
    pages: dict[str, str] = field(default_factory=dict)
    account_ids: dict[str, str] = field(default_factory=dict)


def day_pairs(db: Session, *, owner: User, pages: Mapping[str, str]) -> DayPairs:
    """Every ad group of a chosen pair, filed under it."""
    from app.modules.ads.selectors import page_scope
    from app.modules.integrations.selectors import enabled_pages, stored_pairs

    scope = page_scope(db, owner=owner)
    chosen = {
        (pair.page.external_id, pair.account.external_id): pair
        for pair in stored_pairs(db, owner=owner, pages=enabled_pages(db, owner=owner))
    }
    of: dict[str, str] = {}
    for adset_id, page in scope.page_of.items():
        account = scope.account_of.get(adset_id, "")
        pair = chosen.get((page, account))
        if pair is not None:
            of[adset_id] = page if pair.first else f"{page}:{account}"
    names: dict[str, str] = {}
    accounts: dict[str, str] = {}
    owners: dict[str, str] = {}
    account_ids: dict[str, str] = {}
    for (page, external_id), pair in chosen.items():
        key = page if pair.first else f"{page}:{external_id}"
        names[key] = pages.get(page, "") or pair.page.name or page
        accounts[key] = pair.account.name or external_id
        owners[key] = page
        account_ids[key] = external_id
    return DayPairs(
        of=of, names=names, accounts=accounts, pages=owners, account_ids=account_ids
    )


@dataclass(frozen=True, slots=True)
class PageMoney:
    """One page's currency, and the campaigns that are not in it."""

    currency: str
    apart: frozenset[str] = frozenset()


def money_by_pair(db: Session, *, owner: User, fallback: str) -> dict[str, PageMoney]:
    """``{pair key: what its figures are denominated in}``."""
    from app.modules.metrics.selectors.scope import pages_campaigns

    return {
        found.key: PageMoney(currency=found.currency or fallback, apart=found.foreign)
        for found in pages_campaigns(db, owner=owner)
        if found.page is not None
    }


def apart_spend(
    db: Session, *, owner: User, money: PageMoney, since: date, until: date
) -> tuple[str, ...]:
    """What this page spent in a currency its report is not in."""
    from app.modules.metrics.selectors.lead_sources import other_currency_spend

    return tuple(
        format_minor(amount_minor=amount, currency=code)
        for code, amount in other_currency_spend(
            db, owner=owner, ids=money.apart, since=since, until=until
        )
    )


QUIET: Final = (DiagnosisCause.NO_PROBLEM, DiagnosisCause.TOO_EARLY)


@dataclass(frozen=True, slots=True)
class DayCause:
    """One campaign's cause: the code, and the two lines a reader gets."""

    cause: str
    label: str
    line: str


def campaign_causes(
    db: Session, *, owner: User, currency: str, day: date
) -> dict[str, DayCause]:
    """``{campaign id: the cause to print}``, for the day being reported."""
    rows = list(
        db.scalars(
            diagnoses(owner).where(
                AdSetDiagnosis.until == day, AdSetDiagnosis.cause.not_in(QUIET)
            )
        )
    )
    if not rows:
        return {}
    campaigns = dict(
        db.execute(
            select(AdSet.external_id, Campaign.external_id)
            .join(Campaign, Campaign.id == AdSet.campaign_id)
            .where(
                AdSet.owner_id == owner.id,
                AdSet.external_id.in_([row.adset_external_id for row in rows]),
            )
        ).all()
    )
    found: dict[str, DayCause] = {}
    for row in sorted(rows, key=_spent, reverse=True):
        key = campaigns.get(row.adset_external_id) or ""
        label = str(cause_label(row.cause))
        if not key or not label or key in found:
            continue
        found[key] = DayCause(
            cause=row.cause,
            label=label,
            line=cause_line(
                {"cause": row.cause, "signals": row.signals, "evidence": row.evidence},
                currency=currency,
            ),
        )
    return found


def _spent(row: AdSetDiagnosis) -> int:
    value = (row.evidence or {}).get("spend_minor")
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return value


__all__ = [
    "DayCause",
    "DayPairs",
    "PageMoney",
    "apart_spend",
    "campaign_causes",
    "day_pairs",
    "money_by_pair",
]
