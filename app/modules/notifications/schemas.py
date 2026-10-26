"""Response shapes for the Telegram settings, for the API reference only.

Attached with ``responses=``: the routes still return plain dicts.
"""

from datetime import datetime

from pydantic import BaseModel, Field


class ChatOut(BaseModel):
    username: str
    is_active: bool
    linked_at: datetime | None
    last_error: str
    last_error_at: datetime | None
    notify_suggestions: bool
    notify_spend_guard: bool
    notify_daily_report: bool
    notify_report: bool
    notify_rejections: bool


class SettingsOut(BaseModel):
    chat: ChatOut | None = Field(description="The last linked chat, if any.")
    is_linked: bool
    bot_ready: bool = Field(description="The bot is configured on this server.")
    bot_url: str
    preferences: dict[str, str] = Field(
        description="Each `notify_*` switch and its label."
    )
    undelivered: int = Field(description="Notices that could not be sent lately.")


class ConnectOut(BaseModel):
    url: str = Field(description="Open this Telegram link to finish linking.")


class MessageOut(BaseModel):
    message: str


class PreferencesOut(MessageOut):
    chat: ChatOut | None


__all__ = ["ConnectOut", "MessageOut", "PreferencesOut", "SettingsOut"]
