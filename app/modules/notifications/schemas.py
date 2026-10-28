"""Response shapes for the Telegram settings and the actions screen, for the API reference only.

Attached with ``responses=``: the routes still return plain dicts.
"""

from datetime import datetime
from typing import Any

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


# -- the actions screen ---------------------------------------------------------------


class SubjectOut(BaseModel):
    provider: str
    level: str = Field(description="`campaign`, `adset` or `ad`.")
    id: str = Field(description="The provider's id of the object.")
    name: str
    code: str = Field(description="The provider's own code for a fault, if any.")


class ItemActionOut(BaseModel):
    label: str
    href: str = Field(description="POST here; empty is advice, not a button.")
    advised: bool = Field(description="The recommended choice, drawn green.")
    confirm: str = Field(description="Ask this before posting, when not empty.")


class AskOut(BaseModel):
    label: str
    href: str = Field(description="The chat, opened about this item.")


class InboxItemOut(BaseModel):
    key: str = Field(description="Stable id; what «seen» is remembered by.")
    kind: str = Field(
        description="suggestion, stop, connection, refusal, trouble, subscription, "
        "launch, figures, leads, unpriced, ranking, advice, repair, wait, landing, "
        "creative, audience, lead_gap, sweep, unheard_page, watch, frequency, "
        "meta_hold, account_blocked, feedback or checkup."
    )
    level: str = Field(description="`urgent`, `decision` or `news`.")
    title: str
    body: str
    since: datetime | None
    action: str = Field(description="The one button's label; empty for none.")
    href: str = Field(description="Where the button goes: a frontend path or Meta.")
    method: str = Field(description="`post` for a button that changes something.")
    subject: SubjectOut | None = Field(description="The advert object it is about.")
    actions: list[ItemActionOut] = Field(
        description="A choice of buttons; drawn instead of `action` when present."
    )
    ask: AskOut


class CountsOut(BaseModel):
    new: int = Field(description="The bell: not yet shown to this reader.")
    waiting: int = Field(description="Urgent and decision items: not yet answered.")


class PolicyOut(BaseModel):
    is_enabled: bool
    self_repair: bool
    window_days: int
    cooldown_hours: int
    max_per_run: int
    budget_step_pct: int
    last_run_at: datetime | None


class HistoryOut(BaseModel):
    history: list[dict[str, Any]] = Field(
        description="Answered proposals, newest first, as `GET /agent/history` cards."
    )
    more: bool
    next_before: str | None = Field(
        description="Pass as `before` for the next page; null when there is none."
    )


class ProposalsOut(HistoryOut):
    cards: list[dict[str, Any]] = Field(description="Open proposals, as `GET /agent`.")
    policy: PolicyOut | None
    counted: bool
    late: datetime | None = Field(description="The last finished night, if late.")
    working: bool = Field(description="Poll every `poll_seconds` while true.")
    poll_seconds: int


class SummaryOut(BaseModel):
    standing: str
    last_run_at: datetime | None
    broken: bool


class AdviceOut(BaseModel):
    strategy: str
    title: str
    body: str
    href: str
    link: str
    ready: bool
    blocked_by: list[str]


class ActionsOut(ProposalsOut):
    urgent: list[InboxItemOut]
    decisions: list[InboxItemOut]
    news: list[InboxItemOut]
    summary: SummaryOut
    advice: list[AdviceOut]
    counts: CountsOut


class BellItemOut(InboxItemOut):
    fresh: bool = Field(description="New before this press; marked with a dot.")
    link: str = Field(description="Where pressing the line goes.")


class BellOut(BaseModel):
    items: list[BellItemOut] = Field(description="The first six.")
    more: int = Field(description="How many did not fit.")
    watching: bool = Field(
        description="Some account has been read: an empty list means all is well."
    )
    all_href: str


__all__ = [
    "ActionsOut",
    "BellOut",
    "ConnectOut",
    "CountsOut",
    "HistoryOut",
    "InboxItemOut",
    "MessageOut",
    "PreferencesOut",
    "ProposalsOut",
    "SettingsOut",
]
