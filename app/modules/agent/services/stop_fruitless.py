"""Stopping, without asking, a group that spends with nothing back."""

import logging
from datetime import datetime

from sqlalchemy.orm import Session

from app.common.config import settings
from app.common.exceptions import DomainError
from app.common.money import format_minor
from app.modules.accounts.models import User
from app.modules.ads.constants import ManagedLevel
from app.modules.ads.services.manage import Origin, request_pause
from app.modules.agent.constants import AUTO_STOP_MARK
from app.modules.agent.selectors.auto_stop import StopCandidate, stop_candidates
from app.modules.audit.constants import ActorType
from core.agent.auto_stop import SmallBudget, must_stop

logger = logging.getLogger(__name__)
BY_ITSELF = Origin(actor_type=ActorType.AGENT)


def stop_fruitless(db: Session, *, owner: User, now: datetime) -> int:
    """Stop every group past its bar. Returns how many were stopped. Commits."""
    stopped = 0
    for found in stop_candidates(db, owner=owner, now=now):
        if not must_stop(found.group, small=_small(found.currency)):
            continue
        try:
            _stop(db, owner=owner, found=found)
        except DomainError as exc:
            db.rollback()
            logger.info(
                "auto_stop_refused",
                extra={"adset": found.group.adset_id, "why": type(exc).__name__},
            )
            continue
        db.commit()
        stopped += 1
    return stopped


def _stop(db: Session, *, owner: User, found: StopCandidate) -> None:
    """The stop, and its mark written in the same transaction as the request,
    so the worker never reads the row without it."""
    log = request_pause(
        db,
        user=owner,
        level=ManagedLevel.ADSET,
        external_id=found.group.adset_id,
        origin=BY_ITSELF,
    )
    log.request_payload = {
        **(log.request_payload or {}),
        AUTO_STOP_MARK: {
            "spend_minor": found.spent_ever_minor,
            "results": found.results_ever,
            "impressions": found.impressions_ever,
            "link_clicks": found.link_clicks_ever,
            "spent_since_minor": found.group.spend_minor,
            "budget_minor": found.group.budget_minor,
        },
    }
    spend = format_minor(amount_minor=found.group.spend_minor, currency=found.currency)
    log.reason = (
        f"{spend} sarflandi, lekin birorta ham natija bo'lmadi - pul behuda "
        "ketmasligi uchun guruh to'xtatildi."
    )
    db.flush()


def _small(currency: str) -> SmallBudget | None:
    """The account currency's small-budget bar, where one is set."""
    bar = settings.agent_small_budgets.get(currency)
    if bar is None:
        return None
    budget_minor, spend_minor = bar
    return SmallBudget(budget_minor=budget_minor, spend_minor=spend_minor)


__all__ = ["stop_fruitless"]
