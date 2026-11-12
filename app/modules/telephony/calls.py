"""Finished calls: read out of what the exchange sends, kept once each,
and shown on the journal and on a client's card."""

import logging
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import ColumnElement, and_, delete, exists, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.common import crypto
from app.modules.accounts.models import User
from app.modules.telephony import utel
from app.modules.telephony.constants import (
    BACKFILL_PAGES_MAX,
    CALL_ID_MAX,
    CALL_SEARCH_MAX,
    CARD_CALLS,
    COUNTRY_PREFIX,
    DIRECTION_LABELS,
    EXCHANGE_ZONE,
    EXTENSION_DIGITS_MAX,
    HOOK_EVENTS_KEEP_DAYS,
    LINE_MAX,
    LOCAL_DIGITS,
    NUMBER_MAX,
    PHONE_MAX,
    RECORDING_MAX_BYTES,
    RECORDING_TIMEOUT_SECONDS,
    URL_MAX,
    UTEL_ZONE,
    CallScope,
    Direction,
)
from app.modules.telephony.exceptions import CallNotFound, NoRecording
from app.modules.telephony.models import (
    PhoneCall,
    PhoneConnection,
    PhoneExtension,
    PhoneHookEvent,
)

logger = logging.getLogger(__name__)
ZONE = ZoneInfo(EXCHANGE_ZONE)


def _digits(value: object) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def is_extension(value: object) -> bool:
    digits = _digits(value)
    return 2 <= len(digits) <= EXTENSION_DIGITS_MAX


def as_phone(value: object) -> str:
    """A number the way a client's phone is kept: ``+998901234567``.

    The exchange writes ``998901234567``, ``901234567`` or with a plus.
    Nine digits are a local number whatever they begin with: ``998`` also
    opens some operators' numbers, so it is cut only from a longer one."""
    digits = _digits(value)
    if len(digits) == LOCAL_DIGITS:
        digits = COUNTRY_PREFIX + digits
    if len(digits) < LOCAL_DIGITS:
        return digits
    return ("+" + digits)[:PHONE_MAX]


@dataclass(frozen=True, slots=True)
class Finished:
    call_id: str
    direction: Direction
    answered: bool
    number: str
    extension: str
    line: str
    started_at: datetime
    duration_seconds: int
    talk_seconds: int
    recording_url: str


def _named(value: object) -> tuple[str, int]:
    """``{"number": 1, "name": "Incoming"}``, or the bare word or number."""
    if isinstance(value, dict):
        number = value.get("number")
        return str(value.get("name") or "").lower(), (
            number if isinstance(number, int) else 0
        )
    if isinstance(value, int):
        return "", value
    return str(value or "").lower(), 0


def _direction(kind: object, src: str, dst: str) -> Direction | None:
    """In or out; None for a call between two internal numbers."""
    name, number = _named(kind)
    if (name.startswith("in") and not name.startswith("int")) or number == 1:
        return Direction.IN
    if name.startswith("out") or number == 2:
        return Direction.OUT
    if name.startswith("int") or number == 3:
        return None
    if is_extension(src) and not is_extension(dst):
        return Direction.OUT
    if is_extension(dst) and not is_extension(src):
        return Direction.IN
    return None


def _seconds(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return 0
    try:
        whole = int(float(value))
    except ValueError:
        return 0
    return max(0, min(whole, 24 * 3600))


def _moment(value: object, *, now: datetime) -> datetime:
    try:
        return datetime.strptime(str(value), utel.HISTORY_TIME).replace(tzinfo=ZONE)
    except ValueError:
        return now


def _recording(value: object, *, tenant: str) -> str:
    """UTeL's link, kept only if it is the exchange's own address."""
    url = str(value or "")[:URL_MAX]
    parts = urlsplit(url)
    if parts.scheme == "https" and parts.netloc == f"api.{tenant}.{UTEL_ZONE}":
        return url
    return ""


def finished(item: dict[str, Any], *, tenant: str, now: datetime) -> Finished | None:
    """One ``call_history`` row. None: nothing to keep - no id, a call
    between colleagues, or no outside number in it."""
    call_id = str(item.get("call_id") or "")[:CALL_ID_MAX]
    src, dst = str(item.get("src") or ""), str(item.get("dst") or "")
    direction = _direction(item.get("type"), src, dst)
    if not call_id or direction is None:
        return None
    outside, inside = (src, dst) if direction is Direction.IN else (dst, src)
    number = as_phone(outside)
    if not number:
        return None
    status, code = _named(item.get("status"))
    talk = _seconds(item.get("conversation"))
    return Finished(
        call_id=call_id,
        direction=direction,
        answered=(status == "answered" or code == 1) if (status or code) else talk > 0,
        number=number,
        extension=_digits(inside)[:NUMBER_MAX] if is_extension(inside) else "",
        line=_digits(item.get("external_number"))[:LINE_MAX],
        started_at=_moment(item.get("date_time"), now=now),
        duration_seconds=_seconds(item.get("duration")),
        talk_seconds=talk,
        recording_url=_recording(item.get("recorded_file_url"), tenant=tenant),
    )


def record(
    db: Session, *, connection: PhoneConnection, item: dict[str, Any], now: datetime
) -> bool:
    """Keep a finished call. The exchange may say it twice - again by the
    hook, or in the hourly read - and the later word replaces the earlier.
    The person is whoever holds the internal number now, written once."""
    call = finished(item, tenant=connection.tenant, now=now)
    if call is None:
        return False
    user_id = None
    if call.extension:
        user_id = db.scalar(
            select(PhoneExtension.user_id).where(
                PhoneExtension.connection_id == connection.id,
                PhoneExtension.number == call.extension,
            )
        )
    values = {
        "direction": str(call.direction),
        "answered": call.answered,
        "number": call.number,
        "extension": call.extension,
        "line": call.line,
        "started_at": call.started_at,
        "duration_seconds": call.duration_seconds,
        "talk_seconds": call.talk_seconds,
        "recording_url": call.recording_url,
    }
    statement = insert(PhoneCall).values(
        id=uuid.uuid4(),
        created_at=now,
        connection_id=connection.id,
        call_id=call.call_id,
        user_id=user_id,
        **values,
    )
    db.execute(
        statement.on_conflict_do_update(
            index_elements=["connection_id", "call_id"],
            set_=values
            | {"user_id": func.coalesce(PhoneCall.user_id, statement.excluded.user_id)},
        )
    )
    return True


def backfill(
    db: Session, *, connection: PhoneConnection, since: datetime, now: datetime
) -> int:
    """Read the exchange's own history for the calls a hook did not bring.
    Raises ``utel.Refused`` or ``utel.Unreachable``; what was read is kept."""
    token = crypto.decrypt(connection.api_token)
    kept = 0
    page = 1
    while page <= BACKFILL_PAGES_MAX:
        rows, last = utel.call_history(
            connection.tenant,
            token=token,
            start=since.astimezone(ZONE),
            end=(now + timedelta(minutes=1)).astimezone(ZONE),
            page=page,
        )
        for row in rows:
            kept += record(db, connection=connection, item=row, now=now)
        db.commit()
        if page >= last or not rows:
            break
        page += 1
    return kept


def forget_old_events(db: Session, *, now: datetime) -> int:
    done = db.execute(
        delete(PhoneHookEvent).where(
            PhoneHookEvent.received_at < now - timedelta(days=HOOK_EVENTS_KEEP_DAYS)
        )
    )
    db.commit()
    return int(done.rowcount or 0)  # type: ignore[attr-defined]


def _is_client() -> ColumnElement[bool]:
    """Somebody who signed up, not staff, keeps this call's number."""
    return exists().where(
        User.phone == PhoneCall.number, User.phone != "", User.is_staff.is_(False)
    )


def _person(user: User | None) -> dict[str, str] | None:
    if user is None:
        return None
    return {
        "id": str(user.id),
        "name": user.full_name or user.email,
        "email": user.email,
    }


def _shown(call: PhoneCall, *, staff: dict[uuid.UUID, User]) -> dict[str, Any]:
    direction = Direction(call.direction)
    return {
        "id": str(call.id),
        "direction": call.direction,
        "direction_label": str(DIRECTION_LABELS[direction]),
        "answered": call.answered,
        "number": call.number,
        "started_at": call.started_at,
        "duration_seconds": call.duration_seconds,
        "talk_seconds": call.talk_seconds,
        "extension": call.extension,
        "staff": _person(staff.get(call.user_id)) if call.user_id else None,
        "has_recording": bool(call.recording_url),
    }


def _staff_of(db: Session, calls: list[PhoneCall]) -> dict[uuid.UUID, User]:
    ids = {call.user_id for call in calls if call.user_id}
    if not ids:
        return {}
    return {
        person.id: person for person in db.scalars(select(User).where(User.id.in_(ids)))
    }


def for_client(db: Session, *, owner: User) -> list[dict[str, Any]]:
    """The calls with this client's number, newest first, for their card."""
    if not owner.phone:
        return []
    calls = list(
        db.scalars(
            select(PhoneCall)
            .where(PhoneCall.number == owner.phone)
            .order_by(PhoneCall.started_at.desc(), PhoneCall.id)
            .limit(CARD_CALLS)
        )
    )
    staff = _staff_of(db, calls)
    return [_shown(call, staff=staff) for call in calls]


def _may_see(*, viewer: User, sees_all: bool) -> ColumnElement[bool] | None:
    """Leads and the owner see every call; anybody else their own and the
    ones nobody answered, which are anybody's to call back."""
    if sees_all:
        return None
    return or_(
        PhoneCall.user_id == viewer.id,
        and_(PhoneCall.user_id.is_(None), PhoneCall.answered.is_(False)),
    )


def journal(
    db: Session,
    *,
    viewer: User,
    sees_all: bool,
    scope: CallScope,
    direction: Direction | None,
    answered: bool | None,
    mine: bool,
    q: str,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    from app.modules.boards.models import BoardCard

    where: list[ColumnElement[bool]] = []
    allowed = _may_see(viewer=viewer, sees_all=sees_all)
    if allowed is not None:
        where.append(allowed)
    if scope is CallScope.KNOWN:
        where.append(_is_client())
    elif scope is CallScope.UNKNOWN:
        where.append(~_is_client())
    if direction is not None:
        where.append(PhoneCall.direction == str(direction))
    if answered is not None:
        where.append(PhoneCall.answered.is_(answered))
    if mine:
        where.append(PhoneCall.user_id == viewer.id)
    digits = _digits(q)[:CALL_SEARCH_MAX]
    if digits:
        where.append(PhoneCall.number.like(f"%{digits}%"))
    total = int(
        db.scalar(select(func.count()).select_from(PhoneCall).where(*where)) or 0
    )
    calls = list(
        db.scalars(
            select(PhoneCall)
            .where(*where)
            .order_by(PhoneCall.started_at.desc(), PhoneCall.id)
            .limit(limit)
            .offset(offset)
        )
    )
    staff = _staff_of(db, calls)
    numbers = {call.number for call in calls}
    clients: dict[str, list[User]] = {}
    if numbers:
        for person in db.scalars(
            select(User)
            .where(User.phone.in_(numbers), User.is_staff.is_(False))
            .order_by(User.date_joined)
        ):
            clients.setdefault(person.phone, []).append(person)
    owners = {person.id for people in clients.values() for person in people}
    cards: dict[uuid.UUID, dict[str, str]] = {}
    if owners:
        for card_id, board, owner_id in db.execute(
            select(BoardCard.id, BoardCard.board, BoardCard.owner_id).where(
                BoardCard.owner_id.in_(owners)
            )
        ):
            cards.setdefault(owner_id, {})[board] = str(card_id)
    return {
        "total": total,
        "calls": [
            _shown(call, staff=staff)
            | {
                "clients": [
                    {
                        "id": str(person.id),
                        "name": person.full_name or person.email,
                        "email": person.email,
                        "sales_card_id": cards.get(person.id, {}).get("sales"),
                        "support_card_id": cards.get(person.id, {}).get("support"),
                    }
                    for person in clients.get(call.number, [])
                ]
            }
            for call in calls
        ],
    }


def recording(
    db: Session, *, call_id: uuid.UUID, viewer: User, sees_all: bool
) -> tuple[Iterator[bytes], str]:
    """The call's audio, read from the exchange as it is sent on, and its
    media type. The link was checked to be the exchange's when it was kept."""
    where = [PhoneCall.id == call_id]
    allowed = _may_see(viewer=viewer, sees_all=sees_all)
    if allowed is not None:
        where.append(allowed)
    call = db.scalar(select(PhoneCall).where(*where))
    if call is None:
        raise CallNotFound
    if not call.recording_url:
        raise NoRecording
    client = httpx.Client(timeout=RECORDING_TIMEOUT_SECONDS, follow_redirects=False)
    try:
        answer = client.send(
            client.build_request("GET", call.recording_url), stream=True
        )
    except httpx.HTTPError as exc:
        client.close()
        raise NoRecording from exc
    if answer.status_code != httpx.codes.OK:
        answer.close()
        client.close()
        raise NoRecording

    def chunks() -> Iterator[bytes]:
        sent = 0
        try:
            for chunk in answer.iter_bytes(64 * 1024):
                sent += len(chunk)
                if sent > RECORDING_MAX_BYTES:
                    break
                yield chunk
        except httpx.HTTPError:
            logger.warning("telephony: a recording broke off mid-way")
        finally:
            answer.close()
            client.close()

    kind = answer.headers.get("content-type", "")
    return chunks(), kind if kind.startswith("audio/") else "audio/wav"


def connections(db: Session) -> list[PhoneConnection]:
    return list(db.scalars(select(PhoneConnection)))
