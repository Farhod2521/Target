"""Response shapes for the office's shell and journal, for the API reference only.

Attached with ``responses=``: the routes still return plain dicts.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class PersonOut(BaseModel):
    id: str
    name: str
    email: str


class ChoiceOut(BaseModel):
    value: str
    label: str


class CanOut(BaseModel):
    give: bool = Field(
        description="Plan, days, slots, a payment, the referral switch "
        "(Support, Finance, Owner)."
    )
    grant: bool = Field(
        description="Money: payouts, holds, promo codes (Finance, Owner)."
    )
    owner: bool = Field(description="The roster, the journal, adding a page, deleting.")
    superuser: bool = Field(description="Setting a customer's password.")
    engineer: bool = Field(description="The faults console.")
    answer_support: bool = Field(description="The support chat queue.")
    answer_feedback: bool = Field(description="The feedback queue.")
    sell: bool = Field(description="The sales board.")
    lead_sales: bool = Field(description="The sales lead's screens: holds, settings.")


class WaitingOut(BaseModel):
    """Counts beside the rail's entries; 0 for a door this reader lacks."""

    promos: int
    asks: int = Field(description="Withdrawal requests waiting to be paid.")
    feedback: int
    support: int = Field(description="Chats whose customer spoke last.")
    arizas: int = Field(description="Home page call-back requests in the sales queue.")


class MeOut(BaseModel):
    user: PersonOut
    roles: list[ChoiceOut] = Field(description="The roles this reader holds.")
    can: CanOut
    waiting: WaitingOut


class TraceOut(BaseModel):
    id: str
    created_at: datetime
    kind: str
    kind_label: str
    reason: str
    detail: dict[str, Any]
    actor: PersonOut | None = Field(description="Gone when that member was removed.")


class JournalRowOut(TraceOut):
    customer: PersonOut


class JournalOut(BaseModel):
    kind: str
    kinds: list[ChoiceOut] = Field(
        description='Filter chips; `""` is every write, readings come last.'
    )
    rows: list[JournalRowOut]
    offset: int
    next_offset: int
    has_more: bool
