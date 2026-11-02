"""The ChatGPT Ads section of the cabinet.

Everything here is not found (``chatgpt_ads_unavailable``) for an owner
ChatGPT Ads is not switched on for, except ``/card``, which says so.

The order the cabinet follows: ``/card`` → ``/connect`` with the API key →
``/screen`` for campaigns and figures → ``/campaigns/{id}`` for one
campaign's groups and ads. A new campaign is ``/draft`` (optional, AI
texts), ``/places`` (optional, regions), ``/images`` (optional, picture),
then ``POST /campaigns``. Presses (``/switch``, ``/budget``, ``/archive``)
go to OpenAI while the owner waits and say whether they were rehearsed.
"""

from typing import Annotated

from fastapi import APIRouter, File, Query, UploadFile, status
from openaiadskit import ImageSpec

from app.api.deps import CurrentUser, Db
from app.common.config import settings
from app.modules.chatgpt import services
from app.modules.chatgpt.constants import DEFAULT_PERIOD, PLACE_QUERY_MAX
from app.modules.chatgpt.drafting import write_draft
from app.modules.chatgpt.exceptions import ChatGPTBudgetRequired
from app.modules.chatgpt.schemas import (
    ArchiveIn,
    BudgetIn,
    Card,
    ConnectIn,
    CreatedOut,
    DetailOut,
    DraftIn,
    DraftOut,
    ImageOut,
    NewCampaignIn,
    PlaceOut,
    Pressed,
    Said,
    ScreenOut,
    SwitchIn,
    created_out,
    detail_out,
    minor_of,
    place_out,
    screen_out,
    shown_account,
)
from app.modules.chatgpt.selectors import (
    chatgpt_account,
    chatgpt_ads_on,
    connected,
    usable_connection,
)
from app.modules.integrations.models import AdAccount

router = APIRouter(prefix="/chatgpt", tags=["chatgpt ads"])

SENT = "ChatGPT Ads'ga yuborildi."
REHEARSED = "Sinov rejimi: ChatGPT Ads'ga yuborilmadi."


def _pressed(result_dry_run: bool, done: str) -> Pressed:
    return Pressed(
        message=REHEARSED if result_dry_run else f"{SENT} {done}",
        dry_run=result_dry_run,
    )


def _card(db: Db, user: CurrentUser) -> Card:
    dry_run = settings.chatgpt_ads_dry_run
    if not chatgpt_ads_on(user=user):
        return Card(available=False, connected=False, dry_run=dry_run)
    account: AdAccount | None = chatgpt_account(db, owner=user)
    linked = usable_connection(db, owner=user) is not None and account is not None
    return Card(
        available=True,
        connected=linked,
        account=shown_account(account) if linked and account else None,
        dry_run=dry_run,
    )


@router.get("/card", response_model=Card)
def card(db: Db, user: CurrentUser) -> Card:
    """Whether the section is on for this owner, and which account is connected."""
    return _card(db, user)


@router.post("/connect", response_model=Card)
def connect(body: ConnectIn, db: Db, user: CurrentUser) -> Card:
    """Check the API key with OpenAI and keep it; a new key replaces the old."""
    services.connect_chatgpt(db, user=user, api_key=body.api_key)
    db.commit()
    return _card(db, user)


@router.post("/disconnect", response_model=Said)
def disconnect(db: Db, user: CurrentUser) -> Said:
    """Forget the key. Campaigns at OpenAI keep running as they are."""
    services.disconnect_chatgpt(db, user=user)
    db.commit()
    return Said(
        message="ChatGPT Ads uzildi. Kampaniyalar OpenAI'da o'z holicha qoladi."
    )


@router.get("/screen", response_model=ScreenOut)
def screen(db: Db, user: CurrentUser, period: str = Query(DEFAULT_PERIOD)) -> ScreenOut:
    """The account's campaigns with their figures, read from OpenAI now."""
    found = services.chatgpt_screen(db, user=user, period=period)
    return screen_out(found, dry_run=settings.chatgpt_ads_dry_run)


@router.get("/campaigns/{campaign_id}", response_model=DetailOut)
def campaign(
    campaign_id: str, db: Db, user: CurrentUser, period: str = Query(DEFAULT_PERIOD)
) -> DetailOut:
    """One campaign: its ad groups and their ads, each with figures."""
    found = services.campaign_detail(
        db, user=user, campaign_id=campaign_id, period=period
    )
    return detail_out(found)


@router.post("/switch", response_model=Pressed)
def switch(body: SwitchIn, db: Db, user: CurrentUser) -> Pressed:
    """Stop or start one campaign, ad group or ad."""
    result = services.switch(
        db, user=user, level=body.level, object_id=body.id, wanted=body.wanted
    )
    done = "To'xtatildi." if body.wanted == "pause" else "Yoqildi."
    return _pressed(result.dry_run, done)


@router.post("/budget", response_model=Pressed)
def budget(body: BudgetIn, db: Db, user: CurrentUser) -> Pressed:
    """A campaign's daily budget."""
    services.require_on(user)
    account, _ = connected(db, owner=user)
    amount = minor_of(body.budget, currency=account.currency)
    if amount <= 0:
        raise ChatGPTBudgetRequired
    result = services.change_budget(
        db, user=user, campaign_id=body.id, daily_budget_minor=amount
    )
    return _pressed(result.dry_run, "Byudjet yangilandi.")


@router.post("/archive", response_model=Pressed)
def archive(body: ArchiveIn, db: Db, user: CurrentUser) -> Pressed:
    """Stop one object for good, after the dialog has asked. Cannot be undone."""
    result = services.archive(db, user=user, level=body.level, object_id=body.id)
    return _pressed(result.dry_run, "Arxivlandi.")


@router.get("/places", response_model=list[PlaceOut])
def places(
    db: Db, user: CurrentUser, q: str = Query(min_length=1, max_length=PLACE_QUERY_MAX)
) -> list[PlaceOut]:
    """Markets and regions to target, by name."""
    return [place_out(place) for place in services.find_places(db, user=user, query=q)]


@router.post("/images", response_model=ImageOut)
async def image(
    db: Db,
    user: CurrentUser,
    file: Annotated[
        UploadFile, File(description="JPEG, PNG or WebP, at least 640×640.")
    ],
) -> ImageOut:
    """The card's picture, sent to OpenAI ahead of the campaign."""
    content = await file.read()
    file_id = services.upload_card_image(
        db,
        user=user,
        content=content,
        filename=file.filename or "image",
        content_type=file.content_type or "",
    )
    return ImageOut(file_id=file_id, dry_run=settings.chatgpt_ads_dry_run)


@router.post("/draft", response_model=DraftOut)
def draft(body: DraftIn, db: Db, user: CurrentUser) -> DraftOut:
    """«AI yozib bersin»: title, text and topic options from the business profile."""
    services.require_on(user)
    connected(db, owner=user)
    found = write_draft(db, user=user, target_url=body.target_url)
    return DraftOut(
        titles=found.titles, bodies=found.bodies, context_hints=found.context_hints
    )


@router.post(
    "/campaigns", response_model=CreatedOut, status_code=status.HTTP_201_CREATED
)
def create(body: NewCampaignIn, db: Db, user: CurrentUser) -> CreatedOut:
    """«Yaratish»: a campaign, one ad group and one chat card at OpenAI."""
    services.require_on(user)
    account, _ = connected(db, owner=user)
    daily = minor_of(body.daily_budget, currency=account.currency)
    if daily <= 0:
        raise ChatGPTBudgetRequired
    image = (
        ImageSpec(file_id=body.file_id.strip(), url=body.image_url.strip())
        if body.file_id.strip() or body.image_url.strip()
        else None
    )
    new = services.NewCampaign(
        name=body.name,
        daily_budget_minor=daily,
        title=body.title,
        body=body.body,
        target_url=body.target_url,
        countries=tuple(body.countries),
        place_ids=tuple(body.place_ids),
        context_hints=tuple(body.context_hints),
        max_bid_minor=minor_of(body.max_bid, currency=account.currency)
        if body.max_bid
        else 0,
        image=image,
        start_active=body.start_active,
    )
    made = services.create_campaign(db, user=user, new=new, request_id=body.request_id)
    return created_out(made)
