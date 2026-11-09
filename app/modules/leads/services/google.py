"""Leads from Google's lead forms, read from the account on a clock.

Meta tells us a lead arrived; Google is asked. Every half hour each Google
account that has a running campaign is read for its recent submissions, and
each one is stored the way a Meta lead is - :func:`store_lead` - so the CRM,
the notifications and the sheets take it without knowing where it came from.

**Read again, not resumed.** Each read covers the last two days, not "since
the last one": a read that failed, a worker that was down, a lead Google
filed late are all caught by the next. A lead already stored is stopped by
the database's one-lead-per-provider rule, so reading it twice is free. An
account read for the first time reaches back thirty days.

**Only accounts with something running**, because Google counts every read
against one allowance for the whole product, not per account; a campaign
stopped within the window still counts, for the leads it took before.
"""

import logging
import uuid
from datetime import datetime, timedelta
from typing import Final

from adskit import ExternalRef, registry
from adskit.errors import ProviderError
from googleadskit import PROVIDER as GOOGLE
from sqlalchemy import exists, or_, select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.ads.exceptions import ConnectionUnusable
from app.modules.ads.models import Campaign
from app.modules.ads.services.access import token_for
from app.modules.integrations.constants import USABLE_CONNECTION_STATUSES
from app.modules.integrations.models import AdAccount, ProviderConnection
from app.modules.integrations.selectors.google import google_ads_on
from app.modules.leads.models import Lead

logger = logging.getLogger(__name__)

LOOK_BACK: Final = timedelta(days=2)
FIRST_LOOK: Final = timedelta(days=30)
RUNNING: Final = "ENABLED"
ACCOUNT_LEVEL: Final = "account"


def accounts_to_read(db: Session, *, now: datetime) -> list[uuid.UUID]:
    """Google accounts with a live connection and a campaign that may take leads."""
    live = select(Campaign.id).where(
        Campaign.ad_account_id == AdAccount.id,
        or_(Campaign.status == RUNNING, Campaign.updated_at >= now - LOOK_BACK),
    )
    return list(
        db.scalars(
            select(AdAccount.id)
            .join(ProviderConnection, ProviderConnection.id == AdAccount.connection_id)
            .where(
                AdAccount.provider == GOOGLE,
                AdAccount.is_active.is_(True),
                ProviderConnection.status.in_(USABLE_CONNECTION_STATUSES),
                exists(live),
            )
        )
    )


def sync_google_leads(db: Session, *, ad_account_id: str, now: datetime) -> int:
    """Store the account's new submissions. Returns how many were new."""
    from app.modules.leads.services import CREATED, store_lead

    account = db.get(AdAccount, uuid.UUID(ad_account_id))
    if account is None or account.provider != GOOGLE or not account.is_active:
        return 0
    owner = db.get(User, account.owner_id)
    if owner is None or not google_ads_on(user=owner):
        return 0
    try:
        token = token_for(ad_account=account)
        found = registry.get(GOOGLE).leads.list_leads(
            form=ExternalRef(
                provider=GOOGLE, level=ACCOUNT_LEVEL, id=account.external_id
            ),
            since=now - (LOOK_BACK if _read_before(db, account) else FIRST_LOOK),
            token=token,
        )
    except (ConnectionUnusable, ProviderError) as exc:
        # The next half hour reads the same window again; nothing is lost.
        logger.info("google leads of %s not read: %s", account.external_id, exc)
        return 0
    stored = [
        store_lead(
            db,
            owner=owner,
            provider=GOOGLE,
            leadgen_id=lead.ref.id,
            lead=lead,
            received_at=now,
        )
        for lead in found
        if lead.ref.id
    ]
    db.commit()
    return stored.count(CREATED)


def _read_before(db: Session, account: AdAccount) -> bool:
    """Whether a lead of this account was stored before: then two days are enough."""
    return bool(
        db.scalar(
            select(
                exists().where(
                    Lead.owner_id == account.owner_id,
                    Lead.provider == GOOGLE,
                    Lead.campaign_external_id.startswith(
                        f"customers/{account.external_id}/", autoescape=True
                    ),
                )
            )
        )
    )


__all__ = ["accounts_to_read", "sync_google_leads"]
