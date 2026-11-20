"""What is waiting on a pair's board right now: the work the sales figures
are waiting for.

Three counts, each a thing somebody can go and do:

- ``untaken``: a new enquiry nobody has taken for an hour;
- ``late``: an open card whose due time has passed;
- ``stale``: a qualified lead, still open, that nobody has touched for a
  week - a sale not closed and not refused.

Counted only where the CRM is on. The owner's daily message carries them,
so a board that is filling up is noticed without opening it.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.crm.constants import SetupState, StageKind
from app.modules.crm.models import CrmCard, CrmSetup, CrmStage
from app.modules.integrations.models import AdAccount, PageAccount

UNTAKEN_AFTER: Final = timedelta(hours=1)
STALE_DAYS: Final = 7


@dataclass(frozen=True, slots=True)
class Backlog:
    untaken: int = 0
    late: int = 0
    stale: int = 0

    def __bool__(self) -> bool:
        return bool(self.untaken or self.late or self.stale)


def backlog_by_pair(
    db: Session, *, owner: User, now: datetime
) -> dict[tuple[str, str], Backlog]:
    """``{(page's external id, ad account's external id): what waits}`` for
    every pair of the owner whose CRM is on."""
    still_open = CrmCard.closed_at.is_(None)
    rows = db.execute(
        select(
            PageAccount.external_id,
            AdAccount.external_id,
            func.count(CrmCard.id).filter(
                still_open,
                CrmStage.kind == StageKind.NEW,
                CrmCard.assignee_id.is_(None),
                CrmCard.created_at < now - UNTAKEN_AFTER,
            ),
            func.count(CrmCard.id).filter(still_open, CrmCard.due_at < now),
            func.count(CrmCard.id).filter(
                still_open,
                CrmStage.kind == StageKind.OPEN,
                CrmCard.qualified_at.is_not(None),
                CrmCard.updated_at < now - timedelta(days=STALE_DAYS),
            ),
        )
        .select_from(CrmSetup)
        .join(PageAccount, PageAccount.id == CrmSetup.page_id)
        .join(AdAccount, AdAccount.id == CrmSetup.ad_account_id)
        .outerjoin(
            CrmCard,
            and_(
                CrmCard.owner_id == CrmSetup.owner_id,
                CrmCard.page_id == CrmSetup.page_id,
                CrmCard.ad_account_id == CrmSetup.ad_account_id,
            ),
        )
        .outerjoin(CrmStage, CrmStage.id == CrmCard.stage_id)
        .where(CrmSetup.owner_id == owner.id, CrmSetup.state == SetupState.ON)
        .group_by(PageAccount.external_id, AdAccount.external_id)
    )
    return {
        (page, account): Backlog(untaken=untaken, late=late, stale=stale)
        for page, account, untaken, late, stale in rows
    }


__all__ = ["STALE_DAYS", "UNTAKEN_AFTER", "Backlog", "backlog_by_pair"]
