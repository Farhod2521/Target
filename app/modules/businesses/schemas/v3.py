"""What ``/api/v3/businesses`` says and takes."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.modules.businesses.schemas import BusinessOut

Area = Literal["ads", "crm"]
Level = Literal["view", "edit"]
Role = Literal["targetolog", "sales"]


class GrantOut(BaseModel):
    area: Area
    provider: str
    level: Level


class GrantIn(BaseModel):
    area: Area
    provider: str = Field(min_length=1, max_length=32)
    level: Level


class PageOut(BaseModel):
    id: uuid.UUID
    external_id: str
    name: str
    instagram_username: str


class AccountOut(BaseModel):
    id: uuid.UUID
    external_id: str
    name: str
    currency: str


class NetworkOut(BaseModel):
    """One network the business advertises on. ``pair`` is the value the
    older ``?pair=`` parameters take for this business's Meta pair."""

    provider: str
    kind: str
    pair: str
    page: PageOut | None
    ad_account: AccountOut | None
    bound_at: datetime


class AccessOut(BaseModel):
    is_owner: bool
    roles: list[Role]
    is_rop: bool
    reads_all_leads: bool
    grants: list[GrantOut]


class BusinessCardOut(BaseModel):
    id: uuid.UUID
    name: str
    category_label: str
    city: str
    networks: list[NetworkOut]
    access: AccessOut


class BusinessListOut(BaseModel):
    businesses: list[BusinessCardOut]


class BusinessDetailOut(BusinessCardOut):
    profile: BusinessOut
    members_count: int | None


class RoleOut(BaseModel):
    key: Role
    label: str
    may_be_rop: bool
    grants: list[GrantOut]


class ChoiceOut(BaseModel):
    key: str
    label: str


class CatalogOut(BaseModel):
    """What the member form offers. A role's ``grants`` are written with
    ``provider`` ``*``: one for every network of the business."""

    roles: list[RoleOut]
    areas: list[ChoiceOut]
    levels: list[ChoiceOut]
    other_source: ChoiceOut


class PersonOut(BaseModel):
    id: uuid.UUID
    full_name: str
    email: str


class MemberOut(BaseModel):
    id: uuid.UUID
    user: PersonOut
    roles: list[Role]
    is_rop: bool
    is_active: bool
    joined_at: datetime
    removed_at: datetime | None
    # A sales manager the CRM section added: taken out there, not here.
    from_crm: bool
    grants: list[GrantOut]
    # Taking them out of this business closes their login: they work nowhere
    # else of the owner's.
    login_closes: bool = False
    # The seat they sit in: the business page's free one, a bought one, or
    # none - they wait for a seat and may not work until one is bought.
    seat: Literal["free", "paid", "none"] = "none"


class SeatsOut(BaseModel):
    """Seats across every business of the owner's. One person in one
    business takes one seat, whatever they do there."""

    # People sitting in a seat, the seats there are, and the ones empty.
    taken: int
    capacity: int
    free: int
    # People with no seat: they may not work until one is bought.
    waiting: int = 0
    # Whether one more person added to THIS business would sit: its page's
    # free seat is empty, or a bought one is.
    open_here: bool = False


class MembersOut(BaseModel):
    members: list[MemberOut]
    seats: SeatsOut
    # The owner's people who do not work in this business yet.
    candidates: list[PersonOut]
    networks: list[str]


class MemberIn(BaseModel):
    """Either ``user_id`` of one of the owner's people, or a new login."""

    user_id: uuid.UUID | None = None
    name: str = Field(default="", max_length=255)
    email: str = Field(default="", max_length=254)
    password: str = Field(default="", max_length=128)
    roles: list[Role] = Field(min_length=1)
    is_rop: bool = False
    grants: list[GrantIn] | None = None


class MemberPatch(BaseModel):
    roles: list[Role] = Field(min_length=1)
    is_rop: bool = False
    grants: list[GrantIn] | None = None


class MemberPasswordIn(BaseModel):
    password: str = Field(min_length=1, max_length=128)


class PixelOut(BaseModel):
    id: uuid.UUID
    external_id: str
    name: str
    # The one the business's adverts are measured with.
    is_active: bool
    is_unavailable: bool
    last_fired_at: datetime | None


class PixelsOut(BaseModel):
    pixels: list[PixelOut]


class AccountChoiceOut(BaseModel):
    """One of the owner's accounts on another network, free to tie on."""

    id: uuid.UUID
    provider: str
    external_id: str
    name: str
    currency: str


class NetworksOut(BaseModel):
    networks: list[NetworkOut]
    available: list[AccountChoiceOut]


class NetworkIn(BaseModel):
    ad_account_id: uuid.UUID


class HistoryPersonOut(BaseModel):
    member_id: uuid.UUID | None
    user_id: uuid.UUID | None
    full_name: str


class StandingOut(BaseModel):
    roles: list[str]
    is_rop: bool
    grants: list[GrantOut]


class HistoryItemOut(BaseModel):
    """One change to who works in the business or what it advertises from.

    ``kind`` is ``member_added``, ``member_changed``, ``member_removed``,
    ``network_bound`` or ``network_unbound``. ``via`` is ``crm`` for a change
    the CRM section made (a manager added or removed there).
    """

    id: uuid.UUID
    at: datetime
    kind: str
    label: str
    via: str
    member: HistoryPersonOut | None
    before: StandingOut | None
    after: StandingOut | None
    provider: str
    account_name: str


class HistoryOut(BaseModel):
    items: list[HistoryItemOut]
