"""The cabinet's Telegram settings: link, unlink, which notices to get."""

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from app.api.deps import CurrentUser, Db
from app.common.db import utcnow
from app.modules.notifications import selectors, services
from app.modules.notifications.bot import bot_home, deep_link, is_configured
from app.modules.notifications.models import TelegramChat

router = APIRouter(prefix="/notifications", tags=["notifications"])
PREFERENCE_LABELS = {
    "notify_suggestions": "Agent taklif qilganda",
    "notify_spend_guard": "Bugun pul natijasiz ketayotganda - to'xtatish tugmasi bilan",
    "notify_daily_report": "Har kuni - kechagi kun xulosasi va AI bahosi",
    "notify_report": "Har dushanba - o'tgan hafta xulosasi",
    "notify_rejections": "Reklama rad etilganda yoki Meta profil tasdig'ini so'raganda",
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


@router.get("")
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


@router.post("/connect")
def connect(user: CurrentUser) -> dict[str, str]:
    token = services.issue_link_token(owner=user)
    return {"url": deep_link(payload=token)}


@router.post("/disconnect")
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


@router.post("/preferences")
def preferences(body: PreferencesIn, db: Db, user: CurrentUser) -> dict[str, Any]:
    chat = services.save_preferences(db, user=user, **body.model_dump())
    db.commit()
    return {"message": "Saqlandi.", "chat": chat_out(chat)}
