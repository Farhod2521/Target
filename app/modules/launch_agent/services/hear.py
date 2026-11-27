"""Working out what a typed message said.

A message that plainly answers the question just asked - a sum, an address,
a phone number - is read here, with no model: that is most turns, and they
answer at once. Anything else goes to the model once, which fills a form
(``core.launch_agent.heard.HeardOut``) and writes nothing to the person.
"""

import logging
import re
from dataclasses import dataclass
from typing import Final

from llmkit import LLMError, halves, render
from sqlalchemy.orm import Session

from app.common.exceptions import LLMUnavailable
from app.common.llm import MECHANICAL, claude, prompts
from app.modules.accounts.models import User
from app.modules.audit.constants import LLMPurpose
from app.modules.audit.services import record_llm_result
from app.modules.businesses.selectors import offered_directions
from app.modules.launch_agent.constants import PROMPT, RELATED_TYPE
from app.modules.launch_agent.models import LaunchAgentSession
from core.launch_agent import Ask, Brief, Frame, Heard
from core.launch_agent.hear import amount, phone_number, site_link, telegram_link
from core.launch_agent.heard import HeardOut
from core.launch_agent.words import chips

logger = logging.getLogger(__name__)

BARE_CHARS: Final = 40
_SOM: Final = re.compile(r"so['ʻ’`]?m|sum|ming|mln|сум|сўм|минг|млн", re.IGNORECASE)
_DOLLAR: Final = re.compile(r"\$|dollar|usd|доллар|у\.?\s?е", re.IGNORECASE)
NOTHING: Final = "Nothing yet."
NO_CHANNELS: Final = "None for the goal chosen."


@dataclass(frozen=True, slots=True)
class Listened:
    """What one message said, and what it said of the business's kind."""

    heard: Heard
    understood: bool = True
    kind_direction: str = ""
    kind_subtype: str = ""
    # The one thing the advert sells, when the message named it.
    sold_name: str = ""
    sold_price: str = ""
    by_model: bool = False


def _currency(text: str) -> str:
    if _DOLLAR.search(text):
        return "USD"
    if _SOM.search(text):
        return "UZS"
    return ""


def plain_answer(
    text: str, *, asked: Ask | None, frame: Frame, brief: Brief
) -> Heard | None:
    """The message as a bare answer to the question asked, or nothing when
    it is more than that."""
    if asked is None or len(text) > BARE_CHARS:
        return None
    if asked.slot == "budget" and amount(text) is not None:
        if re.search(r"[A-Za-zА-Яа-я]{6,}", _SOM.sub("", _DOLLAR.sub("", text))):
            return None
        return Heard(budget=text, budget_currency=_currency(text))
    if asked.slot == "link":
        goal = frame.goal(brief.goal)
        wants_telegram = goal is not None and goal.telegram
        found = telegram_link(text) if wants_telegram else site_link(text)
        return Heard(link=text) if found else None
    if asked.slot == "phone" and phone_number(text):
        return Heard(phone=text)
    return None


def _settled(brief: Brief, frame: Frame) -> str:
    lines = [f"- {chip.label}: {chip.value}" for chip in chips(brief, frame)]
    return "\n".join(lines) or NOTHING


def _kinds(db: Session, frame: Frame) -> str:
    if frame.kind_known:
        return ""
    rows = "\n".join(f"- {row.key} - {row.label_uz}" for row in offered_directions(db))
    return f"## Kinds of business\n\n{rows}"


def _variables(
    db: Session, *, asked: Ask | None, brief: Brief, frame: Frame
) -> dict[str, object]:
    goal = frame.goal(brief.goal)
    channels = goal.channels if goal is not None else ()
    return {
        "asked": f"{asked.text} (field: {asked.slot})" if asked else "Nothing.",
        "settled": _settled(brief, frame),
        "goals": "\n".join(f"- {one.key} - {one.label}" for one in frame.goals),
        "channels": "\n".join(f"- {key} - {label}" for key, label in channels)
        or NO_CHANNELS,
        "kinds": _kinds(db, frame),
    }


def listen(
    db: Session,
    *,
    owner: User,
    session: LaunchAgentSession,
    text: str,
    asked: Ask | None,
    brief: Brief,
    frame: Frame,
) -> Listened:
    """What the message said. One model call at most; a model that cannot
    be reached reads as a message nobody understood."""
    plain = plain_answer(text, asked=asked, frame=frame, brief=brief)
    if plain is not None:
        return Listened(heard=plain)
    template, version = prompts().get(PROMPT)
    instructions, account = halves(template)
    try:
        with claude(tier=MECHANICAL) as client:
            result = client.structured(
                prompt=text,
                schema=HeardOut,
                system=instructions,
                system_tail=render(
                    account, _variables(db, asked=asked, brief=brief, frame=frame)
                ),
                prompt_name=PROMPT,
                prompt_version=version,
            )
    except (LLMError, LLMUnavailable):
        logger.warning("launch_agent_hear_failed", extra={"session": str(session.id)})
        return Listened(heard=Heard(), understood=False, by_model=True)
    record_llm_result(
        db,
        owner=owner,
        purpose=LLMPurpose.ONBOARDING,
        result=result,
        related_type=RELATED_TYPE,
        related_id=session.id,
    )
    out: HeardOut = result.value
    return Listened(
        heard=Heard(
            kind=out.kind,
            offer=out.offer,
            goal=out.goal,
            link=out.link,
            phone=out.phone,
            channel=out.channel,
            budget=out.budget,
            budget_currency=out.budget_currency,
            start_day=out.start_day,
        ),
        understood=out.understood,
        kind_direction=out.kind_direction,
        kind_subtype=out.kind_subtype,
        sold_name=" ".join(out.sold_name.split()),
        sold_price=" ".join(out.sold_price.split()),
        by_model=True,
    )


__all__ = ["Listened", "listen", "plain_answer"]
