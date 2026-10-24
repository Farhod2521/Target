import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from adskit import registry
from metaads.writing import is_dry_run_id
from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.integrations.constants import (
    BREADTH_LABELS,
    MIN_AUDIENCE_MEMBERS,
    SOURCE_ACTION_LABELS,
    SOURCE_KIND_LABELS,
    SourceKind,
)
from app.modules.integrations.models import (
    AdAccount,
    CustomAudience,
    PageAccount,
    PixelAccount,
)
from app.modules.integrations.selectors.slots import enabled_pages, page_shown
from core.audiences import CustomerRecord, windows_for

__all__ = ["BREADTH_LABELS"]

LEAD_FIELDS = ("full_name", "phone_e164", "email", "city")


def audiences_query(
    *, owner: User, accounts: Sequence[AdAccount] | None = None
) -> Select[tuple[CustomAudience]]:
    query = select(CustomAudience).where(CustomAudience.owner_id == owner.id)
    if accounts is not None:
        query = query.where(
            CustomAudience.ad_account_id.in_([account.id for account in accounts])
        )
    return query.order_by(CustomAudience.created_at.desc())


def audiences(
    db: Session, *, owner: User, accounts: Sequence[AdAccount] | None = None
) -> list[CustomAudience]:
    return list(db.scalars(audiences_query(owner=owner, accounts=accounts)))


def audience_for(db: Session, *, owner: User, pk: object) -> CustomAudience | None:
    try:
        key = uuid.UUID(str(pk))
    except ValueError:
        return None
    return db.scalar(
        select(CustomAudience).where(
            CustomAudience.owner_id == owner.id, CustomAudience.id == key
        )
    )


def usable_audiences(db: Session, *, owner: User) -> list[CustomAudience]:
    return list(
        db.scalars(
            audiences_query(owner=owner).where(CustomAudience.is_ready.is_(True))
        )
    )


def accounts_holding_audiences(db: Session) -> list[uuid.UUID]:
    return list(
        db.scalars(
            select(AdAccount.id)
            .join(CustomAudience, CustomAudience.ad_account_id == AdAccount.id)
            .where(AdAccount.is_active.is_(True))
            .distinct()
        )
    )


def customer_records(db: Session, *, owner: User) -> tuple[list[CustomerRecord], str]:
    country = _country_of(db, owner=owner)
    return _records(db, query=_fillable(owner=owner), country=country), country


def records_for(
    db: Session, *, owner: User, lead_ids: Sequence[uuid.UUID]
) -> tuple[list[CustomerRecord], str]:
    country = _country_of(db, owner=owner)
    if not lead_ids:
        return [], country
    from app.modules.leads.models import Lead

    query = _fillable(owner=owner).where(Lead.id.in_(list(lead_ids)))
    return _records(db, query=query, country=country), country


def _fillable(*, owner: User) -> Select[tuple[str, str, str, str]]:
    from app.modules.leads.models import Lead

    return select(Lead.full_name, Lead.phone_e164, Lead.email, Lead.city).where(
        Lead.owner_id == owner.id,
        Lead.is_test.is_(False),
        Lead.anonymized_at.is_(None),
        ~((Lead.phone_e164 == "") & (Lead.email == "")),
    )


def _records(
    db: Session, *, query: Select[tuple[str, str, str, str]], country: str
) -> list[CustomerRecord]:
    return [
        CustomerRecord(
            first_name=_first(full_name),
            last_name=_last(full_name),
            phone=phone,
            email=email,
            city=city,
            country_code=country,
        )
        for full_name, phone, email, city in db.execute(query)
    ]


def _country_of(db: Session, *, owner: User) -> str:
    from app.modules.businesses.selectors import business_for

    business = business_for(db, owner)
    return business.country_code if business else ""


def _first(full_name: str) -> str:
    parts = full_name.split()
    return parts[0] if parts else ""


def _last(full_name: str) -> str:
    parts = full_name.split()
    return " ".join(parts[1:]) if len(parts) > 1 else ""


NO_PIXEL_LABEL = "Sayt"
NO_PIXEL = (
    "Saytingizda hisoblagich o'rnatilmagan. O'rnatilgach saytga "
    "kirganlardan auditoriya qurish mumkin bo'ladi."
)
PIXEL_DISABLED = "Bu hisoblagichni Meta o'chirib qo'ygan."
PIXEL_SILENT = (
    "Hisoblagich bor, lekin undan hali birorta hodisa kelmagan - "
    "u saytga qo'yilmagan bo'lishi mumkin."
)


@dataclass(frozen=True, slots=True)
class RuleOption:
    kind: str
    label: str
    actions: tuple[tuple[str, str], ...] = ()
    windows: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class SourceOption:
    kind: str
    external_id: str
    label: str
    blocked_reason: str = ""

    @property
    def is_usable(self) -> bool:
        return not self.blocked_reason


def sources_for(
    db: Session, *, owner: User, account: AdAccount | None
) -> list[SourceOption]:
    page = page_shown(enabled_pages(db, owner=owner))
    return [
        *_forms(db, owner=owner, page=page),
        *_pages(page=page),
        *_pixels(db, account=account),
    ]


def source_for(
    db: Session, *, owner: User, account: AdAccount | None, kind: str, external_id: str
) -> SourceOption | None:
    for option in sources_for(db, owner=owner, account=account):
        if option.kind == kind and option.external_id == external_id:
            return option
    return None


def rule_options(*, provider: str) -> list[RuleOption]:
    return [
        RuleOption(
            kind=support.kind,
            label=str(SOURCE_KIND_LABELS.get(support.kind, support.kind)),
            actions=tuple(
                (action, str(SOURCE_ACTION_LABELS.get(action, action)))
                for action in support.actions
            ),
            windows=windows_for(support=support),
        )
        for support in registry.get(provider).audience_sources.supported_rules()
    ]


def _forms(db: Session, *, owner: User, page: PageAccount | None) -> list[SourceOption]:
    if page is None:
        return []
    from app.modules.leads.models import LeadForm

    rows = db.scalars(
        select(LeadForm)
        .where(
            LeadForm.owner_id == owner.id,
            LeadForm.page_id == page.id,
            LeadForm.external_id != "",
        )
        .order_by(LeadForm.created_time.desc(), LeadForm.name)
    )
    return [
        SourceOption(
            kind=SourceKind.LEAD_FORM,
            external_id=form.external_id,
            label=form.name or form.external_id,
        )
        for form in rows
    ]


def _pages(*, page: PageAccount | None) -> list[SourceOption]:
    if page is None or not page.external_id:
        return []
    return [
        SourceOption(
            kind=SourceKind.PAGE,
            external_id=page.external_id,
            label=page.name or page.external_id,
        )
    ]


def _pixels(db: Session, *, account: AdAccount | None) -> list[SourceOption]:
    if account is None:
        return []
    rows = list(
        db.scalars(
            select(PixelAccount)
            .where(
                PixelAccount.ad_account_id == account.id, PixelAccount.external_id != ""
            )
            .order_by(PixelAccount.is_active.desc(), PixelAccount.name)
        )
    )
    if not rows:
        return [
            SourceOption(
                kind=SourceKind.PIXEL,
                external_id="",
                label=NO_PIXEL_LABEL,
                blocked_reason=NO_PIXEL,
            )
        ]
    return [
        SourceOption(
            kind=SourceKind.PIXEL,
            external_id=pixel.external_id,
            label=pixel.name or pixel.external_id,
            blocked_reason=_pixel_problem(pixel),
        )
        for pixel in rows
    ]


def _pixel_problem(pixel: PixelAccount) -> str:
    if pixel.is_unavailable:
        return PIXEL_DISABLED
    if pixel.last_fired_at is None:
        return PIXEL_SILENT
    return ""


TOO_SMALL_CODE = "300"
FLAGGED_CODE = "471"
STILL_COUNTING = "Platforma hali hisoblamoqda. Tayyor bo'lgach shu yerda tanlanadi."
TARGET_TOO_SMALL = (
    "Bu auditoriyada yetarli odam topilmadi - reklama unga yetkazilmaydi."
)
FLAGGED = "Platforma bu auditoriyani tekshirmoqda. Uni hozir ishlatib bo'lmaydi."
NOT_USABLE = "Bu auditoriyani hozir ishlatib bo'lmaydi."
NOT_FOR_CATEGORY = (
    "O'xshash auditoriya bu turdagi reklamada ishlatilmaydi - platforma uni taqiqlaydi."
)


@dataclass(frozen=True, slots=True)
class TargetOption:
    key: str
    external_id: str
    label: str
    is_lookalike: bool = False
    blocked_reason: str = ""

    @property
    def is_usable(self) -> bool:
        return not self.blocked_reason


def targets_for(
    db: Session, *, owner: User, account: AdAccount, special_ad_category: str = ""
) -> list[TargetOption]:
    return [
        _target(row, special_ad_category=special_ad_category)
        for row in audiences(db, owner=owner, accounts=[account])
        if not is_dry_run_id(row.external_id)
    ]


def targets_by_key(
    db: Session, *, owner: User, keys: Sequence[str], special_ad_category: str = ""
) -> dict[str, TargetOption]:
    wanted = []
    for key in keys:
        try:
            wanted.append(uuid.UUID(str(key)))
        except ValueError:
            continue
    if not wanted:
        return {}
    rows = db.scalars(audiences_query(owner=owner).where(CustomAudience.id.in_(wanted)))
    return {
        str(row.id): _target(row, special_ad_category=special_ad_category)
        for row in rows
    }


def _target(row: CustomAudience, *, special_ad_category: str) -> TargetOption:
    return TargetOption(
        key=str(row.id),
        external_id=row.external_id,
        label=row.name or row.external_id,
        is_lookalike=row.is_lookalike,
        blocked_reason=_target_problem(row, special_ad_category=special_ad_category),
    )


def _target_problem(row: CustomAudience, *, special_ad_category: str) -> str:
    if special_ad_category and row.is_lookalike:
        return NOT_FOR_CATEGORY
    if row.processing_code == FLAGGED_CODE:
        return FLAGGED
    if row.is_ready:
        return ""
    if row.readiness_code == TOO_SMALL_CODE:
        return TARGET_TOO_SMALL
    if not row.is_counted:
        return STILL_COUNTING
    return NOT_USABLE


SEED_TOO_SMALL = (
    "Bunday auditoriya uchun kamida %(limit)s kishi kerak. "
    "Ko'proq mijoz qo'shilgach mumkin bo'ladi."
)
ALREADY_DERIVED = (
    "Bu auditoriyaning o'zi boshqasiga o'xshatib qurilgan - undan yana qurib bo'lmaydi."
)


@dataclass(frozen=True, slots=True)
class SeedOption:
    external_id: str
    label: str
    blocked_reason: str = ""

    @property
    def is_usable(self) -> bool:
        return not self.blocked_reason


def seeds_for(db: Session, *, owner: User) -> list[SeedOption]:
    return [_seed(row) for row in audiences(db, owner=owner)]


def seed_for(db: Session, *, owner: User, external_id: str) -> SeedOption | None:
    if not external_id:
        return None
    for option in seeds_for(db, owner=owner):
        if option.external_id == external_id:
            return option
    return None


def _seed(row: CustomAudience) -> SeedOption:
    return SeedOption(
        external_id=row.external_id,
        label=row.name or row.external_id,
        blocked_reason=_seed_problem(row),
    )


def _seed_problem(row: CustomAudience) -> str:
    if not row.can_seed:
        return ALREADY_DERIVED
    if not row.is_counted:
        return STILL_COUNTING
    if row.approximate_count_upper < MIN_AUDIENCE_MEMBERS:
        return SEED_TOO_SMALL % {"limit": MIN_AUDIENCE_MEMBERS}
    if not row.is_ready:
        return NOT_USABLE
    return ""
