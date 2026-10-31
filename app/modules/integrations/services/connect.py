"""Connecting Meta and Google, keeping the token alive, and letting go of it."""

import logging
import secrets
from datetime import timedelta
from typing import Any, Final

from adskit import GrantDTO, ProviderError, registry
from googleadskit import PROVIDER as GOOGLE
from googlekit import SCOPE_ADWORDS
from metaads import PROVIDER
from metaads.accounts import list_ad_accounts, list_pages
from metaads.adapter import translate_error
from metaads.dto import AdAccountDTO, PageDTO
from metaads.errors import MetaAuthError, MetaError
from metaads.oauth import (
    INSTAGRAM_SCOPE,
    describe_person,
    exchange_for_long_lived,
    inspect_token,
    revoke_access,
)
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.common.config import settings
from app.common.crypto import decrypt, encrypt, fingerprint
from app.common.db import on_commit, utcnow
from app.common.exceptions import DecryptionFailed, DomainError
from app.modules.accounts.models import User
from app.modules.audit.constants import EventName
from app.modules.audit.services import emit
from app.modules.integrations.constants import (
    MAX_IDENTITY_REFUSALS,
    USABLE_CONNECTION_STATUSES,
    ConnectionKind,
    ConnectionStatus,
)
from app.modules.integrations.exceptions import (
    ConnectionFailed,
    GoogleAdsNotGranted,
    GoogleAdsUnavailable,
    GoogleConnectionFailed,
    GoogleIdentityTaken,
    IdentityTaken,
    NoConnection,
    SubscriptionRequired,
)
from app.modules.integrations.models import AdAccount, PageAccount, ProviderConnection
from app.modules.integrations.selectors import (
    google_ads_on,
    identity_refusals,
    meta_connection,
    owner_of_meta_user,
)

logger = logging.getLogger(__name__)
STATE_BYTES: Final = 24
NO_TOKEN = b""
BLOCK_REASON = "meta_identity_reused"
NAME_WIDTH = 255


def build_authorize_url(
    db: Session, *, user: User, redirect_uri: str
) -> tuple[str, str]:
    from app.modules.billing.selectors import may_prepare

    if not may_prepare(db, owner=user):
        raise SubscriptionRequired
    state = secrets.token_urlsafe(STATE_BYTES)
    url = registry.get(PROVIDER).connect.authorize_url(
        redirect_uri=redirect_uri, state=state
    )
    return url, state


def complete_connection(
    db: Session, *, user: User, code: str, redirect_uri: str
) -> ProviderConnection:
    from app.modules.billing.selectors import may_prepare

    if not may_prepare(db, owner=user):
        raise SubscriptionRequired
    try:
        grant = registry.get(PROVIDER).connect.complete(
            redirect_uri=redirect_uri, code=code
        )
        ad_accounts = list_ad_accounts(token=grant.token)
        pages = list_pages(token=grant.token)
    except (ProviderError, MetaError) as exc:
        raise _connection_refused(db, user=user, exc=exc) from exc
    claim_identity(db, user=user, external_user_id=grant.external_user_id)
    try:
        connection = _store_everything(
            db, user=user, grant=grant, ad_accounts=ad_accounts, pages=pages
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise IdentityTaken from exc
    return connection


def _store_everything(
    db: Session,
    *,
    user: User,
    grant: GrantDTO,
    ad_accounts: list[AdAccountDTO],
    pages: list[PageDTO],
) -> ProviderConnection:
    from app.modules.integrations.services.sync import (
        adopt_only_page,
        store_ad_accounts,
        store_pages,
    )

    connection = _store_connection(
        db,
        user=user,
        token=grant.token,
        expires_in=grant.expires_in,
        scopes=grant.scopes,
        external_user_id=grant.external_user_id,
    )
    store_ad_accounts(db, connection=connection, accounts=ad_accounts)
    store_pages(db, connection=connection, pages=pages)
    adopt_only_page(db, connection=connection)
    _reread_pixels(db, connection=connection)
    _reread_pages(db, connection=connection)
    emit(
        db,
        owner_id=user.id,
        name=EventName.CONNECTION_ADDED,
        aggregate_type="connection",
        aggregate_id=connection.id,
        payload={
            "provider": PROVIDER,
            "ad_accounts": len(ad_accounts),
            "pages": len(pages),
        },
    )
    return connection


def _reread_pixels(db: Session, *, connection: ProviderConnection) -> None:
    from app.modules.integrations.tasks import sync_pixels_task

    for account_id in db.scalars(
        select(AdAccount.id).where(
            AdAccount.connection_id == connection.id, AdAccount.is_active.is_(True)
        )
    ):
        on_commit(db, lambda key=str(account_id): sync_pixels_task.delay(key))


def _reread_pages(db: Session, *, connection: ProviderConnection) -> None:
    from app.modules.leads.services import recheck_page
    from app.modules.leads.tasks import reconcile_page_task

    for page in db.scalars(
        select(PageAccount).where(
            PageAccount.connection_id == connection.id, PageAccount.is_active.is_(True)
        )
    ):
        recheck_page(db, page=page, actor_id="reconnect")
        on_commit(db, lambda key=str(page.id): reconcile_page_task.delay(key))


def callback_uri(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/api/v1/connections/meta/callback"


def _store_connection(
    db: Session,
    *,
    user: User,
    token: str,
    expires_in: int,
    scopes: tuple[str, ...] = (),
    external_user_id: str = "",
) -> ProviderConnection:
    now = utcnow()
    connection = db.scalar(
        select(ProviderConnection).where(
            ProviderConnection.owner_id == user.id,
            ProviderConnection.provider == PROVIDER,
        )
    )
    if connection is None:
        connection = ProviderConnection(owner_id=user.id, provider=PROVIDER)
        db.add(connection)
    connection.kind = ConnectionKind.USER_OAUTH
    connection.scopes = list(scopes)
    connection.token_encrypted = encrypt(token)
    connection.token_fingerprint = fingerprint(token)
    connection.status = ConnectionStatus.ACTIVE
    connection.expires_at = now + timedelta(seconds=expires_in) if expires_in else None
    connection.last_verified_at = now
    connection.last_error_code = ""
    connection.action_required_at = None
    connection.external_user_name = ""
    if external_user_id:
        connection.external_user_id = external_user_id
    db.flush()
    return connection


def build_google_authorize_url(
    db: Session, *, user: User, redirect_uri: str
) -> tuple[str, str]:
    from app.modules.billing.selectors import has_live_subscription

    if not google_ads_on(user=user):
        raise GoogleAdsUnavailable
    if not has_live_subscription(db, owner=user):
        raise SubscriptionRequired
    state = secrets.token_urlsafe(STATE_BYTES)
    url = registry.get(GOOGLE).connect.authorize_url(
        redirect_uri=redirect_uri, state=state
    )
    return url, state


def complete_google_connection(
    db: Session, *, user: User, code: str, redirect_uri: str
) -> ProviderConnection:
    from app.modules.billing.selectors import has_live_subscription
    from app.modules.integrations.tasks import sync_google_accounts_task

    if not google_ads_on(user=user):
        raise GoogleAdsUnavailable
    if not has_live_subscription(db, owner=user):
        raise SubscriptionRequired
    try:
        grant = registry.get(GOOGLE).connect.complete(
            redirect_uri=redirect_uri, code=code
        )
    except ProviderError as exc:
        raise GoogleConnectionFailed from exc
    if SCOPE_ADWORDS not in grant.scopes:
        raise GoogleAdsNotGranted
    try:
        connection = db.scalar(
            select(ProviderConnection).where(
                ProviderConnection.owner_id == user.id,
                ProviderConnection.provider == GOOGLE,
            )
        )
        if connection is None:
            connection = ProviderConnection(owner_id=user.id, provider=GOOGLE)
            db.add(connection)
        connection.kind = ConnectionKind.USER_OAUTH
        connection.scopes = list(grant.scopes)
        connection.token_encrypted = encrypt(grant.token)
        connection.token_fingerprint = fingerprint(grant.token)
        connection.status = ConnectionStatus.ACTIVE
        connection.expires_at = None
        connection.last_verified_at = utcnow()
        connection.last_error_code = ""
        if grant.external_user_id:
            connection.external_user_id = grant.external_user_id
        db.flush()
        emit(
            db,
            owner_id=user.id,
            name=EventName.CONNECTION_ADDED,
            aggregate_type="connection",
            aggregate_id=connection.id,
            payload={"provider": GOOGLE},
        )
        key = str(connection.id)
        on_commit(db, lambda: sync_google_accounts_task.delay(key))
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise GoogleIdentityTaken from exc
    return connection


def google_callback_uri(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/api/v1/connections/google/callback"


def _connection_refused(
    db: Session, *, user: User, exc: ProviderError | MetaError
) -> DomainError:
    """A passing fault keeps its sentence; a real refusal gets its answer."""
    from app.modules.chat.services.refused import refused

    found = translate_error(exc) if isinstance(exc, MetaError) else exc
    if found.retryable:
        return ConnectionFailed()
    return refused(db, owner=user, exc=found, operation="connect")


def claim_identity(db: Session, *, user: User, external_user_id: str) -> None:
    if not external_user_id:
        return
    holder = owner_of_meta_user(db, external_user_id=external_user_id)
    if holder is None or holder.id == user.id:
        return
    _record_refusal(db, user=user, external_user_id=external_user_id, holder=holder)
    db.commit()
    raise IdentityTaken


def _record_refusal(
    db: Session, *, user: User, external_user_id: str, holder: User
) -> None:
    from app.modules.accounts.services.block_user import block_user

    emit(
        db,
        owner_id=user.id,
        name=EventName.CONNECTION_REFUSED_DUPLICATE,
        aggregate_type="user",
        aggregate_id=user.id,
        payload={
            "provider": PROVIDER,
            "external_user_id": external_user_id,
            "held_by": str(holder.id),
        },
    )
    db.flush()
    refusals = identity_refusals(db, owner=user)
    if refusals < MAX_IDENTITY_REFUSALS:
        logger.warning(
            "connect refused for account %s: identity %s is held elsewhere (%s/%s)",
            user.id,
            external_user_id,
            refusals,
            MAX_IDENTITY_REFUSALS,
        )
        return
    details: dict[str, Any] = {
        "external_user_id": external_user_id,
        "held_by": str(holder.id),
        "refusals": refusals,
    }
    block_user(db, user=user, reason=BLOCK_REASON, details=details)


def _stored(db: Session, connection: ProviderConnection) -> bool:
    try:
        with db.begin_nested():
            db.flush()
    except IntegrityError:
        logger.warning(
            "connection %s: Facebook account %s is held by another cabinet",
            connection.id,
            connection.external_user_id,
        )
        return False
    return True


def backfill_identity(db: Session, *, connection: ProviderConnection) -> str:
    if connection.external_user_id:
        return "known"
    if connection.status not in USABLE_CONNECTION_STATUSES:
        return "unusable"
    try:
        token = decrypt(connection.token_encrypted)
    except DecryptionFailed:
        logger.exception("connection %s could not be decrypted", connection.id)
        return "unusable"
    if not token:
        return "unusable"
    try:
        info = inspect_token(
            app_id=settings.meta_app_id,
            app_secret=settings.meta_app_secret,
            token=token,
        )
    except MetaError as exc:
        logger.info("identity unknown for connection %s: %s", connection.id, exc)
        return "failed"
    if not info.user_id:
        return "silent"
    connection.external_user_id = info.user_id
    if not _stored(db, connection):
        connection.external_user_id = ""
        return "held"
    db.commit()
    return "filled"


def refresh_connection(
    db: Session, *, connection: ProviderConnection
) -> ProviderConnection:
    try:
        current = decrypt(connection.token_encrypted)
    except Exception:
        logger.exception("connection %s could not be decrypted", connection.id)
        return _mark(db, connection, ConnectionStatus.INVALID, code="decrypt")
    try:
        renewed = exchange_for_long_lived(
            app_id=settings.meta_app_id,
            app_secret=settings.meta_app_secret,
            token=current,
        )
    except MetaAuthError as exc:
        return _mark(db, connection, _status_for(exc), code=str(exc.code or ""))
    except MetaError as exc:
        logger.warning("connection %s refresh deferred: %s", connection.id, exc)
        return connection
    now = utcnow()
    connection.token_encrypted = encrypt(renewed.access_token)
    connection.token_fingerprint = fingerprint(renewed.access_token)
    connection.status = ConnectionStatus.ACTIVE
    connection.expires_at = (
        now + timedelta(seconds=renewed.expires_in) if renewed.expires_in else None
    )
    connection.last_verified_at = now
    connection.last_error_code = ""
    db.commit()
    return connection


def verify_connection(db: Session, *, connection: ProviderConnection) -> bool:
    try:
        token = decrypt(connection.token_encrypted)
    except DecryptionFailed:
        logger.exception("connection %s could not be decrypted", connection.id)
        _mark(db, connection, ConnectionStatus.INVALID, code="decrypt")
        return False
    try:
        info = inspect_token(
            app_id=settings.meta_app_id,
            app_secret=settings.meta_app_secret,
            token=token,
        )
    except MetaError as exc:
        logger.warning("connection %s could not be verified: %s", connection.id, exc)
        return False
    if not info.is_valid:
        status = (
            _status_from_codes(code=info.error_code, subcode=info.error_subcode)
            if info.error_code
            else ConnectionStatus.REVOKED
        )
        _mark(db, connection, status, code=str(info.error_code or ""))
        return False
    connection.scopes = list(info.scopes)
    connection.expires_at = info.expires_at
    connection.last_verified_at = utcnow()
    if not connection.external_user_id and info.user_id:
        connection.external_user_id = info.user_id
        if not _stored(db, connection):
            connection.external_user_id = ""
    db.commit()
    _learn_name(db, connection, token=token)
    return True


def _learn_name(db: Session, connection: ProviderConnection, *, token: str) -> None:
    if connection.external_user_name:
        return
    try:
        person = describe_person(token=token)
    except MetaError as exc:
        logger.warning("connection %s: name not read: %s", connection.id, exc)
        return
    if person.name:
        connection.external_user_name = person.name[:NAME_WIDTH]
        db.commit()


def mark_unusable(
    db: Session,
    *,
    connection: ProviderConnection,
    status: ConnectionStatus,
    code: str = "",
) -> ProviderConnection:
    return _mark(db, connection, status, code=code)


def _status_for(error: MetaAuthError) -> ConnectionStatus:
    return _status_from_codes(code=error.code or 0, subcode=error.subcode or 0)


def _status_from_codes(*, code: int, subcode: int) -> ConnectionStatus:
    if code != 190:
        return ConnectionStatus.INVALID
    if subcode in {458, 466}:
        return ConnectionStatus.REVOKED
    if subcode == 463:
        return ConnectionStatus.EXPIRED
    return ConnectionStatus.INVALID


def _mark(
    db: Session, connection: ProviderConnection, status: ConnectionStatus, *, code: str
) -> ProviderConnection:
    connection.status = status
    connection.last_error_code = code[:16]
    db.commit()
    return connection


def disconnect_meta(db: Session, *, user: User) -> None:
    connection = meta_connection(db, owner=user)
    if connection is None:
        raise NoConnection
    connection.token_encrypted = NO_TOKEN
    connection.token_fingerprint = ""
    connection.status = ConnectionStatus.REVOKED
    connection.expires_at = None
    db.execute(
        update(PageAccount)
        .where(PageAccount.owner_id == user.id, PageAccount.provider == PROVIDER)
        .values(
            token_encrypted=NO_TOKEN,
            token_fingerprint="",
            leadgen_subscribed=False,
            leadgen_subscribed_at=None,
            updated_at=utcnow(),
        )
    )
    emit(
        db,
        owner_id=user.id,
        name=EventName.CONNECTION_REMOVED,
        aggregate_type="connection",
        aggregate_id=connection.id,
        payload={"provider": PROVIDER},
    )
    db.flush()


def unlink_meta_identity(db: Session, *, user: User) -> bool:
    connection = meta_connection(db, owner=user)
    if connection is None or connection.status not in USABLE_CONNECTION_STATUSES:
        return False
    if not connection.external_user_id:
        return False
    if settings.ads_dry_run:
        logger.info("unlink skipped: ADS_DRY_RUN is on")
        return False
    try:
        token = decrypt(connection.token_encrypted)
    except DecryptionFailed:
        logger.exception("unlink: connection %s could not be decrypted", connection.id)
        return False
    try:
        return bool(revoke_access(user_id=connection.external_user_id, token=token))
    except MetaError as exc:
        logger.warning("unlink refused for connection %s: %s", connection.id, exc)
        return False


def learn_instagram_grant(db: Session, *, connection_id: object) -> str:
    connection = db.get(ProviderConnection, _uuid(connection_id))
    if connection is None or connection.status not in USABLE_CONNECTION_STATUSES:
        return "unusable"
    try:
        token = decrypt(connection.token_encrypted)
    except DecryptionFailed:
        logger.exception("connection %s could not be decrypted", connection.id)
        return "unusable"
    try:
        info = inspect_token(
            app_id=settings.meta_app_id,
            app_secret=settings.meta_app_secret,
            token=token,
        )
    except MetaError as exc:
        logger.info("grant read failed for connection %s: %s", connection.id, exc)
        return "failed"
    targets = list(info.targets(INSTAGRAM_SCOPE))
    if connection.instagram_targets != targets:
        connection.instagram_targets = targets
        db.commit()
    return str(len(targets))


def note_action_required(db: Session, *, connection: ProviderConnection) -> None:
    now = utcnow()
    db.execute(
        update(ProviderConnection)
        .where(ProviderConnection.id == connection.id)
        .values(
            action_required_at=func.coalesce(
                ProviderConnection.action_required_at, now
            ),
            action_refusals=ProviderConnection.action_refusals + 1,
            updated_at=now,
        )
    )
    db.commit()
    logger.warning("connection %s: Meta asks its owner to confirm", connection.id)


def clear_action_required(db: Session, *, connection: ProviderConnection) -> None:
    db.execute(
        update(ProviderConnection)
        .where(
            ProviderConnection.id == connection.id,
            or_(
                ProviderConnection.action_required_at.is_not(None),
                ProviderConnection.action_refusals > 0,
            ),
        )
        .values(action_required_at=None, action_refusals=0, updated_at=utcnow())
    )
    db.commit()


def confirm_action_taken(db: Session, *, user: User) -> bool:
    connection = meta_connection(db, owner=user)
    if connection is None or connection.action_required_at is None:
        return False
    connection.action_required_at = None
    db.flush()
    return True


def _uuid(value: object) -> object:
    import uuid

    try:
        return uuid.UUID(str(value))
    except ValueError:
        return value
