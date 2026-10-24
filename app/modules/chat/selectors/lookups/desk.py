"""Which read answers which look-up, and the one way any of them is run."""

from collections.abc import Callable
from datetime import datetime
from typing import Final

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.ads.selectors.page_boundary import PageScope
from app.modules.chat.selectors.lookups.accounts import account_overview, audiences
from app.modules.chat.selectors.lookups.ads import ad_details
from app.modules.chat.selectors.lookups.audience import audience_details
from app.modules.chat.selectors.lookups.campaigns import (
    campaign_details,
    list_campaigns,
)
from app.modules.chat.selectors.lookups.figures import daily_figures, lead_counts
from app.modules.chat.selectors.lookups.forms import lead_forms
from app.modules.chat.selectors.lookups.history import (
    agent_proposals,
    open_problems,
    recent_changes,
)
from app.modules.chat.selectors.lookups.preparations import preparations
from app.modules.chat.selectors.lookups.search import find
from core.chat.lookups import clipped

HANDLERS: Final[dict[str, Callable[..., str]]] = {
    "account_overview": account_overview,
    "find": find,
    "list_campaigns": list_campaigns,
    "campaign_details": campaign_details,
    "audience_details": audience_details,
    "ad_details": ad_details,
    "daily_figures": daily_figures,
    "lead_counts": lead_counts,
    "lead_forms": lead_forms,
    "recent_changes": recent_changes,
    "agent_proposals": agent_proposals,
    "open_problems": open_problems,
    "audiences": audiences,
    "preparations": preparations,
}


def answer_lookup(
    db: Session,
    *,
    owner: User,
    name: str,
    arguments: BaseModel,
    scope: PageScope,
    now: datetime,
    counted: PageScope | None = None,
) -> str:
    """One look-up's result, cut to what a result may cost."""
    handler = HANDLERS.get(name)
    if handler is None:
        return f"There is no look-up called {name!r}."
    if counted is not None and _is_a_total(name, arguments):
        scope = counted
    return clipped(handler(db, owner=owner, arguments=arguments, scope=scope, now=now))


def _is_a_total(name: str, arguments: BaseModel) -> bool:
    """Whether a look-up sums across the page rather than describing one thing."""
    if name == "lead_counts":
        return True
    return name == "daily_figures" and not getattr(arguments, "object_id", "")


__all__ = ["HANDLERS", "answer_lookup"]
