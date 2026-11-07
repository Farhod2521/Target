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
    AccountShut,
    AlreadyLinked,
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
        owner = _signed_up_by_telegram(db, verified=verified, now=now)
        if owner is not None:
            return owner
        logger.warning(
            "miniapp_unlinked",
            extra={"telegram_id": verified.user.id, "known": chat is not None},
        )
        raise ChatNotLinked
    logger.info(
        "miniapp_proof_accepted", extra={"signed_keys": ",".join(verified.signed_keys)}
    )
    if not chat.owner.is_active:
        from app.modules.accounts.services import blocked_message

        raise AccountShut(blocked_message(db, user=chat.owner))
    return chat.owner


def _signed_up_by_telegram(
    db: Session, *, verified: VerifiedInitData, now: datetime
) -> User | None:
    """An account opened (or tied) with the Telegram Login Widget whose bot chat
    was never linked: it is the same Telegram account, so the launch opens it
    and the chat is linked now, so the bot reaches it too."""
    from sqlalchemy import select

    from app.modules.accounts.constants import SocialProvider
    from app.modules.accounts.models import SocialIdentity
    from app.modules.notifications.services.link import attach_chat

    owner_id = db.scalar(
        select(SocialIdentity.owner_id).where(
            SocialIdentity.provider == SocialProvider.TELEGRAM,
            SocialIdentity.subject == str(verified.user.id),
        )
    )
    owner = db.get(User, owner_id) if owner_id is not None else None
    if owner is None:
        return None
    if not owner.is_active:
        from app.modules.accounts.services import blocked_message

        raise AccountShut(blocked_message(db, user=owner))
    if owner.crm_owner_id is None:
        attach_chat(
            db,
            owner=owner,
            chat_id=str(verified.user.id),
            username=verified.user.username or "",
            now=now,
        )
    logger.info("miniapp_by_telegram_signin", extra={"owner": str(owner.id)})
    return owner


def hold_signup(db: Session, *, init_data: str, now: datetime) -> str:
    """Somebody whose Telegram no cabinet holds: the finishing form (email,
    phone, role) that opens one without a password. Refused (``linked``) when
    a cabinet already holds it - the ordinary launch opens that one."""
    from app.modules.accounts.services import social_login
    from app.modules.notifications.selectors import chat_by_id

    if not is_configured():
        raise MiniAppUnavailable
    if not init_data:
        raise NotInsideTelegram
    verified = _verify(init_data=init_data, now=now)
    chat = chat_by_id(db, chat_id=verified.user.id)
    if (chat is not None and chat.is_active) or _holds_telegram(db, verified.user.id):
        raise AlreadyLinked
    vouched = social_login.telegram_vouched(
        user_id=int(verified.user.id), name="", username=verified.user.username
    )
    return social_login.hold_telegram(vouched=vouched)


def _holds_telegram(db: Session, telegram_id: str) -> bool:
    from sqlalchemy import select

    from app.modules.accounts.constants import SocialProvider
    from app.modules.accounts.models import SocialIdentity

    return (
        db.scalar(
            select(SocialIdentity.id).where(
                SocialIdentity.provider == SocialProvider.TELEGRAM,
                SocialIdentity.subject == str(telegram_id),
            )
        )
        is not None
    )


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
