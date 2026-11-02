from typing import Any

from openaiadskit import PROVIDER as CHATGPT
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.config import settings
from app.common.crypto import decrypt
from app.common.exceptions import DecryptionFailed
from app.modules.accounts.models import User
from app.modules.chatgpt.exceptions import ChatGPTNotConnected
from app.modules.integrations.constants import USABLE_CONNECTION_STATUSES
from app.modules.integrations.models import AdAccount, ProviderConnection


def chatgpt_ads_on(*, user: Any) -> bool:
    if settings.chatgpt_ads_enabled:
        return True
    email = str(getattr(user, "email", "") or "").casefold()
    return bool(email) and email in settings.chatgpt_ads_users


def chatgpt_connection(db: Session, *, owner: User) -> ProviderConnection | None:
    return db.scalar(
        select(ProviderConnection).where(
            ProviderConnection.owner_id == owner.id,
            ProviderConnection.provider == CHATGPT,
        )
    )


def usable_connection(db: Session, *, owner: User) -> ProviderConnection | None:
    found = chatgpt_connection(db, owner=owner)
    if found is None or found.status not in USABLE_CONNECTION_STATUSES:
        return None
    return found


def chatgpt_account(db: Session, *, owner: User) -> AdAccount | None:
    return db.scalar(
        select(AdAccount).where(
            AdAccount.owner_id == owner.id,
            AdAccount.provider == CHATGPT,
            AdAccount.is_current.is_(True),
        )
    )


def account_by_external_id(db: Session, *, external_id: str) -> AdAccount | None:
    return db.scalar(
        select(AdAccount).where(
            AdAccount.provider == CHATGPT, AdAccount.external_id == external_id
        )
    )


def connected(db: Session, *, owner: User) -> tuple[AdAccount, str]:
    """The current account and its API key, or ``ChatGPTNotConnected``."""
    connection = usable_connection(db, owner=owner)
    account = chatgpt_account(db, owner=owner)
    if connection is None or account is None or not connection.token_encrypted:
        raise ChatGPTNotConnected
    try:
        return account, decrypt(connection.token_encrypted)
    except DecryptionFailed as exc:
        raise ChatGPTNotConnected from exc
