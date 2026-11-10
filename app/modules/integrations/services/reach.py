"""Whether the connected login still reaches each of its ad accounts.

A reconnect with another Facebook profile keeps every account row the old
profile brought in, still chosen and still "active", while the new token
cannot touch some of them. Meta then refuses the first write with
"does not exist ... missing permissions" and the owner reads a developer's
sentence. Here such an account is marked, so the cabinet can show it and a
launch can stop before anything is sent.
"""

import logging
import uuid

from adskit import AdAccountUnreachable, ProviderError, registry
from adskit.dto import AccountStateDTO
from adskit.refs import ExternalRef, ProviderName
from metaads import PROVIDER as META
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.integrations.models import AdAccount, ProviderConnection

logger = logging.getLogger(__name__)


def lose_reach(account: AdAccount) -> None:
    """Meta said this login cannot reach the account. Flushes nothing."""
    if account.reach_lost_at is not None:
        return
    account.reach_lost_at = utcnow()
    logger.warning(
        "ad account %s is out of reach of connection %s",
        account.external_id,
        account.connection_id,
    )


def regain_reach(account: AdAccount) -> None:
    if account.reach_lost_at is not None:
        account.reach_lost_at = None


def read_reachable(account: AdAccount, *, token: str) -> AccountStateDTO | None:
    """The account's state, marking it when the login cannot reach it.

    Raises :class:`AdAccountUnreachable` after marking; any other failure is
    not an answer about reach and is returned as None, as before.
    """
    ref = ExternalRef(
        provider=ProviderName(account.provider), level="account", id=account.external_id
    )
    try:
        state = registry.get(account.provider).campaigns.read_account(
            account=ref, token=token
        )
    except AdAccountUnreachable:
        lose_reach(account)
        raise
    except ProviderError as exc:
        logger.info("account state of %s not read: %s", account.external_id, exc)
        return None
    regain_reach(account)
    return state


def check_chosen(db: Session, *, connection: ProviderConnection, token: str) -> None:
    """Read each account the owner chose, on its own, and mark or clear it.

    The account list is no answer either way: the business walk that builds
    it stops after a number of businesses, and Meta can list an account
    through a business while refusing this person a read of it. Only Meta's
    own "cannot reach" marks one, and only a read that worked clears it.
    """
    rows = db.scalars(
        select(AdAccount).where(
            AdAccount.connection_id == connection.id,
            AdAccount.provider == connection.provider,
            or_(AdAccount.is_active.is_(True), AdAccount.is_current.is_(True)),
        )
    ).all()
    for account in rows:
        try:
            read_reachable(account, token=token)
        except AdAccountUnreachable:
            continue


def check_connection_reach(db: Session, *, connection_id: str) -> int:
    """Read each chosen account of one connection; answer how many are out of reach."""
    from app.common.crypto import decrypt
    from app.common.exceptions import DecryptionFailed
    from app.modules.integrations.constants import USABLE_CONNECTION_STATUSES

    connection = db.get(ProviderConnection, uuid.UUID(str(connection_id)))
    # Meta only: its stored token is the one calls are made with.
    if (
        connection is None
        or connection.provider != META
        or connection.status not in USABLE_CONNECTION_STATUSES
    ):
        return 0
    try:
        token = decrypt(connection.token_encrypted)
    except DecryptionFailed:
        logger.exception("connection %s could not be decrypted", connection.id)
        return 0
    check_chosen(db, connection=connection, token=token)
    db.commit()
    return int(
        db.scalar(
            select(func.count(AdAccount.id)).where(
                AdAccount.connection_id == connection.id,
                AdAccount.reach_lost_at.is_not(None),
            )
        )
        or 0
    )
