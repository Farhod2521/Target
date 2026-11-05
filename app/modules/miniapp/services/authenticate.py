import logging
from datetime import datetime

from sqlalchemy.orm import Session
from telegramkit import (
    InitDataError,
    InitDataExpired,
    VerifiedInitData,
    parse_init_data,
)

from app.modules.accounts.models import User
from app.modules.miniapp.constants import INIT_DATA_MAX_AGE_SECONDS
from app.modules.miniapp.exceptions import (
    ChatNotLinked,
    MiniAppUnavailable,
    NotInsideTelegram,
    ProofExpired,
    ProofRefused,
)
from app.modules.notifications.bot import bot_token, is_configured

logger = logging.getLogger(__name__)


def authenticate(db: Session, *, init_data: str, now: datetime) -> User:
    """The cabinet a Telegram Mini App launch belongs to, from its signed proof."""
    from app.modules.notifications.selectors import chat_by_id

    if not is_configured():
        logger.warning("miniapp_unconfigured")
        raise MiniAppUnavailable
    if not init_data:
        logger.info("miniapp_no_proof")
        raise NotInsideTelegram
    verified = _verify(init_data=init_data, now=now)
    chat = chat_by_id(db, chat_id=verified.user.id)
    if chat is None or not chat.is_active:
        logger.warning(
            "miniapp_unlinked",
            extra={"telegram_id": verified.user.id, "known": chat is not None},
        )
        raise ChatNotLinked
    logger.info(
        "miniapp_proof_accepted", extra={"signed_keys": ",".join(verified.signed_keys)}
    )
    return chat.owner


def link_launch(db: Session, *, owner: User, init_data: str, now: datetime) -> bool:
    """Tie the Telegram account a Mini App launch came from to ``owner``'s
    cabinet, so the bot's «Kabinetga kirish» opens it next time. A CRM
    manager's sign-in links nothing: the bot speaks to owners."""
    from app.modules.notifications.services.link import attach_chat

    if not is_configured():
        raise MiniAppUnavailable
    if not init_data:
        raise NotInsideTelegram
    verified = _verify(init_data=init_data, now=now)
    if owner.crm_owner_id is not None:
        return False
    attach_chat(
        db,
        owner=owner,
        chat_id=str(verified.user.id),
        username=verified.user.username or "",
        now=now,
    )
    logger.info("miniapp_linked", extra={"owner": str(owner.id)})
    return True


def _verify(*, init_data: str, now: datetime) -> VerifiedInitData:
    try:
        return parse_init_data(
            init_data,
            bot_token=bot_token(),
            now=int(now.timestamp()),
            max_age_seconds=INIT_DATA_MAX_AGE_SECONDS,
        )
    except InitDataExpired as exc:
        logger.warning(
            "miniapp_proof_expired",
            extra={
                "reason": exc.reason,
                "age_seconds": exc.age_seconds,
                "keys": ",".join(exc.keys),
            },
        )
        raise ProofExpired from None
    except InitDataError as exc:
        logger.warning(
            "miniapp_proof_refused",
            extra={"reason": exc.reason, "keys": ",".join(exc.keys)},
        )
        raise ProofRefused from None
