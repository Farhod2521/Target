"""Rewrite the guard's sent Telegram messages in place, with page and campaign.

    python -m tools.guard_place_telegram          # lists what would change, sends nothing
    python -m tools.guard_place_telegram --yes    # edits the messages

Run it after ``tools.guard_place_backfill``. For every open finding that now
knows its page or campaign, the message sent at its present step is
rewritten with ``editMessageText``: the same figures, the same buttons, and
«Sahifa / Kampaniya / Guruh» on top. An edit makes no sound and no new
message. A message of an earlier step is left alone - its figures were that
step's, not today's.
"""

import argparse

from sqlalchemy import select
from sqlalchemy.orm import Session
from telegramkit import BotClient, TelegramError

from app import models as _models  # noqa: F401
from app.common.db import SessionLocal
from app.common.i18n import override
from app.modules.agent.models import GuardAlert
from app.modules.notifications.constants import NoticeKind
from app.modules.notifications.models import TelegramChat, TelegramNotice
from app.modules.notifications.selectors.inbox_guard import guard_key
from app.modules.notifications.services.announce_guard import (
    guard_buttons,
    guard_message,
)

# Telegram's answer when the new text is the old one: nothing to do.
UNCHANGED = "message is not modified"


def sent_messages(
    db: Session,
) -> list[tuple[GuardAlert, TelegramNotice, TelegramChat]]:
    """Every open, named finding's message at its present step."""
    found = []
    for row in db.scalars(
        select(GuardAlert)
        .where(GuardAlert.closed_at.is_(None))
        .order_by(GuardAlert.created_at)
    ):
        figures = row.figures or {}
        if not (figures.get("page_name") or figures.get("campaign_name")):
            continue
        notice = db.scalar(
            select(TelegramNotice).where(
                TelegramNotice.owner_id == row.owner_id,
                TelegramNotice.kind == str(NoticeKind.GUARD),
                TelegramNotice.subject == guard_key(row),
                TelegramNotice.message_id > 0,
            )
        )
        if notice is None:
            continue
        chat = db.get(TelegramChat, notice.chat_id)
        if chat is None or not chat.is_active:
            continue
        found.append((row, notice, chat))
    return found


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Rewrite sent guard messages with page and campaign."
    )
    parser.add_argument("--yes", action="store_true", help="Really edit them.")
    args = parser.parse_args()

    from app.modules.notifications.bot import bot

    db = SessionLocal()
    try:
        messages = sent_messages(db)
        if not args.yes:
            for row, notice, _chat in messages:
                print(
                    f"{row.id}  {row.kind:<9} xabar={notice.message_id}  {row.name!r}"
                )
            if messages:
                row, _notice, chat = messages[0]
                with override(chat.owner.language):
                    print("\nBirinchisining yangi matni:\n")
                    print(guard_message(row))
            print(f"\nYangilanadigan xabarlar: {len(messages)}.")
            print("Hech narsa yuborilmadi. Yangilash uchun --yes qo'shing.")
            return 0
        edited = failed = 0
        with bot() as client:
            for row, notice, chat in messages:
                if _edit(client, row=row, notice=notice, chat=chat):
                    edited += 1
                else:
                    failed += 1
        print(f"\nYangilandi: {edited}, bo'lmadi: {failed}. Yangi xabar ketmadi.")
        return 0 if not failed else 1
    finally:
        db.close()


def _edit(
    client: BotClient, *, row: GuardAlert, notice: TelegramNotice, chat: TelegramChat
) -> bool:
    with override(chat.owner.language):
        text, buttons = guard_message(row), guard_buttons(row)
    try:
        client.edit_message_text(
            chat_id=chat.chat_id,
            message_id=notice.message_id,
            text=text,
            buttons=buttons,
        )
    except TelegramError as exc:
        if UNCHANGED in str(exc):
            print(f"{row.id}  allaqachon yangi")
            return True
        print(f"{row.id}  bo'lmadi: {exc}")
        return False
    print(f"{row.id}  yangilandi")
    return True


if __name__ == "__main__":
    raise SystemExit(main())
