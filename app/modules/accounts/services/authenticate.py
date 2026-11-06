import secrets
from datetime import timedelta
from functools import cache

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.common.passwords import check_password, make_password, needs_rehash
from app.modules.accounts.exceptions import AccountBlocked, BadCredentials
from app.modules.accounts.models import User
from app.modules.accounts.selectors import user_by_email
from app.modules.accounts.services.block_user import (
    blocked_message,
    owner_blocked_message,
)
from app.modules.audit.constants import EventName
from app.modules.audit.models import Event
from app.modules.audit.services import emit

# A Mini App opened ten times over lunch is one sitting on the history.
SIGN_IN_QUIET = timedelta(minutes=30)


@cache
def _decoy() -> str:
    """A hash of a password nobody knows, checked in place of a missing one."""
    return make_password(secrets.token_urlsafe(16))


def authenticate(db: Session, *, email: str, password: str, address: str = "") -> User:
    user = user_by_email(db, email=email)
    # The hash is paid for even with no account or no password to check, so
    # the time taken does not tell which emails are signed up.
    stored = user.password if user is not None and user.password else ""
    matches = check_password(password, stored or _decoy())
    if user is None or not stored or not matches:
        raise BadCredentials
    _refuse_blocked(db, user=user)
    if needs_rehash(user.password):
        user.password = make_password(password)
    note_sign_in(db, user=user, via="password", address=address)
    db.commit()
    return user


def _refuse_blocked(db: Session, *, user: User) -> None:
    if not user.is_active:
        raise AccountBlocked(blocked_message(db, user=user))
    if user.crm_owner_id is not None:
        owner = db.get(User, user.crm_owner_id)
        if owner is None or not owner.is_active:
            raise AccountBlocked(owner_blocked_message(user=user))


def note_sign_in(db: Session, *, user: User, via: str, address: str = "") -> None:
    """Stamp the sign-in and file it under the account it works for: a CRM
    manager's goes on their owner's history, naming the manager."""
    now = utcnow()
    user.last_login = now
    if db.scalar(
        select(Event.id)
        .where(
            Event.owner_id == (user.crm_owner_id or user.id),
            Event.name == EventName.USER_SIGNED_IN,
            Event.aggregate_id == str(user.id),
            Event.occurred_at >= now - SIGN_IN_QUIET,
            Event.payload["via"].as_string() == via,
        )
        .limit(1)
    ):
        return
    payload = {"via": via, "address": address[:64]}
    if user.crm_owner_id is not None:
        payload |= {"member_id": str(user.id), "member": user.full_name or user.email}
    emit(
        db,
        owner_id=user.crm_owner_id or user.id,
        name=EventName.USER_SIGNED_IN,
        aggregate_type="user",
        aggregate_id=user.id,
        payload=payload,
        occurred_at=now,
    )
