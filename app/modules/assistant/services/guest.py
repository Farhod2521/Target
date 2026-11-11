"""A visitor's request for a person: a name and a phone, then a guest chat.

A visitor has no account, so there is no support chat to write into and no
board card to put it on (``board_cards.owner_id`` cannot be empty). The
request opens a guest support chat - the sign-in page's own, which Support
already answers from ``/office/support/guests`` and hears of in Telegram -
and the page follows it there with the token.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

from sqlalchemy.orm import Session

from app.common.cache import cache
from app.common.exceptions import Conflict, DomainError
from app.modules.assistant.constants import GUEST_TICKET_KEY
from app.modules.assistant.services.buttons import ticket_text

CLAIM_KEY: Final = "assistant:guest-ticket-claim:{turn_id}"
CLAIM_SECONDS: Final = 60


class GuestTicketMissing(DomainError):
    status_code = 404

    def __init__(self) -> None:
        super().__init__("Zayavka topilmadi yoki allaqachon yuborilgan.")


class GuestTicketBusy(Conflict):
    def __init__(self) -> None:
        super().__init__("Zayavka yuborilmoqda. Bir oz kuting.")


@dataclass(frozen=True, slots=True)
class Opened:
    token: str
    chat: Any


def send_guest_ticket(
    db: Session,
    *,
    turn_id: str,
    name: str,
    phone: str,
    email: str,
    address: str,
    now: datetime,
) -> Opened:
    """Open the guest chat with the kept request. Once per answer: a double
    press or a retry while the first is still opening is refused, and the
    request is forgotten only once the chat is written."""
    from app.modules.supportchat.services import start_guest_chat

    key = GUEST_TICKET_KEY.format(turn_id=turn_id)
    kept = cache.get(key)
    if not isinstance(kept, dict) or not kept.get("question"):
        raise GuestTicketMissing
    claim = CLAIM_KEY.format(turn_id=turn_id)
    if not cache.add(claim, "1", CLAIM_SECONDS):
        raise GuestTicketBusy
    try:
        started = start_guest_chat(
            db,
            name=name,
            phone=phone,
            email=email,
            body=ticket_text(
                question=str(kept.get("question", "")),
                summary=str(kept.get("summary", "")),
                checked=[str(line) for line in kept.get("checked", ())],
                answer=str(kept.get("answer", "")),
            ),
            address=address,
            now=now,
            email_required=False,
        )
    except BaseException:
        cache.delete(claim)
        raise
    cache.delete(key)
    return Opened(token=started.token, chat=started.chat)


__all__ = ["GuestTicketBusy", "GuestTicketMissing", "Opened", "send_guest_ticket"]
