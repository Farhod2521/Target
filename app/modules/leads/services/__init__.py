"""Writes of leads: webhook deliveries, imports, sweeps, verdicts, erasure."""

import logging
import uuid
from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Final

from adskit import (
    ExternalRef,
    LeadDTO,
    LeadEventDTO,
    LeadSourcePort,
    MinorUnits,
    registry,
)
from adskit.dto import LeadFormDTO
from adskit.errors import AuthFailed, PermissionDenied, ProviderError, ResultTruncated
from metaads import PROVIDER as META
from metaads.webhooks import LeadNotice
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.common import throttle
from app.common.cache import cache
from app.common.config import settings
from app.common.crypto import decrypt
from app.common.db import on_commit, utcnow
from app.common.deletion import delete_rows
from app.common.exceptions import DecryptionFailed, DomainError
from app.common.trace import NoTrace
from app.modules.accounts.models import User
from app.modules.audit.constants import ActionStatus, ActionType, ActorType, EventName
from app.modules.audit.models import ActionLog
from app.modules.audit.services import emit
from app.modules.integrations.constants import (
    NIGHT_LEADS_HOUR,
    USABLE_CONNECTION_STATUSES,
    ConnectionStatus,
)
from app.modules.integrations.models import AdAccount, PageAccount, ProviderConnection
from app.modules.leads.constants import (
    ANONYMIZE_LIMIT,
    FAILED_RETRY_ATTEMPTS,
    FINAL_SWEEP_KEY,
    FINAL_SWEEP_TTL_SECONDS,
    FORMS_REFRESH_SECONDS,
    LEAD_RETENTION_DAYS,
    ORPHAN_REPORT_HOURS,
    ORPHAN_REPORT_PAGES,
    PURGE_BATCH,
    RECONCILE_LOOKBACK_DAYS,
    RECONCILE_OVERLAP_HOURS,
    RECOVERY_BATCH,
    RECOVERY_COOLDOWN_SECONDS,
    UNIMPORTED_REPORT_HOURS,
    UNIMPORTED_REPORT_SAMPLE,
    UNIMPORTED_WINDOW_HOURS,
    UNSIGNED_EVENT_RETENTION_DAYS,
    VERDICTS_PER_RUN,
    LeadFormStatus,
    OutcomeSource,
    OutcomeStatus,
    RawEventStatus,
)
from app.modules.leads.exceptions import (
    FormsAskedRecently,
    NoPageConnected,
    NothingToRecover,
    RecoveryImpossible,
    RecoveryNeedsConnection,
    RecoveryTooSoon,
    UnknownLead,
)
from app.modules.leads.models import Lead, LeadForm, LeadOutcome, RawLeadEvent
from app.modules.leads.selectors import (
    delivery_trouble,
    held_leadgen_ids,
    holder_of_advert,
    leads_matching_email,
    orphan_pages,
    owners_holding_leads,
    owners_with_verdicts,
    page_holders,
    recoverable_deliveries,
    reporting_dataset,
    retired_unread_forms,
    retryable_deliveries,
    shown_page,
    unerased_count,
    unerased_lead_ids,
    unimported_deliveries,
    unread_deliveries,
    verdicts_for,
)
from app.modules.leads.trace import (
    LeadTrace,
    record_fetch,
    record_mapping,
    record_route,
    record_row,
    tracing_lead,
)
from app.modules.leads.trace import record_delivery as trace_delivery
from app.modules.leads.trace import record_outcome as trace_outcome
from core.leads import SETTLE_MINUTES, Verdict, due, event_key, expired, normalise

logger = logging.getLogger(__name__)
LEAD_LEVEL: Final = "lead"
FORM_LEVEL: Final = "form"
PAGE_LEVEL: Final = "page"
DATASET_LEVEL: Final = "dataset"
CREATED: Final = "created"
DUPLICATE: Final = "duplicate"
DISCONNECTED: Final = "disconnected"
UNPLACED: Final = "unplaced"
RETENTION_REASON: Final = "retention"
REFRESH_BUCKET: Final = "leads:forms"
ANONYMIZE_PREFIX: Final = "anonymize"


def _uuid(value: object) -> uuid.UUID | None:
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except ValueError:
        return None


def accepted(event: RawLeadEvent) -> bool:
    return event.signature_valid and bool(event.leadgen_external_id)


def record_delivery(
    db: Session,
    *,
    provider: str,
    payload: dict[str, Any],
    notices: tuple[LeadNotice, ...],
    signature_valid: bool,
) -> list[RawLeadEvent]:
    if not notices:
        if signature_valid:
            return []
        return [
            _raw_row(db, provider=provider, payload=payload, notice=None, valid=False)
        ]
    return [
        _raw_row(
            db, provider=provider, payload=payload, notice=notice, valid=signature_valid
        )
        for notice in notices
    ]


def _raw_row(
    db: Session,
    *,
    provider: str,
    payload: dict[str, Any],
    notice: LeadNotice | None,
    valid: bool,
) -> RawLeadEvent:
    body = payload if valid else {}
    if notice is None:
        row = RawLeadEvent(
            provider=provider,
            payload=body,
            signature_valid=valid,
            status=RawEventStatus.RECEIVED,
            attempts=0,
        )
        db.add(row)
        db.flush()
        return row
    event = db.scalar(
        select(RawLeadEvent).where(
            RawLeadEvent.provider == provider,
            RawLeadEvent.leadgen_external_id == notice.leadgen_external_id,
        )
    )
    if event is None:
        event = RawLeadEvent(
            provider=provider,
            leadgen_external_id=notice.leadgen_external_id,
            payload=body,
            signature_valid=valid,
            page_external_id=notice.page_external_id,
            adset_external_id=notice.adset_external_id,
            status=RawEventStatus.RECEIVED,
            attempts=0,
        )
        try:
            with db.begin_nested():
                db.add(event)
            return event
        except IntegrityError:
            event = db.scalar(
                select(RawLeadEvent).where(
                    RawLeadEvent.provider == provider,
                    RawLeadEvent.leadgen_external_id == notice.leadgen_external_id,
                )
            )
            assert event is not None
    if valid and not event.signature_valid:
        event.signature_valid = True
        event.payload = payload
        event.page_external_id = notice.page_external_id
        event.adset_external_id = notice.adset_external_id
        db.flush()
    return event


def import_lead(db: Session, *, event_id: str) -> str:
    event = db.get(RawLeadEvent, _uuid(event_id))
    if event is None:
        return "gone"
    if event.status == RawEventStatus.PROCESSED:
        return "done"
    with tracing_lead(str(event_id)) as trace:
        trace_delivery(trace, event=event)
        outcome = _process(db, event=event, trace=trace)
        trace_outcome(trace, outcome=outcome, event=event)
    db.commit()
    return outcome


def delivery_page(
    db: Session, event: RawLeadEvent, *, holders: Sequence[PageAccount]
) -> PageAccount | None:
    if len(holders) < 2:
        return holders[0] if holders else None
    if event.adset_external_id:
        found = holder_of_advert(
            db, holders=holders, provider=event.provider, adset=event.adset_external_id
        )
        if found is not None:
            return found
        contested = sum(page.is_active for page in holders) > 1
        if contested and event.attempts < FAILED_RETRY_ATTEMPTS - 1:
            return None
    return holders[0]


def lead_page(
    db: Session,
    *,
    event: RawLeadEvent,
    holders: Sequence[PageAccount],
    page: PageAccount,
    lead: LeadDTO,
) -> PageAccount:
    if len(holders) < 2:
        return page
    return (
        holder_of_advert(
            db,
            holders=holders,
            provider=event.provider,
            adset=lead.adset_external_id,
            campaign=lead.campaign_external_id,
            ad=lead.ad_external_id,
        )
        or page
    )


def _process(db: Session, *, event: RawLeadEvent, trace: LeadTrace) -> str:
    from app.modules.integrations.services import mark_unusable

    if not accepted(event):
        _fail(event, code="unsigned", message="signature did not verify")
        return "refused"
    holders = page_holders(
        db, provider=event.provider, page_external_id=event.page_external_id
    )
    page = delivery_page(db, event, holders=holders)
    record_route(trace, page=page, adset=event.adset_external_id)
    if not holders:
        _mark(event, status=RawEventStatus.ORPHAN)
        return "orphan"
    if page is None:
        trace.note(
            "Sahifa bir nechta kabinetda, reklama guruhi esa hali hech kimda "
            "yo'q. Sinxrondan keyin qayta o'qiladi."
        )
        _fail(event, code=UNPLACED, message="no cabinet holds the ad set yet")
        return UNPLACED
    if page.connection.status not in USABLE_CONNECTION_STATUSES:
        trace.note(
            "Ulanish «yaroqsiz» holatida - Meta'ga umuman murojaat qilinmadi. "
            "Ariza saqlanib turibdi: mijoz qayta ulagach qaytadan o'qiladi."
        )
        event.status = RawEventStatus.FAILED
        event.error_code = DISCONNECTED
        event.error_message = "the provider connection is not usable"
        event.owner_id = page.owner_id
        return DISCONNECTED
    try:
        token = decrypt(page.token_encrypted)
    except DecryptionFailed:
        logger.exception("page token %s could not be decrypted", page.id)
        _fail(
            event,
            code="token",
            message="page token could not be decrypted",
            owner_id=page.owner_id,
        )
        return "unusable"
    try:
        lead = registry.get(event.provider).leads.fetch_lead(
            ref=ExternalRef(
                provider=event.provider, level=FORM_LEVEL, id=event.leadgen_external_id
            ),
            token=token,
        )
    except (AuthFailed, PermissionDenied) as exc:
        logger.warning("page %s was refused a lead: %s", page.external_id, exc)
        trace.note(
            "Meta tokenni rad etdi - ulanish «yaroqsiz» deb belgilandi. "
            "Mijoz Meta'ni qayta ulamaguncha bu sahifadan lid kelmaydi."
        )
        mark_unusable(
            db,
            connection=page.connection,
            status=ConnectionStatus.INVALID,
            code=exc.code or "",
        )
        _fail(event, code=exc.code or "auth", message=str(exc), owner_id=page.owner_id)
        return "failed"
    except ProviderError as exc:
        logger.warning("lead %s could not be read: %s", event.leadgen_external_id, exc)
        _fail(event, code=exc.code or "fetch", message=str(exc), owner_id=page.owner_id)
        return "failed"
    record_fetch(trace, lead=lead)
    page = lead_page(db, event=event, holders=holders, page=page, lead=lead)
    owner = db.get(User, page.owner_id)
    assert owner is not None
    return store_lead(
        db,
        owner=owner,
        page=page,
        provider=event.provider,
        leadgen_id=event.leadgen_external_id,
        lead=lead,
        received_at=event.created_at,
        event=event,
        trace=trace,
    )


def store_lead(
    db: Session,
    *,
    owner: User,
    page: PageAccount | None = None,
    provider: str,
    leadgen_id: str,
    lead: LeadDTO,
    received_at: datetime,
    event: RawLeadEvent | None = None,
    trace: LeadTrace | None = None,
) -> str:
    from app.modules.businesses.selectors import business_for_page

    watch = trace or NoTrace()
    business = business_for_page(db, owner=owner, page=page)
    region = business.country_code if business is not None else ""
    now = utcnow()
    fields = normalise(field_data=lead.field_data, region=region)
    watch.decision("normalizatsiya", {"region": region})
    record_mapping(watch, lead=lead, fields=fields)
    row = Lead(
        owner_id=owner.id,
        provider=provider,
        leadgen_id=leadgen_id,
        field_data_raw=list(lead.field_data),
        answers={key: list(values) for key, values in fields.answers.items()},
        raw_event_id=event.id if event else None,
        full_name=fields.full_name,
        phone_e164=fields.phone_e164,
        email=fields.email,
        city=fields.city,
        form_id=_form_for(db, owner=owner, page=page, lead=lead, provider=provider),
        campaign_external_id=lead.campaign_external_id,
        adset_external_id=lead.adset_external_id,
        ad_external_id=lead.ad_external_id,
        submitted_at=lead.submitted_at or received_at,
        received_at=received_at,
        fetched_at=now,
        is_test=False,
        is_organic=lead.is_organic,
    )
    try:
        with db.begin_nested():
            db.add(row)
    except IntegrityError:
        watch.note(
            f"`{leadgen_id}` allaqachon saqlangan - yangi qator yozilmadi. "
            "Meta bir lidni bir necha marta yuboradi, bu normal holat."
        )
        if event is not None:
            _mark(event, status=RawEventStatus.PROCESSED, owner_id=owner.id)
        return DUPLICATE
    record_row(watch, row=row)
    if event is not None:
        _mark(event, status=RawEventStatus.PROCESSED, owner_id=owner.id)
    emit(
        db,
        owner_id=owner.id,
        name=EventName.LEAD_CREATED,
        aggregate_type="lead",
        aggregate_id=row.id,
        payload={
            "provider": row.provider,
            "leadgen_id": row.leadgen_id,
            "adset_external_id": row.adset_external_id,
            "is_organic": row.is_organic,
        },
        occurred_at=row.submitted_at,
    )
    from app.modules.crm.services import queue_placement

    queue_placement(db, lead_id=str(row.id))
    return CREATED


def _form_for(
    db: Session, *, owner: User, page: PageAccount | None, lead: LeadDTO, provider: str
) -> uuid.UUID | None:
    if lead.form is None:
        return None
    forms = select(LeadForm).where(
        LeadForm.provider == provider, LeadForm.external_id == lead.form.id
    )
    own = db.scalar(forms.where(LeadForm.owner_id == owner.id))
    if own is not None or page is None:
        return own.id if own else None
    other = db.scalar(forms.limit(1))
    if other is None:
        return None
    return copy_lead_form(db, form=other, owner=owner, page=page).id


def _mark(
    event: RawLeadEvent, *, status: str, owner_id: uuid.UUID | None = None
) -> None:
    event.status = status
    event.attempts += 1
    event.processed_at = utcnow()
    if owner_id is not None:
        event.owner_id = owner_id


def _fail(
    event: RawLeadEvent, *, code: str, message: str, owner_id: uuid.UUID | None = None
) -> None:
    event.status = RawEventStatus.FAILED
    event.attempts += 1
    event.error_code = code[:32]
    event.error_message = message
    if owner_id is not None:
        event.owner_id = owner_id


def record_lead_form(
    db: Session,
    *,
    owner: User,
    page: PageAccount,
    provider: str,
    external_id: str,
    name: str = "",
    questions: list[dict[str, Any]] | None = None,
    privacy_policy_url: str = "",
    locale: str = "",
    ending: dict[str, str] | None = None,
) -> LeadForm:
    row = db.scalar(
        select(LeadForm).where(
            LeadForm.owner_id == owner.id,
            LeadForm.provider == provider,
            LeadForm.external_id == external_id,
        )
    )
    if row is None:
        row = LeadForm(owner_id=owner.id, provider=provider, external_id=external_id)
        db.add(row)
    row.page_id = page.id
    row.name = name
    row.questions_raw = questions or []
    row.privacy_policy_url = privacy_policy_url
    row.locale = locale
    row.ending = ending or {}
    row.status = LeadFormStatus.ACTIVE
    row.synced_at = utcnow()
    db.flush()
    return row


def copy_lead_form(
    db: Session, *, form: LeadForm, owner: User, page: PageAccount
) -> LeadForm:
    row = db.scalar(
        select(LeadForm).where(
            LeadForm.owner_id == owner.id,
            LeadForm.provider == form.provider,
            LeadForm.external_id == form.external_id,
        )
    )
    if row is not None:
        return row
    row = LeadForm(
        owner_id=owner.id,
        provider=form.provider,
        external_id=form.external_id,
        page_id=page.id,
        name=form.name,
        questions_raw=form.questions_raw,
        privacy_policy_url=form.privacy_policy_url,
        locale=form.locale,
        ending=form.ending,
        status=form.status,
        status_raw=form.status_raw,
        created_time=form.created_time,
    )
    db.add(row)
    db.flush()
    return row


def mark_outcome(db: Session, *, user: User, lead_id: str, status: str) -> LeadOutcome:
    if status not in {item.value for item in OutcomeStatus}:
        raise UnknownLead
    lead = db.scalar(
        select(Lead).where(Lead.owner_id == user.id, Lead.id == _uuid(lead_id))
    )
    if lead is None:
        raise UnknownLead
    outcome = db.scalar(
        select(LeadOutcome).where(
            LeadOutcome.lead_id == lead.id, LeadOutcome.source == OutcomeSource.USER
        )
    )
    if outcome is None:
        outcome = LeadOutcome(
            owner_id=user.id,
            lead_id=lead.id,
            source=OutcomeSource.USER,
            status=status,
            currency="",
            reported_status="",
        )
        db.add(outcome)
    else:
        outcome.owner_id = user.id
        if outcome.status != status:
            outcome.status = status
            if outcome.reported_at and outcome.reported_status != status:
                outcome.reported_at = None
    db.flush()
    return outcome


def clear_outcome(db: Session, *, user: User, lead_id: str) -> None:
    db.execute(
        delete(LeadOutcome).where(
            LeadOutcome.owner_id == user.id,
            LeadOutcome.lead_id == _uuid(lead_id),
            LeadOutcome.source == OutcomeSource.USER,
        )
    )


def recheck_page(db: Session, *, page: PageAccount, actor_id: str = "") -> None:
    from app.modules.leads.tasks import subscribe_page_task, sync_page_forms_task

    key = str(page.id)
    logger.info("recheck queued for page %s by %s", page.external_id, actor_id or "-")
    on_commit(db, lambda: subscribe_page_task.delay(key))
    on_commit(db, lambda: sync_page_forms_task.delay(key))


def subscribe_page(db: Session, *, page_id: str) -> str:
    page = db.get(PageAccount, _uuid(page_id))
    if page is None:
        return "gone"
    try:
        token = decrypt(page.token_encrypted)
    except DecryptionFailed:
        logger.exception("page token %s could not be decrypted", page.id)
        return "unusable"
    port = registry.get(page.provider).leads
    ref = ExternalRef(provider=page.provider, level=PAGE_LEVEL, id=page.external_id)
    dry_run = settings.ads_dry_run
    try:
        result = port.subscribe(page=ref, token=token, dry_run=dry_run)
    except ProviderError as exc:
        logger.warning(
            "leadgen subscribe failed for page %s: %s", page.external_id, exc
        )
        return "failed"
    page.leadgen_subscribed = bool(result.ok) and not dry_run
    page.leadgen_subscribed_at = utcnow() if page.leadgen_subscribed else None
    db.commit()
    if dry_run:
        return "rehearsed"
    return "subscribed" if page.leadgen_subscribed else "refused"


def sync_page_forms(db: Session, *, page: PageAccount, token: str) -> int:
    try:
        forms = registry.get(page.provider).leads.list_forms(
            page=ExternalRef(
                provider=page.provider, level=PAGE_LEVEL, id=page.external_id
            ),
            token=token,
        )
    except ProviderError as exc:
        logger.warning("form sync failed for page %s: %s", page.external_id, exc)
        return 0
    _store_forms(db, page=page, forms=forms)
    page.forms_synced_at = utcnow()
    db.commit()
    return len(forms)


def _store_forms(db: Session, *, page: PageAccount, forms: list[LeadFormDTO]) -> None:
    now = utcnow()
    seen: set[str] = set()
    for dto in forms:
        row = db.scalar(
            select(LeadForm).where(
                LeadForm.owner_id == page.owner_id,
                LeadForm.provider == dto.ref.provider,
                LeadForm.external_id == dto.ref.id,
            )
        )
        if row is None:
            row = LeadForm(
                owner_id=page.owner_id,
                provider=dto.ref.provider,
                external_id=dto.ref.id,
            )
            db.add(row)
        row.page_id = page.id
        row.name = dto.name
        row.questions_raw = list(dto.questions_raw)
        row.privacy_policy_url = dto.privacy_policy_url
        row.locale = dto.locale
        if dto.ending_kind:
            row.ending = {
                "kind": dto.ending_kind,
                "target": dto.ending_target,
                "button_text": dto.ending_button_text,
            }
        elif row.ending is None:
            row.ending = {}
        row.status = (
            LeadFormStatus.ACTIVE if dto.is_collecting else LeadFormStatus.ARCHIVED
        )
        row.status_raw = dto.status_raw
        row.leads_count = dto.leads_count
        row.created_time = dto.created_time
        row.synced_at = now
        seen.add(dto.ref.id)
    db.flush()
    retired = db.execute(
        update(LeadForm)
        .where(
            LeadForm.owner_id == page.owner_id,
            LeadForm.page_id == page.id,
            LeadForm.status == LeadFormStatus.ACTIVE,
            LeadForm.external_id.not_in(seen),
        )
        .values(status=LeadFormStatus.ARCHIVED, updated_at=now)
    ).rowcount
    if retired:
        logger.info("form sync retired %s forms on page %s", retired, page.external_id)


def request_forms_refresh(
    db: Session, *, owner: User, page: PageAccount | None = None
) -> PageAccount:
    from app.modules.integrations.selectors import active_page
    from app.modules.leads.tasks import sync_page_forms_task

    if page is None:
        page = active_page(db, owner=owner)
    if page is None or page.owner_id != owner.id:
        raise NoPageConnected
    if not throttle.hit(
        bucket=REFRESH_BUCKET,
        key=f"{page.provider}:{page.external_id}",
        limit=1,
        window_seconds=FORMS_REFRESH_SECONDS,
    ):
        raise FormsAskedRecently
    key = str(page.id)
    on_commit(db, lambda: sync_page_forms_task.delay(key))
    return page


def refresh_page_forms(db: Session, *, page_id: str) -> str:
    page = db.get(PageAccount, _uuid(page_id))
    if page is None:
        return "gone"
    try:
        token = decrypt(page.token_encrypted)
    except DecryptionFailed:
        logger.exception("page token %s could not be decrypted", page.id)
        return "unusable"
    return f"{sync_page_forms(db, page=page, token=token)} forms"


def reconcile_page(db: Session, *, page_id: str) -> int:
    page = db.get(PageAccount, _uuid(page_id))
    if page is None:
        return 0
    if page.connection.status not in USABLE_CONNECTION_STATUSES:
        logger.info(
            "page %s not swept: its connection is %s",
            page.external_id,
            page.connection.status,
        )
        return 0
    try:
        token = decrypt(page.token_encrypted)
    except DecryptionFailed:
        logger.exception("page token %s could not be decrypted", page.id)
        return 0
    sync_page_forms(db, page=page, token=token)
    forms = list(
        db.scalars(
            select(LeadForm).where(
                LeadForm.owner_id == page.owner_id,
                LeadForm.page_id == page.id,
                LeadForm.status == LeadFormStatus.ACTIVE,
            )
        )
    )
    found = sum(_sweep(db, page=page, form=form, token=token) for form in forms)
    for form in retired_unread_forms(db, page=page, now=utcnow()):
        before = form.swept_at
        found += _sweep(db, page=page, form=form, token=token)
        db.refresh(form, ["swept_at"])
        if form.swept_at != before:
            cache.set(
                FINAL_SWEEP_KEY.format(form=form.id), "1", FINAL_SWEEP_TTL_SECONDS
            )
    db.commit()
    return found


def day_windows(*, since: datetime, until: datetime) -> list[tuple[datetime, datetime]]:
    windows: list[tuple[datetime, datetime]] = []
    start = since
    while start < until:
        end = min(start + timedelta(days=1), until)
        windows.append((start, end))
        start = end
    return windows


def _sweep(db: Session, *, page: PageAccount, form: LeadForm, token: str) -> int:
    if form.leads_count == 0:
        return 0
    port: LeadSourcePort = registry.get(form.provider).leads
    ref = ExternalRef(provider=form.provider, level=FORM_LEVEL, id=form.external_id)
    floor = utcnow() - timedelta(days=RECONCILE_LOOKBACK_DAYS)
    covered_at = form.swept_at or db.scalar(
        select(func.max(Lead.submitted_at)).where(
            Lead.owner_id == page.owner_id, Lead.form_id == form.id
        )
    )
    since = (
        floor
        if covered_at is None
        else max(floor, covered_at - timedelta(hours=RECONCILE_OVERLAP_HOURS))
    )
    asked_at = utcnow()
    covered: datetime | None
    try:
        leads = port.list_leads(form=ref, since=since, token=token)
        covered = asked_at
    except ResultTruncated as exc:
        logger.info(
            "lead sweep for form %s truncated after %s rows; reading by day",
            form.external_id,
            exc.rows_read,
        )
        leads, covered = [], asked_at
        for start, end in day_windows(since=since, until=asked_at):
            try:
                leads += port.list_leads(form=ref, since=start, until=end, token=token)
            except ProviderError as err:
                logger.warning(
                    "lead sweep for form %s stopped at %s: %s", ref.id, start, err
                )
                covered = start if start > since else None
                break
    except ProviderError as exc:
        logger.warning("lead sweep failed for form %s: %s", form.external_id, exc)
        return 0
    if covered is not None:
        db.execute(
            update(LeadForm).where(LeadForm.id == form.id).values(swept_at=covered)
        )
    holders = page_holders(
        db, provider=page.provider, page_external_id=page.external_id
    )
    held = held_leadgen_ids(
        db,
        owner_ids=[holder.owner_id for holder in holders] or [page.owner_id],
        provider=form.provider,
        leadgen_ids=[lead.ref.id for lead in leads],
    )
    new = 0
    for lead in leads:
        if lead.ref.id in held:
            continue
        target = page
        if len(holders) >= 2:
            target = (
                holder_of_advert(
                    db,
                    holders=holders,
                    provider=page.provider,
                    adset=lead.adset_external_id,
                    campaign=lead.campaign_external_id,
                    ad=lead.ad_external_id,
                )
                or holders[0]
            )
        owner = db.get(User, target.owner_id)
        assert owner is not None
        outcome = store_lead(
            db,
            owner=owner,
            page=target,
            provider=form.provider,
            leadgen_id=lead.ref.id,
            lead=lead,
            received_at=lead.submitted_at or utcnow(),
        )
        new += outcome == CREATED
    return new


def reconcile_all_pages(db: Session, *, now: datetime) -> int:
    from app.modules.integrations.selectors import owners_at_hour
    from app.modules.leads.tasks import reconcile_page_task, subscribe_page_task

    chosen: dict[tuple[str, str], tuple[uuid.UUID, str, uuid.UUID]] = {}
    for pk, status, owner_id, provider, external_id in db.execute(
        select(
            PageAccount.id,
            ProviderConnection.status,
            PageAccount.owner_id,
            PageAccount.provider,
            PageAccount.external_id,
        )
        .join(ProviderConnection, ProviderConnection.id == PageAccount.connection_id)
        .join(User, User.id == PageAccount.owner_id)
        .where(PageAccount.is_active.is_(True))
        .order_by(User.date_joined, PageAccount.created_at)
    ):
        key = (provider, external_id)
        held = chosen.get(key)
        if held is None or (
            held[1] not in USABLE_CONNECTION_STATUSES
            and status in USABLE_CONNECTION_STATUSES
        ):
            chosen[key] = (pk, status, owner_id)
    rows = list(chosen.values())
    due_owners = owners_at_hour(
        db, owner_ids={row[2] for row in rows}, now=now, hour=NIGHT_LEADS_HOUR
    )
    pages = [
        (pk, status) for pk, status, owner_id in rows if str(owner_id) in due_owners
    ]
    for page_id, status in pages:
        if status in USABLE_CONNECTION_STATUSES:
            subscribe_page_task.delay(str(page_id))
        reconcile_page_task.delay(str(page_id))
    return len(pages)


def retry_deliveries(
    db: Session, *, events: Iterable[RawLeadEvent], actor_id: str = ""
) -> tuple[int, int]:
    from app.modules.leads.tasks import import_lead_task

    queued, skipped = 0, 0
    for event in events:
        if event.status == RawEventStatus.PROCESSED:
            skipped += 1
            continue
        on_commit(db, lambda key=str(event.id): import_lead_task.delay(key))
        queued += 1
    if queued:
        logger.info("%s deliveries re-queued by %s", queued, actor_id or "-")
    return queued, skipped


def retry_failed_deliveries(db: Session, *, now: datetime) -> int:
    queued, _ = retry_deliveries(
        db, events=retryable_deliveries(db, now=now), actor_id="sweep"
    )
    db.commit()
    return queued


def sweep_unimported_deliveries(db: Session, *, now: datetime) -> int:
    queued, _ = retry_deliveries(
        db, events=unimported_deliveries(db, now=now), actor_id="unimported"
    )
    db.commit()
    return queued


def recover_leads(db: Session, *, user: User, now: datetime) -> int:
    from app.modules.integrations.selectors import meta_connection

    scope = shown_page(db, owner=user).deliveries
    trouble = delivery_trouble(db, owner=user, now=now, scope=scope)
    if not trouble.recoverable:
        if trouble.unrecoverable:
            raise RecoveryImpossible(lost=trouble.unrecoverable)
        raise NothingToRecover
    connection = meta_connection(db, owner=user)
    if connection is None or connection.status not in USABLE_CONNECTION_STATUSES:
        raise RecoveryNeedsConnection
    if not cache.add(f"leads:recover:{user.id}", "1", RECOVERY_COOLDOWN_SECONDS):
        raise RecoveryTooSoon
    queued, _ = retry_deliveries(
        db,
        events=recoverable_deliveries(
            db, owner=user, now=now, limit=RECOVERY_BATCH, scope=scope
        ),
        actor_id=str(user.id),
    )
    return queued


def report_orphan_deliveries(db: Session, *, now: datetime) -> int:
    pages = orphan_pages(db, since=now - timedelta(hours=ORPHAN_REPORT_HOURS))
    if not pages:
        return 0
    total = sum(page.deliveries for page in pages)
    logger.error(
        "leads arrived for %s page(s) nobody has connected",
        len(pages),
        extra={
            "deliveries": total,
            "hours": ORPHAN_REPORT_HOURS,
            "pages": [
                {
                    "page_external_id": page.page_external_id,
                    "deliveries": page.deliveries,
                    "last_seen": page.last_seen.isoformat(),
                }
                for page in pages[:ORPHAN_REPORT_PAGES]
            ],
        },
    )
    return total


def report_unimported_deliveries(db: Session, *, now: datetime) -> int:
    rows = unread_deliveries(db, now=now)
    if not rows:
        return 0
    logger.error(
        "deliveries arrived and were never read",
        extra={
            "deliveries": len(rows),
            "hours": UNIMPORTED_REPORT_HOURS,
            "unread_after_hours": UNIMPORTED_WINDOW_HOURS,
            "oldest": rows[0].created_at.isoformat(),
            "event_ids": [str(row.id) for row in rows[:UNIMPORTED_REPORT_SAMPLE]],
        },
    )
    return len(rows)


def unsigned_retention_floor(*, today: date) -> datetime:
    floor = today - timedelta(days=UNSIGNED_EVENT_RETENTION_DAYS)
    return datetime.combine(floor, time.min, tzinfo=UTC)


def purge_raw_events(db: Session, *, before: datetime) -> int:
    removed = 0
    while True:
        keys = list(
            db.scalars(
                select(RawLeadEvent.id)
                .where(
                    RawLeadEvent.signature_valid.is_(False),
                    RawLeadEvent.created_at < before,
                )
                .limit(PURGE_BATCH)
            )
        )
        if not keys:
            break
        removed += delete_rows(db, RawLeadEvent.__table__, RawLeadEvent.id.in_(keys))
        db.commit()
    return removed


ANONYMIZED_FIELDS: tuple[str, ...] = (
    "full_name",
    "phone_e164",
    "email",
    "field_data_raw",
    "answers",
)


def anonymize_leads(
    db: Session, *, owner: User, lead_ids: Sequence[uuid.UUID], reason: str
) -> int:
    from app.modules.integrations.services import forget_leads

    ids = list(
        db.scalars(
            select(Lead.id).where(
                Lead.owner_id == owner.id,
                Lead.id.in_(list(lead_ids)),
                Lead.anonymized_at.is_(None),
            )
        )
    )
    if not ids:
        return 0
    audiences = forget_leads(db, owner=owner, lead_ids=ids)
    now = utcnow()
    erased = db.execute(
        update(Lead)
        .where(Lead.owner_id == owner.id, Lead.id.in_(ids))
        .values(
            full_name="",
            phone_e164="",
            email="",
            field_data_raw=[],
            answers={},
            anonymized_at=now,
            updated_at=now,
        )
    ).rowcount
    prefix = f"{ANONYMIZE_PREFIX}:{owner.id}:"
    attempt = (
        db.scalar(
            select(func.count())
            .select_from(ActionLog)
            .where(ActionLog.idempotency_key.startswith(prefix))
        )
        or 0
    ) + 1
    log = ActionLog(
        owner_id=owner.id,
        actor_type=ActorType.SYSTEM,
        actor_id=None,
        action=ActionType.ANONYMIZE_LEADS,
        target_provider="",
        target_level=LEAD_LEVEL,
        target_external_id="",
        request_payload={"leads": erased, "audiences": audiences, "reason": reason},
        previous_state={"fields": list(ANONYMIZED_FIELDS)},
        result_payload={},
        dropped=[],
        status=ActionStatus.APPLIED,
        dry_run=False,
        idempotency_key=f"{prefix}{attempt}",
        applied_at=now,
    )
    db.add(log)
    db.flush()
    emit(
        db,
        owner_id=owner.id,
        name=EventName.LEADS_ANONYMIZED,
        aggregate_type="lead",
        aggregate_id=log.id,
        payload={
            "leads": erased,
            "audiences": audiences,
            "reason": reason,
            "action_log_id": str(log.id),
        },
        occurred_at=now,
    )
    db.commit()
    return int(erased)


def anonymize_for_email(db: Session, *, email: str, reason: str) -> int:
    erased = 0
    for owner, ids in leads_matching_email(db, email=email):
        try:
            erased += anonymize_leads(db, owner=owner, lead_ids=ids, reason=reason)
        except (ProviderError, DomainError):
            db.rollback()
            logger.exception("leads.anonymize_failed", extra={"owner": str(owner.id)})
    return erased


def erase_expired_leads(db: Session, *, now: datetime) -> int:
    from app.modules.billing.selectors import subscription_ended_at

    erased = 0
    for owner in owners_holding_leads(db):
        ended = subscription_ended_at(db, owner=owner)
        if ended is None or ended + timedelta(days=LEAD_RETENTION_DAYS) > now:
            continue
        ids = unerased_lead_ids(db, owner=owner, limit=ANONYMIZE_LIMIT)
        if not ids:
            continue
        try:
            done = anonymize_leads(
                db, owner=owner, lead_ids=ids, reason=RETENTION_REASON
            )
        except (ProviderError, DomainError):
            db.rollback()
            logger.exception("leads.retention_failed", extra={"owner": str(owner.id)})
            continue
        erased += done
        remaining = unerased_count(db, owner=owner)
        if remaining:
            logger.warning(
                "leads.retention_backlog",
                extra={"owner": str(owner.id), "erased": done, "remaining": remaining},
            )
    return erased


def sweep_lead_verdicts(db: Session) -> int:
    from app.modules.leads.tasks import report_outcomes_task

    settled = utcnow() - timedelta(minutes=SETTLE_MINUTES)
    owners = owners_with_verdicts(db, before=settled)
    for owner_id in owners:
        report_outcomes_task.delay(str(owner_id))
    return len(owners)


def report_outcomes(db: Session, *, owner_id: uuid.UUID | str) -> str:
    owner = db.get(User, _uuid(owner_id))
    if owner is None:
        return "gone"
    account = db.scalar(
        select(AdAccount).where(
            AdAccount.owner_id == owner.id,
            AdAccount.provider == META,
            AdAccount.is_active.is_(True),
        )
    )
    if account is None:
        return "no_account"
    dataset = reporting_dataset(db, owner=owner, ad_account=account)
    if not dataset:
        return "no_dataset"
    connection = account.connection
    if connection.status not in USABLE_CONNECTION_STATUSES:
        return "connection_unusable"
    try:
        token = decrypt(connection.token_encrypted)
    except DecryptionFailed:
        logger.exception("connection %s could not be decrypted", connection.id)
        return "connection_unusable"
    now = utcnow()
    port = registry.get(account.provider).conversions
    window = port.report_window_days()
    rehearsing = settings.ads_dry_run
    verdicts = verdicts_for(
        db,
        owner=owner,
        before=now - timedelta(minutes=SETTLE_MINUTES),
        limit=VERDICTS_PER_RUN,
    )
    if not verdicts:
        return "nothing_due"
    ready = due(verdicts=verdicts, now=now, window_days=window)
    stale = expired(verdicts=verdicts, now=now, window_days=window)
    if not rehearsing:
        _close(db, owner=owner, verdicts=stale, at=now, reported="")
    if not ready:
        db.commit()
        return f"expired:{len(stale)}"
    try:
        receipt = port.report_leads(
            dataset=ExternalRef(
                provider=account.provider, level=DATASET_LEVEL, id=dataset
            ),
            events=[
                _verdict_event(verdict=verdict, stage=stage, provider=account.provider)
                for verdict, stage in ready
            ],
            token=token,
            dry_run=rehearsing,
        )
    except ProviderError as exc:
        db.commit()
        logger.warning("verdict reporting failed for %s: %s", owner.id, exc)
        return "provider_failed"
    if rehearsing:
        return f"rehearsed:{len(ready)}"
    by_stage: dict[str, list[Verdict]] = defaultdict(list)
    for verdict, stage in ready:
        by_stage[stage].append(verdict)
    for stage, group in by_stage.items():
        _close(db, owner=owner, verdicts=tuple(group), at=now, reported=stage)
    db.commit()
    return f"sent:{receipt.accepted}"


def _verdict_event(*, verdict: Verdict, stage: str, provider: str) -> LeadEventDTO:
    return LeadEventDTO(
        lead=ExternalRef(
            provider=provider, level=LEAD_LEVEL, id=verdict.lead_external_id
        ),
        stage=stage,  # type: ignore[arg-type]
        occurred_at=verdict.decided_at,
        event_id=event_key(
            provider=provider, lead_external_id=verdict.lead_external_id, stage=stage
        ),
        value_minor=(
            MinorUnits(verdict.value_minor)
            if stage == "converted" and verdict.value_minor is not None
            else None
        ),
        currency=verdict.currency if stage == "converted" else "",
    )


def _close(
    db: Session,
    *,
    owner: User,
    verdicts: tuple[Verdict, ...],
    at: datetime,
    reported: str,
) -> None:
    if not verdicts:
        return
    leads = select(Lead.id).where(
        Lead.owner_id == owner.id,
        Lead.leadgen_id.in_([verdict.lead_external_id for verdict in verdicts]),
    )
    db.execute(
        update(LeadOutcome)
        .where(
            LeadOutcome.owner_id == owner.id,
            LeadOutcome.lead_id.in_(leads),
            LeadOutcome.source == OutcomeSource.USER,
            LeadOutcome.reported_at.is_(None),
        )
        .values(reported_at=at, reported_status=reported)
    )


__all__ = [
    "ANONYMIZED_FIELDS",
    "CREATED",
    "DUPLICATE",
    "accepted",
    "anonymize_for_email",
    "anonymize_leads",
    "clear_outcome",
    "copy_lead_form",
    "day_windows",
    "delivery_page",
    "erase_expired_leads",
    "import_lead",
    "lead_page",
    "mark_outcome",
    "purge_raw_events",
    "recheck_page",
    "reconcile_all_pages",
    "reconcile_page",
    "record_delivery",
    "record_lead_form",
    "recover_leads",
    "refresh_page_forms",
    "report_orphan_deliveries",
    "report_outcomes",
    "report_unimported_deliveries",
    "request_forms_refresh",
    "retry_deliveries",
    "retry_failed_deliveries",
    "store_lead",
    "subscribe_page",
    "sweep_lead_verdicts",
    "sweep_unimported_deliveries",
    "sync_page_forms",
    "unsigned_retention_floor",
]
