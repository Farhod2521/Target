"""Every read of leads, forms and webhook deliveries."""

import math
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import (
    ColumnElement,
    Select,
    and_,
    distinct,
    func,
    not_,
    or_,
    select,
)
from sqlalchemy.orm import Session

from app.common.cache import cache
from app.common.dates import localtime
from app.common.xlsx import Cell, Column
from app.modules.accounts.models import User
from app.modules.integrations.constants import USABLE_CONNECTION_STATUSES
from app.modules.integrations.models import (
    AdAccount,
    PageAccount,
    PixelAccount,
    ProviderConnection,
)
from app.modules.leads.constants import (
    EXPORT_ANSWER_COLUMNS,
    EXPORT_LIMIT,
    FAILED_RETRY_ATTEMPTS,
    FAILED_RETRY_BATCH,
    FAILED_RETRY_COOLDOWN_MINUTES,
    FAILED_RETRY_WINDOW_HOURS,
    FINAL_SWEEP_KEY,
    LEAD_RETENTION_DAYS,
    LEADS_PER_PAGE,
    OUTCOME_STATUS_LABELS,
    PICKER_FORMS,
    QUESTION_LABELS,
    RECONCILE_LOOKBACK_DAYS,
    SWEEP_STUCK_DAYS,
    UNIMPORTED_BATCH,
    UNIMPORTED_GRACE_MINUTES,
    UNIMPORTED_REPORT_HOURS,
    UNIMPORTED_WINDOW_HOURS,
    LeadFormStatus,
    OutcomeSource,
    OutcomeStatus,
    RawEventStatus,
)
from app.modules.leads.models import Lead, LeadForm, LeadOutcome, RawLeadEvent
from app.modules.leads.selectors.core import (
    EVERYTHING,
    NO_FILTERS,
    NOTHING,
    LeadFilters,
    attach_verdicts,
    lead_scope_of_pages,
    leads_query,
    owned,
    priced,
    verdict_of,
)
from core.leads import (
    DESTINATIONS,
    Answer,
    Verdict,
    form_signature,
    label_answers,
)
from core.leads.ending import EndingLine, provider_line

_REAL = Lead.is_test.is_(False)
CUSTOM_TYPE = "CUSTOM"
TIME_FORMAT = "%d.%m.%Y %H:%M"
OWNER_FORMS_LIMIT = 200


def _count(db: Session, query: Select[Any]) -> int:
    return int(db.scalar(select(func.count()).select_from(query.subquery())) or 0)


def _user_outcome() -> Any:
    return and_(
        LeadOutcome.lead_id == Lead.id, LeadOutcome.source == OutcomeSource.USER
    )


def _countable(owner: User) -> Select[Any]:
    return (
        select(Lead.id)
        .outerjoin(LeadOutcome, _user_outcome())
        .where(owned(owner), _REAL, priced())
    )


@dataclass(frozen=True, slots=True)
class CampaignLeads:
    total: int
    tests: int
    organic: int
    first_at: datetime | None
    last_at: datetime | None
    by_ad: dict[str, int]
    by_adset: dict[str, int]
    by_day: dict[date, int]
    recent: tuple[Lead, ...]


def _day(column: Any, tzinfo: ZoneInfo | Any) -> Any:
    return func.date(func.timezone(str(tzinfo), column))


def campaign_leads(
    db: Session,
    *,
    owner: User,
    provider: str,
    campaign_external_id: str,
    tzinfo: ZoneInfo,
    limit: int,
) -> CampaignLeads:
    base = and_(
        owned(owner),
        Lead.provider == provider,
        Lead.campaign_external_id == campaign_external_id,
    )
    counted = db.execute(
        select(
            func.count(Lead.id).filter(_REAL),
            func.count(Lead.id).filter(~_REAL),
            func.count(Lead.id).filter(_REAL, Lead.is_organic.is_(True)),
            func.min(Lead.submitted_at).filter(_REAL),
            func.max(Lead.submitted_at).filter(_REAL),
        ).where(base)
    ).one()
    by_ad = db.execute(
        select(Lead.ad_external_id, func.count(Lead.id))
        .where(base, _REAL, Lead.ad_external_id != "")
        .group_by(Lead.ad_external_id)
    )
    by_adset = db.execute(
        select(Lead.adset_external_id, func.count(Lead.id))
        .where(base, _REAL, Lead.adset_external_id != "")
        .group_by(Lead.adset_external_id)
    )
    day = _day(Lead.submitted_at, tzinfo)
    by_day = db.execute(
        select(day, func.count(Lead.id)).where(base, _REAL).group_by(day)
    )
    recent = db.scalars(
        select(Lead)
        .where(base)
        .order_by(Lead.submitted_at.desc(), Lead.created_at.desc())
        .limit(limit)
    )
    return CampaignLeads(
        total=counted[0],
        tests=counted[1],
        organic=counted[2],
        first_at=counted[3],
        last_at=counted[4],
        by_ad=dict(by_ad.all()),
        by_adset=dict(by_adset.all()),
        by_day=dict(by_day.all()),
        recent=tuple(recent),
    )


def _unreported() -> Select[tuple[LeadOutcome]]:
    return (
        select(LeadOutcome)
        .join(Lead, Lead.id == LeadOutcome.lead_id)
        .where(
            LeadOutcome.reported_at.is_(None),
            LeadOutcome.source == OutcomeSource.USER,
            Lead.is_test.is_(False),
            Lead.is_organic.is_(False),
            Lead.anonymized_at.is_(None),
            Lead.leadgen_id != "",
            priced(),
        )
    )


def owners_with_verdicts(db: Session, *, before: datetime) -> tuple[uuid.UUID, ...]:
    query = _unreported().where(LeadOutcome.updated_at <= before)
    return tuple(db.scalars(select(distinct(query.subquery().c.owner_id))))


def verdicts_for(
    db: Session, *, owner: User, before: datetime, limit: int
) -> tuple[Verdict, ...]:
    rows = db.scalars(
        _unreported()
        .where(LeadOutcome.owner_id == owner.id, LeadOutcome.updated_at <= before)
        .order_by(LeadOutcome.updated_at)
        .limit(limit)
    )
    return tuple(
        Verdict(
            lead_external_id=row.lead.leadgen_id,
            status=row.status,
            decided_at=row.updated_at,
            value_minor=row.deal_value_minor,
            currency=row.currency,
        )
        for row in rows
    )


def qualified_since(db: Session, *, owner: User, since: datetime) -> int:
    return _count(
        db,
        select(LeadOutcome.id)
        .join(Lead, Lead.id == LeadOutcome.lead_id)
        .where(
            LeadOutcome.owner_id == owner.id,
            LeadOutcome.status == OutcomeStatus.QUALIFIED,
            LeadOutcome.source == OutcomeSource.USER,
            LeadOutcome.updated_at >= since,
            Lead.is_test.is_(False),
            Lead.is_organic.is_(False),
            priced(),
        ),
    )


def reporting_dataset(db: Session, *, owner: User, ad_account: AdAccount) -> str:
    row = db.scalar(
        select(PixelAccount.external_id).where(
            PixelAccount.owner_id == owner.id,
            PixelAccount.ad_account_id == ad_account.id,
            PixelAccount.is_active.is_(True),
            PixelAccount.is_unavailable.is_(False),
        )
    )
    return str(row or "")


def unpriced_adset_ids(
    db: Session, *, owner: User, since: datetime, limit: int
) -> tuple[str, ...]:
    return tuple(
        db.scalars(
            select(distinct(Lead.adset_external_id))
            .where(
                owned(owner),
                _REAL,
                not_(priced()),
                Lead.submitted_at >= since,
                Lead.adset_external_id != "",
            )
            .limit(limit)
        )
    )


def lead_adset_ids(db: Session, *, owner: User) -> frozenset[str]:
    return frozenset(
        db.scalars(
            select(distinct(Lead.adset_external_id)).where(
                owned(owner), _REAL, Lead.adset_external_id != ""
            )
        )
    )


def _recoverable(now: datetime) -> ColumnElement[bool]:
    finished = or_(
        RawLeadEvent.attempts >= FAILED_RETRY_ATTEMPTS,
        RawLeadEvent.created_at < now - timedelta(hours=FAILED_RETRY_WINDOW_HOURS),
    )
    unclaimed = or_(
        RawLeadEvent.status == RawEventStatus.UNTRACKED,
        and_(RawLeadEvent.status == RawEventStatus.FAILED, finished),
    )
    return and_(
        unclaimed,
        RawLeadEvent.signature_valid.is_(True),
        RawLeadEvent.created_at >= now - timedelta(days=LEAD_RETENTION_DAYS),
        RawLeadEvent.leadgen_external_id != "",
    )


def _lost(now: datetime) -> ColumnElement[bool]:
    return and_(
        RawLeadEvent.status.in_((RawEventStatus.UNTRACKED, RawEventStatus.FAILED)),
        RawLeadEvent.signature_valid.is_(True),
        RawLeadEvent.created_at < now - timedelta(days=LEAD_RETENTION_DAYS),
        RawLeadEvent.leadgen_external_id != "",
    )


@dataclass(frozen=True, slots=True)
class DeliveryTrouble:
    untracked: int = 0
    failed: int = 0
    recoverable: int = 0
    unrecoverable: int = 0

    @property
    def total(self) -> int:
        return self.untracked + self.failed

    def __bool__(self) -> bool:
        return bool(self.total)


def delivery_trouble(
    db: Session, *, owner: User, now: datetime, scope: ColumnElement[bool] = EVERYTHING
) -> DeliveryTrouble:
    row = db.execute(
        select(
            func.count(RawLeadEvent.id).filter(
                RawLeadEvent.status == RawEventStatus.UNTRACKED
            ),
            func.count(RawLeadEvent.id).filter(
                RawLeadEvent.status == RawEventStatus.FAILED
            ),
            func.count(RawLeadEvent.id).filter(_recoverable(now)),
            func.count(RawLeadEvent.id).filter(_lost(now)),
        ).where(RawLeadEvent.owner_id == owner.id, scope)
    ).one()
    return DeliveryTrouble(*row)


def retryable_deliveries(db: Session, *, now: datetime) -> list[RawLeadEvent]:
    unusable = (
        select(ProviderConnection.id)
        .where(
            ProviderConnection.owner_id == RawLeadEvent.owner_id,
            ProviderConnection.provider == RawLeadEvent.provider,
            ProviderConnection.status.not_in(USABLE_CONNECTION_STATUSES),
        )
        .exists()
    )
    return list(
        db.scalars(
            select(RawLeadEvent)
            .where(
                RawLeadEvent.status == RawEventStatus.FAILED,
                RawLeadEvent.signature_valid.is_(True),
                RawLeadEvent.attempts < FAILED_RETRY_ATTEMPTS,
                RawLeadEvent.created_at
                >= now - timedelta(hours=FAILED_RETRY_WINDOW_HOURS),
                RawLeadEvent.updated_at
                <= now - timedelta(minutes=FAILED_RETRY_COOLDOWN_MINUTES),
                RawLeadEvent.leadgen_external_id != "",
                ~unusable,
            )
            .order_by(RawLeadEvent.created_at)
            .limit(FAILED_RETRY_BATCH)
        )
    )


def recoverable_deliveries(
    db: Session,
    *,
    now: datetime,
    limit: int,
    owner: User | None = None,
    scope: ColumnElement[bool] = EVERYTHING,
) -> list[RawLeadEvent]:
    query = select(RawLeadEvent).where(_recoverable(now), scope)
    if owner is not None:
        query = query.where(RawLeadEvent.owner_id == owner.id)
    return list(db.scalars(query.order_by(RawLeadEvent.created_at).limit(limit)))


@dataclass(frozen=True, slots=True)
class OrphanPage:
    page_external_id: str
    deliveries: int
    last_seen: datetime


def orphan_pages(db: Session, *, since: datetime) -> tuple[OrphanPage, ...]:
    rows = db.execute(
        select(
            RawLeadEvent.page_external_id,
            func.count(RawLeadEvent.id),
            func.max(RawLeadEvent.created_at),
        )
        .where(
            RawLeadEvent.status == RawEventStatus.ORPHAN,
            RawLeadEvent.created_at >= since,
        )
        .group_by(RawLeadEvent.page_external_id)
        .order_by(func.count(RawLeadEvent.id).desc())
    )
    return tuple(OrphanPage(*row) for row in rows)


def unimported_deliveries(db: Session, *, now: datetime) -> list[RawLeadEvent]:
    return list(
        db.scalars(
            select(RawLeadEvent)
            .where(
                RawLeadEvent.status == RawEventStatus.RECEIVED,
                RawLeadEvent.signature_valid.is_(True),
                RawLeadEvent.created_at
                >= now - timedelta(hours=UNIMPORTED_WINDOW_HOURS),
                RawLeadEvent.created_at
                <= now - timedelta(minutes=UNIMPORTED_GRACE_MINUTES),
                RawLeadEvent.leadgen_external_id != "",
            )
            .order_by(RawLeadEvent.created_at)
            .limit(UNIMPORTED_BATCH)
        )
    )


def unread_deliveries(db: Session, *, now: datetime) -> list[RawLeadEvent]:
    return list(
        db.scalars(
            select(RawLeadEvent)
            .where(
                RawLeadEvent.status == RawEventStatus.RECEIVED,
                RawLeadEvent.signature_valid.is_(True),
                RawLeadEvent.created_at
                >= now - timedelta(hours=UNIMPORTED_REPORT_HOURS),
                RawLeadEvent.created_at
                <= now - timedelta(hours=UNIMPORTED_WINDOW_HOURS),
                RawLeadEvent.leadgen_external_id != "",
            )
            .order_by(RawLeadEvent.created_at)
        )
    )


@dataclass(frozen=True, slots=True)
class LeadCounts:
    total: int = 0
    qualified: int = 0
    unqualified: int = 0
    unmarked: int = 0


@dataclass(frozen=True, slots=True)
class LeadPulse:
    counts: LeadCounts
    trouble: DeliveryTrouble
    newest_at: datetime | None = None

    @property
    def cursor(self) -> str:
        return (
            f"{self.newest_at.isoformat() if self.newest_at else '-'}"
            f"|{self.counts.total}|{self.counts.unmarked}|{self.trouble.total}"
            f"|{self.trouble.recoverable}"
        )


def _verdict_counts(*conditions: Any) -> Select[Any]:
    verdict = verdict_of()
    return select(
        func.max(Lead.submitted_at),
        func.count(Lead.id).filter(_REAL),
        func.count(Lead.id).filter(_REAL, verdict == OutcomeStatus.QUALIFIED),
        func.count(Lead.id).filter(_REAL, verdict == OutcomeStatus.UNQUALIFIED),
        func.count(Lead.id).filter(_REAL, verdict.is_(None)),
    ).where(*conditions)


def lead_pulse(
    db: Session,
    *,
    owner: User,
    now: datetime,
    ad: str = "",
    adset: str = "",
    scope: ColumnElement[bool] = EVERYTHING,
    deliveries: ColumnElement[bool] = EVERYTHING,
) -> LeadPulse:
    conditions = [owned(owner), scope]
    if ad:
        conditions.append(Lead.ad_external_id == ad)
    if adset:
        conditions.append(Lead.adset_external_id == adset)
    newest, total, qualified, unqualified, unmarked = db.execute(
        _verdict_counts(*conditions)
    ).one()
    return LeadPulse(
        counts=LeadCounts(total, qualified, unqualified, unmarked),
        trouble=delivery_trouble(db, owner=owner, now=now, scope=deliveries),
        newest_at=newest,
    )


def leads_for(
    db: Session,
    *,
    owner: User,
    filters: LeadFilters = NO_FILTERS,
    scope: ColumnElement[bool] = EVERYTHING,
    limit: int | None = None,
    offset: int = 0,
) -> list[Lead]:
    query = leads_query(owner=owner, filters=filters, scope=scope)
    if limit is not None:
        query = query.limit(limit).offset(offset)
    return attach_verdicts(db, query)


def leads_from_adset(
    db: Session, *, owner: User, provider: str, adset_external_id: str, limit: int
) -> tuple[Lead, ...]:
    if not adset_external_id:
        return ()
    return tuple(
        db.scalars(
            select(Lead)
            .where(
                owned(owner),
                Lead.provider == provider,
                Lead.adset_external_id == adset_external_id,
            )
            .order_by(Lead.submitted_at, Lead.created_at)
            .limit(limit)
        )
    )


def lead_detail(
    db: Session,
    *,
    owner: User,
    lead_id: uuid.UUID,
    scope: ColumnElement[bool] = EVERYTHING,
) -> Lead | None:
    found = attach_verdicts(
        db, select(Lead).where(owned(owner), scope, Lead.id == lead_id)
    )
    return found[0] if found else None


def answer_rows(*, lead: Lead) -> tuple[Answer, ...]:
    questions = lead.form.questions_raw if lead.form is not None else []
    return label_answers(
        field_data=lead.field_data_raw,
        questions=questions if isinstance(questions, list) else [],
    )


def lead_counts(db: Session, *, owner: User) -> LeadCounts:
    _newest, total, qualified, unqualified, unmarked = db.execute(
        _verdict_counts(owned(owner))
    ).one()
    return LeadCounts(total, qualified, unqualified, unmarked)


def newest_lead_at(db: Session, *, owner: User) -> datetime | None:
    return db.scalar(select(func.max(Lead.submitted_at)).where(owned(owner)))


@dataclass(frozen=True, slots=True)
class LeadPage:
    rows: tuple[Lead, ...] = ()
    number: int = 1
    pages: int = 1
    total: int = 0
    first: int = 0
    last: int = 0

    @property
    def has_previous(self) -> bool:
        return self.number > 1

    @property
    def has_next(self) -> bool:
        return self.number < self.pages

    @property
    def is_paged(self) -> bool:
        return self.pages > 1


def page_of_leads(
    db: Session,
    *,
    owner: User,
    filters: LeadFilters = NO_FILTERS,
    number: int = 1,
    scope: ColumnElement[bool] = EVERYTHING,
) -> LeadPage:
    query = leads_query(owner=owner, filters=filters, scope=scope)
    total = _count(db, query)
    pages = max(1, math.ceil(total / LEADS_PER_PAGE))
    number = min(max(1, number), pages)
    rows = attach_verdicts(
        db, query.limit(LEADS_PER_PAGE).offset((number - 1) * LEADS_PER_PAGE)
    )
    first = (number - 1) * LEADS_PER_PAGE + 1 if total else 0
    return LeadPage(
        rows=tuple(rows),
        number=number,
        pages=pages,
        total=total,
        first=first,
        last=first + len(rows) - 1 if rows else 0,
    )


@dataclass(frozen=True, slots=True)
class FormLabel:
    pk: str
    name: str
    page_name: str


def owner_forms(db: Session, *, owner: User) -> tuple[FormLabel, ...]:
    rows = db.execute(
        select(LeadForm.id, LeadForm.name, PageAccount.name)
        .join(PageAccount, PageAccount.id == LeadForm.page_id)
        .where(LeadForm.owner_id == owner.id, LeadForm.status == LeadFormStatus.ACTIVE)
        .limit(OWNER_FORMS_LIMIT)
    )
    return tuple(
        FormLabel(pk=str(pk), name=name, page_name=page) for pk, name, page in rows
    )


def owner_form(db: Session, *, owner: User, form_id: str) -> LeadForm | None:
    try:
        key = uuid.UUID(form_id)
    except ValueError:
        return None
    return db.scalar(
        select(LeadForm).where(LeadForm.owner_id == owner.id, LeadForm.id == key)
    )


@dataclass(frozen=True, slots=True)
class FormOption:
    external_id: str
    name: str
    questions: tuple[str, ...]
    leads_count: int | None
    created_time: datetime | None
    signature: tuple[str, ...]
    ending: EndingLine | None = None
    custom_questions: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True, slots=True)
class FormChoices:
    options: tuple[FormOption, ...]
    hidden: int


def _collecting(*, owner: User, page: PageAccount) -> Select[tuple[LeadForm]]:
    return select(LeadForm).where(
        LeadForm.owner_id == owner.id,
        LeadForm.page_id == page.id,
        LeadForm.status == LeadFormStatus.ACTIVE,
        LeadForm.external_id != "",
    )


def usable_forms(
    db: Session, *, owner: User, page: PageAccount, limit: int | None = PICKER_FORMS
) -> FormChoices:
    offered = _collecting(owner=owner, page=page)
    rows = list(db.scalars(offered if limit is None else offered.limit(limit + 1)))
    if limit is None or len(rows) <= limit:
        return FormChoices(options=tuple(form_card(row) for row in rows), hidden=0)
    return FormChoices(
        options=tuple(form_card(row) for row in rows[:limit]),
        hidden=_count(db, offered) - limit,
    )


def forms_by_external_id(
    db: Session, *, owner: User, provider: str, external_ids: list[str]
) -> dict[str, LeadForm]:
    if not external_ids:
        return {}
    return {
        row.external_id: row
        for row in db.scalars(
            select(LeadForm).where(
                LeadForm.owner_id == owner.id,
                LeadForm.provider == provider,
                LeadForm.external_id.in_(external_ids),
            )
        )
    }


def collecting_form(
    db: Session, *, owner: User, page: PageAccount, external_id: str
) -> LeadForm | None:
    return db.scalar(
        _collecting(owner=owner, page=page).where(LeadForm.external_id == external_id)
    )


def form_option(
    db: Session, *, owner: User, page: PageAccount, external_id: str
) -> FormOption | None:
    row = collecting_form(db, owner=owner, page=page, external_id=external_id)
    return None if row is None else form_card(row)


def form_names(db: Session, *, owner: User, page: PageAccount) -> frozenset[str]:
    return frozenset(
        db.scalars(
            select(LeadForm.name).where(
                LeadForm.owner_id == owner.id,
                LeadForm.page_id == page.id,
                LeadForm.name != "",
            )
        )
    )


def form_card(row: LeadForm) -> FormOption:
    ending = None
    if isinstance(row.ending, dict):
        ending = provider_line(
            kind=str(row.ending.get("kind", "")),
            target=str(row.ending.get("target", "")),
            button_text=str(row.ending.get("button_text", "")),
        )
    return FormOption(
        external_id=row.external_id,
        name=row.name or row.external_id,
        questions=question_summary(row.questions_raw),
        leads_count=row.leads_count,
        created_time=row.created_time,
        signature=form_signature(
            row.questions_raw if isinstance(row.questions_raw, list) else []
        ),
        ending=ending,
        custom_questions=custom_questions(row.questions_raw),
    )


def custom_questions(questions: object) -> tuple[dict[str, Any], ...]:
    if not isinstance(questions, list):
        return ()
    found: list[dict[str, Any]] = []
    for question in questions:
        if not isinstance(question, dict):
            continue
        if str(question.get("type", "")).strip().upper() != CUSTOM_TYPE:
            continue
        label = str(question.get("label", "")).strip()
        options = [
            str(option.get("value", "") if isinstance(option, dict) else option).strip()
            for option in question.get("options") or []
        ]
        options = [option for option in options if option]
        if not label:
            continue
        found.append({"label": label, "options": options})
    return tuple(found)


def question_summary(questions: object) -> tuple[str, ...]:
    if not isinstance(questions, list):
        return ()
    words: list[str] = []
    for question in questions:
        if not isinstance(question, dict):
            continue
        label = str(question.get("label", "")).strip()
        if not label:
            known = QUESTION_LABELS.get(str(question.get("type", "")).strip().upper())
            label = str(known) if known is not None else ""
        if label:
            words.append(label)
    return tuple(words)


def page_holders(
    db: Session, *, provider: str, page_external_id: str
) -> list[PageAccount]:
    return list(
        db.scalars(
            select(PageAccount)
            .join(User, User.id == PageAccount.owner_id)
            .where(
                PageAccount.provider == provider,
                PageAccount.external_id == page_external_id,
            )
            .order_by(
                PageAccount.is_active.desc(), User.date_joined, PageAccount.created_at
            )
        )
    )


def holder_of_advert(
    db: Session,
    *,
    holders: Sequence[PageAccount],
    provider: str,
    adset: str = "",
    campaign: str = "",
    ad: str = "",
) -> PageAccount | None:
    from app.modules.ads.selectors import advert_owner

    if not (adset or campaign or ad):
        return None
    owner_id = advert_owner(
        db,
        provider=provider,
        owner_ids=[page.owner_id for page in holders],
        adset=adset,
        campaign=campaign,
        ad=ad,
    )
    return next((page for page in holders if page.owner_id == owner_id), None)


@dataclass(frozen=True, slots=True)
class ShownPage:
    page: PageAccount | None = None
    sole: bool = False
    account: str = ""
    others: frozenset[str] = field(default_factory=frozenset)
    first: bool = True

    @property
    def leads(self) -> ColumnElement[bool]:
        matched = lead_scope(page=self.page, sole=self.sole)
        if self.page is None or not self.account:
            return matched
        return and_(
            matched,
            pair_leads(
                owner_id=self.page.owner_id,
                account=self.account,
                others=self.others,
                first=self.first,
            ),
        )

    @property
    def deliveries(self) -> ColumnElement[bool]:
        if self.page is None:
            return NOTHING
        return RawLeadEvent.page_external_id == self.page.external_id


def shown_page(db: Session, *, owner: User) -> ShownPage:
    from app.modules.integrations.selectors import (
        enabled_pages,
        page_shown,
        pair_on,
        stored_pairs,
    )

    pages = enabled_pages(db, owner=owner)
    page = page_shown(pages)
    if page is None:
        return ShownPage()
    pairs = stored_pairs(db, owner=owner, pages=[page])
    pair = pair_on(pairs, page)
    if pair is None:
        return ShownPage(page=page, sole=len(pages) == 1)
    return shown_pair(pair=pair, pairs=pairs, sole=len(pages) == 1)


def shown_pair(*, pair: Any, pairs: list[Any], sole: bool) -> ShownPage:
    if pair is None:
        return ShownPage()
    if not pair.stored:
        return ShownPage(page=pair.page, sole=sole)
    return ShownPage(
        page=pair.page,
        sole=sole,
        account=pair.account.external_id,
        others=frozenset(
            other.account.external_id
            for other in pairs
            if other.page.id == pair.page.id
            and other.stored
            and other.account.id != pair.account.id
        ),
        first=pair.first,
    )


def pair_leads(
    *, owner_id: uuid.UUID, account: str, others: frozenset[str], first: bool
) -> ColumnElement[bool]:
    from app.modules.ads.models import Campaign

    def on(*accounts: str) -> Select[tuple[str]]:
        return (
            select(Campaign.external_id)
            .join(AdAccount, AdAccount.id == Campaign.ad_account_id)
            .where(Campaign.owner_id == owner_id, AdAccount.external_id.in_(accounts))
        )

    if not first:
        return Lead.campaign_external_id.in_(on(account))
    if others:
        return Lead.campaign_external_id.not_in(on(*others))
    return EVERYTHING


def lead_scope(*, page: PageAccount | None, sole: bool) -> ColumnElement[bool]:
    if page is None:
        return NOTHING
    return lead_scope_of_pages(pages=[page], sole=sole)


def subscribed_lead_scope(db: Session, *, owner: User) -> ColumnElement[bool]:
    from app.modules.integrations.selectors import enabled_pages

    pages = enabled_pages(db, owner=owner)
    if not pages:
        return NOTHING
    return lead_scope_of_pages(pages=pages, sole=len(pages) == 1)


def _counts_by(
    db: Session,
    column: Any,
    *,
    owner: User,
    since: datetime,
    until: datetime,
    scope: ColumnElement[bool] = EVERYTHING,
    nonempty: bool = True,
) -> dict[Any, tuple[int, int]]:
    query = (
        select(
            column,
            func.count(distinct(Lead.id)),
            func.count(distinct(Lead.id)).filter(
                LeadOutcome.status == OutcomeStatus.QUALIFIED
            ),
        )
        .outerjoin(LeadOutcome, _user_outcome())
        .where(
            owned(owner),
            _REAL,
            priced(),
            Lead.submitted_at >= since,
            Lead.submitted_at <= until,
            scope,
        )
        .group_by(column)
    )
    if nonempty:
        query = query.where(column != "")
    return {key: (leads, qualified) for key, leads, qualified in db.execute(query)}


def daily_counts(
    db: Session,
    *,
    owner: User,
    since: datetime,
    until: datetime,
    tzinfo: object,
    campaign_external_id: str = "",
    scope: ColumnElement[bool] = EVERYTHING,
) -> dict[date, tuple[int, int]]:
    if campaign_external_id:
        scope = and_(scope, Lead.campaign_external_id == campaign_external_id)
    return _counts_by(
        db,
        _day(Lead.submitted_at, tzinfo),
        owner=owner,
        since=since,
        until=until,
        scope=scope,
        nonempty=False,
    )


def counts_by_campaign(
    db: Session,
    *,
    owner: User,
    since: datetime,
    until: datetime,
    scope: ColumnElement[bool] = EVERYTHING,
) -> dict[str, tuple[int, int]]:
    return _counts_by(
        db,
        Lead.campaign_external_id,
        owner=owner,
        since=since,
        until=until,
        scope=scope,
    )


def counts_by_adset(
    db: Session, *, owner: User, since: datetime, until: datetime
) -> dict[str, tuple[int, int]]:
    return _counts_by(db, Lead.adset_external_id, owner=owner, since=since, until=until)


def counts_by_ad(
    db: Session, *, owner: User, since: datetime, until: datetime
) -> dict[str, tuple[int, int]]:
    return _counts_by(db, Lead.ad_external_id, owner=owner, since=since, until=until)


def adset_days(
    db: Session, *, owner: User, since: datetime, until: datetime, tzinfo: object
) -> dict[tuple[str, date], int]:
    day = _day(Lead.submitted_at, tzinfo)
    rows = db.execute(
        select(Lead.adset_external_id, day, func.count(distinct(Lead.id)))
        .where(
            owned(owner),
            _REAL,
            priced(),
            Lead.submitted_at >= since,
            Lead.submitted_at <= until,
            Lead.adset_external_id != "",
        )
        .group_by(Lead.adset_external_id, day)
    )
    return {(adset, when): leads for adset, when, leads in rows}


def counts_by_city(
    db: Session,
    *,
    owner: User,
    since: datetime,
    until: datetime,
    limit: int,
    scope: ColumnElement[bool] = EVERYTHING,
) -> list[tuple[str, int]]:
    query = (
        select(Lead.city, func.count(Lead.id))
        .where(
            owned(owner),
            _REAL,
            priced(),
            Lead.submitted_at >= since,
            Lead.submitted_at <= until,
            scope,
            Lead.city != "",
        )
        .group_by(Lead.city)
        .order_by(func.count(Lead.id).desc(), Lead.city)
    )
    if limit:
        query = query.limit(limit)
    return [(city, leads) for city, leads in db.execute(query)]


def counts_by_hour(
    db: Session,
    *,
    owner: User,
    since: datetime,
    until: datetime,
    tzinfo: object,
    scope: ColumnElement[bool] = EVERYTHING,
) -> dict[int, int]:
    hour = func.extract("hour", func.timezone(str(tzinfo), Lead.submitted_at))
    rows = db.execute(
        select(hour, func.count(Lead.id))
        .where(
            owned(owner),
            _REAL,
            priced(),
            Lead.submitted_at >= since,
            Lead.submitted_at <= until,
            scope,
        )
        .group_by(hour)
    )
    return {int(h): leads for h, leads in rows}


def judged_counts(
    db: Session, *, owner: User, since: datetime, until: datetime
) -> tuple[int, int]:
    leads, judged = db.execute(
        select(
            func.count(distinct(Lead.id)),
            func.count(distinct(Lead.id)).filter(LeadOutcome.id.is_not(None)),
        )
        .outerjoin(LeadOutcome, _user_outcome())
        .where(
            owned(owner),
            _REAL,
            priced(),
            Lead.submitted_at >= since,
            Lead.submitted_at <= until,
        )
    ).one()
    return int(leads or 0), int(judged or 0)


def uncosted_count(
    db: Session,
    *,
    owner: User,
    since: datetime,
    until: datetime,
    scope: ColumnElement[bool] = EVERYTHING,
) -> int:
    return int(
        db.scalar(
            select(func.count(Lead.id)).where(
                owned(owner),
                _REAL,
                not_(priced()),
                scope,
                Lead.submitted_at >= since,
                Lead.submitted_at <= until,
            )
        )
        or 0
    )


def lead_counts_by_owner(
    db: Session,
    *,
    since: datetime,
    until: datetime,
    adset_ids: Iterable[str] | Select[Any],
) -> dict[uuid.UUID, int]:
    ids = adset_ids if isinstance(adset_ids, Select) else list(adset_ids)
    rows = db.execute(
        select(Lead.owner_id, func.count(Lead.id))
        .where(
            _REAL,
            Lead.submitted_at >= since,
            Lead.submitted_at <= until,
            Lead.adset_external_id.in_(ids),
        )
        .group_by(Lead.owner_id)
    )
    return dict(rows.all())


@dataclass(frozen=True, slots=True)
class AdTally:
    external_id: str
    leads: int = 0
    qualified: int = 0
    unmarked: int = 0
    newest_at: datetime | None = None

    @property
    def is_attributed(self) -> bool:
        return bool(self.external_id)


def tallies_by_ad(
    db: Session,
    *,
    owner: User,
    since: datetime | None = None,
    until: datetime | None = None,
    scope: ColumnElement[bool] = EVERYTHING,
) -> tuple[AdTally, ...]:
    conditions = [owned(owner), _REAL, priced(), scope]
    if since is not None:
        conditions.append(Lead.submitted_at >= since)
    if until is not None:
        conditions.append(Lead.submitted_at <= until)
    rows = db.execute(
        select(
            Lead.ad_external_id,
            func.count(distinct(Lead.id)),
            func.count(distinct(Lead.id)).filter(
                LeadOutcome.status == OutcomeStatus.QUALIFIED
            ),
            func.count(distinct(Lead.id)).filter(LeadOutcome.id.is_not(None)),
            func.max(Lead.submitted_at),
        )
        .outerjoin(LeadOutcome, _user_outcome())
        .where(*conditions)
        .group_by(Lead.ad_external_id)
    )
    tallies = [
        AdTally(
            external_id=ad,
            leads=leads,
            qualified=qualified,
            unmarked=leads - judged,
            newest_at=newest,
        )
        for ad, leads, qualified, judged, newest in rows
    ]
    return tuple(
        sorted(
            tallies,
            key=lambda t: (0 if t.is_attributed else 1, -t.leads, t.external_id),
        )
    )


def owners_holding_leads(db: Session) -> list[User]:
    holding = select(Lead.owner_id).where(Lead.anonymized_at.is_(None)).distinct()
    return list(
        db.scalars(select(User).where(User.id.in_(holding)).order_by(User.date_joined))
    )


def unerased_lead_ids(db: Session, *, owner: User, limit: int) -> list[uuid.UUID]:
    return list(
        db.scalars(
            select(Lead.id)
            .where(owned(owner), Lead.anonymized_at.is_(None))
            .order_by(Lead.submitted_at)
            .limit(limit)
        )
    )


def unerased_count(db: Session, *, owner: User) -> int:
    return int(
        db.scalar(
            select(func.count(Lead.id)).where(
                owned(owner), Lead.anonymized_at.is_(None)
            )
        )
        or 0
    )


def leads_matching_email(
    db: Session, *, email: str
) -> list[tuple[User, list[uuid.UUID]]]:
    address = email.strip()
    if not address:
        return []
    grouped: dict[uuid.UUID, list[uuid.UUID]] = {}
    for owner_id, lead_id in db.execute(
        select(Lead.owner_id, Lead.id)
        .where(func.lower(Lead.email) == address.lower(), Lead.anonymized_at.is_(None))
        .order_by(Lead.owner_id, Lead.submitted_at)
    ):
        grouped.setdefault(owner_id, []).append(lead_id)
    if not grouped:
        return []
    owners = {
        user.id: user for user in db.scalars(select(User).where(User.id.in_(grouped)))
    }
    return [(owners[owner_id], ids) for owner_id, ids in grouped.items()]


@dataclass(frozen=True, slots=True)
class StuckForm:
    pk: uuid.UUID
    name: str
    page_name: str
    swept_at: datetime | None


@dataclass(frozen=True, slots=True)
class StuckOwner:
    owner_id: uuid.UUID
    email: str
    forms: int


def held_leadgen_ids(
    db: Session,
    *,
    owner_ids: Sequence[uuid.UUID | str],
    provider: str,
    leadgen_ids: list[str],
) -> set[str]:
    if not leadgen_ids:
        return set()
    return set(
        db.scalars(
            select(Lead.leadgen_id).where(
                Lead.owner_id.in_([uuid.UUID(str(o)) for o in owner_ids]),
                Lead.provider == provider,
                Lead.leadgen_id.in_(leadgen_ids),
            )
        )
    )


def retired_unread_forms(
    db: Session, *, page: PageAccount, now: datetime
) -> list[LeadForm]:
    floor = now - timedelta(days=RECONCILE_LOOKBACK_DAYS)
    rows = db.scalars(
        select(LeadForm).where(
            LeadForm.owner_id == page.owner_id,
            LeadForm.page_id == page.id,
            LeadForm.status == LeadFormStatus.ARCHIVED,
            LeadForm.swept_at >= floor,
            or_(LeadForm.leads_count.is_(None), LeadForm.leads_count != 0),
        )
    )
    return [row for row in rows if not cache.get(FINAL_SWEEP_KEY.format(form=row.id))]


def _stuck(now: datetime) -> ColumnElement[bool]:
    cutoff = now - timedelta(days=SWEEP_STUCK_DAYS)
    return and_(
        LeadForm.status == LeadFormStatus.ACTIVE,
        PageAccount.is_active.is_(True),
        ProviderConnection.status.in_(USABLE_CONNECTION_STATUSES),
        LeadForm.created_at < cutoff,
        or_(LeadForm.swept_at.is_(None), LeadForm.swept_at < cutoff),
        or_(LeadForm.leads_count.is_(None), LeadForm.leads_count != 0),
    )


def _stuck_query(*columns: Any) -> Select[Any]:
    return (
        select(*columns)
        .join(PageAccount, PageAccount.id == LeadForm.page_id)
        .join(ProviderConnection, ProviderConnection.id == PageAccount.connection_id)
    )


def stuck_forms(
    db: Session, *, owner: User, now: datetime, page: PageAccount | None = None
) -> list[StuckForm]:
    query = _stuck_query(LeadForm).where(LeadForm.owner_id == owner.id, _stuck(now))
    if page is not None:
        query = query.where(LeadForm.page_id == page.id)
    return [
        StuckForm(
            pk=row.id,
            name=row.name or row.external_id,
            page_name=row.page.name or row.page.external_id,
            swept_at=row.swept_at,
        )
        for row in db.scalars(query.order_by(LeadForm.swept_at, LeadForm.name))
    ]


def stuck_sweep_owners(
    db: Session, *, now: datetime, limit: int | None = 20
) -> list[StuckOwner]:
    query = (
        _stuck_query(LeadForm.owner_id, User.email, func.count(LeadForm.id))
        .join(User, User.id == LeadForm.owner_id)
        .where(_stuck(now))
        .group_by(LeadForm.owner_id, User.email)
        .order_by(func.count(LeadForm.id).desc())
    )
    if limit:
        query = query.limit(limit)
    return [StuckOwner(owner_id=o, email=e, forms=n) for o, e, n in db.execute(query)]


@dataclass(frozen=True, slots=True)
class LeadSheet:
    columns: tuple[Column, ...] = ()
    rows: tuple[tuple[Cell, ...], ...] = ()
    truncated: bool = False

    def __len__(self) -> int:
        return len(self.rows)


def leads_to_export(
    db: Session,
    *,
    owner: User,
    filters: LeadFilters = NO_FILTERS,
    scope: ColumnElement[bool] = EVERYTHING,
) -> tuple[Lead, ...]:
    return tuple(
        leads_for(db, owner=owner, filters=filters, scope=scope, limit=EXPORT_LIMIT + 1)
    )


def lead_note(lead: Lead) -> str:
    if lead.is_test:
        return "Sinov"
    if lead.is_organic:
        return "Reklamasiz"
    return ""


def extra_answers(lead: Lead) -> dict[str, str]:
    questions = lead.form.questions_raw if lead.form is not None else []
    given = label_answers(
        field_data=lead.field_data_raw,
        questions=questions if isinstance(questions, list) else [],
    )
    return {
        answer.label: ", ".join(answer.values)
        for answer in given
        if answer.key not in DESTINATIONS
    }


def lead_sheet(
    *,
    leads: Sequence[Lead],
    ad_names: Mapping[str, str] | None = None,
    campaign_names: Mapping[str, str] | None = None,
) -> LeadSheet:
    ad_names = ad_names or {}
    campaign_names = campaign_names or {}
    kept = list(leads[:EXPORT_LIMIT])
    answers = [extra_answers(lead) for lead in kept]
    seen: dict[str, None] = {}
    for given in answers:
        for question in given:
            seen.setdefault(question, None)
        if len(seen) >= EXPORT_ANSWER_COLUMNS:
            break
    questions = tuple(seen)[:EXPORT_ANSWER_COLUMNS]
    headings = (
        ("#", 5),
        ("Ism", 26),
        ("Telefon", 18),
        ("Email", 26),
        ("Shahar", 16),
        ("Kelgan vaqt", 18),
        ("Baho", 12),
        ("Reklama", 30),
        ("Kampaniya", 26),
        ("Forma", 24),
        ("Izoh", 14),
        *((question, 24) for question in questions),
    )
    columns = tuple(Column(header=header, width=width) for header, width in headings)
    rows = []
    for number, (lead, given) in enumerate(zip(kept, answers, strict=True), start=1):
        verdict = getattr(lead, "verdict", "") or ""
        rows.append(
            (
                number,
                lead.full_name,
                lead.phone_e164,
                lead.email,
                lead.city,
                localtime(lead.submitted_at).strftime(TIME_FORMAT),
                str(OUTCOME_STATUS_LABELS.get(verdict, "")) if verdict else "",
                ad_names.get(lead.ad_external_id, lead.ad_external_id),
                campaign_names.get(
                    lead.campaign_external_id, lead.campaign_external_id
                ),
                lead.form.name if lead.form is not None else "",
                lead_note(lead),
                *(given.get(question, "") for question in questions),
            )
        )
    return LeadSheet(
        columns=columns, rows=tuple(rows), truncated=len(leads) > EXPORT_LIMIT
    )


def leads_to_deliver(db: Session, *, owner: User) -> list[Lead]:
    return list(
        db.scalars(
            select(Lead)
            .where(owned(owner), Lead.anonymized_at.is_(None))
            .order_by(Lead.submitted_at, Lead.id)
        )
    )
