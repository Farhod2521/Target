"""Turn an approved proposal into a real, paused campaign, bring it into the
mirror, and switch it on without a second press."""

import logging
from collections.abc import Sequence
from typing import Any, Final
from uuid import UUID

from adskit import registry
from adskit.errors import AccountActionRequired, ProviderError, TargetingOptionRetired
from adskit.refs import ExternalRef, Level, ProviderName
from metaads.specs import is_external
from sqlalchemy import update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.common import hooks
from app.common.cache import cache
from app.common.config import settings
from app.common.db import on_commit, utcnow
from app.common.exceptions import DomainError
from app.common.money import format_minor, provider_money
from app.modules.ads import draft as draft_field
from app.modules.ads import geo as geo_field
from app.modules.ads.constants import (
    AUTO_START_RESYNC_TRY,
    AUTO_START_WAIT_SECONDS,
    LAUNCH_PROGRESS,
    LAUNCH_RELATED_TYPE,
    MAX_AUTO_START_TRIES,
    ROLLBACK_ORDER,
    STARTABLE,
    SYNC_LOCK_SECONDS,
    DraftSection,
    LaunchStatus,
    LaunchStep,
    ManagedLevel,
)
from app.modules.ads.exceptions import (
    AdAccountPaymentDue,
    AdAccountUnavailable,
    AudienceEmpty,
    AudienceNotAllowed,
    AudienceWaiting,
    BudgetBelowMinimum,
    CallNumberMissing,
    ChatChannelUnavailable,
    ConnectionUnusable,
    CopyMissing,
    DestinationLinkMissing,
    DestinationLinkUnusable,
    EndDateUnusable,
    GroupBudgetBelowMinimum,
    IdentityHoldPending,
    InstagramProfileUnavailable,
    LaunchNotReady,
    LaunchUnchanged,
    NoAdAccount,
    NoConfirmedInterest,
    NoPage,
    NothingToStart,
    NotLaunchable,
    PageRoleMissing,
    PageTermsNotAccepted,
    PermissionsMissing,
    PlacesNotFound,
)
from app.modules.ads.exceptions import ConversionSourceMissing as NoPixel
from app.modules.ads.exceptions import CostCapTooLow as CapTooLow
from app.modules.ads.models import CampaignLaunch
from app.modules.ads.rows import fresh
from app.modules.ads.selectors.ad_groups import underfunded
from app.modules.ads.selectors.attempts import (
    SENT_KEY,
    attempt_fingerprint,
    reaches_nobody,
    repeats_refusal,
)
from app.modules.ads.selectors.copy_notes import missing_copy
from app.modules.ads.selectors.launched import (
    launch_is_mirrored,
    launched_targets,
    still_starting,
)
from app.modules.ads.selectors.launches import stranded_refs
from app.modules.ads.selectors.owned import owner_paused_campaign
from app.modules.ads.selectors.schedule import runs_long_enough
from app.modules.ads.services.access import (
    launch_account_and_token,
    launch_page_and_token,
    token_for,
)
from app.modules.ads.services.launch_media import check_media
from app.modules.ads.services.preflight import (
    attempt_number,
    check_permissions,
    close_log,
    fail_log,
    look_at_site,
    open_log,
    preflight,
)
from app.modules.ads.services.targeting import build_for, rebuild_targeting
from app.modules.ads.trace import (
    NoTrace,
    record_outcome,
    record_preparation,
    tracing_launch,
)
from app.modules.audit.constants import EventName
from app.modules.businesses.models import Business
from app.modules.integrations.models import AdAccount, PageAccount
from core.targeting import BuiltTargeting, daily_floor
from core.targeting.exceptions import (
    AudienceUnusable,
    LookalikeNotAllowed,
    NoInterestsChosen,
    TargetingError,
)
from core.targeting.exceptions import ConversionSourceMissing as SourceMissing
from core.targeting.exceptions import CostCapTooLow as CapRefused
from core.targeting.exceptions import DestinationLinkMissing as SiteMissing
from core.targeting.exceptions import PhoneNumberMissing as PhoneMissing
from core.targeting.gate import validate_launchable

logger = logging.getLogger(__name__)

QUIET_RESULTS = frozenset({"created", "gone", "not_creating"})
RUN_LOCK_PREFIX: Final = "launch-run:"
RUN_LOCK_SECONDS: Final = 30 * 60
LAUNCH_FAILED_HOOK: Final = "ads.launch_failed"
WAITING: Final = "waiting"
FAILURE_CODES: Final[dict[str, str]] = {
    "AuthFailed": "reconnect",
    "PermissionDenied": "reconnect",
    "RateLimited": "rate_limited",
    "TemporaryFailure": "temporary",
    "NotFound": "refused",
    "InvalidRequest": "refused",
    "LocationNotRecognized": "location_invalid",
    "LocationsOverlap": "location_overlap",
    "MediaTooLarge": "media_too_large",
    "LaunchMediaTooLarge": "media_too_large",
    "TermsNotAccepted": "page_terms",
    "PermissionsMissing": "permissions",
    "AdAccountUnavailable": "account_disabled",
    "PaymentMethodMissing": "payment_missing",
    "BudgetTooLow": "budget_low",
    "BidStrategyRefused": "bid_refused",
    "AccountActionRequired": "account_action",
    "TargetingOptionRetired": "interest_retired",
    "LeadFormPrivacyMissing": "form_privacy_missing",
    "LaunchMediaMissing": "media_missing",
    "LaunchMediaForeign": "media_foreign",
    "LaunchMediaUnsupported": "media_unsupported",
    "VideoNotReady": "video_not_ready",
}
_PORT_LEVELS: dict[str, Level] = {
    ManagedLevel.CAMPAIGN: "campaign",
    ManagedLevel.ADSET: "adset",
    ManagedLevel.AD: "ad",
}


# -- the press -------------------------------------------------------------------------


def request_creation(
    db: Session, *, launch: CampaignLaunch, business: Business
) -> None:
    """Check what can be checked here, mark the row, and queue the work. Commits."""
    from app.modules.ads.services.manage import check_campaign_allowance
    from app.modules.ads.tasks import create_campaign_task
    from app.modules.billing.services import require_live_subscription

    require_live_subscription(db, owner=launch.owner)
    check_campaign_allowance(db, owner=launch.owner)
    if (
        launch.status not in STARTABLE
        or stranded_refs(db, launch)
        or not launch.targeting
    ):
        raise LaunchNotReady
    account, _token = launch_account_and_token(db, launch=launch)
    page, _page_token = launch_page_and_token(db, launch=launch)
    check_permissions(db, owner=launch.owner)
    if account.connection.action_required_at is not None:
        raise IdentityHoldPending
    rebuild_targeting(db, launch=launch, business=business)
    unresolved = geo_field.unresolved(
        draft_field.chosen(launch.draft, DraftSection.AUDIENCE)
    )
    if unresolved:
        raise PlacesNotFound(unresolved)
    built = build_for(db, launch=launch, business=business)
    check_media(db, launch, page=page, built=built)
    if built.opens_profile and not page.can_open_profile:
        raise InstagramProfileUnavailable
    if missing_copy(db, launch=launch):
        raise CopyMissing
    _check_budget(db, launch=launch, account=account, built=built)
    if reaches_nobody(launch=launch):
        raise AudienceEmpty
    if repeats_refusal(
        db, launch=launch, business=business, preset_version=launch.preset_version
    ):
        raise LaunchUnchanged
    if built.needs_link and built.link_url and not is_external(built.link_url):
        raise DestinationLinkUnusable
    _validate(launch=launch, built=built)
    if not runs_long_enough(launch=launch, now=utcnow()):
        raise EndDateUnusable
    claimed = db.execute(
        update(CampaignLaunch)
        .where(CampaignLaunch.id == launch.id, CampaignLaunch.status.in_(STARTABLE))
        .values(status=str(LaunchStatus.CREATING))
        .execution_options(synchronize_session=False)
    ).rowcount
    if not claimed:
        raise LaunchNotReady
    draft_field.drop_form_variants(fresh(launch, "draft"))
    launch.status = str(LaunchStatus.CREATING)
    launch.step = str(LaunchStep.VALIDATE)
    launch.progress = LAUNCH_PROGRESS[LaunchStep.VALIDATE]
    launch.started_at = utcnow()
    launch.finished_at = None
    launch.error_code = ""
    launch.error_message = ""
    launch.error_detail = {}
    launch_id = str(launch.id)
    on_commit(db, lambda: create_campaign_task.delay(launch_id))
    db.commit()


def _validate(*, launch: CampaignLaunch, built: BuiltTargeting) -> None:
    try:
        validate_launchable(built)
    except SiteMissing as exc:
        raise DestinationLinkMissing from exc
    except PhoneMissing as exc:
        raise CallNumberMissing from exc
    except NoInterestsChosen as exc:
        raise NoConfirmedInterest from exc
    except LookalikeNotAllowed as exc:
        raise AudienceNotAllowed(exc.labels) from exc
    except AudienceUnusable as exc:
        raise AudienceWaiting(exc.labels) from exc
    except SourceMissing as exc:
        raise NoPixel from exc
    except CapRefused as exc:
        places = provider_money(provider=launch.provider).decimal_places(built.currency)
        raise CapTooLow(
            needed=format_minor(
                amount_minor=exc.needed_minor, currency=built.currency, places=places
            )
        ) from exc
    except TargetingError as exc:
        logger.warning("launch %s refused by the gate: %s", launch.id, exc)
        raise NotLaunchable from exc


def _check_budget(
    db: Session, *, launch: CampaignLaunch, account: AdAccount, built: BuiltTargeting
) -> None:
    least = daily_floor(
        account_minor=account.min_daily_budget_minor,
        optimization_goal=built.optimization_goal,
    )
    places = provider_money(provider=launch.provider).decimal_places(launch.currency)
    if least and int(launch.daily_budget_minor or 0) < least:
        raise BudgetBelowMinimum(
            minimum_minor=least, currency=launch.currency, places=places
        )
    if underfunded(db, launch=launch, floor_minor=least) is not None:
        raise GroupBudgetBelowMinimum(
            minimum_minor=least, currency=launch.currency, places=places
        )


# -- the worker ------------------------------------------------------------------------


def create_campaign(db: Session, *, launch_id: UUID | str) -> str:
    """The whole sequence, run by one worker at a time."""
    key = f"{RUN_LOCK_PREFIX}{launch_id}"
    if not cache.add(key, "1", RUN_LOCK_SECONDS):
        return "already_running"
    try:
        result = _create(db, launch_id=launch_id)
    finally:
        cache.delete(key)
    if result not in QUIET_RESULTS:
        hooks.fire(LAUNCH_FAILED_HOOK, launch_id=str(launch_id))
    return result


def _create(db: Session, *, launch_id: UUID | str) -> str:
    from app.modules.businesses.selectors import business_for_page

    launch = db.get(CampaignLaunch, UUID(str(launch_id)))
    if launch is None:
        return "gone"
    if launch.status != LaunchStatus.CREATING:
        return "not_creating"
    business = business_for_page(db, owner=launch.owner, page=launch.page)
    if business is None or not business.category:
        return _fail(db, launch, code="profile_incomplete")
    try:
        preflight(db, launch=launch)
        account, token = launch_account_and_token(db, launch=launch)
        page, page_token = launch_page_and_token(db, launch=launch)
    except (NoAdAccount, NoPage, ConnectionUnusable) as exc:
        return _fail(db, launch, code="no_provider", message=str(exc))
    except PermissionsMissing as exc:
        return _fail(
            db, launch, code="permissions", message=f"missing: {', '.join(exc.missing)}"
        )
    except AdAccountPaymentDue:
        return _fail(
            db, launch, code="payment_due", message="ad account owes a payment"
        )
    except AdAccountUnavailable:
        return _fail(
            db, launch, code="account_disabled", message="ad account not usable"
        )
    except PageRoleMissing as exc:
        return _fail(
            db, launch, code="page_role", message=f"page tasks: {', '.join(exc.tasks)}"
        )
    except PageTermsNotAccepted:
        return _fail(db, launch, code="page_terms", message="lead terms not accepted")
    except ChatChannelUnavailable:
        return _fail(
            db, launch, code="chat_channel", message="page has no instagram account"
        )
    except InstagramProfileUnavailable:
        return _fail(
            db,
            launch,
            code="instagram_profile",
            message="page has no instagram profile to open",
        )
    built = build_for(db, launch=launch, business=business)
    if built.needs_link and built.link_url and not is_external(built.link_url):
        return _fail(
            db, launch, code="site_unusable", message="link points inside Meta"
        )
    if built.needs_link and built.link_url:
        from app.modules.ads.services.advanced import without_blind_goal

        site = look_at_site(url=built.link_url)
        if site.is_down:
            return _fail(
                db,
                launch,
                code="site_unreachable",
                message=f"{site.outcome} {site.status_code or ''}".strip(),
                detail={"site": site.outcome},
            )
        built = without_blind_goal(db, launch=launch, built=built, site=site)
    try:
        validate_launchable(built)
    except SiteMissing as exc:
        return _fail(db, launch, code="site_missing", message=str(exc))
    except PhoneMissing as exc:
        return _fail(db, launch, code="phone_missing", message=str(exc))
    except TargetingError as exc:
        return _fail(db, launch, code="not_launchable", message=str(exc))
    dry_run = bool(settings.ads_dry_run)
    sent = attempt_fingerprint(
        db, launch=launch, business=business, preset_version=built.preset_version
    )
    attempt = attempt_number(db, launch)
    log = open_log(db, launch=launch, account=account, built=built, dry_run=dry_run)
    with tracing_launch(str(launch.id)) as trace:
        record_preparation(
            db,
            trace,
            launch=launch,
            business=business,
            built=built,
            account=account,
            page=page,
        )
        result = _run(
            db,
            launch=launch,
            business=business,
            account=account,
            page=page,
            built=built,
            token=token,
            page_token=page_token,
            dry_run=dry_run,
            attempt=attempt,
            log=log,
            trace=trace,
            sent=sent,
        )
        db.refresh(launch)
        record_outcome(trace, launch=launch, result=result)
    return result


def _run(
    db: Session,
    *,
    launch: CampaignLaunch,
    business: Business,
    account: AdAccount,
    page: PageAccount,
    built: BuiltTargeting,
    token: str,
    page_token: str,
    dry_run: bool,
    attempt: int,
    log: str,
    trace: Any,
    sent: str,
) -> str:
    from app.modules.ads.services.sequence import run_sequence

    try:
        run_sequence(
            db,
            launch=launch,
            business=business,
            account=account,
            page=page,
            built=built,
            token=token,
            page_token=page_token,
            dry_run=dry_run,
            attempt=attempt,
            trace=trace,
        )
    except (ProviderError, DomainError) as exc:
        db.rollback()
        _repair(db, launch=launch, business=business, exc=exc)
        _note_hold(db, account=account, exc=exc)
        return _undo(
            db,
            launch=launch,
            log_id=log,
            token=token,
            page_token=page_token,
            dry_run=dry_run,
            code=_code_for(exc),
            message=str(exc),
            detail={**_detail_for(exc), SENT_KEY: sent},
            trace=trace,
        )
    except Exception as exc:
        db.rollback()
        logger.exception("launch %s failed unexpectedly", launch.id)
        return _undo(
            db,
            launch=launch,
            log_id=log,
            token=token,
            page_token=page_token,
            dry_run=dry_run,
            code="unknown",
            message=str(exc),
            trace=trace,
        )
    _succeed(db, launch=launch, log_id=log, account=account, dry_run=dry_run)
    return "created"


def _succeed(
    db: Session,
    *,
    launch: CampaignLaunch,
    log_id: str,
    account: AdAccount,
    dry_run: bool,
) -> None:
    from app.modules.audit.services import emit
    from app.modules.integrations.services.connect import clear_action_required

    launch.status = str(LaunchStatus.CREATED)
    launch.step = str(LaunchStep.VERIFY)
    launch.progress = 100
    launch.finished_at = utcnow()
    db.flush()
    close_log(db, log_id=log_id, launch=launch)
    emit(
        db,
        owner_id=launch.owner_id,
        name=EventName.CAMPAIGN_CREATED,
        aggregate_type=LAUNCH_RELATED_TYPE,
        aggregate_id=launch.id,
        payload={
            "provider": launch.provider,
            "refs": dict(launch.created_refs or {}),
            "dry_run": dry_run,
            "daily_budget_minor": launch.daily_budget_minor,
            "currency": launch.currency,
        },
    )
    if not dry_run:
        clear_action_required(db, connection=account.connection)
        _queue_follow_ups(db, launch=launch)
    db.commit()


def _queue_follow_ups(db: Session, *, launch: CampaignLaunch) -> None:
    from app.modules.ads.tasks import auto_start_delivery_task, mirror_launch_task

    launch_id = str(launch.id)
    on_commit(db, lambda: mirror_launch_task.delay(launch_id))
    on_commit(
        db,
        lambda: auto_start_delivery_task.apply_async(
            args=[launch_id], countdown=AUTO_START_WAIT_SECONDS
        ),
    )


def _undo(
    db: Session,
    *,
    launch: CampaignLaunch,
    log_id: str,
    token: str,
    page_token: str,
    dry_run: bool,
    code: str,
    message: str,
    detail: dict[str, Any] | None = None,
    trace: Any = None,
) -> str:
    """Write the failure down, then delete whatever got created."""
    from app.modules.ads.services.rollback import rollback_launch

    watch = trace if trace is not None else NoTrace()
    watch.step(12, "Rollback")
    watch.inputs("sabab", {"code": code, "message": message})
    fail_log(db, log_id=log_id, code=code, message=message)
    db.refresh(launch)
    _fail(db, launch, code=code, message=message, detail=detail)
    if not launch.created_refs:
        watch.note("Provayderda hech narsa yaratilmagan - o'chiradigan narsa yo'q.")
        return code
    before = dict(launch.created_refs)
    removed = rollback_launch(
        db, launch=launch, token=token, page_token=page_token, dry_run=dry_run
    )
    watch.db(
        "CampaignLaunch", {"created_refs": (before, dict(launch.created_refs or {}))}
    )
    watch.decision(
        "o'chirildi",
        {
            "tartib": list(ROLLBACK_ORDER),
            "soni": removed,
            "qolgani": launch.created_refs,
        },
    )
    return "rolled_back"


def _repair(
    db: Session, *, launch: CampaignLaunch, business: Business, exc: Exception
) -> None:
    from app.modules.ads.services.rollback import retire_options

    if not isinstance(exc, TargetingOptionRetired) or not exc.retired:
        return
    try:
        retire_options(db, launch=launch, business=business, retired=exc.retired)
    except (DomainError, SQLAlchemyError):
        db.rollback()
        logger.exception("could not retire options on %s", launch.id)


def _note_hold(db: Session, *, account: AdAccount, exc: Exception) -> None:
    from app.modules.integrations.services.connect import note_action_required

    if not isinstance(exc, AccountActionRequired):
        return
    try:
        note_action_required(db, connection=account.connection)
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        logger.exception("could not note the hold on %s", account.id)


def _detail_for(exc: Exception) -> dict[str, Any]:
    """The provider's own words for the advertiser, if it sent any."""
    detail: dict[str, Any] = {}
    file_name = str(getattr(exc, "file_name", "") or "").strip()
    if file_name:
        detail["file"] = file_name
    title = str(getattr(exc, "user_title", "") or "").strip()
    sentence = str(getattr(exc, "user_message", "") or "").strip()
    code = str(getattr(exc, "code", "") or "").strip()
    if not (title or sentence):
        return detail
    detail.update({"title": title, "message": sentence, "code": code})
    retired = getattr(exc, "retired", ())
    if retired:
        detail["retired"] = [option.model_dump() for option in retired]
    return detail


def _code_for(exc: Exception) -> str:
    return FAILURE_CODES.get(type(exc).__name__, "unknown")


def _fail(
    db: Session,
    launch: CampaignLaunch,
    *,
    code: str,
    message: str = "",
    detail: dict[str, Any] | None = None,
) -> str:
    """Move the row out of CREATING and say why, in a code and in words."""
    launch.status = str(LaunchStatus.FAILED)
    launch.progress = 0
    launch.error_code = code[:32]
    launch.error_message = message
    launch.error_detail = detail or {}
    launch.finished_at = utcnow()
    db.commit()
    logger.warning("launch %s could not be created: %s - %s", launch.id, code, message)
    return code


# -- after it exists -------------------------------------------------------------------


def mirror_launch(db: Session, *, launch_id: UUID | str) -> str:
    """Read this launch's objects by id and write them. Returns a word."""
    from app.modules.ads.services.mirror import (
        mirror_lock_key,
        write_ads,
        write_adsets,
        write_campaigns,
        write_creatives,
    )

    launch = db.get(CampaignLaunch, UUID(str(launch_id)))
    if launch is None or launch.ad_account is None:
        return "gone"
    targets = launched_targets(launch=launch)
    if not targets:
        return "rehearsal"
    account = launch.ad_account
    key = mirror_lock_key(account)
    if not cache.add(key, "1", SYNC_LOCK_SECONDS):
        return "busy"
    try:
        provider = ProviderName(account.provider)
        refs = [
            ExternalRef(provider=provider, level=_PORT_LEVELS[level], id=external_id)
            for level, external_id in targets
        ]
        try:
            token = token_for(ad_account=account)
            objects = registry.get(account.provider).campaigns.read_objects(
                account=ExternalRef(
                    provider=provider, level="account", id=account.external_id
                ),
                refs=refs,
                token=token,
            )
        except ConnectionUnusable:
            return "unusable"
        except ProviderError as exc:
            logger.warning("launch %s could not be read back: %s", launch.id, exc)
            return "failed"
        now = utcnow()
        refused: list[str] = []
        campaigns = write_campaigns(
            db,
            ad_account=account,
            campaigns=objects.campaigns,
            now=now,
            refused=refused,
        )
        adsets = write_adsets(
            db,
            ad_account=account,
            adsets=objects.adsets,
            campaigns=campaigns,
            now=now,
            refused=refused,
        )
        write_ads(
            db,
            ad_account=account,
            ads=objects.ads,
            adsets=adsets,
            now=now,
            refused=refused,
        )
        write_creatives(
            db, ad_account=account, ads=objects.ads, now=now, refused=refused
        )
        db.commit()
    finally:
        cache.delete(key)
    if refused:
        logger.error(
            "launch rows refused by the database",
            extra={"launch": str(launch.id), "rows": refused},
        )
    return "stored"


def auto_start_delivery(db: Session, *, launch_id: UUID | str, tries: int = 0) -> str:
    """Ask this launch's objects to deliver. Returns a word for the log."""
    from app.modules.ads.services.manage import BY_SYSTEM, start_delivery

    launch = db.get(CampaignLaunch, UUID(str(launch_id)))
    if launch is None:
        return "gone"
    if launch.status != LaunchStatus.CREATED:
        return "not_created"
    if launch.delivery_started_at or launch.delivery_note:
        return "settled"
    targets = launched_targets(launch=launch)
    if not targets:
        return "rehearsal"
    now = utcnow()
    if not launch_is_mirrored(db, owner=launch.owner, launch=launch):
        if tries < MAX_AUTO_START_TRIES and still_starting(launch=launch, now=now):
            if tries and tries % AUTO_START_RESYNC_TRY == 0:
                _ask_for_the_mirror(db, launch=launch)
            return WAITING
        return _too_late(db, launch=launch)
    if not still_starting(launch=launch, now=now):
        return _too_late(db, launch=launch)
    held = owner_paused_campaign(db, launch=launch)
    if held:
        targets = [
            (level, ref) for level, ref in targets if level != ManagedLevel.CAMPAIGN
        ]
    try:
        outcome = start_delivery(
            db, user=launch.owner, targets=targets, origin=BY_SYSTEM
        )
    except NothingToStart:
        db.rollback()
        if held:
            record_delivery(db, launch=launch, refused=[held_note()])
            return "held"
        record_delivery(db, launch=launch)
        return "already"
    except DomainError as exc:
        db.rollback()
        logger.info("launch %s could not start itself: %s", launch.id, exc)
        record_delivery(db, launch=launch, refused=[str(exc)])
        return "refused"
    if outcome.refused or held:
        refused = list(outcome.refused) + ([held_note()] if held else [])
        record_delivery(db, launch=launch, refused=refused)
        return "held" if held and not outcome.refused else "refused"
    record_delivery(db, launch=launch)
    return "started"


def held_note() -> str:
    return (
        "Kampaniya Ads Manager'da to'xtatilgan, shuning uchun yoqilmadi. «Yoqish» bosilsa, "
        "kampaniya yoqiladi va undagi boshqa reklamalar ham ishlay boshlaydi."
    )


def record_delivery(
    db: Session, *, launch: CampaignLaunch, refused: Sequence[str] = ()
) -> None:
    """Write down how the switch-on went, for the screen that draws it. Commits."""
    sentences = [line for line in refused if line]
    launch.delivery_note = " ".join(sentences)
    launch.delivery_started_at = None if sentences else utcnow()
    db.commit()


def _too_late(db: Session, *, launch: CampaignLaunch) -> str:
    record_delivery(db, launch=launch, refused=["Meta hozir javob bermadi."])
    return "late"


def _ask_for_the_mirror(db: Session, *, launch: CampaignLaunch) -> None:
    from app.modules.ads.tasks import mirror_launch_task

    launch_id = str(launch.id)
    logger.info("launch %s is not mirrored yet, reading it again", launch_id)
    mirror_launch_task.delay(launch_id)
