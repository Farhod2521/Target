"""The guard's findings on the phone: one message a finding and step.

Sent by the quarter-hourly sweep, a few minutes after the guard wrote them.
A row is told while what the owner was told (``said_step``) is behind where
it stands (``step``), under a subject that names both the row and the step:
the same step is never said twice, and the next step is a new message.

A stop is always said, at any hour: it changed the owner's advertising. A
warning waits for the morning and for the owner's «takliflar» switch, and a
group gets one a day: a second warning the same day - another kind, the
next step, the same one found again - is written down for the cabinet and
not sent. Ten usual prices are a stop and are said - once the provider
answered it: «I stopped it» is said when it is so, and a refusal is said as
one, with the buttons to stop it by hand.

After a press the same message is rewritten in place (:func:`show_state`):
what was asked, the second look at the figures, the question whether a
change is still wanted, and what the provider did with it.
"""

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session
from telegramkit import BotClient, Button

from app.common.config import settings
from app.common.i18n import override
from app.common.routes import reverse
from app.modules.agent.guard_copy import (
    advised_of,
    button_label,
    buttons_of,
    guard_advice,
    guard_body,
    guard_place,
    guard_title,
)
from app.modules.agent.guard_follow_copy import confirm_label, follow_of, follow_text
from app.modules.agent.models import GuardAlert
from app.modules.audit.constants import ActionStatus
from app.modules.audit.models import ActionLog
from app.modules.miniapp.services import door_url
from app.modules.notifications.constants import (
    GUARD_CALLBACKS,
    MAX_GUARD_WARNINGS_PER_SWEEP,
    NoticeKind,
)
from app.modules.notifications.keys import press_data
from app.modules.notifications.models import TelegramChat, TelegramNotice
from app.modules.notifications.selectors import chats_wanting
from app.modules.notifications.selectors.inbox_guard import guard_key
from app.modules.notifications.services.announce import tell
from app.modules.notifications.services.compose import _bold, escaped
from app.modules.notifications.services.send import edit

STOP = "stop"


def untold(db: Session) -> list[GuardAlert]:
    """Every open finding the owner has not been told at its present step."""
    return list(
        db.scalars(
            select(GuardAlert)
            .where(
                GuardAlert.closed_at.is_(None),
                GuardAlert.said_step < GuardAlert.step,
            )
            .order_by(GuardAlert.times.desc(), GuardAlert.created_at)
        )
    )


def owners_with_findings(db: Session) -> set[object]:
    return {row.owner_id for row in untold(db)}


def announce_guard(
    db: Session, *, client: BotClient, now: datetime, asleep: set[str]
) -> int:
    """Tell every linked owner their new findings. Returns how many were sent."""
    waiting: dict[object, list[GuardAlert]] = {}
    for row in untold(db):
        waiting.setdefault(row.owner_id, []).append(row)
    if not waiting:
        return 0
    sent = 0
    for chat in db.scalars(chats_wanting(db, kind=NoticeKind.GUARD)).all():
        rows = waiting.get(chat.owner_id)
        if rows:
            sent += _announce(
                db,
                client=client,
                chat=chat,
                rows=rows,
                now=now,
                asleep=str(chat.owner_id) in asleep,
            )
    return sent


def _announce(
    db: Session,
    *,
    client: BotClient,
    chat: TelegramChat,
    rows: list[GuardAlert],
    now: datetime,
    asleep: bool,
) -> int:
    sent = warned = 0
    # The stops first: they are news whatever else waits.
    ordered = sorted(rows, key=lambda row: row.action != STOP)
    told_today = _groups_told_today(db, owner_id=chat.owner_id, now=now)
    with override(chat.owner.language):
        for row in ordered:
            if row.action == STOP and not _stop_answered(db, row=row, now=now):
                # On its way to the provider: said once it is so, or refused.
                continue
            if row.action != STOP:
                if asleep or not chat.notify_suggestions:
                    continue
                if _group_of(row) in told_today:
                    # Said once today already: the cabinet has it.
                    row.said_step = row.step
                    db.commit()
                    continue
                if warned >= MAX_GUARD_WARNINGS_PER_SWEEP:
                    break
            told = tell(
                db,
                client=client,
                chat=chat,
                kind=NoticeKind.GUARD,
                subject=guard_key(row),
                text=guard_message(row),
                buttons=guard_buttons(row),
                now=now,
            )
            if told is False:
                # Telegram refused this one; the next sweep tries again.
                break
            # Told now, or claimed before: either way this step is done.
            row.said_step = row.step
            if told:
                row.telegram_sent_at = now
                row.telegram_message_id = _message_id(db, row=row) or None
                sent += 1
                warned += row.action != STOP
            told_today.add(_group_of(row))
            db.commit()
    return sent


def _stop_answered(db: Session, *, row: GuardAlert, now: datetime) -> bool:
    """Whether the provider answered the guard's stop; its answer goes on the
    row here when the write's own note of it did not."""
    from app.modules.agent.services.guard_outcome import settle

    if row.result or row.action_log_id is None:
        return True
    log = db.get(ActionLog, row.action_log_id)
    if log is None:
        return True
    if log.status == ActionStatus.PENDING:
        return False
    settle(row, log=log, now=now)
    db.flush()
    return True


def _message_id(db: Session, *, row: GuardAlert) -> int:
    found = _notice(db, row=row)
    return int(found.message_id) if found is not None else 0


def _notice(db: Session, *, row: GuardAlert) -> TelegramNotice | None:
    """The newest message the phone was sent about this finding."""
    return db.scalar(
        select(TelegramNotice)
        .where(
            TelegramNotice.owner_id == row.owner_id,
            TelegramNotice.kind == str(NoticeKind.GUARD),
            TelegramNotice.subject.startswith(f"guard:{row.id}:"),
            TelegramNotice.message_id > 0,
        )
        .order_by(TelegramNotice.sent_at.desc().nulls_last())
        .limit(1)
    )


def show_state(
    db: Session, *, client: BotClient, row: GuardAlert, message_id: int = 0
) -> bool:
    """Rewrite the finding's sent message with what became of it. Returns
    whether there was a message to rewrite."""
    notice = _notice(db, row=row)
    if notice is None:
        return False
    chat = db.get(TelegramChat, notice.chat_id)
    message = message_id or notice.message_id
    if not message or chat is None or not chat.is_active:
        return False
    with override(chat.owner.language):
        edit(
            client=client,
            chat_id=chat.chat_id,
            message_id=int(message),
            text=guard_message(row),
            buttons=guard_buttons(row),
        )
    return True


def _group_of(row: GuardAlert) -> tuple[object, str]:
    return (row.ad_account_id, row.adset_external_id or row.external_id)


def _groups_told_today(
    db: Session, *, owner_id: object, now: datetime
) -> set[tuple[object, str]]:
    """The owner's groups the phone heard about today, each in its own
    account's clock - a stop included: a warning after it waits a day."""
    rows = db.scalars(
        select(GuardAlert).where(
            GuardAlert.owner_id == owner_id,
            GuardAlert.telegram_sent_at.is_not(None),
            GuardAlert.telegram_sent_at > now - timedelta(days=2),
        )
    )
    found: set[tuple[object, str]] = set()
    for row in rows:
        clock = row.ad_account.tzinfo()
        sent_at = row.telegram_sent_at
        if (
            sent_at is not None
            and sent_at.astimezone(clock).date() == now.astimezone(clock).date()
        ):
            found.add(_group_of(row))
    return found


def guard_message(row: GuardAlert) -> str:
    """The title, where it sits, the figures and cause, and the advice."""
    lines = [_bold(guard_title(row)), ""]
    lines += [escaped(f"{label}: {name}") for label, name in guard_place(row)]
    lines += ["", escaped(guard_body(row))]
    line, answers = follow_of(row)
    if answers is None and (row.action != STOP or row.result == "failed"):
        lines += ["", escaped(guard_advice(row))]
    if line:
        lines += ["", escaped(line)]
    return "\n".join(lines)


def guard_buttons(row: GuardAlert) -> tuple[Button, ...]:
    """The finding's answers, the advised one first - or, after a press, the
    ones its present state offers: none while a change is on its way, yes
    and no while the owner is asked whether it is still wanted."""
    _line, shown = follow_of(row)
    if shown is not None:
        return tuple(
            Button(
                text=confirm_label(row.pending_answer)
                if answer == "confirm"
                else follow_text("button.cancel"),
                data=press_data(action=GUARD_CALLBACKS[answer], pk=row.id),
            )
            for answer in shown
        )
    advised = advised_of(row)
    answers = sorted(buttons_of(row), key=lambda answer: answer != advised)
    found: list[Button] = []
    for answer in answers:
        if answer == "add_creative":
            if settings.site_url.startswith("https://"):
                found.append(
                    Button(
                        text=button_label(answer),
                        web_app=door_url(
                            destination=reverse("agent:guard_creative", args=[row.id])
                        ),
                    )
                )
            continue
        found.append(
            Button(
                text=button_label(answer),
                data=press_data(action=GUARD_CALLBACKS[answer], pk=row.id),
            )
        )
    return tuple(found)


__all__ = [
    "announce_guard",
    "guard_buttons",
    "guard_message",
    "owners_with_findings",
    "show_state",
    "untold",
]
