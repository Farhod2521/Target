import logging
import uuid
from dataclasses import asdict
from datetime import timedelta
from typing import Any, Final
from urllib.parse import parse_qsl, urlencode

from adskit.errors import ProviderError
from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from metaads.accounts import billing_url
from metaads.audiences import terms_url as audience_terms_url
from metaads.leadforms import terms_url
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, Db
from app.common.cache import cache
from app.common.config import settings
from app.common.db import utcnow
from app.common.exceptions import DomainError
from app.modules.accounts.models import User
from app.modules.integrations import selectors, services
from app.modules.integrations.constants import (
    ACTION_NOTES,
    BREADTH_LABELS,
    BREADTH_NOTES,
    MIN_AUDIENCE_MEMBERS,
    USABLE_CONNECTION_STATUSES,
    USEFUL_AUDIENCE_MEMBERS,
)
from app.modules.integrations.exceptions import (
    ConnectionFailed,
    GoogleConnectionFailed,
    StateMismatch,
)
from app.modules.integrations.models import AdAccount, CustomAudience
from app.modules.integrations.schemas import (
    ActionRequiredOut,
    AdAccountOut,
    AudienceIn,
    AudienceOut,
    AudiencesOut,
    CabinetOut,
    ConnectionOut,
    ConnectionsOut,
    ExternalIdIn,
    GoogleCardOut,
    InstagramChoiceOut,
    InstagramIn,
    InstagramProfileOut,
    LookalikeAudienceIn,
    MessageOut,
    OAuthStartIn,
    OAuthStartOut,
    OptionOut,
    PageOut,
    PagePayerOut,
    PageRowOut,
    PagesIn,
    PairIn,
    PairOut,
    PayerOptionOut,
    PixelOut,
    ProfileCardOut,
    RuleAudienceIn,
    RuleOptionOut,
    SlotsOut,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/connections", tags=["connections"])
STATE_TTL: Final = 15 * 60
LOADING_WINDOW: Final = timedelta(minutes=2)
PROFILE_TRIES: Final = 10
MAX_POLLS: Final = 20


def _slots(slots: selectors.Slots) -> SlotsOut:
    return SlotsOut(
        allowed=slots.allowed, used=slots.used, free=slots.free, has_room=slots.has_room
    )


def _payer(payer: selectors.PagePayer) -> PagePayerOut:
    return PagePayerOut(
        page=PageOut.model_validate(payer.page) if payer.page else None,
        payer=AdAccountOut.model_validate(payer.payer) if payer.payer else None,
        options=[
            PayerOptionOut(
                account=AdAccountOut.model_validate(option.account),
                recommended=option.recommended,
                unusable=option.unusable,
            )
            for option in payer.options
        ],
        paired=[AdAccountOut.model_validate(account) for account in payer.paired],
    )


def _pair(pair: selectors.Pair) -> PairOut:
    return PairOut(
        key=pair.key,
        page=PageOut.model_validate(pair.page),
        account=AdAccountOut.model_validate(pair.account),
        stored=pair.stored,
        first=pair.first,
    )


def _ok(db: Session, detail: str) -> MessageOut:
    db.commit()
    return MessageOut(detail=detail)


def _billing():  # type: ignore[no-untyped-def]
    from app.modules.billing import selectors as billing

    return billing


def _bill_url(account: AdAccount | None) -> str:
    if account is None or not account.payment_due:
        return ""
    return billing_url(account.external_id)


def page_rows(db: Session, *, owner: User) -> list[PageRowOut]:
    from app.modules.businesses.selectors import profiles_by_page

    profiles = profiles_by_page(db, owner=owner)
    enabled = selectors.enabled_pages(db, owner=owner)
    payers = selectors.page_payers(db, owner=owner, pages=enabled)
    locked = _billing().setup_locked(db, owner=owner)
    rows = []
    for page, payer in zip(enabled, payers, strict=True):
        instagrams = selectors.instagram_choices(db, page=page)
        accounts: tuple[AdAccount | None, ...] = (
            payer.paired if locked and payer.paired else (None,)
        )
        for account in accounts:
            profile = profiles.get(page.id)
            rows.append(
                PageRowOut(
                    page=PageOut.model_validate(page),
                    profile_id=profile.id if profile else None,
                    payer=_payer(payer),
                    terms_url=terms_url(page.external_id),
                    bill_url=_bill_url(account or payer.payer),
                    instagrams=[
                        InstagramChoiceOut.model_validate(c) for c in instagrams
                    ],
                    account=AdAccountOut.model_validate(account) if account else None,
                )
            )
    return rows


def profile_card(
    db: Session, *, owner: User, since: int = 0, tries: int = 0
) -> ProfileCardOut:
    profile = selectors.instagram_profile(db, owner=owner)
    stale = (
        profile is not None
        and since > 0
        and (
            profile.synced_at is None
            or int(profile.synced_at.timestamp() * 1000) < since
        )
    )
    return ProfileCardOut(
        instagram_profile=(
            InstagramProfileOut.model_validate(
                asdict(profile) | {"is_read": profile.is_read}
            )
            if profile
            else None
        ),
        profile_waiting=stale and tries < PROFILE_TRIES,
        profile_late=stale and tries >= PROFILE_TRIES,
        profile_since=since,
        profile_tries=tries,
    )


def google_card(db: Session, *, owner: User) -> GoogleCardOut:
    from app.modules.businesses.selectors import google_profile

    if not selectors.google_ads_on(user=owner):
        return GoogleCardOut(google_ads_on=False)
    connection = selectors.google_connection(db, owner=owner)
    accounts = selectors.google_accounts(db, owner=owner)
    connected = (
        connection is not None and connection.status in USABLE_CONNECTION_STATUSES
    )
    loading = (
        connected
        and not accounts
        and connection is not None
        and utcnow() - connection.updated_at < LOADING_WINDOW
    )
    subscribed = []
    for account in accounts:
        if not account.is_active:
            continue
        profile = google_profile(db, owner=owner, account=account)
        subscribed.append(
            {
                "account": AdAccountOut.model_validate(account).model_dump(),
                "profile_id": str(profile.id) if profile else None,
            }
        )
    return GoogleCardOut(
        google_ads_on=True,
        connection=ConnectionOut.model_validate(connection) if connection else None,
        connected=connected,
        accounts=[AdAccountOut.model_validate(a) for a in accounts],
        subscribed=subscribed,
        others=[AdAccountOut.model_validate(a) for a in accounts if not a.is_active],
        slots=_slots(selectors.google_slots(db, owner=owner)),
        loading=loading,
        taken=list(connection.ad_accounts_taken or []) if connection else [],
        has_subscription=_billing().has_live_subscription(db, owner=owner),
    )


def add_page_context(
    db: Session, *, owner: User, add_page: str = "", pay_from: str = ""
) -> dict[str, Any]:
    billing = _billing()
    now = utcnow()
    choices = selectors.pages_on_offer(db, owner=owner)
    payer = selectors.new_page_payer(db, owner=owner)
    usable = {
        option.account.external_id for option in payer.options if not option.unusable
    }
    offer = billing.page_offer(db, owner=owner, now=now)
    wallet = (
        billing.wallet_minor(db, owner=owner, currency=offer.plan.currency)
        if offer.plan
        else 0
    )
    quotes = billing.page_quotes(offer=offer, wallet_minor=wallet)
    pairable: list[PagePayerOut] = []
    if billing.setup_locked(db, owner=owner):
        pages = selectors.enabled_pages(db, owner=owner)
        pairable = [
            _payer(p)
            for p in selectors.page_payers(db, owner=owner, pages=pages)
            if p.paired and p.addable
        ]
    return {
        "pairs": [p.model_dump() for p in pairable],
        "choices": [asdict(choice) for choice in choices],
        "payer": _payer(payer).model_dump(),
        "picked_page": next(
            (c.external_id for c in choices if c.external_id == add_page),
            choices[0].external_id if choices else "",
        ),
        "picked_account": pay_from
        if pay_from in usable
        else (payer.payer.external_id if payer.payer else ""),
        "paid": bool(add_page),
        "page_offer": billing.offer_as_dict(offer),
        "page_quote": billing.quote_as_dict(quotes[0]) if quotes else None,
        "wallet_minor": wallet,
        "providers": billing.payment_providers(),
    }


@router.get("", response_model=ConnectionsOut)
def connections(
    db: Db, user: CurrentUser, add_page: str = "", pay_from: str = ""
) -> ConnectionsOut:
    enabled = selectors.enabled_pages(db, owner=user)
    pixel = selectors.active_pixel(db, owner=user)
    account = selectors.active_ad_account(db, owner=user)
    page = selectors.active_page(db, owner=user)
    connection = selectors.meta_connection(db, owner=user)
    return ConnectionsOut(
        connection=ConnectionOut.model_validate(connection) if connection else None,
        is_connected=selectors.is_connected(db, owner=user),
        may_connect=_billing().may_prepare(db, owner=user),
        enabled_rows=page_rows(db, owner=user),
        page_slots=_slots(selectors.page_slots(db, owner=user)),
        setup_locked=_billing().setup_locked(db, owner=user),
        ad_accounts=[
            AdAccountOut.model_validate(a)
            for a in selectors.ad_accounts(db, owner=user)
        ],
        ad_accounts_taken=list(selectors.ad_accounts_held_elsewhere(db, owner=user)),
        spare_pages=[
            PageOut.model_validate(p) for p in selectors.spare_pages(db, owner=user)
        ],
        active_page=PageOut.model_validate(page) if page else None,
        active_ad_account=AdAccountOut.model_validate(account) if account else None,
        any_without_instagram=any(not p.has_instagram for p in enabled),
        ig_needs_permission=selectors.instagram_permission_missing(db, owner=user),
        pixels=[PixelOut.model_validate(p) for p in selectors.pixels(db, owner=user)],
        active_pixel=PixelOut.model_validate(pixel) if pixel else None,
        instagram=profile_card(db, owner=user),
        google=google_card(db, owner=user),
        add_page=add_page_context(db, owner=user, add_page=add_page, pay_from=pay_from),
    )


@router.get("/cabinet", response_model=CabinetOut)
def cabinet(db: Db, user: CurrentUser) -> CabinetOut:
    billing = _billing()
    shown = selectors.enabled_pages(db, owner=user)
    paired = selectors.page_pairs(db, owner=user, pages=shown) if shown else []
    pair = selectors.current_pair(db, owner=user, pairs=paired) if paired else None
    locked = billing.setup_locked(db, owner=user)
    live = billing.live_subscription(db, owner=user)
    room = 0
    if live is not None and live.setup_completed_at is not None:
        room = max(
            0,
            billing.subscription_pages(db, owner=user, subscription=live) - len(shown),
        )
    waiting = next((p for p in paired if not p.stored), None)
    prompt = (
        selectors.confirm_payer(
            db, owner=user, page=waiting.page, shown=waiting.account
        )
        if waiting is not None and locked
        else None
    )
    connection = selectors.meta_connection(db, owner=user)
    broken = selectors.broken_of(connection=connection)
    action = selectors.action_required_of(db, connection=connection, owner=user)
    return CabinetOut(
        pages=[PageOut.model_validate(p) for p in shown],
        pairs=[_pair(p) for p in paired],
        pair=_pair(pair) if pair else None,
        switchable=locked,
        room=room,
        google_ads_nav=selectors.google_ads_on(user=user),
        pair_prompt=_payer(prompt) if prompt else None,
        meta_connection_broken=ConnectionOut.model_validate(broken) if broken else None,
        meta_action_required=ActionRequiredOut(**asdict(action)) if action else None,
    )


@router.get("/pages", response_model=list[PageRowOut])
def page_cards(db: Db, user: CurrentUser) -> list[PageRowOut]:
    return page_rows(db, owner=user)


def _remember_state(provider: str, *, state: str, user: User, next_url: str) -> None:
    cache.set(
        f"oauth:{provider}:{state}",
        {"user": str(user.id), "next": next_url},
        timeout=STATE_TTL,
    )


def _recall_state(db: Session, provider: str, *, state: str) -> tuple[User, str]:
    found = cache.get(f"oauth:{provider}:{state}") if state else None
    if not found:
        raise StateMismatch
    cache.delete(f"oauth:{provider}:{state}")
    user = db.get(User, uuid.UUID(found["user"]))
    if user is None or not user.is_active:
        raise StateMismatch
    return user, str(found.get("next") or "")


def _back(next_url: str, **params: str) -> RedirectResponse:
    path = (
        next_url
        if next_url.startswith("/") and not next_url.startswith("//")
        else "/app/connections"
    )
    # The frontend's next may carry a query of its own (?connected=meta).
    base, _, query = path.partition("?")
    merged = dict(parse_qsl(query)) | params
    if "error" in params:
        merged.pop("connected", None)
    return RedirectResponse(f"{settings.site_url}{base}?{urlencode(merged)}")


def _api_base() -> str:
    return settings.site_url


@router.post("/meta/start", response_model=OAuthStartOut)
def meta_start(body: OAuthStartIn, db: Db, user: CurrentUser) -> OAuthStartOut:
    url, state = services.build_authorize_url(
        db, user=user, redirect_uri=services.callback_uri(_api_base())
    )
    _remember_state("meta", state=state, user=user, next_url=body.next)
    return OAuthStartOut(url=url)


@router.get("/meta/callback", include_in_schema=False)
def meta_callback(
    db: Db,
    state: str = "",
    code: str = "",
    error_reason: str = "",
    error: str = "",
) -> RedirectResponse:
    next_url = ""
    try:
        user, next_url = _recall_state(db, "meta", state=state)
        if not code:
            logger.info(
                "meta authorisation not granted: %s", error_reason or error or "unknown"
            )
            raise ConnectionFailed
        services.complete_connection(
            db, user=user, code=code, redirect_uri=services.callback_uri(_api_base())
        )
    except DomainError as exc:
        return _back(next_url, error=exc.message)
    return _back(next_url, connected="meta")


@router.post("/meta/ad-account", response_model=MessageOut)
def select_ad_account(body: ExternalIdIn, db: Db, user: CurrentUser) -> MessageOut:
    account = services.select_ad_account(db, user=user, external_id=body.external_id)
    return _ok(db, "Reklama akkaunti tanlandi: %(name)s" % {"name": account})


@router.post("/meta/page", response_model=MessageOut)
def select_page(body: ExternalIdIn, db: Db, user: CurrentUser) -> MessageOut:
    page = services.select_page(db, user=user, external_id=body.external_id)
    return _ok(db, "Sahifa tanlandi: %(name)s" % {"name": page})


@router.post("/meta/pixel", response_model=MessageOut)
def select_pixel(body: ExternalIdIn, db: Db, user: CurrentUser) -> MessageOut:
    pixel = services.select_pixel(db, user=user, external_id=body.external_id)
    return _ok(db, "Pixel tanlandi: %(name)s" % {"name": pixel})


@router.post("/meta/refresh", response_model=MessageOut)
def refresh_accounts(db: Db, user: CurrentUser) -> MessageOut:
    services.refresh_accounts(db, user=user)
    return _ok(db, "Tekshirilmoqda. Ro'yxat bir zumda yangilanadi.")


@router.post("/meta/leads/recheck", response_model=MessageOut)
def recheck_leads(db: Db, user: CurrentUser) -> MessageOut:
    services.recheck_leads(db, user=user)
    return _ok(db, "Lidlar ulanishi tekshirilmoqda.")


@router.post("/meta/pages/{page_id}/leads", response_model=MessageOut)
def connect_page_leads(page_id: uuid.UUID, db: Db, user: CurrentUser) -> MessageOut:
    page = services.connect_page_leads(db, user=user, page_id=str(page_id))
    return _ok(
        db,
        "«%(page)s» sahifasi ulanmoqda. U yig'gan murojaatlar bir necha "
        "daqiqada «Mijozlar» bo'limiga tushadi." % {"page": page.name},
    )


@router.post("/meta/confirmed", response_model=MessageOut)
def action_taken(db: Db, user: CurrentUser) -> MessageOut:
    if services.confirm_action_taken(db, user=user):
        return _ok(db, "Rahmat! Endi reklamani qayta yaratib ko'rishingiz mumkin.")
    return MessageOut(detail="")


@router.post("/meta/disconnect", response_model=MessageOut)
def disconnect(db: Db, user: CurrentUser) -> MessageOut:
    services.disconnect_meta(db, user=user)
    return _ok(db, "Meta akkaunti uzildi.")


@router.post("/meta/add/page", response_model=MessageOut)
def enable_pages(body: PagesIn, db: Db, user: CurrentUser) -> MessageOut:
    if len(body.external_ids) == 1 and body.ad_account:
        pages = [
            services.add_page(
                db,
                user=user,
                page_external_id=body.external_ids[0],
                account_external_id=body.ad_account,
            )
        ]
    else:
        pages = services.enable_pages(db, user=user, external_ids=body.external_ids)
    if len(pages) > 1:
        text = (
            "Sahifalar qo'shildi: %(names)s. Yuqoridagi tanlagichdan ularga "
            "o'tish mumkin. Sahifani almashtirish uchun biz bilan bog'lanasiz."
        ) % {"names": ", ".join(str(page) for page in pages)}
    elif pages[0].is_current:
        text = (
            "%(name)s qo'shildi va tanlandi. "
            "Sahifani almashtirish uchun biz bilan bog'lanasiz."
        ) % {"name": pages[0]}
    else:
        text = (
            "%(name)s qo'shildi. Yuqoridagi tanlagichdan unga o'tish "
            "mumkin. Sahifani almashtirish uchun biz bilan bog'lanasiz."
        ) % {"name": pages[0]}
    return _ok(db, text)


@router.post("/meta/instagram", response_model=MessageOut)
def choose_instagram(body: InstagramIn, db: Db, user: CurrentUser) -> MessageOut:
    if body.action == "remove":
        services.disable_instagram(
            db, user=user, page_external_id=body.page, instagram_user_id=body.instagram
        )
        return _ok(db, "Instagram akkaunti olib tashlandi.")
    row = services.enable_instagram(
        db, user=user, page_external_id=body.page, instagram_user_id=body.instagram
    )
    return _ok(db, "%(name)s qo'shildi va bitta o'rin egalladi." % {"name": row})


@router.post("/meta/switch/ad-account", response_model=MessageOut)
def switch_ad_account(body: ExternalIdIn, db: Db, user: CurrentUser) -> MessageOut:
    account = services.switch_ad_account(db, user=user, external_id=body.external_id)
    return _ok(db, "Reklama akkaunti: %(name)s" % {"name": account})


@router.post("/meta/switch/page", response_model=MessageOut)
def switch_page(body: ExternalIdIn, db: Db, user: CurrentUser) -> MessageOut:
    page = services.switch_page(db, user=user, external_id=body.external_id)
    return _ok(db, "Sahifa: %(name)s" % {"name": page})


@router.post("/meta/switch/pair", response_model=MessageOut)
def switch_pair(body: PairIn, db: Db, user: CurrentUser) -> MessageOut:
    services.switch_pair(
        db, user=user, page_external_id=body.page, account_external_id=body.external_id
    )
    return _ok(db, "")


@router.post("/meta/page/account", response_model=MessageOut)
def choose_page_account(body: PairIn, db: Db, user: CurrentUser) -> MessageOut:
    page = services.choose_page_account(
        db, user=user, page_external_id=body.page, account_external_id=body.external_id
    )
    return _ok(
        db,
        "«%(page)s» reklamasi endi «%(account)s» akkauntidan to'lanadi"
        % {"page": page, "account": page.ad_account},
    )


@router.post("/meta/page/pair", response_model=MessageOut)
def add_page_pair(body: PairIn, db: Db, user: CurrentUser) -> MessageOut:
    pair = services.add_page_pair(
        db, user=user, page_external_id=body.page, account_external_id=body.external_id
    )
    return _ok(
        db,
        "«%(page)s» sahifasiga «%(account)s» akkaunti qo'shildi"
        % {"page": pair.page, "account": pair.ad_account},
    )


@router.get("/meta/instagram/profile", response_model=ProfileCardOut)
def instagram_profile(
    db: Db, user: CurrentUser, since: int = 0, tries: int = 0
) -> ProfileCardOut:
    return profile_card(db, owner=user, since=since, tries=tries)


@router.post("/meta/instagram/profile/refresh", response_model=ProfileCardOut)
def instagram_profile_refresh(db: Db, user: CurrentUser) -> ProfileCardOut:
    asked = int(utcnow().timestamp() * 1000)
    error = ""
    try:
        services.refresh_instagram_profile(db, user=user)
        db.commit()
    except DomainError as exc:
        error = exc.message
    card = profile_card(db, owner=user, since=0 if error else asked)
    card.profile_error = error
    return card


@router.get("/google", response_model=GoogleCardOut)
def google(db: Db, user: CurrentUser) -> GoogleCardOut:
    card = google_card(db, owner=user)
    if not card.google_ads_on:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return card


@router.post("/google/start", response_model=OAuthStartOut)
def google_start(body: OAuthStartIn, db: Db, user: CurrentUser) -> OAuthStartOut:
    url, state = services.build_google_authorize_url(
        db, user=user, redirect_uri=services.google_callback_uri(_api_base())
    )
    _remember_state("google", state=state, user=user, next_url=body.next)
    return OAuthStartOut(url=url)


@router.get("/google/callback", include_in_schema=False)
def google_callback(
    db: Db, state: str = "", code: str = "", error: str = ""
) -> RedirectResponse:
    next_url = ""
    try:
        user, next_url = _recall_state(db, "google", state=state)
        if not code:
            logger.info("google authorisation not granted: %s", error or "unknown")
            raise GoogleConnectionFailed
        services.complete_google_connection(
            db,
            user=user,
            code=code,
            redirect_uri=services.google_callback_uri(_api_base()),
        )
    except DomainError as exc:
        return _back(next_url, error=exc.message)
    return _back(next_url, connected="google")


@router.post("/google/account", response_model=MessageOut)
def select_google_account(body: ExternalIdIn, db: Db, user: CurrentUser) -> MessageOut:
    account = services.select_google_account(
        db, user=user, external_id=body.external_id
    )
    return _ok(db, "Google Ads akkaunti tanlandi: %(name)s" % {"name": account})


@router.post("/google/add", response_model=MessageOut)
def enable_google_account(body: ExternalIdIn, db: Db, user: CurrentUser) -> MessageOut:
    account = services.enable_google_account(
        db, user=user, external_id=body.external_id
    )
    return _ok(db, "Obunaga qo'shildi: %(name)s" % {"name": account})


@router.post("/google/refresh", response_model=MessageOut)
def refresh_google_accounts(db: Db, user: CurrentUser) -> MessageOut:
    services.request_google_accounts(db, user=user)
    return _ok(db, "Tekshirilmoqda. Ro'yxat bir zumda yangilanadi.")


def _provider_sentence(exc: ProviderError) -> str:
    if exc.retryable:
        return "Platforma hozir band. Bir necha daqiqadan so'ng qayta urining."
    return (
        "Platforma bu so'rovni rad etdi. Qayta urinish natijani "
        "o'zgartirmaydi — reklama akkaunti ulanishini tekshiring yoki "
        "biz bilan bog'laning."
    )


def _audiences(db: Session, *, owner: User, syncing: bool, tries: int) -> AudiencesOut:
    from app.modules.ads.selectors import page_accounts
    from app.modules.businesses.selectors import business_for

    account = selectors.active_ad_account(db, owner=owner)
    sources = selectors.sources_for(db, owner=owner, account=account)
    rules = selectors.rule_options(provider=account.provider) if account else []
    business = business_for(db, owner)
    return AudiencesOut(
        audiences=[
            AudienceOut.model_validate(row)
            for row in selectors.audiences(
                db, owner=owner, accounts=page_accounts(db, owner=owner)
            )
        ],
        ad_account=AdAccountOut.model_validate(account) if account else None,
        sources=[OptionOut(**asdict(option)) for option in sources],
        rule_options=[
            RuleOptionOut(
                kind=o.kind,
                label=o.label,
                actions=list(o.actions),
                windows=list(o.windows),
            )
            for o in rules
        ],
        seeds=[
            OptionOut(**asdict(option))
            for option in selectors.seeds_for(db, owner=owner)
        ],
        breadths=[
            (str(key), BREADTH_LABELS[key], text) for key, text in BREADTH_NOTES.items()
        ],
        business_country=business.country_code if business else "",
        action_notes={str(key): str(text) for key, text in ACTION_NOTES.items()},
        min_members=MIN_AUDIENCE_MEMBERS,
        useful_members=USEFUL_AUDIENCE_MEMBERS,
        terms_url=(
            audience_terms_url(account.external_id)
            if account is not None and account.custom_audience_terms_accepted is False
            else ""
        ),
        syncing=syncing,
        tries=tries,
    )


@router.get("/audiences", response_model=AudiencesOut)
def audiences(db: Db, user: CurrentUser) -> AudiencesOut:
    account = selectors.active_ad_account(db, owner=user)
    syncing = services.refresh_if_stale(db, account=account) if account else False
    db.commit()
    return _audiences(db, owner=user, syncing=syncing, tries=0)


@router.get("/audiences/rows", response_model=AudiencesOut)
def audience_rows(
    db: Db, user: CurrentUser, tries: int = Query(default=0, ge=0, le=MAX_POLLS)
) -> AudiencesOut:
    return _audiences(db, owner=user, syncing=tries < MAX_POLLS, tries=tries + 1)


def _provider_call(fn: Any) -> Any:
    try:
        return fn()
    except ProviderError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, detail=_provider_sentence(exc)
        ) from exc


@router.post("/audiences", response_model=AudienceOut, status_code=201)
def create_audience(body: AudienceIn, db: Db, user: CurrentUser) -> CustomAudience:
    return _provider_call(
        lambda: services.create_audience(
            db, owner=user, name=body.name, description=body.description
        )
    )


@router.post("/audiences/rule", response_model=AudienceOut, status_code=201)
def create_rule_audience(
    body: RuleAudienceIn, db: Db, user: CurrentUser
) -> CustomAudience:
    kind, _sep, external_id = body.source.partition(":")
    return _provider_call(
        lambda: services.create_rule_audience(
            db,
            owner=user,
            name=body.name,
            kind=kind,
            external_id=external_id,
            action=body.action,
            retention_days=body.retention_days,
        )
    )


@router.post("/audiences/lookalike", response_model=AudienceOut, status_code=201)
def create_lookalike_audience(
    body: LookalikeAudienceIn, db: Db, user: CurrentUser
) -> CustomAudience:
    if body.breadth not in BREADTH_LABELS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Kenglik noto'g'ri."
        )
    return _provider_call(
        lambda: services.create_lookalike_audience(
            db,
            owner=user,
            name=body.name,
            origin_external_id=body.origin,
            breadth=body.breadth,
        )
    )


def _audience(db: Session, user: User, pk: uuid.UUID) -> CustomAudience:
    audience = selectors.audience_for(db, owner=user, pk=pk)
    if audience is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return audience


@router.post("/audiences/{pk}/fill", response_model=MessageOut)
def fill_audience(pk: uuid.UUID, db: Db, user: CurrentUser) -> MessageOut:
    audience = _audience(db, user, pk)
    filled = _provider_call(
        lambda: services.fill_audience(db, owner=user, audience=audience)
    )
    return MessageOut(
        detail="%(count)s ta yozuv yuborildi. Hisoblash bir necha soat davom etadi."
        % {"count": filled.members_sent}
    )


@router.delete("/audiences/{pk}", response_model=MessageOut)
def delete_audience(pk: uuid.UUID, db: Db, user: CurrentUser) -> MessageOut:
    audience = _audience(db, user, pk)
    _provider_call(lambda: services.delete_audience(db, owner=user, audience=audience))
    return MessageOut(detail="Auditoriya o'chirildi.")
