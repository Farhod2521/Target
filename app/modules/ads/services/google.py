"""The Google Search wizard: opening a preparation, its two steps, the worker that
looks up places, writes the words and reads the figures, and the creation."""

import logging
from typing import Any, Final
from uuid import UUID

from adskit import registry
from adskit.errors import (
    AuthFailed,
    PermissionDenied,
    ProviderError,
    RateLimited,
    TemporaryFailure,
)
from googleadskit import (
    AdsClient,
    GoogleAdsError,
    KeywordSpec,
    SearchCampaignSpec,
    country_target,
    create_search_campaign,
    keyword_volumes,
    translate_error,
)
from googleadskit.launch import (
    DESCRIPTION_MAX,
    DESCRIPTIONS_MAX,
    DESCRIPTIONS_MIN,
    HEADLINE_MAX,
    HEADLINES_MAX,
    HEADLINES_MIN,
    KEYWORD_MAX_CHARS,
    KEYWORD_MAX_WORDS,
    PATH_MAX,
)
from llmkit import (
    ClaudeRateLimited,
    LLMError,
    LLMResult,
    StructuredOutputError,
    halves,
    render,
)
from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.common import timezone
from app.common.config import settings
from app.common.db import on_commit, utcnow
from app.common.llm import ASKED, claude, model_for, prompts
from app.common.money import format_minor
from app.common.phone import is_e164
from app.modules.accounts.models import User
from app.modules.ads.constants import (
    GOOGLE_KEYWORDS_MAX,
    GOOGLE_NEGATIVES_MAX,
    GOOGLE_PLACES_MAX,
    WRITING_TIMEOUT_SECONDS,
    GoogleGoal,
    LaunchStatus,
)
from app.modules.ads.exceptions import (
    ConnectionUnusable,
    GoogleBudgetRequired,
    GoogleGoalUnknown,
    GoogleLaunchClosed,
    GoogleLaunchNotReady,
    GooglePhoneRequired,
    GooglePlacesTooMany,
    GoogleWebsiteRequired,
    GoogleWordsInvalid,
    ProfileIncomplete,
)
from app.modules.ads.models import GoogleLaunch
from app.modules.ads.selectors.audiences_chosen import picked_areas
from app.modules.ads.services.access import token_for
from app.modules.audit.constants import (
    ActionStatus,
    ActionType,
    ActorType,
    EventName,
    LLMCallStatus,
    LLMPurpose,
)
from app.modules.audit.models import ActionLog
from app.modules.billing.exceptions import NoEntitlement
from app.modules.businesses.models import Business
from core.agent import GoogleSearchDraft

logger = logging.getLogger(__name__)
OPEN_STATUSES = (
    str(LaunchStatus.DRAFT),
    str(LaunchStatus.BUILDING),
    str(LaunchStatus.READY),
    str(LaunchStatus.FAILED),
)
PROMPT: Final = "google_search_draft"
RELATED_TYPE: Final = "google_launch"
TURN: Final = "Write the advert for the business described above."
DRAFT_HEADLINE_MAX: Final = 30
DRAFT_DESCRIPTION_MAX: Final = 90
DRAFT_PATH_MAX: Final = 15
KEYWORD_MAX: Final = 80
KEY_PREFIX: Final = "google_launch"
LOG_PREFIX: Final = "gl"
REFUSED_PHONE: Final = "phone"
REFUSED_POLICY: Final = "policy"
REFUSED_BUSY: Final = "busy"
REFUSED_CONNECTION: Final = "connection"
REFUSED_GOOGLE: Final = "google"
GOAL_RULES: Final[dict[str, str]] = {
    GoogleGoal.VISITS: (
        "The advert sends people to the website. End descriptions with what to do "
        "there: look, choose, order."
    ),
    GoogleGoal.CALLS: (
        "The business's phone number is shown under the advert and the owner wants "
        "calls. Ask people to call in at least two headlines and in the descriptions."
    ),
}


def _profile(db: Session, launch: GoogleLaunch) -> Business | None:
    from app.modules.businesses.selectors import google_profile

    return google_profile(db, owner=launch.owner, account=launch.ad_account)


def _locked(db: Session, *, owner: User, launch_id: Any) -> GoogleLaunch:
    row = db.scalar(
        select(GoogleLaunch)
        .where(GoogleLaunch.owner_id == owner.id, GoogleLaunch.id == launch_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise GoogleLaunchClosed
    return row


def _require_google(db: Session, user: User) -> None:
    from app.modules.integrations.exceptions import GoogleAdsUnavailable
    from app.modules.integrations.selectors.google import google_ads_on

    if not google_ads_on(user=user):
        raise GoogleAdsUnavailable


# -- opening ---------------------------------------------------------------------------


def start_google_launch(db: Session, *, user: User) -> GoogleLaunch:
    """The open preparation for the current Google account, or a new one. Commits."""
    from app.modules.billing.services import require_live_subscription
    from app.modules.businesses.selectors import google_profile
    from app.modules.integrations.exceptions import GoogleNotConnected
    from app.modules.integrations.selectors.google import current_google_account

    _require_google(db, user)
    require_live_subscription(db, owner=user)
    account = current_google_account(db, owner=user)
    if account is None:
        raise GoogleNotConnected
    profile = google_profile(db, owner=user, account=account)
    if profile is None or not profile.category:
        raise ProfileIncomplete
    found = db.scalar(
        select(GoogleLaunch)
        .where(
            GoogleLaunch.owner_id == user.id,
            GoogleLaunch.ad_account_id == account.id,
            GoogleLaunch.status.in_(OPEN_STATUSES),
        )
        .order_by(GoogleLaunch.created_at.desc())
        .with_for_update()
        .limit(1)
    )
    if found is not None:
        return found
    launch = GoogleLaunch(
        owner_id=user.id,
        ad_account_id=account.id,
        currency=account.currency,
        final_url=profile.website,
        phone=profile.contact_phone,
        places=[],
        keywords=[],
        negative_keywords=[],
        headlines=[],
        descriptions=[],
        volumes={},
        created_refs={},
    )
    db.add(launch)
    db.commit()
    return launch


def request_google_refresh(db: Session, *, user: User) -> Any:
    """Queue the mirror and the figures for the current Google account."""
    from app.modules.ads.tasks import sync_ad_account_task
    from app.modules.integrations.exceptions import GoogleNotConnected
    from app.modules.integrations.selectors.google import current_google_account
    from app.modules.metrics.tasks import sync_insights_task

    _require_google(db, user)
    account = current_google_account(db, owner=user)
    if account is None:
        raise GoogleNotConnected
    account_id = str(account.id)
    sync_ad_account_task.delay(account_id)
    sync_insights_task.delay(account_id)
    return account


# -- the first step --------------------------------------------------------------------


def save_google_answers(
    db: Session,
    *,
    user: User,
    launch: GoogleLaunch,
    goal: str,
    final_url: str,
    phone: str,
    area_keys: list[str],
    country_code: str,
    daily_budget_minor: int | None,
) -> GoogleLaunch:
    """Check and store the first step, then queue the preparation. Commits."""
    from app.modules.ads.tasks import prepare_google_launch_task

    launch = _locked(db, owner=user, launch_id=launch.id)
    if launch.status not in OPEN_STATUSES:
        raise GoogleLaunchClosed
    if goal not in GoogleGoal.values:
        raise GoogleGoalUnknown
    launch.goal = goal
    launch.final_url = _website(final_url)
    launch.phone = _phone(phone) if goal == GoogleGoal.CALLS else ""
    if len(set(area_keys)) > GOOGLE_PLACES_MAX:
        raise GooglePlacesTooMany(limit=GOOGLE_PLACES_MAX)
    launch.places = picked_areas(
        db,
        keys=area_keys,
        previous=list(launch.places or []),
        country_code=country_code,
        limit=GOOGLE_PLACES_MAX,
    )
    if not daily_budget_minor or daily_budget_minor <= 0:
        raise GoogleBudgetRequired
    launch.daily_budget_minor = daily_budget_minor
    launch.status = str(LaunchStatus.BUILDING)
    launch.started_at = utcnow()
    launch.error_code = ""
    launch.error_message = ""
    launch_id, run = str(launch.id), launch.started_at.isoformat()
    on_commit(db, lambda: prepare_google_launch_task.delay(launch_id, run))
    db.commit()
    return launch


def _website(url: str) -> str:
    url = url.strip()
    if url and "://" not in url:
        url = f"https://{url}"
    if not url.startswith(("https://", "http://")) or "." not in url:
        raise GoogleWebsiteRequired
    return url


def _phone(phone: str) -> str:
    phone = "".join(char for char in phone if char.isdigit() or char == "+")
    if not is_e164(phone):
        raise GooglePhoneRequired
    return phone


def change_google_site(
    db: Session, *, user: User, launch: GoogleLaunch, final_url: str
) -> GoogleLaunch:
    """The site changed on the words step: the words already written stay. Commits."""
    launch = _locked(db, owner=user, launch_id=launch.id)
    if launch.status not in OPEN_STATUSES:
        raise GoogleLaunchClosed
    launch.final_url = _website(final_url)
    db.commit()
    return launch


# -- the words step --------------------------------------------------------------------


def save_google_words(
    db: Session,
    *,
    user: User,
    launch: GoogleLaunch,
    keywords: list[str],
    negative_keywords: list[str],
    headlines: list[str],
    descriptions: list[str],
    path1: str,
    path2: str,
) -> GoogleLaunch:
    """Store the edited words, or say which line Google would refuse. Commits."""
    from app.modules.ads.tasks import refresh_google_volumes_task

    launch = _locked(db, owner=user, launch_id=launch.id)
    if launch.status != LaunchStatus.READY:
        raise GoogleLaunchNotReady
    kept = {row["text"]: row for row in launch.keywords or []}
    texts = _lines(keywords)
    _check_keywords(texts, limit=GOOGLE_KEYWORDS_MAX, required=True)
    negatives = _lines(negative_keywords)
    _check_keywords(negatives, limit=GOOGLE_NEGATIVES_MAX, required=False)
    launch.headlines = _texts(
        headlines,
        low=HEADLINES_MIN,
        high=HEADLINES_MAX,
        width=HEADLINE_MAX,
        what="sarlavha",
    )
    launch.descriptions = _texts(
        descriptions,
        low=DESCRIPTIONS_MIN,
        high=DESCRIPTIONS_MAX,
        width=DESCRIPTION_MAX,
        what="tavsif",
    )
    launch.path1, launch.path2 = _paths(path1, path2)
    changed = set(texts) != set(kept)
    launch.keywords = [
        kept.get(text) or {"text": text, "match": "PHRASE"} for text in texts
    ]
    launch.negative_keywords = negatives
    if changed:
        launch_id = str(launch.id)
        on_commit(db, lambda: refresh_google_volumes_task.delay(launch_id))
    db.commit()
    return launch


def _lines(rows: list[str]) -> list[str]:
    seen: list[str] = []
    for row in rows:
        text = " ".join(row.split())
        if text and text.casefold() not in {item.casefold() for item in seen}:
            seen.append(text)
    return seen


def _check_keywords(texts: list[str], *, limit: int, required: bool) -> None:
    if required and not texts:
        raise GoogleWordsInvalid("Kamida bitta kalit so'z yozing.")
    if len(texts) > limit:
        raise GoogleWordsInvalid(f"Ko'pi bilan {limit} ta so'z yozing.")
    for text in texts:
        if len(text) > KEYWORD_MAX_CHARS or len(text.split()) > KEYWORD_MAX_WORDS:
            raise GoogleWordsInvalid(
                f"«{text}» juda uzun: {KEYWORD_MAX_CHARS} belgi va "
                f"{KEYWORD_MAX_WORDS} so'zgacha."
            )


def _texts(rows: list[str], *, low: int, high: int, width: int, what: str) -> list[str]:
    texts = _lines(rows)
    if not low <= len(texts) <= high:
        raise GoogleWordsInvalid(f"{low} tadan {high} tagacha {what} kerak.")
    for text in texts:
        if len(text) > width:
            raise GoogleWordsInvalid(f"«{text}» {width} belgidan uzun ({len(text)}).")
    return texts


def _paths(path1: str, path2: str) -> tuple[str, str]:
    first, second = path1.strip(), path2.strip()
    if len(first) > PATH_MAX or len(second) > PATH_MAX:
        raise GoogleWordsInvalid(f"Manzil so'zi {PATH_MAX} belgidan oshmasin.")
    return first, second if first else ""


# -- the worker that prepares ----------------------------------------------------------


def prepare_google_launch(db: Session, *, launch_id: UUID | str, run: str) -> str:
    """One preparation run. Returns a word for the task log."""
    from app.modules.billing.services import require_live_subscription

    launch = db.get(GoogleLaunch, UUID(str(launch_id)))
    if launch is None:
        return "gone"
    if not _is_this_run(launch, run=run):
        return "superseded"
    try:
        require_live_subscription(db, owner=launch.owner)
    except NoEntitlement:
        return _fail(db, launch, run=run, code="subscription_expired")
    profile = _profile(db, launch)
    if profile is None or not profile.category:
        return _fail(db, launch, run=run, code="profile_incomplete")
    try:
        token = token_for(ad_account=launch.ad_account)
        places = _resolve_places(launch, profile=profile, token=token)
    except (ConnectionUnusable, ProviderError):
        return _fail(db, launch, run=run, code="google_unreachable")
    words = None if launch.ai_written_at else _write(db, launch, profile=profile)
    if words is False:
        return _fail(db, launch, run=run, code="ai_failed")
    keywords = (
        [row["text"] for row in launch.keywords or []]
        if words is None
        else [row["text"] for row in words["keywords"]]  # type: ignore[index]
    )
    volumes = _volumes(
        launch, token=token, keywords=keywords, places=places, profile=profile
    )
    return _finish(
        db,
        launch,
        run=run,
        places=places,
        words=words if isinstance(words, dict) else None,
        volumes=volumes,
    )


def refresh_google_volumes(db: Session, *, launch_id: UUID | str) -> str:
    """Read the figures again after the owner changed the keywords."""
    launch = db.get(GoogleLaunch, UUID(str(launch_id)))
    if launch is None or launch.status != LaunchStatus.READY:
        return "skipped"
    profile = _profile(db, launch)
    if profile is None:
        return "skipped"
    try:
        token = token_for(ad_account=launch.ad_account)
    except (ConnectionUnusable, ProviderError):
        return "unreachable"
    volumes = _volumes(
        launch,
        token=token,
        keywords=[row["text"] for row in launch.keywords or []],
        places=list(launch.places or []),
        profile=profile,
    )
    db.execute(
        update(GoogleLaunch)
        .where(
            GoogleLaunch.id == launch.id, GoogleLaunch.status == str(LaunchStatus.READY)
        )
        .values(volumes=volumes, updated_at=utcnow())
    )
    db.commit()
    return str(len(volumes))


def google_targets(
    *,
    places: list[dict[str, Any]],
    customer_id: str,
    client: AdsClient,
    country_code: str,
) -> list[str]:
    """The geo targets a campaign is aimed at: the places, or the country."""
    found = [str(row["key"]) for row in places if row.get("key")]
    if found:
        return found
    whole = country_target(client, customer_id, country_code)
    return [whole] if whole else []


def _resolve_places(
    launch: GoogleLaunch, *, profile: Business, token: str
) -> list[dict[str, Any]]:
    from app.modules.ads.services.locations import search_areas

    places = list(launch.places or [])
    waiting = [row for row in places if not row.get("searched")]
    if not waiting:
        return places
    found = search_areas(
        audiences=registry.get(launch.ad_account.provider).audiences,
        areas=waiting,
        country_code=profile.country_code,
        token=token,
    )
    return [
        row
        if row.get("searched")
        else row
        | {"key": found.get(str(row["area"]), {}).get("key", ""), "searched": True}
        for row in places
    ]


def _write(
    db: Session, launch: GoogleLaunch, *, profile: Business
) -> dict[str, Any] | bool:
    from app.modules.audit.services import record_llm_failure, record_llm_result

    try:
        result = _ask(launch=launch, profile=profile)
    except LLMError as exc:
        logger.info("google draft for %s failed: %s", launch.id, exc)
        record_llm_failure(
            db,
            owner=launch.owner,
            purpose=LLMPurpose.ONBOARDING,
            status=_ledger_status(exc),
            prompt_name=PROMPT,
            prompt_version=prompts().latest(PROMPT),
            model=model_for(ASKED),
            currency=str(settings.anthropic_price_currency),
            related_type=RELATED_TYPE,
            related_id=launch.id,
        )
        db.commit()
        return False
    record_llm_result(
        db,
        owner=launch.owner,
        purpose=LLMPurpose.ONBOARDING,
        result=result,
        related_type=RELATED_TYPE,
        related_id=launch.id,
    )
    db.commit()
    return fitted(result.value)


def _ledger_status(exc: LLMError) -> LLMCallStatus:
    if isinstance(exc, ClaudeRateLimited):
        return LLMCallStatus.RATE_LIMITED
    if isinstance(exc, StructuredOutputError):
        return LLMCallStatus.SCHEMA_ERROR
    return LLMCallStatus.FAILED


def _ask(*, launch: GoogleLaunch, profile: Business) -> LLMResult[GoogleSearchDraft]:
    from app.modules.businesses.selectors import category_label

    template, version = prompts().get(PROMPT)
    instructions, account = halves(template)
    tail = render(
        account,
        {
            "goal_rule": GOAL_RULES.get(launch.goal, GOAL_RULES[GoogleGoal.VISITS]),
            "business_name": profile.name,
            "business_category": category_label(profile),
            "city": profile.city or "-",
            "country_code": profile.country_code,
            "offer_text": profile.offer_text or "-",
            "final_url": launch.final_url,
            "places": ", ".join(str(row["name"]) for row in launch.places or [])
            or profile.country_code,
            "daily_budget": format_minor(
                amount_minor=launch.daily_budget_minor, currency=launch.currency
            ),
        },
    )
    with claude(timeout=WRITING_TIMEOUT_SECONDS) as client:
        return client.structured(
            prompt=TURN,
            system=instructions,
            system_tail=tail,
            schema=GoogleSearchDraft,
            prompt_name=PROMPT,
            prompt_version=version,
        )


def fitted(draft: GoogleSearchDraft) -> dict[str, Any]:
    """The AI's answer with every text Google would refuse left out."""
    return {
        "keywords": [
            {"text": text, "match": "PHRASE"}
            for text in _unique(draft.keywords, width=KEYWORD_MAX)[:GOOGLE_KEYWORDS_MAX]
        ],
        "negative_keywords": _unique(draft.negative_keywords, width=KEYWORD_MAX)[
            :GOOGLE_NEGATIVES_MAX
        ],
        "headlines": _unique(draft.headlines, width=DRAFT_HEADLINE_MAX)[:15],
        "descriptions": _unique(draft.descriptions, width=DRAFT_DESCRIPTION_MAX)[:4],
        "path1": draft.path1.strip()[:DRAFT_PATH_MAX],
        "path2": draft.path2.strip()[:DRAFT_PATH_MAX] if draft.path1.strip() else "",
    }


def _unique(rows: list[str], *, width: int) -> list[str]:
    kept: list[str] = []
    for row in rows:
        text = " ".join(row.split())
        if (
            text
            and len(text) <= width
            and text.casefold() not in {i.casefold() for i in kept}
        ):
            kept.append(text)
    return kept


def _volumes(
    launch: GoogleLaunch,
    *,
    token: str,
    keywords: list[str],
    places: list[dict[str, Any]],
    profile: Business,
) -> dict[str, int]:
    if not keywords:
        return {}
    try:
        with AdsClient(token=token) as client:
            customer = launch.ad_account.external_id
            targets = google_targets(
                places=places,
                customer_id=customer,
                client=client,
                country_code=profile.country_code,
            )
            rows = keyword_volumes(client, customer, keywords=keywords, places=targets)
    except GoogleAdsError as exc:
        logger.info(
            "keyword figures for %s failed: %s", launch.id, translate_error(exc)
        )
        return {}
    return {row.text: row.monthly_searches for row in rows}


def _finish(
    db: Session,
    launch: GoogleLaunch,
    *,
    run: str,
    places: list[dict[str, Any]],
    words: dict[str, Any] | None,
    volumes: dict[str, int],
) -> str:
    row = _locked(db, owner=launch.owner, launch_id=launch.id)
    if not _is_this_run(row, run=run):
        db.rollback()
        return "superseded"
    row.places = places
    if words:
        for field, value in words.items():
            setattr(row, field, value)
        row.ai_written_at = utcnow()
    row.volumes = volumes
    row.status = str(LaunchStatus.READY)
    row.finished_at = utcnow()
    db.commit()
    return "ready"


def _fail(db: Session, launch: GoogleLaunch, *, run: str, code: str) -> str:
    row = _locked(db, owner=launch.owner, launch_id=launch.id)
    if not _is_this_run(row, run=run):
        db.rollback()
        return "superseded"
    row.status = str(LaunchStatus.FAILED)
    row.error_code = code
    row.finished_at = utcnow()
    db.commit()
    return code


def _is_this_run(launch: GoogleLaunch, *, run: str) -> bool:
    return (
        launch.status == LaunchStatus.BUILDING
        and launch.started_at is not None
        and launch.started_at.isoformat() == run
    )


# -- the creation ----------------------------------------------------------------------


def request_google_creation(
    db: Session, *, user: User, launch: GoogleLaunch
) -> GoogleLaunch:
    """The «Yaratish» press: checked, marked, handed to a worker. Commits."""
    from app.modules.ads.tasks import create_google_campaign_task
    from app.modules.billing.services import require_live_subscription

    _require_google(db, user)
    require_live_subscription(db, owner=user)
    launch = _locked(db, owner=user, launch_id=launch.id)
    if (
        launch.status not in (LaunchStatus.READY, LaunchStatus.FAILED)
        or not launch.ai_written_at
    ):
        raise GoogleLaunchNotReady
    launch.status = str(LaunchStatus.CREATING)
    launch.started_at = utcnow()
    launch.error_code = ""
    launch.error_message = ""
    launch_id, run = str(launch.id), launch.started_at.isoformat()
    on_commit(db, lambda: create_google_campaign_task.delay(launch_id, run))
    db.commit()
    return launch


def create_google_campaign(db: Session, *, launch_id: UUID | str, run: str) -> str:
    """The worker half. Returns a word for the task log."""
    launch = db.get(GoogleLaunch, UUID(str(launch_id)))
    if launch is None:
        return "gone"
    if launch.status != LaunchStatus.CREATING or (
        launch.started_at is None or launch.started_at.isoformat() != run
    ):
        return "superseded"
    dry_run = bool(settings.ads_dry_run or settings.google_ads_dry_run)
    log = _open_log(db, launch, dry_run=dry_run)
    try:
        created = _create(db, launch, dry_run=dry_run)
    except (ConnectionUnusable, AuthFailed, PermissionDenied) as exc:
        return _failed(db, launch, log=log, kind=REFUSED_CONNECTION, exc=exc)
    except ProviderError as exc:
        return _failed(db, launch, log=log, kind=_kind(exc), exc=exc)
    except ValidationError as exc:
        return _failed(db, launch, log=log, kind=REFUSED_GOOGLE, exc=exc)
    return _succeeded(db, launch, log=log, created=created, dry_run=dry_run)


def campaign_name(*, launch: GoogleLaunch, business_name: str) -> str:
    """Unique in the account, as Google requires, and readable in its screens."""
    goal = GoogleGoal(launch.goal).label if launch.goal else ""
    stamp = timezone.localtime(utcnow()).strftime("%Y-%m-%d %H:%M")
    return " · ".join(part for part in (business_name, str(goal), stamp) if part)


def _create(db: Session, launch: GoogleLaunch, *, dry_run: bool) -> dict[str, Any]:
    profile = _profile(db, launch)
    country = profile.country_code if profile is not None else ""
    name = campaign_name(launch=launch, business_name=profile.name if profile else "")
    token = token_for(ad_account=launch.ad_account)
    customer = launch.ad_account.external_id
    try:
        with AdsClient(token=token) as client:
            targets = google_targets(
                places=list(launch.places or []),
                customer_id=customer,
                client=client,
                country_code=country,
            )
            spec = _spec(launch, name=name, places=targets, country=country)
            created = create_search_campaign(
                client, customer, spec, validate_only=dry_run
            )
    except GoogleAdsError as exc:
        raise translate_error(exc) from exc
    return {"name": name} | created.model_dump(exclude={"validated_only"})


def _spec(
    launch: GoogleLaunch, *, name: str, places: list[str], country: str
) -> SearchCampaignSpec:
    calls = launch.goal == GoogleGoal.CALLS and bool(launch.phone)
    return SearchCampaignSpec(
        name=name,
        daily_budget_minor=int(launch.daily_budget_minor or 0),
        currency=launch.currency,
        final_url=launch.final_url,
        headlines=tuple(launch.headlines or ()),
        descriptions=tuple(launch.descriptions or ()),
        path1=launch.path1,
        path2=launch.path2,
        keywords=tuple(
            KeywordSpec(text=row["text"], match=row.get("match", "PHRASE"))
            for row in launch.keywords or []
        ),
        negative_keywords=tuple(launch.negative_keywords or ()),
        places=tuple(places),
        phone=launch.phone if calls else "",
        phone_country=country if calls else "",
    )


def _kind(exc: ProviderError) -> str:
    code = (exc.code or "").upper()
    if isinstance(exc, (RateLimited, TemporaryFailure)):
        return REFUSED_BUSY
    if "PHONE" in code or code.startswith("CALL_"):
        return REFUSED_PHONE
    if "POLICY" in code or "PROHIBITED" in code:
        return REFUSED_POLICY
    return REFUSED_GOOGLE


def _open_log(db: Session, launch: GoogleLaunch, *, dry_run: bool) -> ActionLog:
    started = launch.started_at or utcnow()
    log = ActionLog(
        owner_id=launch.owner_id,
        actor_type=str(ActorType.USER),
        actor_id=launch.owner_id,
        action=str(ActionType.CREATE_CAMPAIGN),
        target_provider=launch.ad_account.provider,
        target_level="campaign",
        target_external_id="",
        request_payload={
            "goal": launch.goal,
            "final_url": launch.final_url,
            "daily_budget_minor": launch.daily_budget_minor,
            "currency": launch.currency,
            "keywords": len(launch.keywords or []),
            "places": [row.get("key") for row in launch.places or []],
        },
        previous_state={},
        status=str(ActionStatus.PENDING),
        dry_run=dry_run,
        idempotency_key=f"{LOG_PREFIX}:{launch.id}:{int(started.timestamp() * 1000)}",
    )
    db.add(log)
    db.commit()
    return log


def _succeeded(
    db: Session,
    launch: GoogleLaunch,
    *,
    log: ActionLog,
    created: dict[str, Any],
    dry_run: bool,
) -> str:
    from app.modules.ads.tasks import sync_ad_account_task
    from app.modules.audit.services import emit

    now = utcnow()
    launch.status = str(LaunchStatus.CREATED)
    launch.created_refs = {key: value for key, value in created.items() if value}
    launch.campaign_name = str(created.get("name", ""))
    launch.dry_run = dry_run
    launch.finished_at = now
    log.status = str(ActionStatus.APPLIED)
    log.target_external_id = str(created.get("campaign", ""))
    log.result_payload = dict(launch.created_refs)
    log.applied_at = now
    emit(
        db,
        owner_id=launch.owner_id,
        name=EventName.CAMPAIGN_CREATED,
        aggregate_type=KEY_PREFIX,
        aggregate_id=launch.id,
        payload={
            "provider": launch.ad_account.provider,
            "refs": dict(launch.created_refs),
            "dry_run": dry_run,
            "daily_budget_minor": launch.daily_budget_minor,
            "currency": launch.currency,
        },
    )
    if not dry_run:
        account_id = str(launch.ad_account_id)
        on_commit(db, lambda: sync_ad_account_task.delay(account_id))
    db.commit()
    return "rehearsed" if dry_run else "created"


def _failed(
    db: Session, launch: GoogleLaunch, *, log: ActionLog, kind: str, exc: Exception
) -> str:
    code = str(getattr(exc, "code", "") or type(exc).__name__)
    logger.info("google campaign for %s refused (%s): %s", launch.id, code, exc)
    launch.status = str(LaunchStatus.FAILED)
    launch.error_code = kind
    launch.error_message = str(exc)[:2000]
    launch.finished_at = utcnow()
    log.status = str(ActionStatus.FAILED)
    log.error_code = code[:32]
    log.error_message = str(exc)
    db.commit()
    return kind
