"""One turn of the advert chat: take what was said, save what stands, ask
the next thing.

Nothing here decides what to ask or how to say it - that is the engine's
(``core.launch_agent``). This module joins it to the account: the launch it
fills, the limits, the model that reads free text, and the wizard's own
check that every saved answer passes.
"""

import logging
from dataclasses import asdict, fields
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.acting import acting_for
from app.common.exceptions import DomainError, InputRefused
from app.common.throttle import hit
from app.modules.accounts.models import User
from app.modules.ads.inputs.plan import PlanIn, check_plan
from app.modules.ads.models import CampaignLaunch
from app.modules.ads.services import launch as launch_services
from app.modules.businesses.constants import KnowledgeSource, TypeState
from app.modules.businesses.exceptions import BadKnowledgeChange, BadSubtype
from app.modules.businesses.models import Business
from app.modules.businesses.selectors import business_for_page, offered_directions
from app.modules.businesses.selectors.knowledge import known
from app.modules.businesses.services import knowledge, subtypes
from app.modules.businesses.services.kinds import set_kind
from app.modules.launch_agent.constants import (
    HEARD_BUCKET,
    HEARD_PER_DAY,
    MAX_TEXT_CHARS,
    MAX_TURNS,
    MESSAGES_KEPT,
    NEXT_MEDIA,
    Author,
    SessionStatus,
)
from app.modules.launch_agent.exceptions import (
    HeardLimit,
    SessionClosed,
    SessionNotFound,
    TextTooLong,
    TooManyTurns,
)
from app.modules.launch_agent.models import LaunchAgentSession
from app.modules.launch_agent.services.frame import build_frame
from app.modules.launch_agent.services.hear import Listened, listen, plain_answer
from app.modules.launch_agent.services.stages import (
    ASKING,
    MEDIA,
    SETTLED,
    STAGE_SLOTS,
    Staged,
    press,
    stage_of,
    staged,
)
from core.launch_agent import (
    KIND_NO,
    KIND_YES,
    Brief,
    Frame,
    Heard,
    Reply,
    is_ready,
    kind_open,
    merge,
    money,
    reply,
)
from core.launch_agent.hear import Note
from core.launch_agent.words import READY, ask_for, next_slot

logger = logging.getLogger(__name__)

# A button may answer these; what the business does is always said in words.
PRESSABLE = frozenset({"offer", "goal", "link", "phone", "channel", "form", "budget"})
# The wizard's field for each slot, to read its refusals back.
PLAN_FIELDS = {
    "goal": "goal",
    "daily_budget": "budget",
    "link_url": "link",
    "phone_number": "phone",
    "chat_channel": "channel",
}
DAY_SECONDS = 86400


def _brief(session: LaunchAgentSession) -> Brief:
    raw = dict(session.brief or {})
    names = {field.name for field in fields(Brief)}
    kept = {key: value for key, value in raw.items() if key in names}
    kept["said"] = frozenset(kept.get("said") or ())
    return Brief(**kept)


def _keep(session: LaunchAgentSession, brief: Brief) -> None:
    session.brief = {**asdict(brief), "said": sorted(brief.said)}


def _say(session: LaunchAgentSession, author: str, text: str, now: datetime) -> None:
    if not text:
        return
    session.messages = [
        *(session.messages or []),
        {"author": author, "text": text, "at": now.isoformat()},
    ][-MESSAGES_KEPT:]


def _launch(db: Session, session: LaunchAgentSession) -> CampaignLaunch | None:
    if session.launch_id is None:
        return None
    return db.get(CampaignLaunch, session.launch_id)


def session_for(
    db: Session, *, user: User, pk: Any, lock: bool = False
) -> LaunchAgentSession:
    query = select(LaunchAgentSession).where(
        LaunchAgentSession.id == pk, LaunchAgentSession.owner_id == user.id
    )
    if lock:
        query = query.with_for_update()
    found = db.scalar(query)
    if found is None:
        raise SessionNotFound
    held = acting_for(user.id)
    if held is not None and found.business_id != held.business_id:
        # A request that names its business reads that business's
        # conversations: a member of one never opens another's by its id.
        raise SessionNotFound
    return found


def _placed(db: Session, *, launch: CampaignLaunch, said: Reply) -> Staged:
    """An engine reply with where the launch stands: past the questions it
    is the stage's own words and buttons."""
    if not said.ready and stage_of(launch, brief_ready=False) == ASKING:
        return Staged(reply=said, stage=ASKING)
    # Prepared already - here or on the wizard's screens: the launch says
    # where it stands, whatever this conversation has heard.
    return staged(
        db,
        launch=launch,
        base=said,
        lines=tuple(line for line in said.lines if line != READY),
    )


def start(
    db: Session, *, user: User, now: datetime
) -> tuple[LaunchAgentSession, Staged]:
    """Open the conversation for the launch the wizard would open; the one
    still open for it is carried on. Caller commits."""
    launch = launch_services.start_launch(db, user=user)
    business = business_for_page(db, owner=user, page=launch.page)
    assert business is not None  # ``start_launch`` refuses without one
    session = db.scalar(
        select(LaunchAgentSession)
        .where(
            LaunchAgentSession.owner_id == user.id,
            LaunchAgentSession.launch_id == launch.id,
            LaunchAgentSession.status != SessionStatus.CLOSED,
        )
        .order_by(LaunchAgentSession.created_at.desc())
        .limit(1)
        .with_for_update()
    )
    frame = build_frame(db, launch=launch, user=user, business=business, now=now)
    if session is None:
        session = LaunchAgentSession(
            owner_id=user.id,
            business_id=business.id,
            launch_id=launch.id,
            brief={},
            messages=[],
        )
        db.add(session)
        db.flush()
        out = _placed(db, launch=launch, said=reply(Brief(), frame))
        if out.stage != ASKING:
            session.status = SessionStatus.READY
        _say(session, Author.AGENT, _spoken(out.reply), now)
        return session, out
    return session, _placed(db, launch=launch, said=reply(_brief(session), frame))


def _spoken(said: Reply) -> str:
    """A reply as one message of the transcript."""
    return "\n".join([*said.lines, *([said.ask.text] if said.ask else [])])


def _heard_button(slot: str, value: str) -> Heard:
    if slot == "kind" and value in (KIND_YES, KIND_NO):
        return Heard(kind_ok=value)
    if slot not in PRESSABLE:
        return Heard()
    return Heard(**{slot: value})


def _set_kind_from(
    db: Session, *, business: Business, user: User, listened: Listened, now: datetime
) -> bool:
    """The kind the person just described, kept as our reading of it until
    they carry on past the summary. Answers whether a kind was written."""
    direction = next(
        (
            row
            for row in offered_directions(db)
            if row.key == listened.kind_direction.strip().lower()
        ),
        None,
    )
    if direction is None:
        return False
    subtype = None
    if listened.kind_subtype.strip():
        try:
            subtype, _made = subtypes.ensure(
                db, direction=direction, name=listened.kind_subtype, actor=user
            )
        except BadSubtype:
            subtype = None
    set_kind(
        db,
        business=business,
        direction=direction,
        subtype=subtype,
        state=TypeState.GUESSED,
        source=KnowledgeSource.LAUNCH_AGENT,
        actor=user,
        now=now,
    )
    return True


def _plan_body(brief: Brief, frame: Frame) -> PlanIn:
    return PlanIn(
        goal=brief.goal,
        daily_budget=Decimal(money(brief.budget_minor, frame)),
        link_url=brief.link,
        phone_number=brief.phone,
        chat_channel=brief.channel,
        start_day=brief.start_day if brief.start_day == "tomorrow" else "today",
    )


def _save_plan(
    db: Session,
    *,
    launch: CampaignLaunch,
    user: User,
    brief: Brief,
    frame: Frame,
    now: datetime,
) -> tuple[Brief, tuple[Note, ...], tuple[str, ...]]:
    """Save the finished brief through the wizard's own check. What it
    refuses is emptied and asked again, in the wizard's own words."""
    try:
        answers = check_plan(
            db, launch=launch, user=user, body=_plan_body(brief, frame), now=now
        )
    except InputRefused as refused:
        cleared = brief
        lines: list[str] = []
        for field_name, sentence in refused.problems.items():
            slot = PLAN_FIELDS.get(field_name, "")
            if slot == "budget":
                cleared = cleared.with_(budget_minor=0)
            elif slot:
                cleared = cleared.with_(**{slot: ""})
            if sentence:
                lines.append(str(sentence))
        if cleared == brief:
            # Refused over something the chat does not ask: nothing to ask
            # again, so the goal is, rather than turning in a circle.
            cleared = brief.with_(goal="", link="", phone="", channel="")
        return cleared, (), tuple(lines)
    launch_services.save_answers(
        db,
        launch=launch,
        **answers,
        # What this advert is about, in the person's own words: the advert
        # writer and the audience are worked out from it.
        offer_text=brief.offer,
    )
    return brief, (), ()


def _agree_kind(db: Session, *, business: Business, user: User, now: datetime) -> None:
    """Our reading of the kind becomes theirs: they said yes to it."""
    view = known(db, business)
    if view.type_state == TypeState.GUESSED and view.direction is not None:
        set_kind(
            db,
            business=business,
            direction=view.direction,
            subtype=view.subtype,
            state=TypeState.CONFIRMED,
            source=KnowledgeSource.LAUNCH_AGENT,
            actor=user,
            now=now,
        )


def _confirm(
    db: Session, *, business: Business, user: User, brief: Brief, now: datetime
) -> None:
    """The questions are answered: a kind this conversation filed from the
    person's own words becomes theirs, and what they said the business does
    is kept. A kind read off the page is never settled here - only by their
    yes to it (:func:`_agree_kind`)."""
    view = known(db, business)
    if (
        brief.kind_set
        and view.type_state == TypeState.GUESSED
        and view.direction is not None
    ):
        set_kind(
            db,
            business=business,
            direction=view.direction,
            subtype=view.subtype,
            state=TypeState.CONFIRMED,
            source=KnowledgeSource.LAUNCH_AGENT,
            actor=user,
            now=now,
        )
    if brief.kind_said and not view.does:
        try:
            knowledge.apply(
                db,
                business=business,
                changes=[{"op": knowledge.SET_ABOUT, "text": brief.kind_said}],
                source=KnowledgeSource.LAUNCH_AGENT,
                actor=user,
                now=now,
            )
        except BadKnowledgeChange:
            logger.info("launch_agent_about_not_kept")


def _remember(
    db: Session, *, business: Business, user: User, brief: Brief, now: datetime
) -> Brief:
    """Offer the business's knowledge the thing this advert sells. It waits
    on the business's list: kept by itself once the advert is created
    (:func:`settle`), or answered by hand on the business's page."""
    if not brief.sold_name or brief.memo:
        return brief
    key = subtypes.level(brief.sold_name)
    view = known(db, business)
    held = next(
        (
            one
            for one in view.items
            if subtypes.level(str(one.get("name") or "")) == key
        ),
        None,
    )
    if held is not None and (
        not brief.sold_price or brief.sold_price == str(held.get("price") or "")
    ):
        return brief
    change: dict[str, Any] = {"op": knowledge.ADD_ITEM, "name": brief.sold_name}
    if brief.sold_price:
        change["price"] = brief.sold_price
    try:
        proposal = knowledge.propose(
            db,
            business=business,
            changes=[change],
            source=KnowledgeSource.LAUNCH_AGENT,
            actor=user,
            why="Reklama suhbatida aytilgan",
            now=now,
        )
    except BadKnowledgeChange:
        return brief
    return brief.with_(memo=str(proposal["id"])) if proposal is not None else brief


def settle(
    db: Session, *, user: User, session: LaunchAgentSession, now: datetime
) -> None:
    """The advert was created: the conversation is over, and what it sells
    is the business's knowledge now - advertising it was the yes. Flushes;
    safe to call again."""
    if session.status == SessionStatus.CLOSED:
        return
    brief = _brief(session)
    business = db.get(Business, session.business_id) if session.business_id else None
    if brief.memo and business is not None:
        try:
            with db.begin_nested():
                knowledge.confirm(
                    db,
                    business=business,
                    proposal_id=brief.memo,
                    actor=user,
                    now=now,
                )
        except DomainError:
            # Answered on the business's page meanwhile.
            logger.info("launch_agent_memo_gone", extra={"session": str(session.id)})
    session.status = SessionStatus.CLOSED
    session.updated_at = now
    db.flush()


def turn(
    db: Session,
    *,
    user: User,
    session: LaunchAgentSession,
    text: str = "",
    slot: str = "",
    value: str = "",
    asset_ids: list[str] | None = None,
    now: datetime,
) -> Staged:
    """One message or one press; caller commits. Raises a ``DomainError``
    the page shows as it is."""
    if session.status == SessionStatus.CLOSED:
        raise SessionClosed
    launch = _launch(db, session)
    if launch is None:
        # Dropped on the wizard's screens.
        session.status = SessionStatus.CLOSED
        raise SessionClosed
    if session.turns >= MAX_TURNS:
        raise TooManyTurns
    text = " ".join(str(text or "").split())
    if len(text) > MAX_TEXT_CHARS:
        raise TextTooLong(MAX_TEXT_CHARS)
    business = business_for_page(db, owner=user, page=launch.page)
    if business is None:
        raise SessionClosed
    frame = build_frame(db, launch=launch, user=user, business=business, now=now)
    brief = _brief(session)
    stage = stage_of(launch, brief_ready=is_ready(brief, frame))
    if slot in STAGE_SLOTS or stage not in (ASKING, MEDIA):
        return _past_the_questions(
            db,
            session=session,
            launch=launch,
            business=business,
            brief=brief,
            frame=frame,
            text=text,
            slot=slot,
            value=value,
            asset_ids=list(asset_ids or []),
            now=now,
        )
    waiting = next_slot(brief, frame)
    asked = ask_for(waiting, brief, frame) if waiting is not None else None

    if slot:
        listened = Listened(heard=_heard_button(slot, value))
        shown = next(
            (
                option.label
                for option in (asked.options if asked is not None else ())
                if option.slot == slot and option.value == value
            ),
            value,
        )
        _say(session, Author.USER, shown, now)
    else:
        plain = plain_answer(text, asked=asked, frame=frame, brief=brief)
        if plain is not None:
            listened = Listened(heard=plain)
        elif not text:
            listened = Listened(heard=Heard())
        else:
            if not hit(
                bucket=HEARD_BUCKET,
                key=str(user.id),
                limit=HEARD_PER_DAY,
                window_seconds=DAY_SECONDS,
            ):
                raise HeardLimit
            listened = listen(
                db,
                owner=user,
                session=session,
                text=text,
                asked=asked,
                brief=brief,
                frame=frame,
            )
            session.heard_calls += 1
        _say(session, Author.USER, text, now)

    if (
        (not frame.kind_known or kind_open(brief, frame))
        and listened.kind_direction
        and _set_kind_from(db, business=business, user=user, listened=listened, now=now)
    ):
        # Another kind of business is offered other goals and floors.
        kind_said = listened.heard.kind or text
        frame = build_frame(db, launch=launch, user=user, business=business, now=now)
        brief = brief.with_(kind_said=kind_said[:300], kind_set=True)

    if listened.sold_name:
        brief = brief.with_(
            sold_name=listened.sold_name[:80], sold_price=listened.sold_price[:60]
        )
    merged = merge(brief, listened.heard, frame)
    if merged.brief.kind_ok == KIND_YES and brief.kind_ok != KIND_YES:
        _agree_kind(db, business=business, user=user, now=now)
        frame = build_frame(db, launch=launch, user=user, business=business, now=now)
    brief, notes, lines = merged.brief, merged.notes, ()
    understood = listened.understood and (bool(merged.took) or bool(notes) or not text)
    ready = is_ready(brief, frame)
    if ready:
        brief, _none, lines = _save_plan(
            db, launch=launch, user=user, brief=brief, frame=frame, now=now
        )
        ready = is_ready(brief, frame)
    if ready:
        _confirm(db, business=business, user=user, brief=brief, now=now)
        brief = _remember(db, business=business, user=user, brief=brief, now=now)
    session.status = SessionStatus.READY if ready else SessionStatus.OPEN
    session.turns += 1
    session.updated_at = now
    _keep(session, brief)
    said = reply(brief, frame, notes=notes, understood=understood or bool(lines))
    if lines:
        said = Reply(
            lines=(*lines, *said.lines),
            ask=said.ask,
            chips=said.chips,
            ready=said.ready,
        )
    out = _placed(db, launch=launch, said=said)
    _say(session, Author.AGENT, _spoken(out.reply), now)
    db.flush()
    return out


def _past_the_questions(
    db: Session,
    *,
    session: LaunchAgentSession,
    launch: CampaignLaunch,
    business: Business,
    brief: Brief,
    frame: Frame,
    text: str,
    slot: str,
    value: str,
    asset_ids: list[str],
    now: datetime,
) -> Staged:
    """A turn once the questions are answered: a press is carried out by
    the wizard's own service; words change nothing any more, and cost no
    model call."""
    if slot in STAGE_SLOTS:
        lines = press(
            db,
            launch=launch,
            business=business,
            slot=slot,
            value=value,
            asset_ids=asset_ids,
        )
        # The press commits or rolls back on its own: the row is read again.
        db.refresh(session)
    else:
        lines = (SETTLED,) if text or slot else ()
        _say(session, Author.USER, text, now)
    out = staged(db, launch=launch, base=reply(brief, frame), lines=lines)
    session.status = SessionStatus.READY
    session.turns += 1
    session.updated_at = now
    _say(session, Author.AGENT, _spoken(out.reply), now)
    db.flush()
    return out


def current(
    db: Session, *, user: User, session: LaunchAgentSession, now: datetime
) -> Staged:
    """Where the conversation stands, for a page opened again or asking
    whether the preparation has finished."""
    launch = _launch(db, session)
    business = (
        business_for_page(db, owner=user, page=launch.page)
        if launch is not None
        else None
    )
    if launch is None or business is None:
        return Staged(reply=Reply(), stage=ASKING)
    frame = build_frame(db, launch=launch, user=user, business=business, now=now)
    return _placed(db, launch=launch, said=reply(_brief(session), frame))


def close(db: Session, *, session: LaunchAgentSession, now: datetime) -> None:
    session.status = SessionStatus.CLOSED
    session.updated_at = now
    db.flush()


__all__ = [
    "NEXT_MEDIA",
    "DomainError",
    "close",
    "current",
    "session_for",
    "settle",
    "start",
    "turn",
]
