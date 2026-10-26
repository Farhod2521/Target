from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, File, Form, Query, UploadFile
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field, field_validator

from app.api.deps import CurrentUser, Db
from app.common.config import settings
from app.common.db import utcnow
from app.common.money import decimal_places, to_minor
from app.modules.referrals import selectors, services
from app.modules.referrals.constants import (
    BONUS_FRIENDS_MAX,
    CARD_HOLDER_MAX,
    FEEDBACK_TEXT_MAX,
    FEEDBACK_TEXT_MIN,
    REFERRAL_PERCENT,
    FeedbackKind,
    FeedbackPromptAnswer,
)
from app.modules.referrals.schemas import (
    BonusOut,
    CodeOut,
    FeedbackOfferOut,
    FeedbackSentOut,
    IdOut,
    InviteOut,
    PromptAnswerOut,
    WalletOut,
)
from app.modules.referrals.selectors import FeedbackOffer, WalletBalance

router = APIRouter(prefix="/referrals", tags=["referrals"])
landing = APIRouter(tags=["referrals"])
HISTORY_PER_PAGE = 20


def _offer(offer: FeedbackOffer | None) -> dict[str, Any] | None:
    if offer is None:
        return None
    return {
        "is_open": offer.is_open,
        "rewards": [
            asdict(row) | {"may_send": row.may_send, "is_paid": row.is_paid}
            for row in offer.rewards
        ],
        "total_minor": offer.total_minor,
        "currency": offer.currency,
        "total_percent": offer.total_percent,
        "earned_percent": offer.earned_percent,
        "earned_minor": offer.earned_minor,
        "earned_currency": offer.earned_currency,
        "is_done": offer.is_done,
    }


def _cut(rows: list[Any], page: int) -> list[Any]:
    return rows[(page - 1) * HISTORY_PER_PAGE : page * HISTORY_PER_PAGE]


def _main_balance(balances: tuple[WalletBalance, ...]) -> WalletBalance:
    found = next(
        (row for row in balances if row.currency == settings.billing_currency), None
    )
    if found is None and balances:
        found = max(balances, key=lambda row: row.available_minor)
    return found or WalletBalance(settings.billing_currency, 0, 0, 0, 0)


def _bonus(db: Db, *, friends: int) -> dict[str, Any]:
    friends = max(1, min(friends, BONUS_FRIENDS_MAX))
    return {
        "friends": friends,
        "friends_max": BONUS_FRIENDS_MAX,
        "plan_rewards": [
            asdict(row) for row in selectors.plan_rewards(db, friends=friends)
        ],
    }


@router.get("", responses={200: {"model": WalletOut}})
def wallet(
    db: Db,
    user: CurrentUser,
    page_i: int = Query(1, ge=1, description="Page of `invited`, 20 a page."),
    page_p: int = Query(1, ge=1, description="Page of `withdrawals`, 20 a page."),
    page_f: int = Query(1, ge=1, description="Page of `feedback_rows`, 20 a page."),
) -> dict[str, Any]:
    eligible = selectors.may_invite(db, owner_id=user.id)
    code = selectors.code_of(db, owner=user) if eligible else None
    link = selectors.invite_link(code=code.code) if code else ""
    invited = selectors.invited_users(db, owner=user)
    shown = _cut(invited, page_i)
    rows = selectors.invited_rows(db, owner=user, bindings=shown, now=utcnow())
    balance = _main_balance(selectors.wallet_balance(db, owner=user))
    spends = selectors.spend_history(db, owner=user)
    payouts = selectors.payout_history(db, owner=user)
    feedback = selectors.feedback_history(db, owner=user)
    ask = selectors.open_withdrawal(db, owner=user)
    return {
        "eligible": eligible,
        "invite_link": link,
        "share_url": selectors.share_url(link=link) if link else "",
        "invited": [
            {
                "email": row.binding.owner.email,
                "full_name": row.binding.owner.full_name,
                "joined_at": row.binding.created_at,
                "state": row.state,
                "first_minor": row.first_minor,
                "reward_minor": row.reward.amount_minor if row.reward else 0,
                "currency": row.reward.currency
                if row.reward
                else (row.first_bill.currency if row.first_bill else ""),
            }
            for row in rows
        ],
        "invited_total": len(invited),
        "invited_paid": selectors.invited_paid_count(db, owner=user),
        **_bonus(db, friends=1),
        "feedback": _offer(selectors.feedback_offer(db, owner=user)),
        "feedback_rows": [
            {
                "kind": row.kind,
                "status": row.status,
                "reason": row.reason,
                "amount_minor": row.amount_minor,
                "currency": row.currency,
                "created_at": row.created_at,
            }
            for row in _cut(feedback, page_f)
        ],
        "feedback_text_min": FEEDBACK_TEXT_MIN,
        "payable": settings.withdrawals_open and selectors.may_withdraw(db, owner=user),
        "withdrawals_open": settings.withdrawals_open,
        "referral_percent": REFERRAL_PERCENT,
        "balance": asdict(balance),
        "available_whole": f"{balance.available_minor // 10 ** decimal_places(balance.currency):,}".replace(
            ",", " "
        ),
        "counts": asdict(selectors.wallet_counts(db, owner=user)),
        "last_spend": {
            "amount_minor": spends[0].amount_minor,
            "currency": spends[0].currency,
            "invoice": spends[0].invoice.number,
            "created_at": spends[0].created_at,
        }
        if spends
        else None,
        "withdrawals": [
            {
                "id": str(row.id),
                "amount_minor": row.amount_minor,
                "currency": row.currency,
                "status": row.status,
                "method": row.method,
                "card_last4": row.card_last4,
                "reject_reason": row.reject_reason,
                "created_at": row.created_at,
                "decided_at": row.decided_at,
            }
            for row in _cut(payouts, page_p)
        ],
        "open_ask": {
            "id": str(ask.id),
            "amount_minor": ask.amount_minor,
            "currency": ask.currency,
        }
        if ask
        else None,
    }


@router.get("/bonus", responses={200: {"model": BonusOut}})
def bonus(
    db: Db,
    user: CurrentUser,
    friends: int = Query(1, description="How many friends to price; 1 to 20."),
) -> dict[str, Any]:
    from fastapi import HTTPException

    if not selectors.may_invite(db, owner_id=user.id):
        raise HTTPException(404)
    return _bonus(db, friends=friends)


@router.post("/code", responses={200: {"model": CodeOut}})
def mint_code(db: Db, user: CurrentUser) -> dict[str, str]:
    code = services.ensure_referral_code(db, owner=user)
    db.commit()
    link = selectors.invite_link(code=code.code)
    return {
        "code": code.code,
        "link": link,
        "share_url": selectors.share_url(link=link),
    }


@router.get("/invite", responses={200: {"model": InviteOut | None}})
def invite(db: Db, user: CurrentUser) -> dict[str, Any] | None:
    offer = selectors.invite_offer(db, owner=user)
    if offer is None:
        return None
    return {
        "link": offer.link,
        "share_url": offer.share_url,
        "percent": offer.percent,
        "top_bonus": asdict(offer.top_bonus) if offer.top_bonus else None,
    }


class WithdrawalIn(BaseModel):
    amount: str = Field(max_length=20)
    currency: str = Field(min_length=3, max_length=3)
    card_number: str = Field(max_length=23)
    card_holder: str = Field(max_length=CARD_HOLDER_MAX)

    @field_validator("amount")
    @classmethod
    def _amount(cls, value: str) -> str:
        raw = "".join(value.split())
        if not (raw.isascii() and raw.isdigit()) or int(raw) <= 0:
            raise ValueError("Summani kiriting.")
        return raw


@router.post("/withdraw", status_code=201, responses={201: {"model": IdOut}})
def withdraw(body: WithdrawalIn, db: Db, user: CurrentUser) -> dict[str, str]:
    currency = body.currency.upper()
    ask = services.request_withdrawal(
        db,
        owner=user,
        amount_minor=int(to_minor(amount=body.amount, currency=currency)),
        currency=currency,
        card_number=body.card_number,
        card_holder=body.card_holder,
        now=utcnow(),
    )
    db.commit()
    return {"id": str(ask.id)}


@router.post("/feedback", status_code=201, responses={201: {"model": FeedbackSentOut}})
def submit_feedback(
    db: Db,
    user: CurrentUser,
    kind: FeedbackKind = Form(...),
    text: str = Form("", max_length=FEEDBACK_TEXT_MAX),
    consent: bool = Form(False),
    file: UploadFile | None = File(None),
) -> dict[str, str]:
    piece = services.submit_feedback(
        db,
        owner=user,
        kind=kind,
        text=text,
        upload=file.file if file else None,
        upload_name=file.filename or "" if file else "",
        upload_size=file.size or 0 if file else 0,
        consent=consent,
        now=utcnow(),
    )
    db.commit()
    return {
        "id": str(piece.id),
        "detail": "Fikringiz yuborildi. Javobni shu yerda va Telegram'da ko'rasiz.",
    }


@router.get("/feedback/prompt", responses={200: {"model": FeedbackOfferOut | None}})
def feedback_prompt(db: Db, user: CurrentUser) -> dict[str, Any] | None:
    return _offer(selectors.feedback_prompt_due(db, owner=user, now=utcnow()))


class PromptIn(BaseModel):
    answer: str = ""


@router.post("/feedback/prompt", responses={200: {"model": PromptAnswerOut}})
def answer_feedback_prompt(body: PromptIn, db: Db, user: CurrentUser) -> dict[str, str]:
    values = {item.value for item in FeedbackPromptAnswer}
    answer = (
        FeedbackPromptAnswer(body.answer)
        if body.answer in values
        else FeedbackPromptAnswer.LATER
    )
    services.answer_feedback_prompt(db, owner=user, answer=answer, now=utcnow())
    db.commit()
    return {"answer": str(answer)}


@landing.get("/r/{code}/", include_in_schema=False)
def referral_landing(code: str) -> RedirectResponse:
    from urllib.parse import urlencode

    return RedirectResponse(
        f"{settings.site_url}/accounts/signup/?{urlencode({'ref': code.strip()[:32]})}"
    )
