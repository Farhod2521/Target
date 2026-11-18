"""Telling the team's Developers about our own faults.

Only our faults come here (a crash, an AI that would not answer, a change no
worker carried out, a write Meta took without doing it); Meta's refusals go
to Support's board instead. Each comes with its reference, what it was
about, and a log file: the traceback and the context as kept. A launch's
trace file goes too when tracing was on. The same fault for the same client
goes out once an hour, however often it repeats. Uzbek, like the trace
files: the readers are the team.
"""

import json
import logging
import uuid
from typing import Any

from sqlalchemy.orm import Session
from telegramkit import DOCUMENT_MAX_BYTES, BotClient, TelegramError

from app.common.cache import cache
from app.common.config import settings
from app.common.hooks import on
from app.common.routes import reverse
from app.modules.ads.models import CampaignLaunch
from app.modules.audit.models import ErrorEvent
from app.modules.audit.services.faults import FAULT_HOOK
from app.modules.backoffice.services import may_read_faults
from app.modules.notifications.bot import staff_bot, staff_bot_configured
from app.modules.notifications.constants import (
    DEV_ALERT_KEY,
    DEV_ALERT_MESSAGE_CHARS,
    DEV_ALERT_REPEAT_SECONDS,
)
from app.modules.notifications.selectors import launch_trace, staff_chats_where
from app.modules.notifications.services.compose import escaped

logger = logging.getLogger(__name__)
LAUNCH_SUBJECT = "launch:"


@on(FAULT_HOOK)
def queue_fault(*, event_id: str, **_: Any) -> None:
    from app.modules.notifications.tasks import deliver_fault_task

    try:
        deliver_fault_task.delay(event_id)
    except Exception:
        logger.exception("dev alert not queued", extra={"event": event_id})


def alert_fault(db: Session, *, event_id: str) -> int:
    """Send the fault to every linked Developer. Returns how many got it."""
    if not staff_bot_configured():
        return 0
    event = db.get(ErrorEvent, uuid.UUID(str(event_id)))
    if event is None or event.resolved_at is not None:
        return 0
    chat_ids = [
        chat.chat_id
        for chat in staff_chats_where(
            db, allowed=lambda user: may_read_faults(db, user=user)
        )
    ]
    if not chat_ids or not _first_in_a_while(event):
        return 0
    launch = _launch_of(db, event)
    text = fault_text(event=event, launch=launch)
    files = [(f"xato_{event.reference}.txt", fault_log(event).encode())]
    trace = launch_trace(launch_id=str(launch.id)) if launch else None
    if trace is not None and 0 < trace.stat().st_size <= DOCUMENT_MAX_BYTES:
        files.append((trace.name, trace.read_bytes()))
    delivered = 0
    with staff_bot() as client:
        for chat_id in chat_ids:
            if not _deliver(client=client, chat_id=chat_id, text=text):
                continue
            delivered += 1
            for name, content in files:
                _attach(client=client, chat_id=chat_id, name=name, content=content)
    return delivered


def fault_text(*, event: ErrorEvent, launch: CampaignLaunch | None) -> str:
    owner = event.owner
    context = event.context or {}
    lines = [
        f"🛠 <b>Tizim xatosi</b> · <code>{escaped(event.reference)}</code>",
        "",
        f"<b>Kod:</b> <code>{escaped(str(context.get('code') or event.exception))}</code>",
        f"<b>Joy:</b> <code>{escaped(event.where)}</code>",
        f"<b>Nima:</b> <code>{escaped(event.path)}</code>",
        f"<b>Mijoz:</b> {escaped(owner.full_name or '-')} · {escaped(owner.email)}",
    ]
    if event.seen > 1:
        lines.append(f"<b>Takror:</b> {event.seen} marta")
    if launch is not None:
        lines += [
            f"<b>Sahifa:</b> {escaped(launch.page.name if launch.page else '-')}",
            "<b>Kabinet:</b> "
            + escaped(launch.ad_account.name or launch.ad_account.external_id),
            f"<b>Holat:</b> {escaped(launch.status)} · {escaped(launch.step or '-')}",
        ]
    if event.message:
        lines += ["", "<b>Xato:</b>", f"<code>{_cut(event.message)}</code>"]
    links = [
        f'<a href="{escaped(_office(event))}">Developer sahifasida ochish</a>',
    ]
    if launch is not None:
        path = reverse(
            "backoffice:customer_ad",
            kwargs={"customer_id": launch.owner_id, "launch_id": launch.id},
        )
        links.append(f'<a href="{escaped(settings.site_url + path)}">Reklama</a>')
    lines += ["", " · ".join(links)]
    return "\n".join(lines)


def fault_log(event: ErrorEvent) -> str:
    """The file beside the message: everything kept, as text."""
    parts = [
        f"Havola: {event.reference}",
        f"Joy: {event.where}",
        f"Nima: {event.path}",
        f"Birinchi: {event.created_at:%Y-%m-%d %H:%M:%S} UTC",
        f"Oxirgi: {event.last_seen_at:%Y-%m-%d %H:%M:%S} UTC · {event.seen} marta",
        "",
        "Xato:",
        event.message,
        "",
        "Kontekst:",
        json.dumps(event.context or {}, ensure_ascii=False, indent=2),
    ]
    if event.trace:
        parts += ["", "Traceback:", event.trace]
    return "\n".join(parts)


def _office(event: ErrorEvent) -> str:
    return (
        f"{settings.site_url}{reverse('backoffice:engineer')}?havola={event.reference}"
    )


def _launch_of(db: Session, event: ErrorEvent) -> CampaignLaunch | None:
    if not event.path.startswith(LAUNCH_SUBJECT):
        return None
    try:
        return db.get(CampaignLaunch, uuid.UUID(event.path[len(LAUNCH_SUBJECT) :]))
    except ValueError:
        return None


def _first_in_a_while(event: ErrorEvent) -> bool:
    key = DEV_ALERT_KEY.format(event=event.id)
    return bool(cache.add(key, "1", DEV_ALERT_REPEAT_SECONDS))


def _cut(value: str) -> str:
    if len(value) <= DEV_ALERT_MESSAGE_CHARS:
        return escaped(value)
    return escaped(value[:DEV_ALERT_MESSAGE_CHARS]) + "…"


def _deliver(*, client: BotClient, chat_id: str, text: str) -> bool:
    try:
        client.send_message(chat_id=chat_id, text=text)
    except TelegramError:
        logger.warning("dev alert not delivered", extra={"chat_id": chat_id})
        return False
    return True


def _attach(*, client: BotClient, chat_id: str, name: str, content: bytes) -> None:
    try:
        client.send_document(chat_id=chat_id, filename=name, content=content)
    except TelegramError:
        logger.warning("dev alert file not delivered", extra={"chat_id": chat_id})
