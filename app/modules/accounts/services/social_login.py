"""Signing in, and signing up, with a Google account.

The browser leaves the site for Google and comes back to the callback,
which never answers JSON: it sends the browser on to a page of the cabinet.

- A Google account already tied to one of ours signs it in.
- A verified Google email that one of our accounts holds ties the two and
  signs it in (decided 2026-11-07).
- Anything else is somebody new: the cabinet's finishing page asks for the
  phone and the role, and only then is the account opened. A number another
  account holds opens nothing: that person most likely has an account.

Signed-in owners tie a Google account from Settings the same way; there the
Google email need not match the account's.

Every way into the cabinet ends on the handoff page, which trades a one-use
token for a session - the tokens never ride in an address.
"""

import logging
import secrets
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl, urlencode

from googlekit import GoogleError, GoogleProfile, login_profile, login_url
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.common.cache import cache
from app.common.config import settings
from app.common.db import utcnow
from app.common.routes import reverse
from app.modules.accounts.constants import (
    SOCIAL_PENDING_KEY,
    SOCIAL_PENDING_TTL_SECONDS,
    SOCIAL_STATE_KEY,
    SOCIAL_STATE_TTL_SECONDS,
    SOCIAL_TOKEN_BYTES,
    Language,
    SocialProvider,
)
from app.modules.accounts.exceptions import (
    AccountBlocked,
    EmailTaken,
    PhoneTaken,
    SocialLastWay,
    SocialPendingExpired,
    SocialSignInOff,
)
from app.modules.accounts.models import SocialIdentity, User
from app.modules.accounts.selectors import user_by_email
from app.modules.accounts.services.authenticate import note_sign_in, refuse_blocked
from app.modules.accounts.services.members import issue_handoff, safe_destination
from app.modules.accounts.services.register_user import register_user

logger = logging.getLogger(__name__)

LOGIN_PATH = "/accounts/login/"
FINISH_PATH = "/accounts/social/{token}/"
SETTINGS_PATH = "/app/account/"
LOGIN = "login"
LINK = "link"


class SocialError:
    """Why the callback sent the browser back, as the ``social_error`` the
    sign-in page (or Settings) reads."""

    CANCELLED = "cancelled"  # the person closed Google's screen
    EXPIRED = "expired"  # the round trip outlived its state, or the state was forged
    FAILED = "failed"  # Google refused the code, or answered something unreadable
    UNVERIFIED = "unverified"  # Google has not confirmed the address
    BLOCKED = "blocked"  # the account is blocked
    TAKEN = "taken"  # Settings: that Google account signs another of ours in
    UNAVAILABLE = "unavailable"  # Google sign-in is switched off


@dataclass(frozen=True, slots=True)
class Pending:
    """Somebody Google vouched for, before the account exists."""

    provider: str
    subject: str
    email: str
    full_name: str
    language: str
    referral_code: str
    next: str


def providers() -> list[str]:
    """The sign-in pages' buttons, in the order to draw them."""
    found = []
    if (
        settings.google_login_enabled
        and settings.google_oauth_client_id
        and settings.google_oauth_client_secret
    ):
        found.append(SocialProvider.GOOGLE.value)
    return found


def callback_uri(provider: str) -> str:
    """The same string on both halves of the handshake, and on the OAuth client."""
    return f"{settings.site_url}/api/v1/auth/social/{provider}/callback"


def start(
    *,
    provider: str,
    next_path: str = "",
    referral_code: str = "",
    language: str = "",
    linking: User | None = None,
) -> str:
    """Where to send the browser. ``linking`` is the signed-in owner tying a
    Google account from Settings; without it this is a sign-in or sign-up."""
    if provider not in providers():
        raise SocialSignInOff
    state = secrets.token_urlsafe(SOCIAL_TOKEN_BYTES)
    cache.set(
        SOCIAL_STATE_KEY.format(state=state),
        {
            "provider": provider,
            "intent": LINK if linking is not None else LOGIN,
            "user": str(linking.id) if linking is not None else "",
            "next": next_path[:512],
            "referral": referral_code[:32],
            "language": language if language in Language.values else "",
        },
        SOCIAL_STATE_TTL_SECONDS,
    )
    return login_url(
        client_id=settings.google_oauth_client_id,
        redirect_uri=callback_uri(provider),
        state=state,
    )


def finish(
    db: Session,
    *,
    provider: str,
    state: str,
    code: str,
    error: str = "",
    address: str = "",
) -> str:
    """The callback: the cabinet path to send the browser to, always."""
    found = _spend(SOCIAL_STATE_KEY.format(state=state)) if state else None
    if not isinstance(found, dict) or found.get("provider") != provider:
        return _login_refused(SocialError.EXPIRED)
    linking = found.get("intent") == LINK
    if provider not in providers():
        return _refused(found, SocialError.UNAVAILABLE)
    if not code:
        logger.info("%s sign-in not granted: %s", provider, error or "unknown")
        return _refused(found, SocialError.CANCELLED)
    try:
        profile = login_profile(
            client_id=settings.google_oauth_client_id,
            client_secret=settings.google_oauth_client_secret,
            redirect_uri=callback_uri(provider),
            code=code,
        )
    except GoogleError as exc:
        logger.warning("%s sign-in failed: %s", provider, exc)
        return _refused(found, SocialError.FAILED)
    if linking:
        return _link(db, found=found, provider=provider, profile=profile)
    return _sign_in(
        db, found=found, provider=provider, profile=profile, address=address
    )


def pending(*, token: str) -> Pending:
    """What the finishing page shows: the name and the address Google gave."""
    found = cache.get(SOCIAL_PENDING_KEY.format(token=token)) if token else None
    if not isinstance(found, dict):
        raise SocialPendingExpired
    return Pending(**found)


def complete(
    db: Session,
    *,
    token: str,
    phone: str,
    role: str,
    full_name: str = "",
    address: str = "",
) -> tuple[User, str]:
    """Open the account the finishing page asked for: it and where to land.

    The token is spent only once the account exists, so a refused number
    can be corrected and sent again.
    """
    held = pending(token=token)
    if user_by_email(db, email=held.email) is not None:
        # Opened with this address since Google was pressed: Google again
        # signs into it.
        raise EmailTaken
    if db.scalar(select(User.id).where(User.phone == phone).limit(1)) is not None:
        raise PhoneTaken
    if not cache.add(SOCIAL_PENDING_KEY.format(token=token) + ":spent", 1, timeout=60):
        raise SocialPendingExpired
    try:
        user = register_user(
            db,
            email=held.email,
            full_name=(full_name or held.full_name or held.email.split("@")[0])[:255],
            phone=phone,
            language=held.language or Language.UZ,
            referral_code=held.referral_code,
            role=role,
            commit=False,
        )
        db.add(
            SocialIdentity(
                owner_id=user.id,
                provider=held.provider,
                subject=held.subject,
                email=held.email,
                last_used_at=utcnow(),
            )
        )
        note_sign_in(db, user=user, via=held.provider, address=address)
        db.commit()
    except (EmailTaken, IntegrityError):
        # The address or the Google account was taken in the half hour the
        # form was open: signing in again finds whichever holds it now.
        db.rollback()
        cache.delete(SOCIAL_PENDING_KEY.format(token=token) + ":spent")
        raise EmailTaken from None
    cache.delete(SOCIAL_PENDING_KEY.format(token=token))
    return user, safe_destination(held.next)


def linked(db: Session, *, owner: User) -> list[SocialIdentity]:
    return list(
        db.scalars(
            select(SocialIdentity)
            .where(SocialIdentity.owner_id == owner.id)
            .order_by(SocialIdentity.created_at)
        )
    )


def unlink(db: Session, *, owner: User, provider: str) -> None:
    """Forget the tie. Refused while it is the only way in."""
    identity = db.scalar(
        select(SocialIdentity).where(
            SocialIdentity.owner_id == owner.id, SocialIdentity.provider == provider
        )
    )
    if identity is None:
        return
    others = [i for i in linked(db, owner=owner) if i.id != identity.id]
    if not owner.has_password and not others:
        raise SocialLastWay
    db.delete(identity)
    db.commit()


def _sign_in(
    db: Session,
    *,
    found: dict[str, Any],
    provider: str,
    profile: GoogleProfile,
    address: str,
) -> str:
    identity = _identity(db, provider=provider, subject=profile.subject)
    user = db.get(User, identity.owner_id) if identity is not None else None
    if identity is None or user is None:
        if not profile.email_verified or not profile.email:
            return _login_refused(SocialError.UNVERIFIED)
        user = user_by_email(db, email=profile.email)
        if user is None:
            return _ask_the_rest(found=found, provider=provider, profile=profile)
        # The address is Google-verified and ours: the same person (2026-11-07).
        identity = SocialIdentity(
            owner_id=user.id, provider=provider, subject=profile.subject
        )
        db.add(identity)
    try:
        refuse_blocked(db, user=user)
    except AccountBlocked:
        db.rollback()
        return _login_refused(SocialError.BLOCKED)
    identity.email = profile.email
    identity.last_used_at = utcnow()
    note_sign_in(db, user=user, via=provider, address=address)
    try:
        db.commit()
    except IntegrityError:
        # A second callback for the same account tied it a moment ago.
        db.rollback()
        return _login_refused(SocialError.FAILED)
    token = issue_handoff(owner=user, destination=str(found.get("next") or ""))
    return reverse("accounts:handoff", [token])


def _link(
    db: Session, *, found: dict[str, Any], provider: str, profile: GoogleProfile
) -> str:
    try:
        user = db.get(User, uuid.UUID(str(found.get("user") or "")))
    except ValueError:
        user = None
    if user is None or not user.is_active:
        return _login_refused(SocialError.EXPIRED)
    identity = _identity(db, provider=provider, subject=profile.subject)
    if identity is not None and identity.owner_id != user.id:
        return _back(found, social_error=SocialError.TAKEN)
    if identity is None:
        identity = db.scalar(
            select(SocialIdentity).where(
                SocialIdentity.owner_id == user.id, SocialIdentity.provider == provider
            )
        )
        if identity is None:
            identity = SocialIdentity(owner_id=user.id, provider=provider)
            db.add(identity)
        identity.subject = profile.subject
    identity.email = profile.email
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return _back(found, social_error=SocialError.TAKEN)
    return _back(found, linked=provider)


def _ask_the_rest(
    *, found: dict[str, Any], provider: str, profile: GoogleProfile
) -> str:
    token = secrets.token_urlsafe(SOCIAL_TOKEN_BYTES)
    cache.set(
        SOCIAL_PENDING_KEY.format(token=token),
        {
            "provider": provider,
            "subject": profile.subject,
            "email": profile.email,
            "full_name": profile.name,
            "language": str(found.get("language") or ""),
            "referral_code": str(found.get("referral") or ""),
            "next": str(found.get("next") or ""),
        },
        SOCIAL_PENDING_TTL_SECONDS,
    )
    return FINISH_PATH.format(token=token)


def _identity(db: Session, *, provider: str, subject: str) -> SocialIdentity | None:
    return db.scalar(
        select(SocialIdentity).where(
            SocialIdentity.provider == provider, SocialIdentity.subject == subject
        )
    )


def _spend(key: str) -> Any:
    found = cache.get(key)
    cache.delete(key)
    return found


def _refused(found: dict[str, Any], error: str) -> str:
    if found.get("intent") == LINK:
        return _back(found, social_error=error)
    return _login_refused(error)


def _login_refused(error: str) -> str:
    return f"{LOGIN_PATH}?{urlencode({'social_error': error})}"


def _back(found: dict[str, Any], **params: str) -> str:
    """Settings (or the page that asked), with the outcome in the query."""
    asked = str(found.get("next") or "")
    path = asked if safe_destination(asked) == asked else SETTINGS_PATH
    base, _, query = path.partition("?")
    merged = dict(parse_qsl(query)) | params
    return f"{base}?{urlencode(merged)}"
