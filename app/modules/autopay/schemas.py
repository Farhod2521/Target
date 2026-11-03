from datetime import datetime

from pydantic import BaseModel, Field

from app.modules.autopay.constants import CHARGE_LEAD
from app.modules.autopay.models import SavedCard


class BindIn(BaseModel):
    consent: bool = Field(
        description="The owner agreed to renew the plan from this card each term."
    )
    phone: str = Field(
        "",
        max_length=20,
        description="The card owner's phone, 998XXXXXXXXX. Empty: the account's.",
    )


class AutopayIn(BaseModel):
    enabled: bool


class BindOut(BaseModel):
    session_id: str
    form_url: str = Field(description="Open it: Multicard's page for adding a card.")


class ShownCard(BaseModel):
    pan: str = Field(description="Masked: 986027******1519.")
    ps: str = Field(description="uzcard, humo, visa, mastercard or unionpay.")
    holder: str
    bound_at: datetime | None


class LastCharge(BaseModel):
    at: datetime | None
    outcome: str = Field(description="charged, pending, declined or needs_code.")
    error: str = Field(description="Why it failed, ready to show. Empty otherwise.")


class CardOut(BaseModel):
    available: bool = Field(description="Autopay is switched on for this deployment.")
    card: ShownCard | None = None
    autopay: bool = False
    pending: bool = Field(
        False, description="This binding page has not returned a card yet."
    )
    next_charge_at: datetime | None = Field(
        None, description="When the plan will be renewed from the card."
    )
    last_charge: LastCharge | None = None


def card_out(
    card: SavedCard | None,
    *,
    available: bool,
    expires_at: datetime | None = None,
    pending: bool = False,
) -> CardOut:
    if card is None or card.status != "active":
        return CardOut(available=available, pending=pending)
    last = (
        LastCharge(
            at=card.last_charge_at,
            outcome=card.last_charge_outcome,
            error=card.last_charge_error,
        )
        if card.last_charge_outcome
        else None
    )
    return CardOut(
        available=available,
        card=ShownCard(
            pan=card.pan, ps=card.ps, holder=card.holder, bound_at=card.bound_at
        ),
        autopay=card.autopay,
        next_charge_at=(
            expires_at - CHARGE_LEAD if card.autopay and expires_at else None
        ),
        last_charge=last,
    )
