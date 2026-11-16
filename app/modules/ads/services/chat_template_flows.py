"""A saved chat template, kept on the page as well, so Ads Manager offers it.

The template itself lives here (:mod:`app.modules.ads.services.chat_templates`)
and the product's own adverts take it from here, answers and all. This keeps
a copy on the page as a Meta welcome message flow - the greeting with the
questions listed under it - which Ads Manager shows under «Message template»
→ «Partner App», the way a lead form made here is offered there.

Never in the way of a save or a launch: the copy needs ``pages_messaging``,
which only some connections carry, and whatever Meta answers is written on
the template as its ``meta_state`` for the screen to say, not raised.
"""

import logging
from typing import Final

from metaads.errors import MetaAPIError, MetaAuthError, MetaError
from metaads.oauth import INSTAGRAM_MESSAGES_SCOPE, PAGES_MESSAGING_SCOPE, holds
from metaads.welcome_flows import (
    INSTAGRAM,
    MESSENGER,
    create_flow,
    delete_flow,
    update_flow,
)
from sqlalchemy.orm import Session

from app.common.config import settings
from app.common.exceptions import DomainError
from app.modules.ads.models import CampaignLaunch, ChatTemplate
from app.modules.ads.services.access import launch_page_and_token
from app.modules.integrations.selectors import meta_connection

logger = logging.getLogger(__name__)

SAVED: Final = "saved"
NO_PERMISSION: Final = "no_permission"
FAILED: Final = "failed"
# Meta's codes for a permission the token does not carry.
_PERMISSION_CODES: Final = frozenset({10, 200, 230, 551})


def _refused_for_permission(exc: MetaError) -> bool:
    if isinstance(exc, MetaAuthError):
        return True
    return isinstance(exc, MetaAPIError) and exc.code in _PERMISSION_CODES


def keep_on_page(
    db: Session, *, launch: CampaignLaunch, template: ChatTemplate
) -> None:
    """Make or rewrite the template's flow on the advert's page; the outcome
    goes on ``template.meta_state``. Commits it."""
    if not settings.meta_ask_messaging:
        return
    connection = meta_connection(db, owner=launch.owner)
    scopes = connection.scopes if connection is not None else []
    if connection is None or not holds(scopes, PAGES_MESSAGING_SCOPE):
        template.meta_state = NO_PERMISSION
        db.commit()
        return
    try:
        page, token = launch_page_and_token(db, launch=launch)
    except DomainError:
        logger.info("chat template %s: no usable page to keep it on", template.id)
        template.meta_state = FAILED
        db.commit()
        return

    platforms: tuple[str, ...] = (MESSENGER,)
    if page.instagram_user_id and holds(scopes, INSTAGRAM_MESSAGES_SCOPE):
        platforms += (INSTAGRAM,)
    fields = {
        "page_id": page.external_id,
        "name": template.name,
        "text": template.welcome_text,
        "questions": tuple(template.questions or ()),
        "platforms": platforms,
        "page_token": token,
        "dry_run": settings.ads_dry_run,
    }
    try:
        if template.meta_flow_id:
            try:
                update_flow(flow_id=template.meta_flow_id, **fields)
            except MetaAPIError as exc:
                if _refused_for_permission(exc):
                    raise
                # An advert uses it, so Meta keeps it as it is: the new
                # wording becomes a flow of its own.
                logger.info(
                    "chat template %s: flow %s not rewritten, making another: %s",
                    template.id,
                    template.meta_flow_id,
                    exc,
                )
                template.meta_flow_id = create_flow(**fields)
        else:
            template.meta_flow_id = create_flow(**fields)
    except MetaError as exc:
        template.meta_state = NO_PERMISSION if _refused_for_permission(exc) else FAILED
        logger.warning("chat template %s not kept on the page: %s", template.id, exc)
    except ValueError as exc:
        template.meta_state = FAILED
        logger.warning("chat template %s: %s", template.id, exc)
    else:
        template.meta_state = SAVED
    db.commit()


def take_off_page(
    db: Session, *, launch: CampaignLaunch, template: ChatTemplate
) -> None:
    """Remove the template's flow from the page, when it has one. Meta keeps a
    flow an advert uses; that refusal is logged and the template goes anyway."""
    if not template.meta_flow_id or not settings.meta_ask_messaging:
        return
    try:
        page, token = launch_page_and_token(db, launch=launch)
        delete_flow(
            page_id=page.external_id,
            flow_id=template.meta_flow_id,
            page_token=token,
            dry_run=settings.ads_dry_run,
        )
    except (DomainError, MetaError) as exc:
        logger.info(
            "chat template %s: flow %s left on the page: %s",
            template.id,
            template.meta_flow_id,
            exc,
        )


__all__ = ["FAILED", "NO_PERMISSION", "SAVED", "keep_on_page", "take_off_page"]
