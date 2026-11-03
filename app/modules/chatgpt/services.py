"""Connecting by API key, reading the account live, and the presses on it.

Every call to OpenAI happens while the owner waits, so every one is
wrapped by :func:`openai_refusals`: a passing fault is a sentence to try
again, a refusal is the cabinet's refusal dialog with OpenAI's own words in
it.

Writes go through the registry's port, which honours
``CHATGPT_ADS_DRY_RUN``; the launch honours it here, since it is not a port.
"""

import logging
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Final

from adskit import registry
from adskit.dto import ActionResult
from adskit.errors import (
    AuthFailed,
    InvalidRequest,
    NotFound,
    PermissionDenied,
    ProviderError,
    RateLimited,
)
from adskit.refs import ExternalRef, Level, MinorUnits
from openaiadskit import (
    PROVIDER as CHATGPT,
)
from openaiadskit import (
    AdsClient,
    ChatCardSpec,
    ImageSpec,
    OpenAIAdsError,
    create_chat_campaign,
    read_ad_account,
    search_places,
    translate_error,
)
from openaiadskit.accounts import AdAccountInfo, PlaceInfo
from openaiadskit.campaigns import ads_of, campaign_found, campaigns_of, groups_of
from openaiadskit.launch import campaign_body, upload_image
from openaiadskit.metrics import Totals, report_totals
from openaiadskit.rows import Locations, minor_to_micros
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.common.config import settings
from app.common.contract import Refusal
from app.common.crypto import encrypt, fingerprint
from app.common.db import utcnow
from app.common.exceptions import InputRefused
from app.modules.accounts.models import User
from app.modules.audit.constants import EventName
from app.modules.audit.services import emit
from app.modules.chatgpt.constants import (
    API_KEY_MAX,
    DEFAULT_PERIOD,
    IMAGE_MAX_BYTES,
    IMAGE_TYPES,
    PERIODS,
    PLACES_SHOWN,
)
from app.modules.chatgpt.exceptions import (
    ChatGPTAccountTaken,
    ChatGPTAdsUnavailable,
    ChatGPTImageRefused,
    ChatGPTKeyRejected,
    ChatGPTKeyRequired,
    ChatGPTNotConnected,
    ChatGPTRefused,
    ChatGPTUnreachable,
)
from app.modules.chatgpt.selectors import (
    account_by_external_id,
    chatgpt_ads_on,
    chatgpt_connection,
    connected,
    usable_connection,
)
from app.modules.integrations.constants import ConnectionKind, ConnectionStatus
from app.modules.integrations.exceptions import SubscriptionRequired
from app.modules.integrations.models import AdAccount, ProviderConnection

logger = logging.getLogger(__name__)
NO_TOKEN: Final = b""
AGGREGATE: Final = "connection"

# What the owner pressed, as the refusal dialog's title.
TITLES: Final[dict[str, str]] = {
    "read": "ChatGPT Ads ma'lumot bermadi",
    "switch": "ChatGPT Ads holatni o'zgartirmadi",
    "budget": "ChatGPT Ads byudjetni qabul qilmadi",
    "archive": "ChatGPT Ads o'chirishni rad etdi",
    "create": "ChatGPT Ads kampaniyani qabul qilmadi",
    "place": "ChatGPT Ads joyni qidira olmadi",
}
# The field each launch rule speaks of, and what to say under it.
SPEC_PROBLEMS: Final[dict[str, tuple[str, str]]] = {
    "name": ("name", "Kampaniya nomi 3 belgidan kam bo'lmasin."),
    "budget": ("dailyBudget", "Kunlik byudjet kamida 1 (akkaunt valyutasida)."),
    "title": ("title", "Sarlavha 3-50 belgi bo'lsin."),
    "body": ("body", "Matn bo'sh bo'lmasin va 100 belgidan oshmasin."),
    "target_url": ("targetUrl", "Havola https:// bilan boshlansin."),
    "locations": ("countries", "Kamida bitta davlat yoki hudud tanlang."),
    "countries": ("countries", "Davlat kodi ikki harf bo'lsin (masalan, UZ)."),
    "context_hints": (
        "contextHints",
        "Mavzular 20 tadan oshmasin, har biri 300 belgigacha.",
    ),
    "max_bid": ("maxBid", "Eng yuqori narx manfiy bo'lmasin."),
}


def require_on(user: User) -> None:
    if not chatgpt_ads_on(user=user):
        raise ChatGPTAdsUnavailable


@contextmanager
def openai_refusals(operation: str) -> Iterator[None]:
    """OpenAI's failures as the owner reads them, for every call made here."""
    try:
        yield
    except OpenAIAdsError as exc:
        raise _refused(translate_error(exc), operation=operation) from exc
    except ProviderError as exc:
        raise _refused(exc, operation=operation) from exc


def _refused(exc: ProviderError, *, operation: str) -> Exception:
    if exc.retryable and not isinstance(exc, RateLimited):
        return ChatGPTUnreachable()
    if isinstance(exc, AuthFailed):
        cause = "API kalit endi ishlamayapti: u o'chirilgan yoki almashtirilgan."
        steps = [
            "ads.openai.com → Settings'da yangi kalit yarating.",
            "ChatGPT Ads'ni qayta ulang.",
        ]
    elif isinstance(exc, PermissionDenied):
        cause = "Bu kalitga shu amal uchun ruxsat yo'q yoki bu imkoniyat akkauntda yoqilmagan."
        steps = ["Ads Manager'da akkaunt holatini tekshiring."]
    elif isinstance(exc, NotFound):
        cause = "Bu obyekt ChatGPT Ads'da topilmadi. U Ads Manager'da o'chirilgan bo'lishi mumkin."
        steps = ["Sahifani yangilang."]
    elif isinstance(exc, RateLimited):
        cause = "So'rovlar juda ko'p bo'ldi."
        steps = ["Bir daqiqadan keyin qayta urinib ko'ring."]
    else:
        cause = "OpenAI kiritilgan qiymatlarni qabul qilmadi."
        steps = ["Quyidagi OpenAI izohini o'qing va qiymatni to'g'rilang."]
    refusal = Refusal(
        key=exc.key or None,
        retryable=isinstance(exc, RateLimited),
        title=TITLES.get(operation, TITLES["read"]),
        cause=cause,
        steps=steps,
        provider_words=str(exc) or None,
        retry_after_seconds=getattr(exc, "retry_after_seconds", None) or None,
    )
    return ChatGPTRefused(cause, refusal=refusal.model_dump(by_alias=True))


# -- connecting ------------------------------------------------------------


def connect_chatgpt(db: Session, *, user: User, api_key: str) -> AdAccount:
    """Check the key with OpenAI, keep it encrypted, remember its account."""
    from app.modules.billing.selectors import has_live_subscription

    require_on(user)
    if not has_live_subscription(db, owner=user):
        raise SubscriptionRequired
    key = api_key.strip()
    if not key or len(key) > API_KEY_MAX or any(ch.isspace() for ch in key):
        raise ChatGPTKeyRequired
    info = _account_behind(key)

    held = account_by_external_id(db, external_id=info.id)
    if held is not None and held.owner_id != user.id:
        other = usable_connection(db, owner=held.owner)
        if other is not None and other.external_user_id == info.id:
            raise ChatGPTAccountTaken
        # The cabinet that had it let go: the account moves here.
        _release_identity(db, external_id=info.id)

    try:
        connection = _store_key(db, user=user, key=key, info=info)
        account = _store_account(
            db, user=user, connection=connection, info=info, held=held
        )
        emit(
            db,
            owner_id=user.id,
            name=EventName.CONNECTION_ADDED,
            aggregate_type=AGGREGATE,
            aggregate_id=connection.id,
            payload={"provider": CHATGPT, "ad_account": info.id},
        )
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ChatGPTAccountTaken from exc
    return account


def _account_behind(key: str) -> AdAccountInfo:
    try:
        with AdsClient(api_key=key) as client:
            info = read_ad_account(client)
    except OpenAIAdsError as exc:
        found = translate_error(exc)
        if isinstance(found, AuthFailed | PermissionDenied | NotFound | InvalidRequest):
            raise ChatGPTKeyRejected from exc
        raise ChatGPTUnreachable from exc
    if not info.id:
        raise ChatGPTKeyRejected
    return info


def _release_identity(db: Session, *, external_id: str) -> None:
    db.execute(
        update(ProviderConnection)
        .where(
            ProviderConnection.provider == CHATGPT,
            ProviderConnection.external_user_id == external_id,
        )
        .values(external_user_id="", updated_at=utcnow())
    )


def _store_key(
    db: Session, *, user: User, key: str, info: AdAccountInfo
) -> ProviderConnection:
    connection = chatgpt_connection(db, owner=user)
    if connection is None:
        connection = ProviderConnection(owner_id=user.id, provider=CHATGPT)
        db.add(connection)
    connection.kind = ConnectionKind.API_KEY
    connection.scopes = []
    connection.token_encrypted = encrypt(key)
    connection.token_fingerprint = fingerprint(key)
    connection.status = ConnectionStatus.ACTIVE
    connection.expires_at = None
    connection.last_verified_at = utcnow()
    connection.last_error_code = ""
    # One ChatGPT ad account, one cabinet: the identity index holds it.
    connection.external_user_id = info.id
    connection.external_user_name = info.name[:255]
    db.flush()
    return connection


def _store_account(
    db: Session,
    *,
    user: User,
    connection: ProviderConnection,
    info: AdAccountInfo,
    held: AdAccount | None,
) -> AdAccount:
    db.execute(
        update(AdAccount)
        .where(
            AdAccount.owner_id == user.id,
            AdAccount.provider == CHATGPT,
            AdAccount.is_current.is_(True),
            AdAccount.external_id != info.id,
        )
        .values(is_current=False, updated_at=utcnow())
    )
    account = held or AdAccount(provider=CHATGPT, external_id=info.id)
    if held is None:
        db.add(account)
    account.owner_id = user.id
    account.connection_id = connection.id
    account.name = info.name[:255]
    account.currency = info.currency[:3]
    account.timezone = info.timezone[:64]
    account.account_status = info.status[:32]
    # Never active: see the module's package doc. The sweeps read only
    # active accounts, and none of them speaks ChatGPT yet.
    account.is_active = False
    account.is_current = True
    account.synced_at = utcnow()
    db.flush()
    return account


def disconnect_chatgpt(db: Session, *, user: User) -> None:
    require_on(user)
    connection = chatgpt_connection(db, owner=user)
    if connection is None or not connection.token_encrypted:
        raise ChatGPTNotConnected
    connection.token_encrypted = NO_TOKEN
    connection.token_fingerprint = ""
    connection.status = ConnectionStatus.REVOKED
    # Frees the account for whichever cabinet connects it next.
    connection.external_user_id = ""
    emit(
        db,
        owner_id=user.id,
        name=EventName.CONNECTION_REMOVED,
        aggregate_type=AGGREGATE,
        aggregate_id=connection.id,
        payload={"provider": CHATGPT},
    )
    db.flush()


# -- reading ---------------------------------------------------------------

EMPTY: Final = Totals(impressions=0, clicks=0, spend_minor=MinorUnits(0), conversions=0)


@dataclass(frozen=True, slots=True)
class Period:
    key: str
    since: date
    until: date


@dataclass(frozen=True, slots=True)
class Screen:
    account: AdAccount
    info: AdAccountInfo
    period: Period
    campaigns: list[tuple[Any, Totals]]
    totals: Totals


@dataclass(frozen=True, slots=True)
class CampaignDetail:
    account: AdAccount
    period: Period
    campaign: Any
    figures: Totals
    groups: list[tuple[Any, Totals, list[tuple[Any, Totals]]]] = field(
        default_factory=list
    )
    locations: Locations = field(default_factory=Locations)


def period_of(account: AdAccount, key: str) -> Period:
    key = key if key in PERIODS else DEFAULT_PERIOD
    until = utcnow().astimezone(account.tzinfo()).date()
    return Period(key=key, since=until - timedelta(days=PERIODS[key] - 1), until=until)


def summed(rows: list[Totals]) -> Totals:
    return Totals(
        impressions=sum(row.impressions for row in rows),
        clicks=sum(row.clicks for row in rows),
        spend_minor=MinorUnits(sum(row.spend_minor for row in rows)),
        conversions=sum(row.conversions for row in rows),
    )


def chatgpt_screen(db: Session, *, user: User, period: str) -> Screen:
    """The account and its campaigns with their figures, read from OpenAI now."""
    require_on(user)
    account, key = connected(db, owner=user)
    shown = period_of(account, period)
    with openai_refusals("read"), AdsClient(api_key=key) as client:
        info = read_ad_account(client)
        campaigns = campaigns_of(client, currency=info.currency)
        figures = report_totals(
            client,
            since=shown.since,
            until=shown.until,
            level="campaign",
            currency=info.currency,
        )
    rows = [(campaign, figures.get(campaign.ref.id, EMPTY)) for campaign in campaigns]
    return Screen(
        account=account,
        info=info,
        period=shown,
        campaigns=rows,
        totals=summed([found for _, found in rows]),
    )


def campaign_detail(
    db: Session, *, user: User, campaign_id: str, period: str
) -> CampaignDetail:
    """One campaign's groups and ads, each with its figures."""
    require_on(user)
    account, key = connected(db, owner=user)
    shown = period_of(account, period)
    currency = account.currency
    with openai_refusals("read"), AdsClient(api_key=key) as client:
        found = campaign_found(client, campaign_id=campaign_id, currency=currency)
        if found is None:
            raise _refused(NotFound("campaign"), operation="read")
        campaign, locations = found
        groups = groups_of(client, campaign_id=campaign_id, currency=currency)
        ads = {
            group.ref.id: ads_of(client, ad_group_id=group.ref.id) for group in groups
        }
        by_campaign, by_group, by_ad = (
            report_totals(
                client,
                since=shown.since,
                until=shown.until,
                level=level,
                currency=currency,
            )
            for level in ("campaign", "adset", "ad")
        )
    return CampaignDetail(
        account=account,
        period=shown,
        campaign=campaign,
        locations=locations,
        figures=by_campaign.get(campaign_id, EMPTY),
        groups=[
            (
                group,
                by_group.get(group.ref.id, EMPTY),
                [(ad, by_ad.get(ad.ref.id, EMPTY)) for ad in ads[group.ref.id]],
            )
            for group in groups
        ],
    )


def upload_card_image(
    db: Session, *, user: User, content: bytes, filename: str, content_type: str
) -> str:
    """The picture sent to OpenAI ahead of the campaign; its ``file_id``.

    Rehearsed like every write: nothing is sent and the answer is empty,
    which the launch then reads as «no picture».
    """
    require_on(user)
    _, key = connected(db, owner=user)
    if content_type not in IMAGE_TYPES or not content or len(content) > IMAGE_MAX_BYTES:
        raise ChatGPTImageRefused
    if settings.chatgpt_ads_dry_run:
        return ""
    image = ImageSpec(content=content, filename=filename, content_type=content_type)
    with openai_refusals("create"), AdsClient(api_key=key) as client:
        return upload_image(client, image)


def find_places(db: Session, *, user: User, query: str) -> list[PlaceInfo]:
    require_on(user)
    _, key = connected(db, owner=user)
    with openai_refusals("place"), AdsClient(api_key=key) as client:
        return search_places(client, query=query.strip(), limit=PLACES_SHOWN)


# -- presses ---------------------------------------------------------------


def _ref(level: Level, object_id: str) -> ExternalRef:
    return ExternalRef(provider=CHATGPT, level=level, id=object_id)


def switch(
    db: Session, *, user: User, level: Level, object_id: str, wanted: str
) -> ActionResult:
    require_on(user)
    _, key = connected(db, owner=user)
    status = "paused" if wanted == "pause" else "active"
    with openai_refusals("switch"):
        return registry.get(CHATGPT).campaigns.set_status(
            ref=_ref(level, object_id), status=status, token=key, dry_run=False
        )


def change_budget(
    db: Session, *, user: User, campaign_id: str, daily_budget_minor: int
) -> ActionResult:
    require_on(user)
    _, key = connected(db, owner=user)
    with openai_refusals("budget"):
        return registry.get(CHATGPT).campaigns.set_budget(
            ref=_ref("campaign", campaign_id),
            daily_budget_minor=daily_budget_minor,
            token=key,
            dry_run=False,
        )


def archive(db: Session, *, user: User, level: Level, object_id: str) -> ActionResult:
    require_on(user)
    _, key = connected(db, owner=user)
    with openai_refusals("archive"):
        return registry.get(CHATGPT).campaigns.delete(
            ref=_ref(level, object_id), token=key, dry_run=False
        )


@dataclass(frozen=True, slots=True)
class NewCampaign:
    """What the owner filled in, money already in the account's minor units."""

    name: str
    daily_budget_minor: int
    title: str
    body: str
    target_url: str
    countries: tuple[str, ...] = ()
    place_ids: tuple[str, ...] = ()
    context_hints: tuple[str, ...] = ()
    max_bid_minor: int = 0
    image: ImageSpec | None = None
    start_active: bool = True


@dataclass(frozen=True, slots=True)
class Created:
    dry_run: bool
    campaign_id: str = ""
    ad_group_id: str = ""
    ad_id: str = ""
    review_status: str = ""
    active: bool = False
    sent: dict[str, Any] = field(default_factory=dict)


def spec_of(new: NewCampaign, *, currency: str) -> ChatCardSpec:
    spec = ChatCardSpec(
        name=new.name,
        daily_budget_micros=minor_to_micros(new.daily_budget_minor, currency),
        title=new.title,
        body=new.body,
        target_url=new.target_url,
        countries=tuple(code.strip().upper() for code in new.countries if code.strip()),
        place_ids=tuple(place for place in new.place_ids if place),
        context_hints=tuple(hint.strip() for hint in new.context_hints if hint.strip()),
        max_bid_micros=minor_to_micros(new.max_bid_minor, currency)
        if new.max_bid_minor
        else 0,
        image=new.image,
        start_active=new.start_active,
        query_string_template=(
            "utm_source=chatgpt&utm_medium=paid&utm_campaign={campaign_id}&utm_content={ad_id}"
        ),
    )
    try:
        return spec.checked()
    except InvalidRequest as exc:
        name, sentence = SPEC_PROBLEMS.get(exc.code, ("", str(exc)))
        raise InputRefused({name: sentence}) from exc


def create_campaign(
    db: Session, *, user: User, new: NewCampaign, request_id: str = ""
) -> Created:
    """One campaign, one ad group, one chat card - or nothing that spends."""
    require_on(user)
    account, key = connected(db, owner=user)
    spec = spec_of(new, currency=account.currency)
    if settings.chatgpt_ads_dry_run:
        return Created(dry_run=True, sent=campaign_body(spec))
    idempotency = f"targetolog:{user.id}:{request_id or uuid.uuid4()}"
    with openai_refusals("create"), AdsClient(api_key=key) as client:
        made = create_chat_campaign(client, spec, key=idempotency)
    logger.info(
        "chatgpt campaign %s made for owner %s (ad %s)",
        made.campaign_id,
        user.id,
        made.ad_id,
    )
    return Created(
        dry_run=False,
        campaign_id=made.campaign_id,
        ad_group_id=made.ad_group_id,
        ad_id=made.ad_id,
        review_status=made.review_status,
        active=made.active,
    )
