"""What happened on one account, from every log that keeps it, newest first.

Three logs answer: ``action_logs`` (changes with who made them and how they
ended), ``events`` (the account's milestones: sign-ins, payments, pages, cards)
and the office's own rows. Where both of the first two tell the same change,
the action log speaks, because it knows the actor and the outcome; the
event names it repeats are left out. ``lead.created`` is left out too: a lead
is not something the customer did, and it would bury the rest; so is a card
laid on the board for it.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.audit.constants import (
    ACTION_STATUS_LABELS,
    ACTION_TYPE_LABELS,
    EVENT_NAME_LABELS,
    ActionStatus,
    ActorType,
    EventName,
)
from app.modules.audit.models import ActionLog, Event
from app.modules.backoffice.constants import READ_KINDS
from app.modules.backoffice.models import StaffAction
from app.modules.backoffice.selectors import kind_label

FEED_PAGE = 50
GROUPS = (
    "akkaunt",
    "tolov",
    "ulanish",
    "reklama",
    "crm",
    "aloqa",
    "sotuv",
    "kontent",
    "ofis",
)
WHO = ("customer", "manager", "system", "agent", "staff")
_EVENT_GROUPS = {
    "user": "akkaunt",
    "business": "akkaunt",
    "setup": "akkaunt",
    "invoice": "tolov",
    "payment": "tolov",
    "subscription": "tolov",
    "promo": "tolov",
    "wallet": "tolov",
    "referral": "tolov",
    "withdrawal": "tolov",
    "connection": "ulanish",
    "page": "ulanish",
    "account": "ulanish",
    "google_account": "ulanish",
    "instagram": "ulanish",
    "sheet": "ulanish",
    "campaign": "reklama",
    "adset": "reklama",
    "ad": "reklama",
    "budget": "reklama",
    "launch": "reklama",
    "targeting": "reklama",
    "creative": "reklama",
    "delivery": "reklama",
    "ads": "reklama",
    "audience": "reklama",
    "media": "reklama",
    "agent": "reklama",
    "leads": "reklama",
    "crm": "crm",
    "support": "aloqa",
    "feedback": "aloqa",
    "feedback_prompt": "aloqa",
    "survey": "aloqa",
    "sales": "sotuv",
    "montage": "kontent",
}
_ACTION_GROUPS = {
    "sheet": "ulanish",
    "support": "aloqa",
    "montage": "kontent",
    "sales": "sotuv",
    "crm": "crm",
}
# Told by the action log already, with its actor and outcome.
_TOLD_TWICE = frozenset(
    {
        EventName.LEAD_CREATED,
        EventName.CAMPAIGN_CREATED,
        EventName.CAMPAIGN_ACTIVATED,
        EventName.CAMPAIGN_PAUSED,
        EventName.CAMPAIGN_DELETED,
        EventName.ADSET_CREATED,
        EventName.ADSET_DELETED,
        EventName.AD_CREATED,
        EventName.AD_DELETED,
        EventName.BUDGET_CHANGED,
        EventName.TARGETING_CHANGED,
        EventName.CREATIVE_CHANGED,
        EventName.MEDIA_UPLOADED,
        EventName.MEDIA_DELETED,
        EventName.AUDIENCE_CREATED,
        EventName.AUDIENCE_FILLED,
        EventName.AUDIENCE_DELETED,
        EventName.AUDIENCE_MEMBERS_REMOVED,
        EventName.LEADS_ANONYMIZED,
        EventName.SHEET_CONNECTED,
        EventName.SHEET_DISCONNECTED,
        EventName.SHEET_RECREATED,
        EventName.SHEET_PICKED,
        EventName.SUPPORT_CONVERSATION_OPENED,
        EventName.SUPPORT_MESSAGE_POSTED,
        EventName.SUPPORT_CONVERSATION_SETTLED,
        EventName.SUPPORT_MESSAGE_EDITED,
        EventName.SUPPORT_MESSAGE_DELETED,
        EventName.MONTAGE_REQUESTED,
        EventName.MONTAGE_BRAND_SAVED,
        EventName.MONTAGE_DELETED,
        EventName.CRM_SETUP_SAVED,
        EventName.CRM_MEMBER_SAVED,
        EventName.CRM_MEMBER_REMOVED,
        EventName.CRM_ERASED,
        EventName.SALES_ARIZAS_ADOPTED,
        # A lead landing on the board is the lead arriving, not anyone acting.
        EventName.CRM_CARD_PLACED,
    }
)
_LEVEL_WORDS = {
    "campaign": "kampaniya",
    "adset": "guruh",
    "ad": "reklama",
    "account": "kabinet",
    "audience": "auditoriya",
    "member": "menejer",
    "setup": "sozlama",
    "stage": "ustun",
    "reason": "rad sababi",
    "card": "karta",
    "crm": "CRM",
}


@dataclass(frozen=True)
class FeedRow:
    id: str
    source: str
    at: datetime
    group: str
    title: str
    text: str
    who: str
    who_name: str
    status: str
    status_label: str
    error: str
    detail: dict[str, Any]


@dataclass(frozen=True)
class FeedPage:
    rows: list[FeedRow]
    next_before: datetime | None


def event_group(name: str) -> str:
    return _EVENT_GROUPS.get(name.split(".", 1)[0], "akkaunt")


def action_group(action: str) -> str:
    return _ACTION_GROUPS.get(action.split("_", 1)[0], "reklama")


def _names_in(group: str) -> list[str]:
    return [
        str(name)
        for name in EventName
        if event_group(str(name)) == group and name not in _TOLD_TWICE
    ]


def _actions_in(group: str) -> list[str]:
    return [str(a) for a in ACTION_TYPE_LABELS if action_group(str(a)) == group]


def activity(
    db: Session,
    *,
    owner: User,
    group: str = "",
    who: str = "",
    before: datetime | None = None,
    limit: int = FEED_PAGE,
) -> FeedPage:
    logins = {
        login.id: login
        for login in db.scalars(select(User).where(User.crm_owner_id == owner.id))
    }
    rows = [
        *_actions(
            db,
            owner=owner,
            logins=logins,
            group=group,
            who=who,
            before=before,
            limit=limit,
        ),
        *_events(db, owner=owner, group=group, who=who, before=before, limit=limit),
        *_office(db, owner=owner, group=group, who=who, before=before, limit=limit),
    ]
    rows.sort(key=lambda row: row.at, reverse=True)
    page = rows[:limit]
    more = len(rows) > limit
    return FeedPage(rows=page, next_before=page[-1].at if more and page else None)


def _actions(
    db: Session,
    *,
    owner: User,
    logins: dict[uuid.UUID, User],
    group: str,
    who: str,
    before: datetime | None,
    limit: int,
) -> list[FeedRow]:
    if group == "ofis" or who == "staff":
        return []
    query = select(ActionLog).where(ActionLog.owner_id == owner.id)
    if group:
        query = query.where(ActionLog.action.in_(_actions_in(group)))
    if who == "customer":
        query = query.where(
            ActionLog.actor_type == ActorType.USER, ActionLog.actor_id == owner.id
        )
    elif who == "manager":
        query = query.where(ActionLog.actor_id.in_(list(logins)))
    elif who in ("system", "agent"):
        query = query.where(ActionLog.actor_type == who)
    if before is not None:
        query = query.where(ActionLog.created_at < before)
    found = list(
        db.scalars(query.order_by(ActionLog.created_at.desc()).limit(limit + 1))
    )
    others = {row.actor_id for row in found if row.actor_id} - {owner.id, *logins}
    staff = (
        {user.id: user for user in db.scalars(select(User).where(User.id.in_(others)))}
        if others
        else {}
    )
    return [_action_row(row, owner=owner, logins=logins, staff=staff) for row in found]


def _action_row(
    row: ActionLog,
    *,
    owner: User,
    logins: dict[uuid.UUID, User],
    staff: dict[uuid.UUID, User],
) -> FeedRow:
    title = ACTION_TYPE_LABELS.get(row.action, row.action)  # type: ignore[call-overload]
    level = _LEVEL_WORDS.get(row.target_level, row.target_level)
    if row.action == "crm_change" and level:
        title = f"{title}: {level}"
    actor, name = _actor(row, owner=owner, logins=logins, staff=staff)
    text = " · ".join(
        part
        for part in (
            f"{level} {row.target_external_id}"
            if row.target_external_id and row.action != "crm_change"
            else "",
            row.reason,
            "sinov rejimi" if row.dry_run else "",
        )
        if part
    )
    return FeedRow(
        id=f"action:{row.id}",
        source="action",
        at=row.created_at,
        group=action_group(row.action),
        title=title,
        text=text,
        who=actor,
        who_name=name,
        status=row.status,
        status_label=ACTION_STATUS_LABELS.get(row.status, row.status),  # type: ignore[call-overload]
        error=row.error_message or row.error_code,
        detail={
            "request": row.request_payload or {},
            "before": row.previous_state or {},
            "result": row.result_payload or {},
        },
    )


def _actor(
    row: ActionLog,
    *,
    owner: User,
    logins: dict[uuid.UUID, User],
    staff: dict[uuid.UUID, User],
) -> tuple[str, str]:
    if row.actor_type == ActorType.SYSTEM:
        return "system", "Tizim"
    if row.actor_type == ActorType.AGENT:
        return "agent", "AI agent"
    if row.actor_id == owner.id:
        return "customer", owner.full_name or owner.email
    login = logins.get(row.actor_id) if row.actor_id else None
    if login is not None:
        return "manager", login.full_name or login.email
    if row.actor_id is None:
        return "customer", owner.full_name or owner.email
    person = staff.get(row.actor_id)
    return "staff", (person.full_name or person.email) if person else "Ofis xodimi"


def _events(
    db: Session,
    *,
    owner: User,
    group: str,
    who: str,
    before: datetime | None,
    limit: int,
) -> list[FeedRow]:
    if group == "ofis" or who in ("staff", "system", "agent"):
        return []
    names = (
        _names_in(group)
        if group
        else [str(n) for n in EventName if n not in _TOLD_TWICE]
    )
    query = select(Event).where(Event.owner_id == owner.id, Event.name.in_(names))
    member = Event.payload["member_id"].as_string()
    if who == "manager":
        query = query.where(member.is_not(None))
    elif who == "customer":
        query = query.where(
            Event.name.like("user.%"), or_(member.is_(None), member == "")
        )
    if before is not None:
        query = query.where(Event.occurred_at < before)
    found = db.scalars(query.order_by(Event.occurred_at.desc()).limit(limit + 1))
    return [_event_row(row, owner=owner) for row in found]


def _event_row(row: Event, *, owner: User) -> FeedRow:
    payload = row.payload if isinstance(row.payload, dict) else {}
    if payload.get("member"):
        who, name = "manager", str(payload["member"])
    elif row.name.startswith("user."):
        who, name = "customer", owner.full_name or owner.email
    else:
        who, name = "", ""
    return FeedRow(
        id=f"event:{row.id}",
        source="event",
        at=row.occurred_at,
        group=event_group(row.name),
        title=EVENT_NAME_LABELS.get(row.name, row.name),  # type: ignore[call-overload]
        text=_event_text(row.name, payload),
        who=who,
        who_name=name,
        status=ActionStatus.APPLIED,
        status_label="",
        error="",
        detail=payload,
    )


def _event_text(name: str, payload: dict[str, Any]) -> str:
    """The one or two facts a reader looks for first; the rest is in ``detail``."""
    parts = []
    if name == EventName.USER_SIGNED_IN:
        parts.append(
            {"password": "parol bilan", "miniapp": "Telegram Mini App"}.get(
                str(payload.get("via")), str(payload.get("via", ""))
            )
        )
    for key in ("plan", "provider", "stage", "number", "external_id"):
        value = payload.get(key)
        if value and isinstance(value, str | int):
            parts.append(str(value))
    if payload.get("amount_minor") and payload.get("currency"):
        parts.append(f"{int(payload['amount_minor']) / 100:,.0f} {payload['currency']}")
    return " · ".join(p for p in parts if p)


def _office(
    db: Session,
    *,
    owner: User,
    group: str,
    who: str,
    before: datetime | None,
    limit: int,
) -> list[FeedRow]:
    if (group and group != "ofis") or (who and who != "staff"):
        return []
    query = select(StaffAction).where(
        StaffAction.owner_id == owner.id,
        StaffAction.kind.not_in([str(kind) for kind in READ_KINDS]),
    )
    if before is not None:
        query = query.where(StaffAction.created_at < before)
    found = db.scalars(query.order_by(StaffAction.created_at.desc()).limit(limit + 1))
    return [
        FeedRow(
            id=f"office:{row.id}",
            source="office",
            at=row.created_at,
            group="ofis",
            title=kind_label(row.kind),
            text=row.reason,
            who="staff",
            who_name=(row.actor.full_name or row.actor.email) if row.actor else "",
            status=ActionStatus.APPLIED,
            status_label="",
            error="",
            detail=row.detail or {},
        )
        for row in found
    ]


__all__ = ["FEED_PAGE", "GROUPS", "WHO", "FeedPage", "FeedRow", "activity"]
