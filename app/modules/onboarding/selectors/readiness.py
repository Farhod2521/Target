"""How far this cabinet has got, read from the modules that hold the answer.

``core.onboarding`` decides the order; this gathers the facts it decides
from, each through another module's public selector.
"""

from dataclasses import asdict, dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.businesses.selectors import business_for
from app.modules.integrations.models import PageAccount
from app.modules.integrations.selectors import (
    active_ad_account,
    active_page,
    active_pixel,
    ad_accounts,
    is_connected,
    missing_scopes,
)
from app.modules.integrations.selectors.connection import pages
from app.modules.notifications.bot import is_configured as telegram_configured
from core.onboarding import (
    SetupFacts,
    Step,
    StepId,
    StepState,
    blocking,
    can_finish,
    is_ready,
    paired_state,
    plan,
    progress,
)


@dataclass(frozen=True, slots=True)
class SetupOverview:
    """Everything the preparation screen draws, decided once."""

    facts: SetupFacts
    steps: tuple[Step, ...]
    state: dict[StepId, StepState]
    # The page and its paying account, drawn as one row.
    pick: StepState
    ready: bool
    # Whether the finish press would be taken - shorter than ``ready``.
    can_finish: bool
    blocked_on: str
    done: int
    total: int
    page: PageAccount | None


def setup_overview(db: Session, *, owner: User) -> SetupOverview:
    """The plan for this owner, with the facts it was decided from."""
    page = active_page(db, owner=owner)
    facts = _facts(db, owner=owner, page=page)
    steps = plan(facts)
    done, total = progress(facts)
    return SetupOverview(
        facts=facts,
        steps=steps,
        state={step.id: step.state for step in steps},
        pick=paired_state(steps),
        ready=is_ready(facts),
        can_finish=can_finish(facts),
        blocked_on=blocking(facts),
        done=done,
        total=total,
        page=page,
    )


def setup_facts(db: Session, *, owner: User) -> SetupFacts:
    """Every fact the sequence turns on, for one owner."""
    return _facts(db, owner=owner, page=active_page(db, owner=owner))


def _facts(db: Session, *, owner: User, page: PageAccount | None) -> SetupFacts:
    # Imported here: notifications reads the preparation state for its inbox.
    from app.modules.notifications.selectors import chat_for

    business = business_for(db, owner)
    offered = telegram_configured()
    return SetupFacts(
        has_profile=business is not None,
        has_category=bool(business is not None and business.category),
        connected=is_connected(db, owner=owner),
        scopes_missing=bool(missing_scopes(db, owner=owner)),
        ad_account_chosen=active_ad_account(db, owner=owner) is not None,
        ad_accounts_found=len(ad_accounts(db, owner=owner)),
        page_chosen=page is not None,
        pages_found=len(pages(db, owner=owner)),
        page_terms_accepted=page.leadgen_terms_accepted if page is not None else None,
        leads_subscribed=bool(page is not None and page.leadgen_subscribed),
        pixel_chosen=active_pixel(db, owner=owner) is not None,
        telegram_offered=offered,
        telegram_linked=offered and chat_for(db, owner=owner) is not None,
    )


def overview_as_dict(overview: SetupOverview) -> dict[str, Any]:
    """The overview as JSON: ``page`` is the chosen page, or null."""
    from app.modules.integrations.schemas import PageOut

    page = overview.page
    return {
        "facts": asdict(overview.facts),
        "steps": [asdict(step) for step in overview.steps],
        "state": dict(overview.state),
        "pick": overview.pick,
        "ready": overview.ready,
        "can_finish": overview.can_finish,
        "blocked_on": overview.blocked_on,
        "done": overview.done,
        "total": overview.total,
        "page": PageOut.model_validate(page).model_dump(mode="json") if page else None,
    }


__all__ = ["SetupOverview", "overview_as_dict", "setup_facts", "setup_overview"]
