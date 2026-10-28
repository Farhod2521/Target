"""The press that ends preparation.

Readiness is ``core.onboarding``'s question, asked through this module's
selector; the row that records the answer is billing's. Also switches the
agent on - once, and only for an account nobody has asked yet.
"""

import logging
from datetime import datetime

from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.agent.selectors import policy_for
from app.modules.agent.services import save_policy
from app.modules.billing.models import Subscription
from app.modules.billing.selectors import setup_locked
from app.modules.billing.services import complete_setup
from app.modules.integrations.services import pin_shown_pair
from app.modules.onboarding.exceptions import SetupNotReady
from app.modules.onboarding.selectors import setup_overview

logger = logging.getLogger(__name__)


def finish_setup(db: Session, *, user: User, now: datetime) -> Subscription | None:
    """Check the choices it fixes are made, then close preparation. Caller commits.

    ``None`` for an account that has never opened a plan. Asked again here
    rather than trusted from the screen: a connection may have expired
    while it stood open. Three gates, not four - see
    ``core.onboarding.FINISH_GATES``.
    """
    overview = setup_overview(db, owner=user)
    if not overview.can_finish:
        raise SetupNotReady

    first_press = not setup_locked(db, owner=user)
    with db.begin_nested():
        subscription = complete_setup(db, owner=user, now=now)
        pin_shown_pair(db, user=user)
        if first_press:
            _switch_agent_on(db, user=user)

    logger.info("setup finished by %s", user.id)
    return subscription


def _switch_agent_on(db: Session, *, user: User) -> None:
    """The agent on - unless a settings row already answered the question."""
    if policy_for(db, owner=user) is not None:
        return
    save_policy(db, user=user, is_enabled=True)
    logger.info("agent switched on for %s as preparation closed", user.id)
