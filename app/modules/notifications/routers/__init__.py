"""The cabinet's Telegram settings: link, unlink, which notices to get."""

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from app.api.deps import CurrentUser, Db
from app.common.db import utcnow
from app.modules.notifications import selectors, services
from app.modules.notifications.bot import (
    bot_home,
    deep_link,
    is_configured,
    support_bot_configured,
)
from app.modules.notifications.models import TelegramChat
from app.modules.notifications.schemas import (
    ConnectOut,
    MessageOut,
    PreferencesOut,
    SettingsOut,
    SupportBotOut,
)

router = APIRouter(prefix="/notifications", tags=["notifications"])
PREFERENCE_LABELS = {
    "notify_suggestions": "Agent taklif qilganda",
    "notify_spend_guard": "Bugun pul natijasiz ketayotganda",
    "notify_daily_report": "Har kuni - kechagi kun xulosasi",
    "notify_report": "Har dushanba - o'tgan hafta xulosasi",
    "notify_rejections": "Reklama rad etilganda yoki Meta profil tasdig'ini so'raganda",
    "notify_news": "Yangiliklar va e'lonlar",
}


def chat_out(chat: TelegramChat | None) -> dict[str, Any] | None:
    if chat is None:
        return None
    return {
        "username": chat.username,
        "is_active": chat.is_active,
        "linked_at": chat.linked_at,
        "last_error": chat.last_error,
        "last_error_at": chat.last_error_at,
        **{field: getattr(chat, field) for field in PREFERENCE_LABELS},
    }


@router.get("", responses={200: {"model": SettingsOut}})
def settings_screen(db: Db, user: CurrentUser) -> dict[str, Any]:
    chat = selectors.last_chat_for(db, owner=user)
    return {
        "chat": chat_out(chat),
        "is_linked": chat is not None and chat.is_active,
        "bot_ready": is_configured(),
        "bot_url": bot_home() if is_configured() else "",
        "preferences": PREFERENCE_LABELS,
        "undelivered": selectors.undelivered_notices(db, owner=user, now=utcnow()),
    }


@router.post("/connect", responses={200: {"model": ConnectOut}})
def connect(user: CurrentUser) -> dict[str, str]:
    token = services.issue_link_token(owner=user)
    return {"url": deep_link(payload=token)}


@router.get("/support-bot", responses={200: {"model": SupportBotOut}})
def support_bot_link(db: Db, user: CurrentUser) -> dict[str, Any]:
    """The help window's «Telegramda yozish»: a fresh link each time, so
    the Telegram that opens it writes into this account's support chat."""
    if not support_bot_configured() or not services.may_use_support_bot(user):
        return {"available": False, "linked": False, "url": ""}
    return {
        "available": True,
        "linked": selectors.support_bot_chat_for(db, owner=user) is not None,
        "url": services.support_link_url(owner=user),
    }


@router.post("/disconnect", responses={200: {"model": MessageOut}})
def disconnect(db: Db, user: CurrentUser) -> dict[str, str]:
    services.unlink_chat(db, owner=user)
    db.commit()
    return {"message": "Telegram uzildi."}


class PreferencesIn(BaseModel):
    notify_suggestions: bool = False
    notify_spend_guard: bool = False
    notify_daily_report: bool = False
    notify_report: bool = False
    notify_rejections: bool = False
    # Left out keeps it as it is: a screen built before the switch existed
    # does not turn the news off by saving the others.
    notify_news: bool | None = None


@router.post("/preferences", responses={200: {"model": PreferencesOut}})
def preferences(body: PreferencesIn, db: Db, user: CurrentUser) -> dict[str, Any]:
    chat = services.save_preferences(
        db, user=user, **body.model_dump(exclude_none=True)
    )
    db.commit()
    return {"message": "Saqlandi.", "chat": chat_out(chat)}
