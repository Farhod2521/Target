"""Tying the office to its exchange: the login, the internal numbers and
who answers each, and the address the exchange sends events to."""

import logging
import secrets
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.common import crypto
from app.common.config import settings
from app.common.db import utcnow
from app.common.deletion import delete_rows
from app.modules.accounts.models import User
from app.modules.telephony import calls, utel
from app.modules.telephony.constants import (
    CALL_ID_MAX,
    CALL_SAVED,
    ERROR_MAX,
    EVENT_NAME_MAX,
    FIRST_BACKFILL_DAYS,
    HOOK_KEY_BYTES,
    HOOK_PATH,
    NUMBER_MAX,
    SIP_SOCKET,
    TENANT_SHAPE,
    TITLE_MAX,
    UTEL_ZONE,
    Provider,
)
from app.modules.telephony.exceptions import (
    ExchangeRefusedLogin,
    ExchangeSessionEnded,
    ExchangeUnreachable,
    ExtensionGone,
    ExtensionNotFound,
    NotConnected,
    NotStaff,
    TenantShape,
)
from app.modules.telephony.models import PhoneConnection, PhoneExtension, PhoneHookEvent

logger = logging.getLogger(__name__)


def tenant_of(value: str) -> str:
    """``utc181`` out of whatever was pasted: the name, the address, a link."""
    words = value.strip().lower()
    for prefix in ("https://", "http://", "wss://"):
        words = words.removeprefix(prefix)
    words = words.split("/", 1)[0].split(":", 1)[0]
    words = words.removeprefix("api.").removesuffix(f".{UTEL_ZONE}")
    if not TENANT_SHAPE.fullmatch(words):
        raise TenantShape
    return words


def office_connection(db: Session, *, lock: bool = False) -> PhoneConnection | None:
    query = select(PhoneConnection).where(
        PhoneConnection.owner_id.is_(None),
        PhoneConnection.provider == str(Provider.UTEL),
    )
    if lock:
        query = query.with_for_update()
    return db.scalar(query)


def _connected(db: Session) -> PhoneConnection:
    found = office_connection(db, lock=True)
    if found is None:
        raise NotConnected
    return found


def hook_url(connection: PhoneConnection) -> str:
    return settings.site_url + HOOK_PATH.format(key=connection.hook_key)


def _ask[T](connection: PhoneConnection, ask: Callable[[str], T]) -> T:
    """One question to the exchange with the kept key."""
    try:
        return ask(crypto.decrypt(connection.api_token))
    except utel.Refused as exc:
        raise ExchangeSessionEnded from exc
    except utel.Unreachable as exc:
        raise ExchangeUnreachable from exc


def _pull(db: Session, connection: PhoneConnection, *, now: datetime) -> None:
    """The exchange's internal numbers as they are now. A number it no
    longer lists stays, marked gone and taken from its person."""
    listed = _ask(
        connection, lambda token: utel.extensions(connection.tenant, token=token)
    )
    kept = {
        row.number: row
        for row in db.scalars(
            select(PhoneExtension).where(PhoneExtension.connection_id == connection.id)
        )
    }
    seen: set[str] = set()
    for found in listed:
        number = found.number[:NUMBER_MAX]
        if number in seen:
            continue
        seen.add(number)
        row = kept.get(number)
        if row is None:
            row = PhoneExtension(connection_id=connection.id, number=number)
            db.add(row)
        row.title = found.title[:TITLE_MAX]
        row.sip_password = crypto.encrypt(found.password)
        row.is_gone = False
    for number, row in kept.items():
        if number not in seen:
            row.is_gone = True
            row.user_id = None
    connection.synced_at = now


def _set_hook(connection: PhoneConnection, *, now: datetime) -> None:
    """Our address among those the exchange sends events to, with every
    event on. The others on its list are sent back as they were: the list
    is replaced whole."""
    ours = hook_url(connection)
    prefix = settings.site_url + HOOK_PATH.format(key="")

    def put(token: str) -> None:
        others = [
            row
            for row in utel.hooks(connection.tenant, token=token)
            if not str(row.get("url") or "").startswith(prefix)
        ]
        utel.put_hooks(
            connection.tenant, token=token, rows=[*others, utel.hook_row(ours)]
        )

    _ask(connection, put)
    connection.hook_set_at = now


def _try_hook(connection: PhoneConnection, *, now: datetime) -> None:
    try:
        _set_hook(connection, now=now)
        connection.last_error = ""
    except (ExchangeSessionEnded, ExchangeUnreachable) as exc:
        connection.hook_set_at = None
        connection.last_error = exc.message[:ERROR_MAX]


def connect(
    db: Session, *, tenant: str, email: str, password: str, actor: User
) -> None:
    """Sign in to the exchange, keep its key, read the numbers and ask for
    events. A second sign-in to the same exchange keeps who answers what;
    another exchange starts the numbers anew."""
    name = tenant_of(tenant)
    try:
        token = utel.login(name, email=email.strip(), password=password)
    except utel.Refused as exc:
        raise ExchangeRefusedLogin from exc
    except utel.Unreachable as exc:
        raise ExchangeUnreachable from exc
    now = utcnow()
    connection = office_connection(db, lock=True)
    if connection is not None and connection.tenant != name:
        _forget_hook(connection)
        delete_rows(db, PhoneConnection.__table__, PhoneConnection.id == connection.id)
        db.flush()
        db.expunge(connection)
        connection = None
    if connection is None:
        connection = PhoneConnection(
            provider=str(Provider.UTEL),
            tenant=name,
            hook_key=secrets.token_urlsafe(HOOK_KEY_BYTES),
            api_email="",
            api_token=b"",
        )
        db.add(connection)
    connection.api_email = email.strip()
    connection.api_token = crypto.encrypt(token)
    connection.connected_by_id = actor.id
    db.flush()
    _pull(db, connection, now=now)
    _try_hook(connection, now=now)
    db.commit()
    logger.info("telephony connected: %s by %s", name, actor.id)
    from app.modules.telephony.tasks import backfill_calls_task

    backfill_calls_task.delay(FIRST_BACKFILL_DAYS * 24)


def sync(db: Session) -> None:
    connection = _connected(db)
    _pull(db, connection, now=utcnow())
    db.commit()


def set_hook(db: Session) -> None:
    connection = _connected(db)
    _set_hook(connection, now=utcnow())
    connection.last_error = ""
    db.commit()


def _forget_hook(connection: PhoneConnection) -> None:
    """Take our address off the exchange's list. Leaving it there is
    harmless - the key stops opening anything - so a failure is let go."""
    prefix = settings.site_url + HOOK_PATH.format(key="")

    def put(token: str) -> None:
        rows = utel.hooks(connection.tenant, token=token)
        others = [
            row for row in rows if not str(row.get("url") or "").startswith(prefix)
        ]
        if len(others) != len(rows):
            utel.put_hooks(connection.tenant, token=token, rows=others)

    try:
        _ask(connection, put)
    except (ExchangeSessionEnded, ExchangeUnreachable):
        logger.warning("telephony: our hook stays on %s", connection.tenant)


def disconnect(db: Session, *, actor: User) -> None:
    connection = _connected(db)
    _forget_hook(connection)
    delete_rows(db, PhoneConnection.__table__, PhoneConnection.id == connection.id)
    db.commit()
    logger.info("telephony disconnected: %s by %s", connection.tenant, actor.id)


def assign(
    db: Session,
    *,
    extension_id: uuid.UUID,
    changes: dict[str, Any],
) -> None:
    """Who answers a number, and whether they call from the browser. A
    person given a number leaves the one they held."""
    connection = _connected(db)
    row = db.scalar(
        select(PhoneExtension)
        .where(
            PhoneExtension.id == extension_id,
            PhoneExtension.connection_id == connection.id,
        )
        .with_for_update()
    )
    if row is None:
        raise ExtensionNotFound
    if "user_id" in changes:
        user_id = changes["user_id"]
        if user_id is None:
            row.user_id = None
        else:
            if row.is_gone:
                raise ExtensionGone
            person = db.get(User, user_id)
            if person is None or not person.is_staff or not person.is_active:
                raise NotStaff
            held = db.scalar(
                select(PhoneExtension).where(
                    PhoneExtension.connection_id == connection.id,
                    PhoneExtension.user_id == person.id,
                    PhoneExtension.id != row.id,
                )
            )
            if held is not None:
                held.user_id = None
                # The unique index is checked row by row: empty first.
                db.flush()
            row.user_id = person.id
    if changes.get("softphone") is not None:
        row.softphone = bool(changes["softphone"])
    db.commit()


def _person(user: User) -> dict[str, str]:
    return {
        "id": str(user.id),
        "name": user.full_name or user.email,
        "email": user.email,
    }


def state(db: Session, *, now: datetime) -> dict[str, Any]:
    """The settings page. No key, password or hook address leaves here."""
    staff = list(
        db.scalars(
            select(User)
            .where(User.is_staff.is_(True), User.is_active.is_(True))
            .order_by(User.full_name, User.email)
        )
    )
    people = {person.id: person for person in staff}
    connection = office_connection(db)
    if connection is None:
        return {
            "connected": False,
            "connection": None,
            "extensions": [],
            "staff": [_person(person) for person in staff],
        }
    rows = sorted(
        db.scalars(
            select(PhoneExtension).where(PhoneExtension.connection_id == connection.id)
        ),
        key=lambda row: (row.is_gone, len(row.number), row.number),
    )
    last_event, day_events = db.execute(
        select(
            func.max(PhoneHookEvent.received_at),
            func.count().filter(PhoneHookEvent.received_at >= now - timedelta(days=1)),
        ).where(PhoneHookEvent.connection_id == connection.id)
    ).one()
    return {
        "connected": True,
        "connection": {
            "tenant": connection.tenant,
            "api_email": connection.api_email,
            "connected_at": connection.created_at,
            "synced_at": connection.synced_at,
            "sip_domain": f"{connection.tenant}.{UTEL_ZONE}",
            "sip_socket": SIP_SOCKET.format(tenant=connection.tenant),
            "hook_set_at": connection.hook_set_at,
            "last_event_at": last_event,
            "events_last_day": int(day_events or 0),
            "last_error": connection.last_error,
        },
        "extensions": [
            {
                "id": str(row.id),
                "number": row.number,
                "title": row.title,
                "user": _person(people[row.user_id]) if row.user_id in people else None,
                "softphone": row.softphone,
                "is_gone": row.is_gone,
            }
            for row in rows
        ],
        "staff": [_person(person) for person in staff],
    }


def _text(value: object, limit: int) -> str:
    return value[:limit] if isinstance(value, str) else ""


def keep_event(db: Session, *, key: str, payload: dict[str, Any]) -> bool:
    """Write down what the exchange sent. False: the key opens nothing.

    Two shapes come: the event under ``data``, or at the top."""
    connection = db.scalar(
        select(PhoneConnection).where(PhoneConnection.hook_key == key)
    )
    if connection is None:
        return False
    inner = payload.get("data")
    data: dict[str, Any] = inner if isinstance(inner, dict) else payload
    call = data.get("call")
    saved = data.get("call_history")
    call_id = ""
    if isinstance(saved, dict):
        call_id = _text(saved.get("call_id"), CALL_ID_MAX)
    if not call_id and isinstance(call, dict):
        call_id = _text(call.get("id"), CALL_ID_MAX)
    name = _text(data.get("name"), EVENT_NAME_MAX)
    db.add(
        PhoneHookEvent(
            connection_id=connection.id, name=name, call_id=call_id, payload=payload
        )
    )
    db.commit()
    if name == CALL_SAVED and isinstance(saved, dict):
        # The event is kept whatever happens here; a call that fails to be
        # read out of it is brought by the hourly read of UTeL's history.
        try:
            calls.record(db, connection=connection, item=saved, now=utcnow())
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("telephony: call %s not kept from its event", call_id)
    return True
