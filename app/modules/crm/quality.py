"""What makes a lead qualified, sold or looked at: the CRM's word, once.

The one definition every count reads - the cabinet's panels, the expert
table, the dashboard, the reports and the agent - and the same one the CAPI
signals tell Meta (:func:`core.leads.reporting.card_signals`). A lead is
qualified when its card stands won, or stands open after being moved into a
stage that counts as quality; a card lost, called junk or put back among the
new is not. Sold is a card standing won. A manual verdict on the leads page
is not counted.

A lead is counted by the day it arrived, so a period's spend is set against
the leads that spend brought. Where the CRM is not on, nothing is counted
and the screen says so rather than showing nought.
"""

import uuid
from collections.abc import Collection

from sqlalchemy import ColumnElement, and_, or_, select
from sqlalchemy.orm import Session

from app.modules.crm.constants import SetupState, StageKind
from app.modules.crm.models import CrmCard, CrmSetup, CrmStage


def qualified_card() -> ColumnElement[bool]:
    return or_(
        won_card(),
        and_(
            CrmCard.qualified_at.is_not(None),
            CrmCard.stage_id.in_(
                select(CrmStage.id).where(CrmStage.kind == StageKind.OPEN)
            ),
        ),
    )


def won_card() -> ColumnElement[bool]:
    return CrmCard.stage_id.in_(
        select(CrmStage.id).where(CrmStage.kind == StageKind.WON)
    )


def junk_card() -> ColumnElement[bool]:
    return CrmCard.stage_id.in_(
        select(CrmStage.id).where(CrmStage.kind == StageKind.JUNK)
    )


def judged_card() -> ColumnElement[bool]:
    """Somebody has moved the card on from the new column."""
    return CrmCard.stage_id.in_(
        select(CrmStage.id).where(CrmStage.kind != StageKind.NEW)
    )


def crm_account_ids(db: Session, *, owner_id: uuid.UUID) -> frozenset[uuid.UUID]:
    """The ad accounts with a CRM switched on for at least one of their pages."""
    return frozenset(
        db.scalars(
            select(CrmSetup.ad_account_id).where(
                CrmSetup.owner_id == owner_id,
                CrmSetup.page_id.is_not(None),
                CrmSetup.ad_account_id.is_not(None),
                CrmSetup.state == SetupState.ON,
            )
        )
    )


def crm_is_on(
    db: Session, *, owner_id: uuid.UUID, ad_account_ids: Collection[uuid.UUID]
) -> bool:
    """Whether any of these accounts counts its leads in a CRM."""
    return bool(crm_account_ids(db, owner_id=owner_id) & set(ad_account_ids))


__all__ = [
    "crm_account_ids",
    "crm_is_on",
    "judged_card",
    "junk_card",
    "qualified_card",
    "won_card",
]
