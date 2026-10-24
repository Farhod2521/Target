"""Tokens, provider ports and the audit trail every audience write leaves."""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from adskit import AudienceSourcePort, ExternalRef, registry
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.common.crypto import decrypt
from app.common.db import utcnow
from app.common.exceptions import DecryptionFailed
from app.modules.accounts.models import User
from app.modules.audit.constants import ActionStatus, ActionType, ActorType
from app.modules.audit.models import ActionLog
from app.modules.integrations.constants import USABLE_CONNECTION_STATUSES
from app.modules.integrations.exceptions import ConnectionFailed, NoConnection
from app.modules.integrations.models import AdAccount
from app.modules.integrations.selectors import active_ad_account
from core.audiences import (
    ActionNotSupported,
    AudienceRuleError,
    BreadthNotOffered,
    CountryUnknown,
    RetentionNotOffered,
    RetentionTooLong,
    SourceNotSupported,
)

logger = logging.getLogger(__name__)
ACCOUNT_LEVEL = "account"
AUDIENCE_LEVEL = "audience"
AUDIENCE_LOG_PREFIX = "audience"


def account_and_token(db: Session, *, owner: User) -> tuple[AdAccount, str]:
    account = active_ad_account(db, owner=owner)
    if account is None:
        raise NoConnection
    return account, token_for(ad_account=account)


def token_for(*, ad_account: AdAccount) -> str:
    connection = ad_account.connection
    if connection.status not in USABLE_CONNECTION_STATUSES:
        raise ConnectionFailed
    try:
        return decrypt(connection.token_encrypted)
    except DecryptionFailed as exc:
        logger.exception("connection %s could not be decrypted", connection.id)
        raise ConnectionFailed from exc


def port_for(*, provider: str) -> AudienceSourcePort:
    return registry.get(provider).audience_sources


def account_ref(account: AdAccount) -> ExternalRef:
    return ExternalRef(
        provider=account.provider, level=ACCOUNT_LEVEL, id=account.external_id
    )


def audience_ref(*, provider: str, external_id: str) -> ExternalRef:
    return ExternalRef(provider=provider, level=AUDIENCE_LEVEL, id=external_id)


def open_log(
    db: Session,
    *,
    owner: User,
    action: ActionType,
    provider: str,
    external_id: str,
    requested: dict[str, Any],
    previous: dict[str, Any],
    dry_run: bool,
) -> ActionLog:
    log = ActionLog(
        owner_id=owner.id,
        actor_type=ActorType.USER,
        actor_id=owner.id,
        action=action,
        target_provider=provider,
        target_level=AUDIENCE_LEVEL,
        target_external_id=external_id,
        request_payload=requested,
        previous_state=previous,
        result_payload={},
        dropped=[],
        status=ActionStatus.PENDING,
        dry_run=dry_run,
        idempotency_key=next_key(db, action=action, external_id=external_id),
    )
    db.add(log)
    db.commit()
    return log


def close_log(
    *, log: ActionLog, external_id: str, result: dict[str, Any], dry_run: bool
) -> None:
    log.target_external_id = external_id
    log.status = ActionStatus.APPLIED
    log.result_payload = result
    log.dry_run = dry_run
    log.applied_at = utcnow()


def fail_log(db: Session, *, log: ActionLog, code: str, message: str) -> None:
    log.status = ActionStatus.FAILED
    log.error_code = code[:32]
    log.error_message = message
    db.commit()


@contextmanager
def recording(db: Session, *, log: ActionLog) -> Iterator[None]:
    try:
        yield
    except Exception as exc:
        fail_log(
            db,
            log=log,
            code=str(getattr(exc, "code", "") or type(exc).__name__),
            message=str(exc),
        )
        raise


def next_key(db: Session, *, action: ActionType, external_id: str) -> str:
    prefix = f"{AUDIENCE_LOG_PREFIX}:{action}:{external_id}:"
    attempt = (
        db.scalar(
            select(func.count())
            .select_from(ActionLog)
            .where(ActionLog.idempotency_key.startswith(prefix))
        )
        or 0
    ) + 1
    return f"{prefix}{attempt}"


def rule_words(exc: AudienceRuleError) -> str:
    if isinstance(exc, SourceNotSupported):
        return "Bu manbadan auditoriya yasab bo'lmaydi. Boshqa manba tanlang."
    if isinstance(exc, ActionNotSupported):
        return "Bu manba bunday harakatni qayd qilmaydi. Boshqa harakat tanlang."
    if isinstance(exc, RetentionTooLong):
        return (
            "Bu manba uchun eng uzog'i %(maximum)s kun. Hozir %(days)s kun tanlangan."
            % {"maximum": exc.maximum, "days": exc.days}
        )
    if isinstance(exc, RetentionNotOffered):
        return "Bunday muddat tanlanmaydi. Ro'yxatdagi muddatlardan birini tanlang."
    if isinstance(exc, BreadthNotOffered):
        return "Bunday kenglik tanlanmaydi. Ro'yxatdagi kengliklardan birini tanlang."
    if isinstance(exc, CountryUnknown):
        if not exc.country:
            return "Profilingizda mamlakat ko'rsatilmagan. Sozlamalarda to'ldiring."
        return "Profilingizdagi mamlakat tanilmadi. Sozlamalarda qaytadan tanlang."
    return (
        "Bu auditoriyani shu sozlamalar bilan yasab bo'lmaydi. Tanlovni o'zgartiring."
    )
