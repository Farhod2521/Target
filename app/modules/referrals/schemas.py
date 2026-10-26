"""Response shapes for the referral wallet, for the API reference only.

Attached with ``responses=``: the routes still return plain dicts.
"""

from datetime import datetime

from pydantic import BaseModel, Field

from app.modules.referrals.selectors import PlanReward, WalletBalance, WalletCounts


class RewardOut(BaseModel):
    kind: str = Field(description="`text`, `audio` or `video`.")
    label: str
    percent: int
    amount_minor: int
    status: str
    reason: str
    paid_minor: int
    paid_currency: str
    is_shut: bool
    may_send: bool
    is_paid: bool


class FeedbackOfferOut(BaseModel):
    is_open: bool
    rewards: list[RewardOut]
    total_minor: int
    currency: str
    total_percent: int
    earned_percent: int
    earned_minor: int
    earned_currency: str
    is_done: bool


class BonusOut(BaseModel):
    friends: int
    friends_max: int
    plan_rewards: list[PlanReward] = Field(
        description="What inviting `friends` friends to each plan earns."
    )


class InvitedOut(BaseModel):
    email: str
    full_name: str
    joined_at: datetime
    state: str
    first_minor: int | None
    reward_minor: int
    currency: str


class FeedbackRow(BaseModel):
    kind: str
    status: str
    reason: str
    amount_minor: int
    currency: str
    created_at: datetime


class SpendOut(BaseModel):
    amount_minor: int
    currency: str
    invoice: str
    created_at: datetime


class WithdrawalOut(BaseModel):
    id: str
    amount_minor: int
    currency: str
    status: str
    method: str
    card_last4: str
    reject_reason: str
    created_at: datetime
    decided_at: datetime | None


class OpenAsk(BaseModel):
    id: str
    amount_minor: int
    currency: str


class WalletOut(BonusOut):
    eligible: bool = Field(description="May invite friends.")
    invite_link: str
    share_url: str
    invited: list[InvitedOut] = Field(description="Page `page_i`, 20 a page.")
    invited_total: int
    invited_paid: int
    feedback: FeedbackOfferOut | None
    feedback_rows: list[FeedbackRow] = Field(description="Page `page_f`, 20 a page.")
    feedback_text_min: int
    payable: bool = Field(description="A withdrawal may be asked for now.")
    withdrawals_open: bool
    referral_percent: int
    balance: WalletBalance
    available_whole: str = Field(description="Available balance, whole units, spaced.")
    counts: WalletCounts
    last_spend: SpendOut | None
    withdrawals: list[WithdrawalOut] = Field(description="Page `page_p`, 20 a page.")
    open_ask: OpenAsk | None = Field(description="A withdrawal still being decided.")


class CodeOut(BaseModel):
    code: str
    link: str
    share_url: str


class InviteOut(BaseModel):
    link: str
    share_url: str
    percent: int
    top_bonus: PlanReward | None


class IdOut(BaseModel):
    id: str


class FeedbackSentOut(IdOut):
    detail: str


class PromptAnswerOut(BaseModel):
    answer: str = Field(description="`open` or `later`.")


__all__ = [
    "BonusOut",
    "CodeOut",
    "FeedbackOfferOut",
    "FeedbackSentOut",
    "IdOut",
    "InviteOut",
    "PromptAnswerOut",
    "WalletOut",
]
