"""The pieces every read of leads is built from: scope, price, verdict, filters."""

import re
import uuid
from dataclasses import dataclass
from typing import Final

from sqlalchemy import (
    ColumnElement,
    Select,
    and_,
    exists,
    false,
    not_,
    or_,
    select,
    true,
)
from sqlalchemy.orm import Session, aliased

from app.modules.accounts.models import User
from app.modules.leads.constants import (
    SEARCH_DIGITS,
    UNMARKED,
    OutcomeSource,
    OutcomeStatus,
)
from app.modules.leads.models import Lead, LeadForm, LeadOutcome, RawLeadEvent

EVERYTHING: Final[ColumnElement[bool]] = true()
NOTHING: Final[ColumnElement[bool]] = false()
_NOT_DIGITS: Final = re.compile(r"\D")


def verdict_of() -> ColumnElement[str | None]:
    return (
        select(LeadOutcome.status)
        .where(LeadOutcome.lead_id == Lead.id, LeadOutcome.source == OutcomeSource.USER)
        .limit(1)
        .correlate(Lead)
        .scalar_subquery()
    )


def _unpaid(lead: type[Lead] = Lead) -> ColumnElement[bool]:
    return or_(lead.is_organic.is_(True), lead.adset_external_id == "")


def _spend_collected(lead: type[Lead] = Lead) -> ColumnElement[bool]:
    from app.modules.metrics.models import MetricsDaily

    return exists(
        select(MetricsDaily.id).where(
            MetricsDaily.owner_id == lead.owner_id,
            MetricsDaily.provider == lead.provider,
            MetricsDaily.adset_external_id == lead.adset_external_id,
        )
    )


def _in_a_collected_account(lead: type[Lead] = Lead) -> ColumnElement[bool]:
    from app.modules.ads.models import AdSet, Campaign
    from app.modules.integrations.models import AdAccount

    return exists(
        select(AdSet.id)
        .join(Campaign, Campaign.id == AdSet.campaign_id)
        .join(AdAccount, AdAccount.id == Campaign.ad_account_id)
        .where(
            AdSet.owner_id == lead.owner_id,
            AdSet.provider == lead.provider,
            AdSet.external_id == lead.adset_external_id,
            AdAccount.is_active.is_(True),
        )
    )


def priced(lead: type[Lead] = Lead) -> ColumnElement[bool]:
    return or_(_unpaid(lead), _spend_collected(lead), _in_a_collected_account(lead))


def owned(owner: User | uuid.UUID) -> ColumnElement[bool]:
    owner_id = owner if isinstance(owner, uuid.UUID) else owner.id
    return Lead.owner_id == owner_id


@dataclass(frozen=True, slots=True)
class LeadFilters:
    verdict: str = ""
    ad: str = ""
    adset: str = ""
    query: str = ""

    def __bool__(self) -> bool:
        return bool(self.verdict or self.ad or self.adset or self.query)


NO_FILTERS: Final = LeadFilters()


def narrow(query: Select[tuple[Lead]], *, filters: LeadFilters) -> Select[tuple[Lead]]:
    if filters.ad:
        query = query.where(Lead.ad_external_id == filters.ad)
    if filters.adset:
        query = query.where(Lead.adset_external_id == filters.adset)
    if filters.query:
        query = query.where(_matching(filters.query))
    if filters.verdict in {item.value for item in OutcomeStatus}:
        return query.where(verdict_of() == filters.verdict)
    if filters.verdict == UNMARKED:
        return query.where(verdict_of().is_(None))
    return query


def _matching(text: str) -> ColumnElement[bool]:
    text = text.strip()
    matched = or_(
        Lead.full_name.icontains(text),
        Lead.email.icontains(text),
        Lead.city.icontains(text),
    )
    digits = _NOT_DIGITS.sub("", text)
    if len(digits) >= SEARCH_DIGITS:
        matched = or_(matched, Lead.phone_e164.contains(digits))
    return matched


def lead_scope_of_pages(*, pages: list, sole: bool) -> ColumnElement[bool]:  # type: ignore[type-arg]
    form = aliased(LeadForm)
    raw = aliased(RawLeadEvent)
    by_form = exists(
        select(form.id).where(
            form.id == Lead.form_id, form.page_id.in_([p.id for p in pages])
        )
    )
    by_delivery = and_(
        Lead.form_id.is_(None),
        exists(
            select(raw.id).where(
                raw.id == Lead.raw_event_id,
                raw.page_external_id.in_([p.external_id for p in pages]),
            )
        ),
    )
    matched = or_(by_form, by_delivery)
    if sole:
        matched = or_(
            matched, and_(Lead.form_id.is_(None), Lead.raw_event_id.is_(None))
        )
    return matched


def attach_verdicts(db: Session, query: Select[tuple[Lead]]) -> list[Lead]:
    rows = []
    for lead, verdict in db.execute(query.add_columns(verdict_of().label("verdict"))):
        lead.verdict = verdict
        rows.append(lead)
    return rows


def leads_query(
    *,
    owner: User,
    filters: LeadFilters = NO_FILTERS,
    scope: ColumnElement[bool] = EVERYTHING,
) -> Select[tuple[Lead]]:
    query = (
        select(Lead)
        .where(owned(owner), scope)
        .order_by(Lead.submitted_at.desc(), Lead.created_at.desc())
    )
    return narrow(query, filters=filters)


__all__ = [
    "EVERYTHING",
    "NOTHING",
    "NO_FILTERS",
    "LeadFilters",
    "attach_verdicts",
    "lead_scope_of_pages",
    "leads_query",
    "narrow",
    "not_",
    "owned",
    "priced",
    "verdict_of",
]
