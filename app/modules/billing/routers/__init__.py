import logging
from dataclasses import asdict
from datetime import datetime
from typing import Annotated, Any, Literal
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from paykit import REDIRECT, ProviderNotRegistered
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, Db, client_address
from app.common.config import settings
from app.common.db import utcnow
from app.common.exceptions import DomainError
from app.common.geo import country_of
from app.common.money import to_minor
from app.modules.accounts.models import User
from app.modules.billing import selectors, services
from app.modules.billing.constants import (
    EXPIRY_REMINDER_DAYS,
    MAX_PAGES_PER_PURCHASE,
    MAX_POLL_TRIES,
    POLL_SECONDS,
    SETTLED_INVOICE_STATUSES,
    TRIAL_MAX_CAMPAIGNS,
    InvoiceKind,
    InvoiceStatus,
    PagesChoice,
    PlanMove,
    SubscriptionStatus,
    WalletChoice,
)
from app.modules.billing.exceptions import (
    PromoAlreadyUsed,
    PromoNotApplicable,
    PromoNotFound,
    PromoUsedUp,
)
from app.modules.billing.models import Invoice, Plan, PromoRedemption, Subscription
from app.modules.billing.schemas import (
    DetailOut,
    DisplayOut,
    HistoryOut,
    InvoiceStatusOut,
    OkOut,
    PaywallOut,
    PlansOut,
    PromoOut,
    StatusOut,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/billing", tags=["billing"])
webhooks = APIRouter(tags=["webhooks"])
PROMO_MAX_CHARS = 32
RECENT_BILLS = 5
HISTORY_PER_PAGE = 20
PROMO_REFUSALS = (PromoNotFound, PromoNotApplicable, PromoAlreadyUsed, PromoUsedUp)


def shown_prices(request: Request) -> selectors.Display:
    """The currency this visitor is shown prices in, from where they are."""
    return selectors.display_for(
        country=country_of(headers=request.headers, address=client_address(request))
    )


Shown = Annotated[selectors.Display, Depends(shown_prices)]

PLAN_Q = Query("", description="A plan `code`: price it in `chosen`.")
PROMO_Q = Query("", description="A typed promo code to price `plan` with.")


def plan_out(
    plan: Plan | None, display: selectors.Display | None = None
) -> dict[str, Any] | None:
    if plan is None:
        return None
    sheet = selectors.tier_sheet(plan=plan)
    shown = (
        selectors.plan_in_display(plan, per_page=sheet.per_page, display=display)
        if display is not None
        else None
    )
    return {
        "id": str(plan.id),
        "code": plan.code,
        "name": plan.name,
        "tagline": plan.tagline,
        "price": plan.price,
        "currency": plan.currency,
        "period_days": plan.period_days,
        "max_adsets": plan.max_adsets,
        "daily_chat_requests": plan.daily_chat_requests,
        "included_pages": plan.included_pages,
        "included_google_accounts": plan.included_google_accounts,
        "extra_page_price": plan.extra_page_price,
        "is_one_time": plan.is_one_time,
        "features": [asdict(line) for line in sheet.lines],
        "highlights": list(sheet.highlights),
        "per_page": sheet.per_page,
        "shown": shown,
    }


def subscription_out(subscription: Subscription | None) -> dict[str, Any] | None:
    if subscription is None:
        return None
    return {
        "id": str(subscription.id),
        "status": subscription.status,
        "plan": plan_out(subscription.plan),
        "extra_pages": subscription.extra_pages,
        "started_at": subscription.started_at,
        "expires_at": subscription.expires_at,
        "term_started_at": subscription.term_started_at,
        "setup_completed_at": subscription.setup_completed_at,
        "ad_account_id": str(subscription.ad_account_id)
        if subscription.ad_account_id
        else None,
    }


def invoice_out(invoice: Invoice, *, paid_via: str = "") -> dict[str, Any]:
    return {
        "number": invoice.number,
        "kind": invoice.kind,
        "status": invoice.status,
        "plan": plan_out(invoice.plan),
        "amount_minor": invoice.amount_minor,
        "credit_minor": invoice.credit_minor,
        "wallet_minor": invoice.wallet_minor,
        "currency": invoice.currency,
        "period_days": invoice.period_days,
        "pages": invoice.pages,
        "pages_minor": invoice.pages_minor,
        "expires_at": invoice.expires_at,
        "paid_at": invoice.paid_at,
        "created_at": invoice.created_at,
        "paid_via": paid_via,
    }


def offer_out(offer: selectors.Offer) -> dict[str, Any]:
    return {
        "plan": plan_out(offer.plan),
        "move": offer.switch.move,
        "until": offer.switch.until,
        "credit_days": offer.switch.credit_days,
        "price_minor": offer.price_minor,
        "discount_minor": offer.discount_minor,
        "credit_minor": offer.credit_minor,
        "wallet_minor": offer.wallet_minor,
        "pages": offer.pages,
        "pages_minor": offer.pages_minor,
        "page_credit_minor": offer.page_credit_minor,
        "due_minor": offer.due_minor,
        "due_without_wallet_minor": offer.due_without_wallet_minor,
    }


def redemption_out(redemption: PromoRedemption | None) -> dict[str, Any] | None:
    if redemption is None:
        return None
    return {
        "id": str(redemption.id),
        "code": redemption.promo.code,
        "status": redemption.status,
        "granted_days": redemption.granted_days,
        "granted_pages": redemption.granted_pages,
        "plan": plan_out(redemption.promo.plan),
        "redeemed_at": redemption.redeemed_at,
    }


def priced_choice(
    db: Session,
    *,
    user: User,
    plans: list[Plan],
    now: datetime,
    asked: str,
    promo: str,
    pages: PagesChoice,
) -> dict[str, Any]:
    promo = promo.strip()[:PROMO_MAX_CHARS]
    wallets = {
        currency: selectors.wallet_minor(db, owner=user, currency=currency)
        for currency in {plan.currency for plan in plans}
    }
    offers = selectors.checkout_offers(
        db, owner=user, plans=plans, discounts={}, wallets=wallets, now=now
    )
    last = selectors.latest_subscription(db, owner=user)
    cards = []
    for code, offer in offers.items():
        running = offer.switch.current
        tag = ""
        if last is not None and offer.plan.id == last.plan_id:
            tag = "running" if running is not None else "last"
        action = "pick"
        if offer.switch.move == PlanMove.WAIT:
            action = "wait"
        elif (
            tag == "running"
            and running is not None
            and running.status != SubscriptionStatus.TRIAL
        ):
            action = "renew"
        elif offer.switch.move == PlanMove.RESTART:
            action = "switch"
        cards.append(
            {"code": code, "offer": offer_out(offer), "tag": tag, "action": action}
        )
    page: dict[str, Any] = {"cards": cards, "promo_typed": promo}
    offer = offers.get(asked)
    if offer is None or offer.switch.move == PlanMove.WAIT:
        return page
    discount: dict[str, Any] = {}
    if promo:
        discount["promo_typed"] = promo
        try:
            quote = selectors.discount_quote(
                db,
                owner=user,
                code=promo,
                base_minor=int(
                    to_minor(amount=str(offer.plan.price), currency=offer.plan.currency)
                ),
                currency=offer.plan.currency,
                now=now,
            )
            discount["promo_quote"] = {
                "code": quote.promo.code,
                "base_minor": quote.base_minor,
                "discount_minor": quote.discount_minor,
                "total_minor": quote.total_minor,
                "percent": quote.percent,
                "currency": quote.currency,
            }
        except DomainError as exc:
            discount["promo_error"] = exc.message
    quote_minor = discount.get("promo_quote", {}).get("discount_minor")
    chosen = selectors.checkout_offers(
        db,
        owner=user,
        plans=[offer.plan],
        discounts={asked: quote_minor} if quote_minor else {},
        wallets=wallets,
        now=now,
        pages=pages,
    )[asked]
    return (
        page
        | discount
        | {
            "chosen": offer_out(chosen),
            "chosen_ends_at": selectors.offer_ends_at(offer=chosen, now=now),
            "pages_dropped": pages == PagesChoice.DROP,
            "carried_pages": offer.pages,
            "wallet_balance_minor": wallets.get(chosen.plan.currency, 0),
        }
    )


@router.get("/display", responses={200: {"model": DisplayOut}})
def price_display(shown: Shown) -> dict[str, Any]:
    """The currency to show prices in. Needs no sign-in: the landing page asks too."""
    return selectors.display_as_dict(shown)


@router.get("/status", responses={200: {"model": StatusOut}})
def subscription_status(
    db: Db,
    user: CurrentUser,
    seen_days: int | None = Query(
        None,
        description="The `days_left` the reminder was last shown at; it is not "
        "shown again for the same day.",
    ),
) -> dict[str, Any]:
    live = selectors.live_subscription(db, owner=user)
    left = selectors.days_left(subscription=live, now=utcnow())
    never = live is None and not selectors.has_ever_subscribed(db, owner=user)
    lapse_until = ""
    if live is None and not never:
        from app.modules.ads.selectors import open_hold
        from app.modules.notifications.selectors import deadline_text

        hold = open_hold(db, owner=user)
        if hold is not None:
            lapse_until = deadline_text(db, owner=user, moment=hold.delete_after)
    return {
        "is_read_only": live is None,
        "subscription": subscription_out(live),
        "never_subscribed": never,
        "may_prepare": live is not None,
        "days_left": left,
        "ending_soon": left is not None
        and left <= max(EXPIRY_REMINDER_DAYS)
        and seen_days != left,
        "lapse_until": lapse_until,
    }


@router.get("", responses={200: {"model": PlansOut}})
def plans(
    db: Db,
    user: CurrentUser,
    shown: Shown,
    plan: str = PLAN_Q,
    promo: str = PROMO_Q,
    pages: PagesChoice = Query(
        PagesChoice.KEEP,
        description="`keep` extra pages on a plan switch, or `drop` them.",
    ),
) -> dict[str, Any]:
    from app.modules.ads.selectors import adsets_here, trial_campaigns_left
    from app.modules.integrations.selectors import page_slots
    from app.modules.referrals.constants import REFERRAL_PERCENT

    now = utcnow()
    offered = selectors.sellable_plans(db, owner=user)
    subscription = selectors.live_subscription(db, owner=user)
    is_trial = (
        subscription is not None and subscription.status == SubscriptionStatus.TRIAL
    )
    trial = None
    if is_trial:
        left = trial_campaigns_left(db, owner=user)
        if left is not None:
            trial = {"allowed": TRIAL_MAX_CAMPAIGNS, "used": TRIAL_MAX_CAMPAIGNS - left}
    offer = selectors.page_offer(db, owner=user, now=now)
    wallet = (
        selectors.wallet_minor(db, owner=user, currency=offer.plan.currency)
        if offer.plan
        else 0
    )
    term = selectors.term(subscription=subscription, now=now)
    slots = page_slots(db, owner=user)
    announcement = selectors.promo_announcement(db, owner=user, now=now)
    featured = selectors.featured_plan(offered)
    return priced_choice(
        db, user=user, plans=offered, now=now, asked=plan, promo=promo, pages=pages
    ) | {
        "subscription": subscription_out(subscription),
        "term": asdict(term) | {"percent_left": term.percent_left} if term else None,
        "is_trial": is_trial,
        "page_slots": {
            "allowed": slots.allowed,
            "used": slots.used,
            "free": slots.free,
        },
        "page_mix": asdict(
            selectors.page_mix(db, owner=user, subscription=subscription, now=now)
        ),
        "trial_campaigns": trial,
        "adsets_running": 0 if trial is not None else adsets_here(db, owner=user),
        "chat": asdict(selectors.chat_allowance(db, owner=user, now=now)),
        "page_offer": selectors.offer_as_dict(offer),
        "page_quotes": [
            selectors.quote_as_dict(q)
            for q in selectors.page_quotes(offer=offer, wallet_minor=wallet)
        ],
        "wallet_minor": wallet,
        "pending_promo": redemption_out(selectors.pending_redemption(db, owner=user)),
        "promo_announcement": {
            "redemption": redemption_out(announcement.redemption),
            "free_slots": announcement.free_slots,
            "choices": [asdict(c) for c in announcement.choices],
            "can_choose": announcement.can_choose,
        }
        if announcement
        else None,
        "recent_bills": [
            invoice_out(invoice, paid_via=via)
            for invoice, via in selectors.recent_invoices(
                db, owner=user, limit=RECENT_BILLS
            )
        ],
        "plans": [plan_out(p, shown) for p in offered],
        "featured": featured.code if featured else "",
        "providers": selectors.payment_providers(),
        "payments_on": selectors.payments_configured(),
        "referral_percent": REFERRAL_PERCENT,
        "max_pages_per_purchase": MAX_PAGES_PER_PURCHASE,
        "display": selectors.display_as_dict(shown),
    }


@router.get("/paywall", responses={200: {"model": PaywallOut}})
def paywall(
    db: Db, user: CurrentUser, shown: Shown, plan: str = PLAN_Q, promo: str = PROMO_Q
) -> dict[str, Any]:
    if selectors.has_ever_subscribed(db, owner=user):
        return {"already_open": True}
    now = utcnow()
    offered = selectors.sellable_plans(db, owner=user)
    featured = selectors.featured_plan(offered)
    codes = [p.code for p in offered]
    asked = (
        plan
        if plan in codes
        else (featured.code if featured else (codes[0] if codes else ""))
    )
    typed = promo.strip()[:PROMO_MAX_CHARS]
    usable, refusal = "", {}
    if typed:
        if selectors.discount_code(db, code=typed, now=now) is not None:
            usable = typed
        elif selectors.live_promo(db, code=typed, now=now) is not None:
            refusal = {"promo_elsewhere": True}
        else:
            refusal = {"promo_unknown": PromoNotFound().message}
    return (
        priced_choice(
            db,
            user=user,
            plans=offered,
            now=now,
            asked=asked,
            promo=usable,
            pages=PagesChoice.KEEP,
        )
        | refusal
        | {
            "plans": [plan_out(p, shown) for p in offered],
            "featured": featured.code if featured else "",
            "asked": asked,
            "promo_typed": typed,
            "providers": selectors.payment_providers(),
            "payments_on": selectors.payments_configured(),
            "display": selectors.display_as_dict(shown),
        }
    )


class CheckoutIn(BaseModel):
    plan: str = Field(min_length=1, max_length=32)
    provider: str = ""
    promo: str = Field(default="", max_length=32)
    wallet: WalletChoice = WalletChoice.KEEP
    pages: PagesChoice = PagesChoice.KEEP


class PagesCheckoutIn(BaseModel):
    count: int = Field(ge=1, le=MAX_PAGES_PER_PURCHASE)
    provider: str = ""
    wallet: WalletChoice = WalletChoice.KEEP
    add_page: str = Field(default="", max_length=128)
    pay_from: str = Field(default="", max_length=128)


class CheckoutOut(BaseModel):
    number: str
    kind: Literal["redirect", "wait", "covered"]
    url: str = ""
    wait_url: str


def _wait_url(number: str, **query: str) -> str:
    query = {k: v for k, v in query.items() if v}
    path = f"/app/billing/invoice/{number}"
    return f"{path}?{urlencode(query)}" if query else path


def _start(
    db: Session,
    *,
    user: User,
    invoice: Invoice,
    provider: str,
    now: datetime,
    **back: str,
) -> CheckoutOut:
    wait = _wait_url(invoice.number, **back)
    if invoice.amount_minor == 0:
        services.settle_covered_invoice(db, invoice=invoice, now=now)
        db.commit()
        return CheckoutOut(number=invoice.number, kind="covered", wait_url=wait)
    if not provider:
        db.commit()
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail="To'lov usulini tanlang."
        )
    checkout = services.checkout_for(
        invoice=invoice,
        provider=provider,
        return_url=settings.site_url + wait,
        language=user.language,
        now=now,
    )
    db.commit()
    logger.info(
        "checkout started", extra={"provider": provider, "invoice": invoice.number}
    )
    if checkout.kind == REDIRECT:
        return CheckoutOut(
            number=invoice.number, kind="redirect", url=checkout.url, wait_url=wait
        )
    return CheckoutOut(
        number=invoice.number,
        kind="wait",
        wait_url=_wait_url(invoice.number, via=provider, **back),
    )


@router.post("/checkout", response_model=CheckoutOut)
def checkout(body: CheckoutIn, db: Db, user: CurrentUser) -> CheckoutOut:
    plan = selectors.sellable_plan(db, code=body.plan)
    if plan is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail="Bu tarif hozir sotuvda emas."
        )
    now = utcnow()
    try:
        invoice = services.create_invoice(db, owner=user, plan=plan, now=now)
        invoice = services.price_invoice(
            db,
            invoice=invoice,
            promo_code=body.promo.strip(),
            wallet=body.wallet,
            now=now,
            pages=body.pages,
        )
    except PROMO_REFUSALS as exc:
        db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=exc.message) from exc
    return _start(db, user=user, invoice=invoice, provider=body.provider, now=now)


@router.post("/pages", response_model=CheckoutOut)
def buy_pages(body: PagesCheckoutIn, db: Db, user: CurrentUser) -> CheckoutOut:
    now = utcnow()
    invoice = services.create_page_invoice(
        db, owner=user, count=body.count, wallet=body.wallet, now=now
    )
    return _start(
        db,
        user=user,
        invoice=invoice,
        provider=body.provider,
        now=now,
        add_page=body.add_page,
        pay_from=body.pay_from if body.add_page else "",
    )


@router.get("/history", responses={200: {"model": HistoryOut}})
def history(
    db: Db,
    user: CurrentUser,
    page: int = Query(1, ge=1, description="Page of `lines`, 20 a page."),
    bills: int = Query(1, ge=1, description="Page of `invoices`, 20 a page."),
) -> dict[str, Any]:
    lines = selectors.subscription_history(db, owner=user)
    invoices = selectors.invoice_history(db, owner=user)

    def cut(rows: list[Any], number: int) -> list[Any]:
        return rows[(number - 1) * HISTORY_PER_PAGE : number * HISTORY_PER_PAGE]

    return {
        "lines": [
            {
                "kind": row["change"].kind,
                "move": row["change"].move,
                "days": row["change"].days,
                "from_plan": plan_out(row["change"].from_plan),
                "to_plan": plan_out(row["change"].to_plan),
                "expires_before": row["change"].expires_before,
                "expires_after": row["change"].expires_after,
                "reason": row["change"].reason,
                "occurred_at": row["change"].occurred_at,
                "invoice": row["change"].invoice.number
                if row["change"].invoice
                else "",
                "paid_minor": row["paid_minor"],
                "credit_minor": row["credit_minor"],
                "wallet_minor": row["wallet_minor"],
                "discount_minor": row["discount_minor"],
                "price_minor": row["price_minor"],
            }
            for row in cut(lines, page)
        ],
        "lines_total": len(lines),
        "invoices": [invoice_out(invoice) for invoice in cut(invoices, bills)],
        "invoices_total": len(invoices),
        "per_page": HISTORY_PER_PAGE,
    }


class PromoIn(BaseModel):
    code: str = Field(min_length=1, max_length=32)


@router.post("/promo", responses={200: {"model": PromoOut}})
def promo(body: PromoIn, db: Db, user: CurrentUser) -> dict[str, Any]:
    now = utcnow()
    discount = selectors.discount_code(db, code=body.code, now=now)
    if discount is not None:
        return {
            "kind": "discount",
            "code": discount.code,
            "detail": (
                "«%(code)s» kodi qabul qilindi. Endi tarifni tanlang — "
                "chegirma to'lov oynasida narxdan ayriladi."
            )
            % {"code": discount.code},
        }
    result = services.redeem_promo(db, user=user, code=body.code, now=now)
    db.commit()
    return {
        "kind": "grant",
        "detail": services.redeemed_summary(result),
        "days": result.days,
        "pages": result.pages,
        "plan_changed": result.plan_changed,
        "pending": result.pending,
    }


class RedemptionIn(BaseModel):
    redemption: str
    external_ids: list[str] = []


@router.post("/promo/seen", responses={200: {"model": OkOut}})
def promo_seen(body: RedemptionIn, db: Db, user: CurrentUser) -> dict[str, bool]:
    done = services.acknowledge_promo(
        db, owner=user, redemption_id=body.redemption, now=utcnow()
    )
    db.commit()
    return {"ok": done is not None}


@router.post("/promo/page", responses={200: {"model": DetailOut}})
def promo_page(body: RedemptionIn, db: Db, user: CurrentUser) -> dict[str, str]:
    from app.modules.integrations.services import take_promo_pages

    pages = take_promo_pages(
        db,
        user=user,
        external_ids=body.external_ids,
        redemption_id=body.redemption,
        now=utcnow(),
    )
    db.commit()
    names = ", ".join(str(page) for page in pages)
    if len(pages) > 1:
        text = (
            "Sahifalar biriktirildi: %(names)s. "
            "Ularni almashtirish uchun biz bilan bog'laning."
        ) % {"names": names}
    else:
        text = "%(name)s biriktirildi. Uni almashtirish uchun biz bilan bog'laning." % {
            "name": names
        }
    return {"detail": text}


@router.get("/invoice/{number}", responses={200: {"model": InvoiceStatusOut}})
def invoice_status(
    number: str,
    db: Db,
    user: CurrentUser,
    tries: int = Query(0, ge=0, description="The last answer's `tries`."),
    via: str = Query("", description="The provider paid with; echoed back."),
    add_page: str = Query(
        "", description="The page being added after a pages bill; sets `back_url`."
    ),
    pay_from: str = Query("", description="Where the pages purchase was started."),
) -> dict[str, Any]:
    invoice = selectors.invoice_for(db, owner=user, number=number)
    if invoice is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    settled = invoice.status in SETTLED_INVOICE_STATUSES
    exhausted = tries >= MAX_POLL_TRIES
    paid = invoice.status == InvoiceStatus.PAID
    back_url = ""
    if invoice.kind != InvoiceKind.PAGES:
        if selectors.setup_pending(db, owner=user):
            back_url = "/app/start"
    elif add_page:
        query = {"add_pages": "1", "add_page": add_page[:128]} | (
            {"pay_from": pay_from[:128]} if pay_from else {}
        )
        back_url = f"/app/connections?{urlencode(query)}"
    return {
        "invoice": invoice_out(invoice),
        "via": via,
        "polling": not settled and not exhausted,
        "settled": settled,
        "gave_up": exhausted and not settled,
        "paid": paid,
        "just_landed": paid and tries > 0,
        "tries": tries + 1,
        "poll_seconds": POLL_SECONDS,
        "back_url": back_url,
    }


@webhooks.post("/webhooks/pay/{provider}", include_in_schema=False)
async def payment_callback(provider: str, request: Request) -> JSONResponse:
    from app.common.db import SessionLocal

    body = await request.body()
    try:
        form = {k: str(v) for k, v in (await request.form()).items()}
    except Exception:
        form = {}
    db = SessionLocal()
    try:
        answer = services.handle_callback(
            db,
            provider=provider,
            headers=dict(request.headers),
            body=body,
            form=form,
            now=utcnow(),
        )
    except ProviderNotRegistered:
        logger.warning(
            "payment callback for an unregistered provider",
            extra={"provider": provider},
        )
        raise HTTPException(status.HTTP_404_NOT_FOUND) from None
    finally:
        db.close()
    return JSONResponse(dict(answer.body), status_code=answer.status_code)
