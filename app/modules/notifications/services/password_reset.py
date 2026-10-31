"""A forgotten password, answered in the bot.

The sign-in page cannot tell who is asking - it is public, and there is no
email delivery to prove an address with. The bot can: a chat linked from a
signed-in cabinet is that cabinet's owner's phone. So the page only opens
the bot, and the bot sends the new-password link to the chat it belongs to.

A chat that is not linked, or was switched off, gets the support desk
instead. A switched-off link is the record of a phone somebody stopped
using - which may be the phone they sold - and it opens nothing.
"""

import logging
from datetime import datetime

from sqlalchemy.orm import Session
from telegramkit import BotClient, Button, TelegramError

from app.common.config import settings
from app.common.db import on_commit
from app.common.i18n import override
from app.common.routes import reverse
from app.modules.accounts.models import User
from app.modules.accounts.services import issue_password_reset
from app.modules.notifications.bot import bot, deep_link, is_configured
from app.modules.notifications.constants import RESET_PAYLOAD
from app.modules.notifications.models import TelegramChat
from app.modules.notifications.selectors import chat_for
from app.modules.notifications.services.compose import escaped
from app.modules.notifications.services.send import send_to

logger = logging.getLogger(__name__)


def reset_bot_link() -> str:
    """Where "Parolni unutdingizmi?" points, or empty with no bot."""
    if not is_configured():
        return ""
    return deep_link(payload=RESET_PAYLOAD)


def answer_reset_request(
    *, client: BotClient, chat_id: str, known: TelegramChat | None
) -> str:
    """The new-password link for a linked chat, the support desk otherwise."""
    if known is None or not known.is_active or not known.owner.is_active:
        _reply(
            client=client,
            chat_id=chat_id,
            text=(
                "Bu Telegram hech qaysi kabinetga ulanmagan, shuning uchun "
                "parolni bu yerda tiklab bo'lmaydi. Yordam xizmatiga yozing - "
                "parolni tiklashga yordam beramiz."
            ),
            buttons=_support_button(),
        )
        return "reset_unlinked"

    owner = known.owner
    path = reverse("accounts:password_reset", [issue_password_reset(owner=owner)])
    _reply(
        client=client,
        chat_id=chat_id,
        text=(
            f"{masked_email(owner.email)} akkaunti uchun yangi parol o'rnating. "
            "Havola 15 daqiqa ishlaydi va bir marta ishlatiladi. Buni siz "
            "so'ramagan bo'lsangiz, e'tibor bermang."
        ),
        buttons=(
            Button(
                text="Parolni yangilash",
                url=f"{settings.site_url}{path}",
                style="success",
            ),
        ),
    )
    return "reset_sent"


def queue_password_changed(db: Session, *, owner: User) -> None:
    """Tell the linked phone once the new password has committed."""
    from app.modules.notifications.tasks import deliver_password_changed_task

    owner_id = str(owner.id)
    on_commit(db, lambda: deliver_password_changed_task.delay(owner_id))


def announce_password_changed(db: Session, *, owner: User, now: datetime) -> bool:
    """ "Your password changed", so a change nobody asked for is noticed.

    No journal claim: the message answers something the reader just did,
    and a redelivered task saying it twice costs less than a new notice
    kind would.
    """
    chat = chat_for(db, owner=owner)
    if chat is None or not is_configured():
        return False
    with override(owner.language), bot() as client:
        sent = send_to(
            db,
            client=client,
            chat=chat,
            text=escaped(
                "Parolingiz o'zgartirildi. Boshqa qurilmalardagi kirishlar "
                "yopildi. Buni siz qilmagan bo'lsangiz, darhol yordam "
                "xizmatiga yozing."
            ),
            buttons=_support_button(),
            now=now,
        )
    return bool(sent)


def masked_email(email: str) -> str:
    """``a***@gmail.com``: enough to tell two accounts apart, not to read."""
    name, _at, domain = email.partition("@")
    return f"{name[:1]}***@{domain}" if domain else "***"


def _support_button() -> tuple[Button, ...]:
    if not settings.support_telegram_url:
        return ()
    return (Button(text="Yordam xizmati", url=settings.support_telegram_url),)


def _reply(
    *, client: BotClient, chat_id: str, text: str, buttons: tuple[Button, ...]
) -> None:
    """A reply without a stored chat to blame a failure on - see ``respond._say``."""
    try:
        client.send_message(chat_id=chat_id, text=escaped(text), buttons=buttons)
    except TelegramError as exc:
        logger.info("telegram_reply_failed", extra={"reason": str(exc)})


__all__ = [
    "announce_password_changed",
    "answer_reset_request",
    "masked_email",
    "queue_password_changed",
    "reset_bot_link",
]
