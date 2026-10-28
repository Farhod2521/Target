"""Response shapes for the preparation screen, for the API reference only.

Attached with ``responses=``: the routes still return plain dicts.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.modules.integrations.schemas import (
    AdAccountOut,
    ConnectionOut,
    InstagramChoiceOut,
    PageOut,
    SlotsOut,
)


class SetupFactsOut(BaseModel):
    has_profile: bool
    has_category: bool
    connected: bool
    scopes_missing: bool
    ad_account_chosen: bool
    ad_accounts_found: int
    page_chosen: bool
    pages_found: int
    page_terms_accepted: bool | None = Field(description="Null: Meta never asked.")
    leads_subscribed: bool
    pixel_chosen: bool
    telegram_offered: bool
    telegram_linked: bool


class StepOut(BaseModel):
    id: str = Field(
        description="`connect`, `page`, `ad_account`, `profile`, `leads`, "
        "`telegram` (only where a bot is configured), `pixel`."
    )
    state: str = Field(
        description="`done`, `current`, `attention`, `waiting` or `optional`."
    )
    optional: bool


class SetupOut(BaseModel):
    facts: SetupFactsOut
    steps: list[StepOut] = Field(description="In the order the screen draws them.")
    state: dict[str, str] = Field(description="The same states keyed by step id.")
    pick: str = Field(description="State of the page + ad account row.")
    ready: bool = Field(description="A campaign can be created.")
    can_finish: bool = Field(description="`POST /start/finish` would be taken.")
    blocked_on: str = Field(
        description="The step creating is refused on (`connect`, `page`, "
        "`ad_account`, `profile`), or empty."
    )
    done: int
    total: int
    page: PageOut | None = Field(description="The chosen page.")


class ProfileOut(BaseModel):
    id: uuid.UUID
    name: str
    category: str
    category_label: str


class PickRowOut(BaseModel):
    page: PageOut
    payer: AdAccountOut | None = Field(description="The account that pays for it.")
    profile: ProfileOut | None
    problems: list[str] = Field(
        description="What stops it advertising: `no_account`, `account_off`, "
        "`account_debt`, `no_profile`, `page_role`."
    )
    warnings: list[str] = Field(description="`account_cap`, `no_instagram`.")
    paired: bool = Field(description="The account was stored by a choice.")
    ready: bool


class AccountOptionOut(BaseModel):
    account: AdAccountOut
    recommended: bool = Field(description="A campaign for this page ran on it.")
    unusable: bool = Field(description="Switched off by Meta; listed, never chosen.")


class PagePickOut(BaseModel):
    rows: list[PickRowOut]
    chosen: PickRowOut | None
    options: list[AccountOptionOut] = Field(
        description="The chosen page's accounts, recommended first, unusable last."
    )
    recommended: list[AccountOptionOut]
    others: list[AccountOptionOut]
    unusable: list[AccountOptionOut]
    any_without_instagram: bool


class OfferedPageOut(BaseModel):
    external_id: str
    name: str
    instagram_username: str


class TelegramChatOut(BaseModel):
    username: str
    linked_at: datetime


class GateOut(BaseModel):
    setup_pending: bool = Field(
        description="A live plan whose preparation is not finished: send the "
        "reader from the closed screens to `redirect_to`."
    )
    redirect_to: str
    message: str = Field(description="Shown after the redirect; empty when open.")
    closed: list[str] = Field(
        description="The cabinet sections closed until `POST /start/finish`."
    )


class StartOut(BaseModel):
    setup: SetupOut
    gate: GateOut
    pick: PagePickOut
    next_action: str = Field(
        description="What the main button does: `renew`, `launch`, `finish`, "
        "`pick`, `connect`, `profile` or `leads`."
    )
    business_label: str
    connection: ConnectionOut | None
    ad_accounts: list[AdAccountOut]
    active_ad_account: AdAccountOut | None
    ad_accounts_taken: list[dict[str, str]] = Field(
        description="Accounts the token reached that another cabinet holds."
    )
    pages: list[PageOut]
    ig_needs_permission: bool
    active_page: PageOut | None
    spare_pages: list[OfferedPageOut] = Field(
        description="Pages the subscription has not taken in."
    )
    billing_url: str = Field(description="Meta's billing page for the chosen account.")
    page_terms_url: str = Field(description="Meta's lead terms for the chosen page.")
    may_connect: bool = Field(description="False: the plan ran out.")
    account_locked: bool = Field(description="Preparation was finished.")
    page_slots: SlotsOut
    setup_instagrams: list[InstagramChoiceOut]
    telegram_chat: TelegramChatOut | None = Field(
        description="The linked phone, once the step is done."
    )
    watching_telegram: bool
    polling: bool = Field(
        description="Ask `GET /start?tries=...` again after `poll_seconds`."
    )
    tries: int = Field(description="Pass back as `tries` on the next poll.")
    poll_seconds: int
    message: str = Field("", description="Only after `POST /start/finish`.")
