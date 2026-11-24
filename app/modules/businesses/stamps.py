"""The business written beside the pair, wherever a row is made.

The rows that name a page and an ad account are made in many places, and
the pairs themselves are written by the cabinet in several more. None of
those places is told about businesses. Two listeners on the session do it
for them, so a place added later is covered without knowing:

- at every flush, a new row that names a pair and has no business gets the
  pair's; a lead gets its card's, or its form's page's when that page is one
  business;
- at commit, an owner whose stored pairs or page profile changed in the
  transaction has their links brought level (:func:`links.settle`), which
  cannot fail the commit.

A row written around the session (a bulk ``INSERT``) is not seen here;
``python -m app.modules.businesses.backfill --apply`` fills those.
"""

import uuid
from functools import cache
from typing import Any

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

from app.modules.businesses.models import Business

_TOUCHED = "business_owners_touched"
_SETTLING = "business_links_settling"


@cache
def _models() -> dict[str, Any]:
    from app.modules.ads.models import CampaignLaunch
    from app.modules.chat.models import ChatSession
    from app.modules.crm.models import (
        CrmCard,
        CrmLostReason,
        CrmMember,
        CrmSetup,
        CrmStage,
    )
    from app.modules.integrations.models import PagePair
    from app.modules.leads.models import Lead, LeadForm

    return {
        "paired": (
            CrmStage,
            CrmLostReason,
            CrmCard,
            CrmMember,
            CrmSetup,
            ChatSession,
            CampaignLaunch,
        ),
        "card": CrmCard,
        "lead": Lead,
        "form": LeadForm,
        "pair": PagePair,
    }


@event.listens_for(Session, "before_flush")
def _stamp(session: Session, _context: Any, _instances: Any) -> None:
    if session.info.get(_SETTLING):
        return
    models = _models()
    _mark(session, models)
    _write(session, models)


def _mark(session: Session, models: dict[str, Any]) -> None:
    touched: set[uuid.UUID] = set()
    for row in (*session.new, *session.dirty, *session.deleted):
        if isinstance(row, models["pair"]):
            touched.add(row.owner_id)
    for row in session.new:
        if isinstance(row, Business) and row.page_id is not None:
            touched.add(row.user_id)
    for row in session.dirty:
        if (
            isinstance(row, Business)
            and inspect(row).attrs.page_id.history.has_changes()
        ):
            touched.add(row.user_id)
    touched.discard(None)  # type: ignore[arg-type]
    if touched:
        session.info.setdefault(_TOUCHED, set()).update(touched)


def _write(session: Session, models: dict[str, Any]) -> None:
    from app.modules.businesses.services.links import business_of_pair

    found: dict[tuple[Any, Any], uuid.UUID | None] = {}

    def of(page_id: Any, account_id: Any) -> uuid.UUID | None:
        key = (page_id, account_id)
        if key not in found:
            found[key] = business_of_pair(
                session, page_id=page_id, ad_account_id=account_id
            )
        return found[key]

    new = list(session.new)
    for row in new:
        if (
            isinstance(row, models["paired"])
            and row.business_id is None
            and row.page_id is not None
        ):
            row.business_id = of(row.page_id, row.ad_account_id)
    for row in new:
        if isinstance(row, models["card"]) and row.business_id is not None:
            lead = row.lead
            if lead is None and row.lead_id is not None:
                lead = session.get(models["lead"], row.lead_id)
            if lead is not None and lead.business_id is None:
                lead.business_id = row.business_id
    for row in new:
        if (
            isinstance(row, models["lead"])
            and row.business_id is None
            and row.form_id is not None
        ):
            form = session.get(models["form"], row.form_id)
            if form is not None:
                row.business_id = of(form.page_id, None)


@event.listens_for(Session, "before_commit")
def _settle(session: Session) -> None:
    # A commit flushes after this hook; what is still pending has to be
    # written first, or the pairs it changes are not marked yet.
    session.flush()
    owners = session.info.pop(_TOUCHED, None)
    if not owners:
        return
    from app.modules.businesses.services.links import settle

    session.info[_SETTLING] = True
    try:
        for owner_id in sorted(owners, key=str):
            settle(session, owner_id=owner_id)
    finally:
        session.info.pop(_SETTLING, None)


@event.listens_for(Session, "after_rollback")
def _forget(session: Session) -> None:
    session.info.pop(_TOUCHED, None)
