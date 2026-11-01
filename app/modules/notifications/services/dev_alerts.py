"""Telling the team's Developers that a campaign could not be created.

The launch's own screen tells the customer. This is the office's copy, with the
provider's words and the trace file if tracing was on, in the staff bot. The same
failure for the same customer goes out once an hour. Uzbek, like the trace files:
the readers are the team.
"""

import hashlib
import logging
from typing import Any

from sqlalchemy.orm import Session
from telegramkit import DOCUMENT_MAX_BYTES, BotClient, TelegramError

from app.common.cache import cache
from app.common.config import settings
from app.common.hooks import on
from app.common.routes import reverse
from app.modules.ads.constants import LaunchStatus
from app.modules.ads.models import CampaignLaunch
from app.modules.ads.services.creation import LAUNCH_FAILED_HOOK
from app.modules.backoffice.services import may_read_faults
from app.modules.notifications.bot import staff_bot, staff_bot_configured
from app.modules.notifications.constants import (
    DEV_ALERT_KEY,
    DEV_ALERT_MESSAGE_CHARS,
    DEV_ALERT_REPEAT_SECONDS,
)
from app.modules.notifications.selectors import (
    failed_launch,
    launch_trace,
    staff_chats_where,
)
from app.modules.notifications.services.compose import escaped

logger = logging.getLogger(__name__)


@on(LAUNCH_FAILED_HOOK)
def queue_launch_failure(*, launch_id: str, **_: Any) -> None:
    from app.modules.notifications.tasks import deliver_launch_failure_task

    try:
        deliver_launch_failure_task.delay(launch_id)
    except Exception:
        logger.exception("dev alert not queued", extra={"launch_id": launch_id})


def report_launch_failure(db: Session, *, launch_id: str) -> int:
    """Send the report to every linked Developer. Returns how many got it."""
    if not staff_bot_configured():
        return 0
    launch = failed_launch(db, launch_id=launch_id)
    if launch is None:
        return 0
    chat_ids = [
        chat.chat_id
        for chat in staff_chats_where(
            db, allowed=lambda user: may_read_faults(db, user=user)
        )
    ]
    if not chat_ids or not _first_in_a_while(launch):
        return 0
    text = launch_failure_text(launch=launch)
    trace = launch_trace(launch_id=str(launch.id))
    content = (
        trace.read_bytes()
        if trace and 0 < trace.stat().st_size <= DOCUMENT_MAX_BYTES
        else None
    )
    delivered = 0
    with staff_bot() as client:
        for chat_id in chat_ids:
            if not _deliver(client=client, chat_id=chat_id, text=text):
                continue
            delivered += 1
            if trace is not None and content is not None:
                _attach(
                    client=client, chat_id=chat_id, name=trace.name, content=content
                )
    return delivered


def launch_failure_text(*, launch: CampaignLaunch) -> str:
    owner = launch.owner
    rolled_back = launch.status == LaunchStatus.ROLLED_BACK
    lines = [
        "🔴 <b>Reklama yaratilmadi</b>",
        "",
        f"<b>Kod:</b> <code>{escaped(launch.error_code or '-')}</code>",
        f"<b>Holat:</b> {escaped(launch.status)}"
        + (" (yaratilganlari o'chirildi)" if rolled_back else ""),
        f"<b>Mijoz:</b> {escaped(owner.full_name or '-')} · {escaped(owner.email)}",
        f"<b>Sahifa:</b> {escaped(launch.page.name if launch.page else '-')}",
        f"<b>Kabinet:</b> {escaped(launch.ad_account.name or launch.ad_account.external_id)}",
        f"<b>Platforma:</b> {escaped(launch.provider)}",
        f"<b>Launch:</b> <code>{launch.id}</code>",
    ]
    if launch.error_message:
        lines += ["", "<b>Xato:</b>", f"<code>{_cut(launch.error_message)}</code>"]
    said = _provider_words(launch)
    if said:
        lines += ["", "<b>Meta mijozga aytgani:</b>", _cut(said)]
    path = reverse(
        "backoffice:customer_ad",
        kwargs={"customer_id": launch.owner_id, "launch_id": launch.id},
    )
    lines += ["", f'<a href="{escaped(settings.site_url + path)}">Ofisda ochish</a>']
    return "\n".join(lines)


def _first_in_a_while(launch: CampaignLaunch) -> bool:
    digest = hashlib.sha1(launch.error_message.encode(), usedforsecurity=False)
    key = DEV_ALERT_KEY.format(
        owner=launch.owner_id, code=launch.error_code, digest=digest.hexdigest()[:12]
    )
    return bool(cache.add(key, "1", DEV_ALERT_REPEAT_SECONDS))


def _provider_words(launch: CampaignLaunch) -> str:
    detail = launch.error_detail or {}
    parts = [str(detail.get("title") or ""), str(detail.get("message") or "")]
    return " — ".join(part for part in parts if part.strip())


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
        logger.warning("dev alert trace not delivered", extra={"chat_id": chat_id})
