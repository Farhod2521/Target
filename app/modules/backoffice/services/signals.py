"""The office sending what a night left unsent.

The same send the night runs, for one customer, now: finished days only,
inside the provider's window. Rows Meta refused one by one are given one
more try, since a refusal is often a pixel or token since put right.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.backoffice.constants import ActionKind
from app.modules.backoffice.exceptions import NothingToSend
from app.modules.backoffice.selectors.signals import signal_book
from app.modules.backoffice.services.journal import record
from app.modules.leads.constants import SignalStatus
from app.modules.leads.models import LeadSignal
from app.modules.leads.services.signals import report_signals

OUTCOME_WORDS = {
    "sent": "{n} ta signal Metaga yuborildi.",
    "rehearsed": "Sinov rejimi: {n} ta signal yuborilmadi, faqat tekshirildi.",
    "no_dataset": "Piksel tanlanmagan — yuborilmadi.",
    "connection_unusable": "Meta ulanishi ishlamayapti — yuborilmadi.",
    "provider_failed": "Meta javob bermadi — keyinroq qayta urinib ko'ring.",
    "nothing_ready": "Yuboriladigan signal qolmadi: muddati o'tgan.",
    "no_account": "Reklama kabineti topilmadi.",
    "nothing_due": "Yuboriladigan signal yo'q.",
    "gone": "Mijoz topilmadi.",
}


@dataclass(frozen=True)
class SendResult:
    words: list[str]
    sent: int
    waiting: int

    @property
    def message(self) -> str:
        lines = []
        for word in self.words:
            name, _, count = word.partition(":")
            text = OUTCOME_WORDS.get(name, name)
            lines.append(text.format(n=count or 0))
        return " ".join(dict.fromkeys(lines)) or OUTCOME_WORDS["nothing_due"]


def send_unsent_signals(
    db: Session, *, customer: User, actor: User, reason: str, now: datetime
) -> SendResult:
    book = signal_book(db, owner=customer, now=now)
    if not book.sendable:
        raise NothingToSend
    db.execute(
        update(LeadSignal)
        .where(
            LeadSignal.owner_id == customer.id,
            LeadSignal.status == SignalStatus.FAILED,
            LeadSignal.occurred_at >= now - timedelta(days=book.window_days),
        )
        .values(status=SignalStatus.PENDING, updated_at=now)
    )
    db.commit()
    words = report_signals(db, owner_id=customer.id, now=now).split(",")
    sent = sum(int(w.partition(":")[2] or 0) for w in words if w.startswith("sent:"))
    after = signal_book(db, owner=customer, now=now)
    result = SendResult(words=words, sent=sent, waiting=after.sendable)
    record(
        db,
        customer=customer,
        actor=actor,
        kind=ActionKind.SIGNALS_SENT,
        reason=reason,
        detail={
            "words": words,
            "sent": sent,
            "before": book.sendable,
            "waiting": after.sendable,
        },
    )
    return result


__all__ = ["OUTCOME_WORDS", "SendResult", "send_unsent_signals"]
