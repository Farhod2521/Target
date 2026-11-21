"""Writing the showcase account - see the package's own note.

Everything is written with plain inserts, in one transaction, with its own
dates: the services would stamp today's on thirty days of history, and
would tell Telegram, the audit trail and the queues about each made-up
lead. The figures hang together the way real ones do - a campaign's day is
the sum of its groups', a lead form advert's results are the leads that
exist - because the screens check them against each other.
"""

from __future__ import annotations

import hashlib
import math
import random
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, insert, select
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.common.money import format_minor
from app.common.passwords import make_password
from app.modules.accounts.exceptions import EmailTaken
from app.modules.accounts.models import User
from app.modules.ads.models import Ad, AdCreative, AdSet, Campaign, CampaignLaunch
from app.modules.billing.constants import (
    HistoryKind,
    InvoiceKind,
    InvoiceStatus,
    PlanMove,
    SubscriptionStatus,
    TransactionState,
)
from app.modules.billing.models import (
    Invoice,
    PaymentTransaction,
    Plan,
    Subscription,
    SubscriptionChange,
)
from app.modules.businesses.models import Business, BusinessCategory
from app.modules.crm.constants import (
    DEFAULT_LOST_REASONS,
    PRESET_LABELS,
    ActivityKind,
    Distribution,
    Preset,
    SetupState,
    Since,
    StageKind,
)
from app.modules.crm.models import (
    CrmActivity,
    CrmCard,
    CrmLostReason,
    CrmMember,
    CrmSetup,
    CrmStage,
    CrmStageMove,
)
from app.modules.integrations.constants import ConnectionStatus
from app.modules.integrations.models import (
    AdAccount,
    PageAccount,
    PageInstagram,
    PagePair,
    PixelAccount,
    ProviderConnection,
)
from app.modules.leads.constants import MANUAL_PROVIDER, SignalSource, SignalStatus
from app.modules.leads.models import Lead, LeadForm, LeadSignal
from app.modules.metrics.constants import BreakdownKind, MetricLevel
from app.modules.metrics.models import (
    FxRate,
    MetricsBreakdown,
    MetricsDaily,
    PeopleCount,
)
from app.modules.metrics.services.sync import extra_people_ranges, people_ranges

PROVIDER = "meta"
# The preset a learning centre's goals and words are read from.
CATEGORY = "education"
ZONE = "Asia/Tashkent"
TZ = ZoneInfo(ZONE)
# The thirty days every screen opens on, and thirty before them to be
# compared with.
DAYS = 60
MANAGERS = (
    ("Dilnoza Karimova", 0.40, 0.135, 14),
    ("Jasur Toshpo'latov", 0.35, 0.095, 26),
    ("Madina Yusupova", 0.25, 0.060, 55),
)
# Nobody's number: Uzbekistan has no "00" operator code, so a manager who
# taps one of these calls no one.
PHONE = "+99800{:07d}"

FIRST_NAMES = (
    "Aziz", "Bekzod", "Dilshod", "Eldor", "Farrux", "Jahongir", "Kamron",
    "Laziz", "Mirjalol", "Nodir", "Otabek", "Rustam", "Sardor", "Temur",
    "Ulug'bek", "Xurshid", "Zafar", "Shohruh", "Islom", "Abror",
    "Dilnoza", "Gulnora", "Kamola", "Lola", "Madina", "Nigora", "Ozoda",
    "Sevara", "Shahlo", "Zarina", "Malika", "Nargiza", "Feruza", "Mohira",
    "Sitora", "Umida", "Yulduz", "Ziyoda", "Charos", "Durdona",
)  # fmt: skip
LAST_NAMES = (
    "Abdullayev", "Karimov", "Rahimov", "Tursunov", "Yusupov", "Ismoilov",
    "Qodirov", "Saidov", "Xolmatov", "Nazarov", "Ergashev", "Mirzayev",
    "Olimov", "Sobirov", "Hamidov", "Jo'rayev", "Normatov", "Usmonov",
    "Valiyev", "Zokirov",
)  # fmt: skip
CITIES = ("Toshkent", "Toshkent", "Toshkent", "Chirchiq", "Yangiyo'l", "Samarqand")
NOTES_TALK = (
    "Kurs narxini so'radi, jadvalni yubordim",
    "Kechki guruhga qiziqyapti",
    "Ota-onasi bilan maslahatlashib, qayta aloqaga chiqadi",
    "Dam olish kunlari guruhi bormi deb so'radi",
    "Telegramdan dastur va narxlarni yubordim",
    "Darajasini aniqlash testiga yozildi",
    "Chegirma bor-yo'qligini so'radi",
    "Do'sti bilan birga kelmoqchi",
)
NOTES_TRIAL = (
    "Sinov darsiga shanba 11:00 ga yozildi",
    "Sinov darsiga keldi, o'qituvchi yoqdi",
    "Sinov darsi seshanba 18:30",
)
NOTES_PAY = (
    "Shartnoma yuborildi, to'lovni ertaga qiladi",
    "Bo'lib to'lashni so'radi, 2 oyga bo'lib berdik",
    "Karta orqali to'laydi",
)
NOTES_WON = (
    "3 oylik to'lov qildi",
    "Birinchi oy uchun to'ladi",
    "To'liq kurs uchun to'ladi",
    "",
)
DUE_NOTES = (
    "Qayta qo'ng'iroq qilish",
    "Sinov darsini eslatish",
    "To'lovni eslatish",
    "Jadvalni tasdiqlash",
)
LOST_WEIGHTS = (0.30, 0.24, 0.16, 0.18, 0.05, 0.07)


@dataclass(frozen=True, slots=True)
class AdSpec:
    name: str
    share: float
    headline: str
    message: str
    # How it does against the group's own numbers: >1 is the better advert.
    pull: float = 1.0
    video: bool = False


@dataclass(frozen=True, slots=True)
class GroupSpec:
    name: str
    share: float
    age: tuple[int, int]
    ads: tuple[AdSpec, ...]
    women: float = 0.55


@dataclass(frozen=True, slots=True)
class CampaignSpec:
    key: str
    name: str
    kind: str  # lead | chat | click
    course: str
    daily_usd: float
    cpm: float
    ctr: float
    # Dollars for one result of its own kind.
    price: float
    groups: tuple[GroupSpec, ...]
    # Days ago it started; ``stopped`` days ago it was switched off.
    started: int = DAYS + 12
    stopped: int | None = None
    check: tuple[int, int] = (0, 0)


CAMPAIGNS: tuple[CampaignSpec, ...] = (
    CampaignSpec(
        key="ielts",
        name="Zukko - Ariza qoldirsin - IELTS",
        kind="lead",
        course="IELTS",
        daily_usd=12.0,
        cpm=1.55,
        ctr=0.021,
        price=2.6,
        check=(1_800_000, 3_200_000),
        groups=(
            GroupSpec(
                name="Toshkent, 18-27, talabalar",
                share=0.6,
                age=(18, 27),
                ads=(
                    AdSpec(
                        name="IELTS 7.0 - natija videosi",
                        share=0.55,
                        headline="3 oyda IELTS 7.0",
                        message="O'quvchimiz Malika 3 oyda 5.5 dan 7.0 ga chiqdi. "
                        "Bepul sinov darsiga yoziling.",
                        pull=1.25,
                        video=True,
                    ),
                    AdSpec(
                        name="IELTS - bepul sinov darsi",
                        share=0.45,
                        headline="Bepul sinov darsi",
                        message="Darajangizni bepul aniqlaymiz va shaxsiy reja "
                        "tuzib beramiz. Joylar soni cheklangan.",
                        pull=0.85,
                    ),
                ),
            ),
            GroupSpec(
                name="Toshkent, 28-40, ishlaydiganlar",
                share=0.4,
                age=(28, 40),
                women=0.48,
                ads=(
                    AdSpec(
                        name="IELTS - kechki guruh",
                        share=1.0,
                        headline="Ishdan keyin IELTS",
                        message="19:00 dan keyingi guruhlar. Haftasiga 3 kun, "
                        "ishdan qolmasdan tayyorlaning.",
                    ),
                ),
            ),
        ),
    ),
    CampaignSpec(
        key="it",
        name="Zukko - Ariza qoldirsin - Dasturlash",
        kind="lead",
        course="Dasturlash",
        daily_usd=10.0,
        cpm=1.85,
        ctr=0.017,
        price=3.3,
        check=(2_400_000, 4_500_000),
        groups=(
            GroupSpec(
                name="Toshkent, 16-24, IT qiziqishi",
                share=0.65,
                age=(16, 24),
                women=0.34,
                ads=(
                    AdSpec(
                        name="Python - 6 oyda kasb",
                        share=0.5,
                        headline="6 oyda dasturchi bo'ling",
                        message="Noldan Python. Amaliy loyihalar va ishga "
                        "joylashishda yordam.",
                        pull=1.15,
                    ),
                    AdSpec(
                        name="Frontend - bitiruvchilar",
                        share=0.5,
                        headline="Bitiruvchilarimiz qayerda ishlaydi",
                        message="O'tgan yilgi bitiruvchilarimizning 70 foizi "
                        "IT kompaniyalarda ishlayapti.",
                        pull=0.9,
                        video=True,
                    ),
                ),
            ),
            GroupSpec(
                name="Viloyatlar, 18-30",
                share=0.35,
                age=(18, 30),
                women=0.30,
                ads=(
                    AdSpec(
                        name="Dasturlash - onlayn guruh",
                        share=1.0,
                        headline="Onlayn ham o'qish mumkin",
                        message="Viloyatdan turib o'qing: jonli darslar, "
                        "yozuvlar va ustoz yordami.",
                        pull=0.8,
                    ),
                ),
            ),
        ),
    ),
    CampaignSpec(
        key="math",
        name="Zukko - Ariza qoldirsin - Matematika",
        kind="lead",
        course="Matematika",
        daily_usd=8.0,
        cpm=1.35,
        ctr=0.024,
        price=2.1,
        started=12,
        check=(1_200_000, 2_100_000),
        groups=(
            GroupSpec(
                name="Toshkent, ota-onalar 30-45",
                share=1.0,
                age=(30, 45),
                women=0.68,
                ads=(
                    AdSpec(
                        name="Matematika - abituriyentlar",
                        share=0.6,
                        headline="DTM matematikasi 30/30",
                        message="Farzandingizni kirish imtihoniga tayyorlaymiz. "
                        "Kichik guruhlar, har hafta nazorat.",
                        pull=1.1,
                    ),
                    AdSpec(
                        name="Matematika - 5-9 sinflar",
                        share=0.4,
                        headline="Matematikani yaxshi ko'radigan bola",
                        message="5-9 sinflar uchun mantiq va matematika to'garagi.",
                        pull=0.9,
                    ),
                ),
            ),
        ),
    ),
    CampaignSpec(
        key="chat",
        name="Zukko - Xabar yozishsin - Instagram",
        kind="chat",
        course="Rus tili",
        daily_usd=7.0,
        cpm=1.25,
        ctr=0.019,
        price=0.62,
        groups=(
            GroupSpec(
                name="Toshkent, 18-35",
                share=1.0,
                age=(18, 35),
                ads=(
                    AdSpec(
                        name="Rus tili - so'zlashuv",
                        share=0.6,
                        headline="2 oyda rus tilida gapiring",
                        message="So'zlashuv klubi va kichik guruhlar. "
                        "Direct'ga yozing, darajangizni aytamiz.",
                        pull=1.1,
                        video=True,
                    ),
                    AdSpec(
                        name="Rus tili - narxlar",
                        share=0.4,
                        headline="Oyiga 450 000 so'mdan",
                        message="Narx va jadvalni Direct'da yuboramiz.",
                        pull=0.9,
                    ),
                ),
            ),
        ),
    ),
    CampaignSpec(
        key="site",
        name="Zukko - Saytga o'tsin - Kurslar",
        kind="click",
        course="Kurslar",
        daily_usd=6.0,
        cpm=1.10,
        ctr=0.015,
        price=0.09,
        stopped=9,
        groups=(
            GroupSpec(
                name="Toshkent, 18-40",
                share=1.0,
                age=(18, 40),
                ads=(
                    AdSpec(
                        name="Barcha kurslar - sayt",
                        share=1.0,
                        headline="Zukko kurslari",
                        message="Til, IT va aniq fanlar. Jadval va narxlar saytda.",
                    ),
                ),
            ),
        ),
    ),
)

OBJECTIVES = {
    "lead": ("OUTCOME_LEADS", "LEAD_GENERATION", "ON_AD", "SIGN_UP", "leads"),
    "chat": (
        "OUTCOME_ENGAGEMENT",
        "CONVERSATIONS",
        "INSTAGRAM_DIRECT",
        "MESSAGE_PAGE",
        "messages",
    ),
    "click": ("OUTCOME_TRAFFIC", "LINK_CLICKS", "WEBSITE", "LEARN_MORE", "traffic"),
}
AGE_BANDS = ("13-17", "18-24", "25-34", "35-44", "45-54", "55-64")
PLACES = (
    ("instagram", "feed", 0.34, 1.0),
    ("instagram", "story", 0.27, 0.85),
    ("instagram", "reels", 0.21, 1.15),
    ("facebook", "feed", 0.12, 0.9),
    ("facebook", "facebook_reels", 0.04, 0.7),
    ("audience_network", "classic", 0.02, 0.4),
)
REGIONS = (
    ("Tashkent", 0.52, 1.0),
    ("Tashkent Region", 0.17, 1.1),
    ("Samarqand Region", 0.10, 1.25),
    ("Fergana Region", 0.08, 1.2),
    ("Andijan Region", 0.07, 1.15),
    ("Bukhara Region", 0.06, 1.05),
)


@dataclass(frozen=True, slots=True)
class Seeded:
    owner_email: str
    manager_emails: tuple[str, ...]
    plan: str
    campaigns: int
    leads: int
    cards: int
    sales: int
    metric_rows: int
    # Whether the Central Bank's rates are there to read dollars in so'm with.
    rates: bool


@dataclass(slots=True)
class _Ids:
    """External ids nobody else has: made from the owner's own id."""

    stem: str
    n: int = 0

    def next(self) -> str:
        self.n += 1
        return f"{self.stem}{self.n:05d}"


@dataclass(slots=True)
class _Unit:
    """An advert as the numbers see it."""

    campaign: CampaignSpec
    group: GroupSpec
    spec: AdSpec
    campaign_id: str
    adset_id: str
    ad_id: str
    form_id: uuid.UUID | None
    form_external: str = ""
    leads: dict[date, int] = field(default_factory=dict)


def _local(moment: datetime) -> datetime:
    return moment.astimezone(TZ)


def _at(day: date, hour: float) -> datetime:
    whole = int(hour)
    minute = int((hour - whole) * 60)
    return datetime.combine(day, time(whole, minute), tzinfo=TZ)


def _poisson(rng: random.Random, mean: float) -> int:
    if mean <= 0:
        return 0
    if mean > 30:
        return max(0, round(rng.gauss(mean, math.sqrt(mean))))
    limit, k, p = math.exp(-mean), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def _working(moment: datetime) -> datetime:
    """The next moment a manager is at the desk: 09:00-19:00, not Sunday."""
    local = _local(moment)
    for _ in range(8):
        if local.weekday() == 6:
            local = datetime.combine(local.date() + timedelta(days=1), time(9, 5), TZ)
        elif local.hour < 9:
            local = local.replace(hour=9, minute=5)
        elif local.hour >= 19:
            local = datetime.combine(local.date() + timedelta(days=1), time(9, 5), TZ)
        else:
            break
    return local


def _plan(db: Session) -> Plan:
    for code in ("pro", "standart"):
        found = db.scalar(select(Plan).where(Plan.code == code, Plan.is_active))
        if found is not None:
            return found
    found = db.scalar(
        select(Plan).where(Plan.is_active).order_by(Plan.price.desc()).limit(1)
    )
    if found is None:
        raise LookupError("no active plan to subscribe the showcase account to")
    return found


def _number(db: Session) -> str:
    from app.modules.billing.services.entitlement import new_invoice_number

    for _ in range(20):
        number = new_invoice_number()
        if db.scalar(select(Invoice.id).where(Invoice.number == number)) is None:
            return number
    raise RuntimeError("no free invoice number")


def seed(
    db: Session,
    *,
    email: str,
    password: str,
    now: datetime | None = None,
) -> Seeded:
    """Write the account. The caller commits; nothing is written on a raise."""
    now = now or utcnow()
    address = email.strip().lower()
    if db.scalar(select(User.id).where(func.lower(User.email) == address)):
        raise EmailTaken
    local_part, _, domain = address.partition("@")
    manager_emails = tuple(
        f"{local_part}+sotuv{n}@{domain}" for n in range(1, len(MANAGERS) + 1)
    )
    for other in manager_emails:
        if db.scalar(select(User.id).where(func.lower(User.email) == other)):
            raise EmailTaken
    rng = random.Random(int(hashlib.sha256(address.encode()).hexdigest()[:12], 16))
    today = _local(now).date()
    first_day = today - timedelta(days=DAYS - 1)
    opened = _at(first_day - timedelta(days=14), 11.5)
    plan = _plan(db)
    secret = make_password(password)

    owner = User(
        email=address,
        password=secret,
        full_name="Zukko o'quv markazi",
        phone="",
        language="uz",
        expert_mode=True,
        role="business_owner",
        email_verified_at=opened,
        welcomed_at=opened,
        prepared_at=opened,
        date_joined=opened,
        signup_via="email",
    )
    db.add(owner)
    db.flush()
    ids = _Ids(stem=f"99{int(owner.id.hex[:10], 16) % 10**9:09d}")

    connection = ProviderConnection(
        owner_id=owner.id,
        provider=PROVIDER,
        external_user_id=ids.next(),
        external_user_name="Zukko Admin",
        scopes=[
            "ads_management",
            "ads_read",
            "business_management",
            "pages_show_list",
            "pages_read_engagement",
            "pages_manage_ads",
            "pages_manage_metadata",
            "leads_retrieval",
            "instagram_basic",
        ],
        # No token at all: nothing can be decrypted and sent, whatever the status.
        token_encrypted=b"",
        token_fingerprint="",
        status=ConnectionStatus.DEMO,
        expires_at=None,
        last_verified_at=now,
        created_at=opened,
    )
    db.add(connection)
    db.flush()
    business_id = ids.next()
    account = AdAccount(
        owner_id=owner.id,
        provider=PROVIDER,
        external_id=f"act_{ids.next()}",
        connection_id=connection.id,
        name="Zukko reklama hisobi",
        business_external_id=business_id,
        business_ids=[business_id],
        currency="USD",
        timezone=ZONE,
        account_status="ACTIVE",
        may_advertise=True,
        payment_due=False,
        min_daily_budget_minor=100,
        prepaid=False,
        custom_audience_terms_accepted=True,
        is_active=True,
        is_current=True,
        synced_at=now,
        created_at=opened,
    )
    instagram_id = ids.next()
    page = PageAccount(
        owner_id=owner.id,
        provider=PROVIDER,
        external_id=ids.next(),
        connection_id=connection.id,
        name="Zukko o'quv markazi",
        token_encrypted=b"",
        token_fingerprint="",
        leadgen_subscribed=True,
        leadgen_subscribed_at=opened,
        tasks=["ADVERTISE", "ANALYZE", "CREATE_CONTENT", "MANAGE", "MODERATE"],
        may_advertise=True,
        leadgen_terms_accepted=True,
        location_city="Toshkent",
        location_lat=Decimal("41.311081"),
        location_lng=Decimal("69.240562"),
        instagram_user_id=instagram_id,
        instagram_username="zukko.demo",
        instagram_name="Zukko o'quv markazi",
        instagram_biography="IELTS · Dasturlash · Matematika · Rus tili. Toshkent.",
        instagram_followers=18_420,
        instagram_follows=312,
        instagram_posts=486,
        instagram_profile_synced_at=now,
        is_active=True,
        is_current=True,
        business_external_id=business_id,
        business_name="Zukko Education",
        business_ids=[business_id],
        business_state="business",
        synced_at=now,
        forms_synced_at=now,
        created_at=opened,
    )
    db.add_all([account, page])
    db.flush()
    page.ad_account_id = account.id
    db.add_all(
        [
            PagePair(
                owner_id=owner.id,
                page_id=page.id,
                ad_account_id=account.id,
                created_at=opened,
            ),
            PageInstagram(
                owner_id=owner.id,
                page_id=page.id,
                instagram_user_id=instagram_id,
                username="zukko.demo",
                is_active=True,
                is_linked=True,
                synced_at=now,
            ),
        ]
    )
    pixel = PixelAccount(
        owner_id=owner.id,
        provider=PROVIDER,
        external_id=ids.next(),
        connection_id=connection.id,
        ad_account_id=account.id,
        name="Zukko piksel",
        is_active=True,
        last_fired_at=now - timedelta(minutes=40),
        synced_at=now,
        events_synced_at=now,
    )
    db.add(pixel)
    db.flush()

    _business(db, owner=owner, page=page)
    _billing(db, owner=owner, plan=plan, account=account, opened=opened, now=now)

    units = _adverts(
        db, owner=owner, account=account, page=page, ids=ids, today=today, now=now
    )
    metric_rows = _figures(
        db, owner=owner, account=account, units=units, today=today, now=now, rng=rng
    )
    members = _managers(
        db,
        owner=owner,
        page=page,
        account=account,
        emails=manager_emails,
        secret=secret,
        opened=opened,
    )
    leads, cards, sales = _crm(
        db,
        owner=owner,
        page=page,
        account=account,
        pixel=pixel,
        units=units,
        members=members,
        ids=ids,
        first_day=first_day,
        now=now,
        rng=rng,
    )
    db.flush()
    rates = (
        db.scalar(
            select(FxRate.day).where(FxRate.currency == "USD", FxRate.day <= today)
        )
        is not None
    )
    return Seeded(
        owner_email=address,
        manager_emails=manager_emails,
        plan=plan.name or plan.code,
        campaigns=len(CAMPAIGNS),
        leads=leads,
        cards=cards,
        sales=sales,
        metric_rows=metric_rows,
        rates=rates,
    )


def _business(db: Session, *, owner: User, page: PageAccount) -> None:
    direction = db.scalar(
        select(BusinessCategory)
        .where(BusinessCategory.is_active, BusinessCategory.preset_key == CATEGORY)
        .order_by(BusinessCategory.position)
        .limit(1)
    )
    db.add(
        Business(
            user_id=owner.id,
            page_id=page.id,
            name="Zukko o'quv markazi",
            category=CATEGORY,
            direction_id=direction.id if direction is not None else None,
            timezone=ZONE,
            country_code="UZ",
            city="Toshkent",
            lat=Decimal("41.311081"),
            lng=Decimal("69.240562"),
            contact_phone=PHONE.format(1000000),
            website="",
            offer_text=(
                "IELTS, dasturlash, matematika va rus tili kurslari. Kichik "
                "guruhlar, bepul sinov darsi, kechki va dam olish kuni guruhlari."
            ),
            working_hours={},
            locales=[],
            audience_gender="all",
            regions=[],
        )
    )


def _billing(
    db: Session,
    *,
    owner: User,
    plan: Plan,
    account: AdAccount,
    opened: datetime,
    now: datetime,
) -> None:
    from app.modules.billing.services.entitlement import new_transaction_reference

    period = int(plan.period_days or 30)
    # Far ahead on purpose: a showcase must not lapse, be offered a renewal
    # or have its adverts stopped in the middle of a recording.
    until = now + timedelta(days=365)
    subscription = Subscription(
        owner_id=owner.id,
        plan_id=plan.id,
        ad_account_id=account.id,
        status=SubscriptionStatus.ACTIVE,
        setup_completed_at=opened + timedelta(hours=2),
        started_at=opened,
        expires_at=until,
        term_started_at=opened,
        note="Namoyish hisobi",
        created_at=opened,
    )
    db.add(subscription)
    db.flush()
    seats = len(MANAGERS) - 1
    bills = [
        (InvoiceKind.PLAN, opened, int(plan.price), 0),
        (
            InvoiceKind.SEATS,
            opened + timedelta(hours=3),
            int(plan.crm_seat_price or 0) * seats,
            seats,
        ),
        (InvoiceKind.PLAN, opened + timedelta(days=period), int(plan.price), 0),
        (InvoiceKind.PLAN, opened + timedelta(days=2 * period), int(plan.price), 0),
    ]
    expires = opened
    for kind, paid_at, amount, count in bills:
        if paid_at > now:
            continue
        invoice = Invoice(
            owner_id=owner.id,
            number=_number(db),
            plan_id=plan.id,
            amount_minor=amount,
            currency=plan.currency or "UZS",
            period_days=period,
            status=InvoiceStatus.PAID,
            expires_at=paid_at + timedelta(days=1),
            paid_at=paid_at,
            subscription_id=subscription.id,
            applied_days=period if kind == InvoiceKind.PLAN else 0,
            kind=kind,
            seats=count,
            seats_minor=amount if count else 0,
            seats_from=paid_at if count else None,
            seats_until=until if count else None,
            seats_days=365 if count else 0,
            note="Namoyish hisobi",
            created_at=paid_at - timedelta(minutes=4),
        )
        db.add(invoice)
        db.flush()
        if amount:
            db.add(
                PaymentTransaction(
                    owner_id=owner.id,
                    invoice_id=invoice.id,
                    provider="demo",
                    external_id=f"demo-{uuid.uuid4().hex}",
                    reference=new_transaction_reference(),
                    state=TransactionState.PERFORMED,
                    amount_minor=amount,
                    currency=plan.currency or "UZS",
                    requested_at=paid_at - timedelta(minutes=2),
                    performed_at=paid_at,
                    created_at=paid_at - timedelta(minutes=2),
                )
            )
        before = expires
        if kind == InvoiceKind.PLAN:
            expires = max(expires, paid_at) + timedelta(days=period)
        db.add(
            SubscriptionChange(
                owner_id=owner.id,
                subscription_id=subscription.id,
                kind=HistoryKind.PAID
                if kind == InvoiceKind.PLAN
                else HistoryKind.SEATS,
                move=PlanMove.STACK,
                to_plan_id=plan.id,
                days=period if kind == InvoiceKind.PLAN else 0,
                expires_before=before if before != opened else None,
                expires_after=expires,
                invoice_id=invoice.id,
                occurred_at=paid_at,
                created_at=paid_at,
            )
        )
    db.add(
        SubscriptionChange(
            owner_id=owner.id,
            subscription_id=subscription.id,
            kind=HistoryKind.GIVEN,
            move=PlanMove.STACK,
            to_plan_id=plan.id,
            days=365,
            expires_before=expires,
            expires_after=until,
            reason="Namoyish hisobi",
            occurred_at=now,
            created_at=now,
        )
    )


def _adverts(
    db: Session,
    *,
    owner: User,
    account: AdAccount,
    page: PageAccount,
    ids: _Ids,
    today: date,
    now: datetime,
) -> list[_Unit]:
    units: list[_Unit] = []
    for spec in CAMPAIGNS:
        objective, optimization, destination, action, goal = OBJECTIVES[spec.kind]
        born = _at(today - timedelta(days=spec.started), 10.25)
        running = spec.stopped is None
        status = "ACTIVE" if running else "PAUSED"
        delivery = "active" if running else "paused"
        campaign_external = ids.next()
        form: LeadForm | None = None
        if spec.kind == "lead":
            form = LeadForm(
                owner_id=owner.id,
                provider=PROVIDER,
                external_id=ids.next(),
                page_id=page.id,
                name=f"{spec.course} - ariza",
                questions_raw=[
                    {"key": "full_name", "type": "FULL_NAME", "label": "Ism"},
                    {"key": "phone_number", "type": "PHONE", "label": "Telefon"},
                    {
                        "key": "qachon",
                        "type": "CUSTOM",
                        "label": "Qachon boshlamoqchisiz?",
                        "options": [
                            {"key": "hozir", "value": "Shu hafta"},
                            {"key": "oy", "value": "Shu oy ichida"},
                            {"key": "keyin", "value": "Hali aniq emas"},
                        ],
                    },
                ],
                privacy_policy_url="",
                locale="uz_UZ",
                status="ACTIVE",
                status_raw="ACTIVE",
                created_time=born,
                synced_at=now,
                swept_at=now,
                created_at=born,
            )
            db.add(form)
            db.flush()
        campaign = Campaign(
            owner_id=owner.id,
            provider=PROVIDER,
            external_id=campaign_external,
            name=spec.name,
            status=status,
            effective_status=status,
            delivery=delivery,
            synced_at=now,
            ad_account_id=account.id,
            objective_raw=objective,
            currency="USD",
            special_ad_categories=[],
            created_time=born,
            created_at=born,
        )
        db.add(campaign)
        db.flush()
        refs: dict[str, Any] = {"campaign": campaign_external}
        if form is not None:
            refs["form"] = form.external_id
        learning = spec.started <= 14 and running
        for group in spec.groups:
            adset_external = ids.next()
            adset = AdSet(
                owner_id=owner.id,
                provider=PROVIDER,
                external_id=adset_external,
                name=group.name,
                status=status,
                effective_status=status if running else "CAMPAIGN_PAUSED",
                delivery=delivery,
                synced_at=now,
                campaign_id=campaign.id,
                optimization_goal_raw=optimization,
                billing_event_raw="IMPRESSIONS",
                destination_type_raw=destination,
                daily_budget_minor=round(spec.daily_usd * group.share * 100),
                currency="USD",
                targeting_raw={
                    "age_min": group.age[0],
                    "age_max": group.age[1],
                    "geo_locations": {"countries": ["UZ"]},
                    "publisher_platforms": ["instagram", "facebook"],
                },
                promoted_object_raw={"page_id": page.external_id},
                learning_status="LEARNING" if learning else "SUCCESS",
                is_learning=learning,
                start_time=born,
                created_at=born,
            )
            db.add(adset)
            db.flush()
            refs.setdefault("adset", []).append(adset_external)
            for advert in group.ads:
                creative_external, ad_external = ids.next(), ids.next()
                db.add(
                    AdCreative(
                        owner_id=owner.id,
                        provider=PROVIDER,
                        external_id=creative_external,
                        ad_account_id=account.id,
                        name=advert.name,
                        status="ACTIVE",
                        kind="video" if advert.video else "image",
                        message=advert.message,
                        headline=advert.headline,
                        call_to_action=action,
                        page_id=page.external_id,
                        instagram_user_id=page.instagram_user_id,
                        synced_at=now,
                        created_at=born,
                    )
                )
                db.add(
                    Ad(
                        owner_id=owner.id,
                        provider=PROVIDER,
                        external_id=ad_external,
                        name=advert.name,
                        status=status,
                        effective_status=status if running else "CAMPAIGN_PAUSED",
                        delivery=delivery,
                        synced_at=now,
                        adset_id=adset.id,
                        creative_external_id=creative_external,
                        lead_form_external_id=form.external_id if form else "",
                        created_at=born,
                    )
                )
                refs.setdefault("creative", []).append(creative_external)
                refs.setdefault("ad", []).append(ad_external)
                units.append(
                    _Unit(
                        campaign=spec,
                        group=group,
                        spec=advert,
                        campaign_id=campaign_external,
                        adset_id=adset_external,
                        ad_id=ad_external,
                        form_id=form.id if form else None,
                        form_external=form.external_id if form else "",
                    )
                )
        db.add(
            CampaignLaunch(
                owner_id=owner.id,
                provider=PROVIDER,
                ad_account_id=account.id,
                page_id=page.id,
                answers={"goal": goal},
                preset_key=CATEGORY,
                campaign_name=spec.name[:80],
                daily_budget_minor=round(spec.daily_usd * 100),
                currency="USD",
                start_date=born.date(),
                status="created",
                step="verify",
                progress=100,
                created_refs=refs,
                lead_form_external_id=form.external_id if form else "",
                started_at=born,
                finished_at=born + timedelta(minutes=3),
                delivery_started_at=born + timedelta(hours=2),
                created_at=born - timedelta(minutes=10),
            )
        )
    db.flush()
    return units


def _day_factor(
    rng: random.Random, day: date, spec: CampaignSpec, today: date
) -> float:
    ago = (today - day).days
    if ago >= spec.started or (spec.stopped is not None and ago < spec.stopped):
        return 0.0
    weekday = (1.0, 1.04, 1.02, 1.0, 0.94, 0.86, 0.9)[day.weekday()]
    warming = 0.55 + 0.15 * (spec.started - ago) if spec.started - ago <= 3 else 1.0
    return weekday * min(warming, 1.0) * rng.uniform(0.9, 1.06)


def _row(
    *,
    owner: User,
    account: AdAccount,
    level: str,
    external: str,
    unit: _Unit,
    day: date,
    name: str,
    numbers: dict[str, int],
    now: datetime,
) -> dict[str, Any]:
    spend, shown, clicks = numbers["spend"], numbers["impressions"], numbers["clicks"]
    reach = max(numbers["reach"], 1) if shown else 0
    leads = numbers["leads"]
    return {
        "owner_id": owner.id,
        "provider": PROVIDER,
        "external_id": external,
        "ad_account_id": account.id,
        "level": level,
        "campaign_external_id": unit.campaign_id,
        "adset_external_id": unit.adset_id if level != "campaign" else "",
        "ad_external_id": unit.ad_id if level == "ad" else "",
        "date": day,
        "spend_minor": spend,
        "currency": "USD",
        "impressions": shown,
        "reach": reach,
        "clicks": clicks,
        "leads_reported": leads,
        "results_reported": numbers["results"],
        "profile_visits": numbers["profile"],
        "frequency": Decimal(shown) / Decimal(reach) if reach else Decimal(0),
        "ctr": Decimal(clicks * 100) / Decimal(shown) if shown else Decimal(0),
        "cpm_minor": round(spend * 1000 / shown) if shown else 0,
        "cpc_minor": round(spend / clicks) if clicks else 0,
        "object_name": name,
        "optimization_goal_raw": OBJECTIVES[unit.campaign.kind][1],
        "unique_clicks": round(clicks * 0.93),
        "inline_link_clicks": numbers["link"],
        "unique_inline_link_clicks": round(numbers["link"] * 0.94),
        "outbound_clicks": numbers["outbound"],
        "landing_page_views": numbers["landing"],
        "video_plays": numbers["plays"],
        "video_thruplays": numbers["thru"],
        "video_p25": round(numbers["plays"] * 0.46),
        "video_p50": round(numbers["plays"] * 0.27),
        "video_p75": round(numbers["plays"] * 0.16),
        "video_p100": round(numbers["plays"] * 0.09),
        "video_views_3s": round(numbers["plays"] * 0.62),
        "reactions": numbers["reactions"],
        "comments": numbers["comments"],
        "shares": numbers["shares"],
        "saves": numbers["saves"],
        "cost_per_lead_minor": round(spend / leads) if leads else 0,
        "quality_ranking": "",
        "engagement_rate_ranking": "",
        "conversion_rate_ranking": "",
        "attribution_setting": "7d_click_1d_view",
        "synced_at": now,
        "created_at": now,
        "updated_at": now,
    }


_KEYS = (
    "spend", "impressions", "reach", "clicks", "leads", "results", "profile",
    "link", "outbound", "landing", "plays", "thru", "reactions", "comments",
    "shares", "saves",
)  # fmt: skip


def _ranking(pull: float) -> tuple[str, str, str]:
    if pull >= 1.1:
        return ("above_average", "above_average", "average")
    if pull <= 0.85:
        return ("average", "below_average_35", "below_average_35")
    return ("average", "average", "average")


def _figures(
    db: Session,
    *,
    owner: User,
    account: AdAccount,
    units: list[_Unit],
    today: date,
    now: datetime,
    rng: random.Random,
) -> int:
    """Sixty days of each advert, and its group's and campaign's as their sums."""
    part_of_today = (_local(now).hour * 60 + _local(now).minute) / 1440
    rows: list[dict[str, Any]] = []
    cuts: list[dict[str, Any]] = []
    per_ad: dict[str, dict[date, dict[str, int]]] = {}
    per_adset: dict[str, dict[date, dict[str, int]]] = {}
    per_campaign: dict[str, dict[date, dict[str, int]]] = {}
    lead_units: dict[str, _Unit] = {}
    for back in range(DAYS - 1, -1, -1):
        day = today - timedelta(days=back)
        share_of_day = max(part_of_today, 0.02) if back == 0 else 1.0
        factors: dict[str, float] = {}
        for unit in units:
            spec = unit.campaign
            if spec.key not in factors:
                factors[spec.key] = _day_factor(rng, day, spec, today)
            factor = factors[spec.key] * share_of_day
            if factor <= 0:
                continue
            pull = unit.spec.pull
            dollars = spec.daily_usd * unit.group.share * unit.spec.share * factor
            spend = round(dollars * rng.uniform(0.96, 1.0) * 100)
            cpm = spec.cpm * rng.uniform(0.9, 1.12)
            shown = round(spend / 100 / cpm * 1000)
            clicks = round(shown * spec.ctr * pull * rng.uniform(0.88, 1.14))
            link = round(clicks * 0.78)
            results = _poisson(rng, spend / 100 / spec.price * pull)
            if spec.kind == "click":
                results = link
            plays = round(shown * 0.58) if unit.spec.video else 0
            numbers = {
                "spend": spend,
                "impressions": shown,
                "reach": round(shown / rng.uniform(1.12, 1.24)),
                "clicks": clicks,
                "leads": results if spec.kind == "lead" else 0,
                "results": results,
                "profile": round(clicks * 0.11),
                "link": link,
                "outbound": link if spec.kind == "click" else 0,
                "landing": round(link * 0.74) if spec.kind == "click" else 0,
                "plays": plays,
                "thru": round(plays * 0.13),
                "reactions": round(clicks * 0.42),
                "comments": round(clicks * 0.035),
                "shares": round(clicks * 0.05),
                "saves": round(clicks * 0.07),
            }
            if spec.kind == "lead":
                unit.leads[day] = results
                lead_units[unit.ad_id] = unit
            per_ad.setdefault(unit.ad_id, {})[day] = numbers
            for store, key in (
                (per_adset, unit.adset_id),
                (per_campaign, unit.campaign_id),
            ):
                total = store.setdefault(key, {}).setdefault(
                    day, dict.fromkeys(_KEYS, 0)
                )
                for name in _KEYS:
                    total[name] += numbers[name]
            line = _row(
                owner=owner,
                account=account,
                level=MetricLevel.AD,
                external=unit.ad_id,
                unit=unit,
                day=day,
                name=unit.spec.name,
                numbers=numbers,
                now=now,
            )
            (
                line["quality_ranking"],
                line["engagement_rate_ranking"],
                line["conversion_rate_ranking"],
            ) = _ranking(pull)
            rows.append(line)
    first_of: dict[str, _Unit] = {}
    for unit in units:
        first_of.setdefault(unit.adset_id, unit)
        first_of.setdefault(unit.campaign_id, unit)
    for level, store in (
        (MetricLevel.ADSET, per_adset),
        (MetricLevel.CAMPAIGN, per_campaign),
    ):
        for external, days in store.items():
            unit = first_of[external]
            name = unit.group.name if level == MetricLevel.ADSET else unit.campaign.name
            for day, numbers in days.items():
                # People do not add up: a group reaches fewer than its adverts' sum.
                shown = dict(numbers, reach=round(numbers["reach"] * 0.93))
                rows.append(
                    _row(
                        owner=owner,
                        account=account,
                        level=level,
                        external=external,
                        unit=unit,
                        day=day,
                        name=name,
                        numbers=shown,
                        now=now,
                    )
                )
                if level == MetricLevel.ADSET:
                    cuts += _cuts(
                        owner=owner,
                        account=account,
                        unit=unit,
                        day=day,
                        numbers=shown,
                        now=now,
                        rng=rng,
                    )
    for start in range(0, len(rows), 1000):
        db.execute(insert(MetricsDaily), rows[start : start + 1000])
    for start in range(0, len(cuts), 2000):
        db.execute(insert(MetricsBreakdown), cuts[start : start + 2000])
    people = _people(
        owner=owner,
        account=account,
        units=units,
        stores={
            MetricLevel.AD: per_ad,
            MetricLevel.ADSET: per_adset,
            MetricLevel.CAMPAIGN: per_campaign,
        },
        today=today,
        now=now,
    )
    if people:
        db.execute(insert(PeopleCount), people)
    return len(rows) + len(cuts) + len(people)


def _split(total: int, weights: list[float]) -> list[int]:
    whole = sum(weights) or 1.0
    parts = [int(total * weight / whole) for weight in weights]
    for index in range(total - sum(parts)):
        parts[index % len(parts)] += 1
    return parts


def _cuts(
    *,
    owner: User,
    account: AdAccount,
    unit: _Unit,
    day: date,
    numbers: dict[str, int],
    now: datetime,
    rng: random.Random,
) -> list[dict[str, Any]]:
    low, high = unit.group.age
    bands = [
        band for band in AGE_BANDS if int(band[:2]) <= high and int(band[3:]) >= low
    ]
    people = [
        (
            f"{band}|{gender}",
            share * rng.uniform(0.85, 1.15),
            1.1 if gender == "female" else 0.92,
        )
        for band in bands
        for gender, share in (
            ("female", unit.group.women),
            ("male", 1 - unit.group.women),
        )
    ]
    places = [
        (f"{platform}|{position}", share * rng.uniform(0.9, 1.1), worth)
        for platform, position, share, worth in PLACES
    ]
    regions = [
        (name, share * rng.uniform(0.9, 1.1), worth) for name, share, worth in REGIONS
    ]
    out: list[dict[str, Any]] = []
    for kind, segments in (
        (BreakdownKind.AGE_GENDER, people),
        (BreakdownKind.PLATFORM_POSITION, places),
        (BreakdownKind.REGION, regions),
    ):
        weights = [share for _, share, _ in segments]
        worth = [share * value for _, share, value in segments]
        spend = _split(numbers["spend"], weights)
        shown = _split(numbers["impressions"], weights)
        reach = _split(numbers["reach"], weights)
        clicks = _split(numbers["clicks"], worth)
        leads = _split(numbers["leads"], worth)
        for index, (value, _, _) in enumerate(segments):
            if not shown[index]:
                continue
            out.append(
                {
                    "owner_id": owner.id,
                    "provider": PROVIDER,
                    "external_id": unit.adset_id,
                    "ad_account_id": account.id,
                    "level": MetricLevel.ADSET,
                    "campaign_external_id": unit.campaign_id,
                    "adset_external_id": unit.adset_id,
                    "ad_external_id": "",
                    "date": day,
                    "breakdown_kind": kind,
                    "breakdown_value": value,
                    "spend_minor": spend[index],
                    "currency": "USD",
                    "impressions": shown[index],
                    "reach": reach[index],
                    "clicks": clicks[index],
                    "leads_reported": leads[index],
                    "synced_at": now,
                    "created_at": now,
                    "updated_at": now,
                }
            )
    return out


def _people(
    *,
    owner: User,
    account: AdAccount,
    units: list[_Unit],
    stores: dict[Any, dict[str, dict[date, dict[str, int]]]],
    today: date,
    now: datetime,
) -> list[dict[str, Any]]:
    """How many different people each range reached: fewer than its days'
    sum, and fewer the longer it is, as the same people come back."""
    ranges = list(dict.fromkeys([*people_ranges(today), *extra_people_ranges(today)]))
    owners: dict[str, _Unit] = {}
    for unit in units:
        owners.setdefault(unit.ad_id, unit)
        owners.setdefault(unit.adset_id, unit)
        owners.setdefault(unit.campaign_id, unit)
    out: list[dict[str, Any]] = []

    def line(
        level: str,
        external: str,
        unit: _Unit | None,
        since: date,
        until: date,
        reach: int,
        clicks: int,
    ) -> None:
        if reach <= 0:
            return
        out.append(
            {
                "owner_id": owner.id,
                "provider": PROVIDER,
                "external_id": external,
                "ad_account_id": account.id,
                "level": level,
                "campaign_external_id": unit.campaign_id if unit else "",
                "adset_external_id": unit.adset_id
                if unit and level != "campaign"
                else "",
                "ad_external_id": unit.ad_id if unit and level == "ad" else "",
                "since": since,
                "until": until,
                "reach": reach,
                "recallers": round(reach * 0.071),
                "unique_link_clicks": clicks,
                "synced_at": now,
                "created_at": now,
                "updated_at": now,
            }
        )

    for since, until in ranges:
        days = (until - since).days + 1
        repeat = 1 + 0.42 * math.log1p(days - 1)
        whole_reach = whole_clicks = 0
        for level, store in stores.items():
            for external, by_day in store.items():
                inside = [n for day, n in by_day.items() if since <= day <= until]
                if not inside:
                    continue
                reach = round(sum(n["reach"] for n in inside) / repeat)
                clicks = round(sum(n["link"] for n in inside) * 0.9)
                line(
                    str(level), external, owners[external], since, until, reach, clicks
                )
                if level == MetricLevel.CAMPAIGN:
                    whole_reach += reach
                    whole_clicks += clicks
        line(
            "account",
            account.external_id,
            None,
            since,
            until,
            round(whole_reach * 0.84),
            whole_clicks,
        )
    return out


def _managers(
    db: Session,
    *,
    owner: User,
    page: PageAccount,
    account: AdAccount,
    emails: tuple[str, ...],
    secret: str,
    opened: datetime,
) -> list[User]:
    people: list[User] = []
    for (name, _share, _skill, _minutes), email in zip(MANAGERS, emails, strict=True):
        joined = opened + timedelta(hours=4 + len(people))
        user = User(
            email=email,
            password=secret,
            full_name=name,
            phone="",
            language="uz",
            crm_owner_id=owner.id,
            date_joined=joined,
            email_verified_at=joined,
        )
        db.add(user)
        db.flush()
        db.add(
            CrmMember(
                owner_id=owner.id,
                page_id=page.id,
                ad_account_id=account.id,
                user_id=user.id,
                is_active=True,
                takes_leads=True,
                # The person trying the board signs in with the password
                # they chose for the showcase: nothing to change first.
                must_change_password=False,
                kpi_percent=5,
                kpi_currency="UZS",
                created_at=joined,
            )
        )
        people.append(user)
    db.flush()
    return people


@dataclass(slots=True)
class _Card:
    id: uuid.UUID
    lead_id: uuid.UUID
    arrived: datetime
    stage: uuid.UUID
    assignee: uuid.UUID
    updated: datetime
    qualified_at: datetime | None = None
    closed_at: datetime | None = None
    won_minor: int | None = None
    reason: uuid.UUID | None = None
    reason_name: str = ""
    attempts: int = 0
    note: str = ""
    note_at: datetime | None = None
    due_at: datetime | None = None
    due_note: str = ""
    junk_at: datetime | None = None
    # When its manager pressed «Olish»; none while it waits in the first column.
    taken_at: datetime | None = None


def _crm(
    db: Session,
    *,
    owner: User,
    page: PageAccount,
    account: AdAccount,
    pixel: PixelAccount,
    units: list[_Unit],
    members: list[User],
    ids: _Ids,
    first_day: date,
    now: datetime,
    rng: random.Random,
) -> tuple[int, int, int]:
    pair = {"owner_id": owner.id, "page_id": page.id, "ad_account_id": account.id}
    began = _at(first_day - timedelta(days=1), 12)
    columns = (
        (str(PRESET_LABELS[Preset.NEW]), StageKind.NEW, "#0A64E0", False),
        ("Bog'lanildi", StageKind.OPEN, "#7C6CFF", False),
        (str(PRESET_LABELS[Preset.INFORMED]), StageKind.OPEN, "#0891B2", True),
        ("Sinov darsi", StageKind.OPEN, "#B7791F", True),
        (str(PRESET_LABELS[Preset.PAYMENT]), StageKind.OPEN, "#C2255C", True),
        (str(PRESET_LABELS[Preset.WON]), StageKind.WON, "#0E7F5C", True),
        (str(PRESET_LABELS[Preset.LOST]), StageKind.LOST, "#C2262E", False),
        (str(PRESET_LABELS[Preset.JUNK]), StageKind.JUNK, "#4A5878", False),
    )
    stages: list[CrmStage] = []
    for position, (name, kind, color, quality) in enumerate(columns):
        stage = CrmStage(
            **pair,
            name=name,
            color=color,
            kind=kind,
            position=position,
            counts_as_quality=quality,
            created_at=began,
        )
        db.add(stage)
        stages.append(stage)
    reasons: list[CrmLostReason] = []
    for position, name in enumerate(DEFAULT_LOST_REASONS):
        reason = CrmLostReason(
            **pair, name=str(name), position=position, created_at=began
        )
        db.add(reason)
        reasons.append(reason)
    db.add(
        CrmSetup(
            **pair,
            state=SetupState.ON,
            step=4,
            since=Since.DATE,
            leads_since=began,
            every_ad=True,
            take_new_ads=True,
            # Whoever presses «Olish» first: the wait before it is the
            # first-response time the statistics show.
            distribution=Distribution.CLAIM,
            currency="UZS",
            enabled_at=began,
            created_at=began,
        )
    )
    db.flush()
    new, talk, told, trial, pay, won, lost, junk = stages
    name_of = {stage.id: stage.name for stage in stages}
    kind_of = {stage.id: str(stage.kind) for stage in stages}
    by_user = {user.id: user for user in members}
    skill = {user.id: MANAGERS[i][2] for i, user in enumerate(members)}
    speed = {user.id: MANAGERS[i][3] for i, user in enumerate(members)}

    leads: list[dict[str, Any]] = []
    cards: list[_Card] = []
    activities: list[dict[str, Any]] = []
    moves: list[dict[str, Any]] = []
    signals: list[dict[str, Any]] = []
    phone = rng.randrange(1_000_000, 8_000_000)

    def say(
        card: _Card,
        at: datetime,
        kind: ActivityKind,
        text: str = "",
        actor: uuid.UUID | None = None,
    ) -> None:
        activities.append(
            {
                "id": uuid.uuid4(),
                "owner_id": owner.id,
                "card_id": card.id,
                "actor_id": actor,
                "kind": str(kind),
                "text": text[:500],
                "created_at": at,
                "updated_at": at,
            }
        )
        card.updated = max(card.updated, at)

    def step(
        card: _Card,
        at: datetime,
        target: CrmStage,
        actor: uuid.UUID | None,
        *,
        told: bool = True,
    ) -> None:
        """The card changes column. ``told=False`` where the board writes its
        own line for the change - a sale, a refusal - and none for the move."""
        moves.append(
            {
                "id": uuid.uuid4(),
                "owner_id": owner.id,
                "card_id": card.id,
                "from_stage_id": card.stage,
                "from_kind": kind_of[card.stage],
                "to_stage_id": target.id,
                "to_kind": str(target.kind),
                "at": at,
                "rebuilt": False,
                "created_at": at,
                "updated_at": at,
            }
        )
        if told:
            say(
                card,
                at,
                ActivityKind.MOVED,
                f"{name_of[card.stage]} → {target.name}",
                actor,
            )
        card.stage = target.id
        card.updated = max(card.updated, at)
        if target.counts_as_quality and card.qualified_at is None:
            card.qualified_at = at
            say(card, at, ActivityKind.QUALIFIED, "", actor)

    def live(
        card: _Card,
        unit: _Unit | None,
        manual_by: uuid.UUID | None = None,
        sure: str = "",
    ) -> None:
        """One customer from arriving to wherever today finds them."""
        who = card.assignee
        t = card.arrived
        moves.append(
            {
                "id": uuid.uuid4(),
                "owner_id": owner.id,
                "card_id": card.id,
                "from_stage_id": None,
                "from_kind": "",
                "to_stage_id": new.id,
                "to_kind": str(new.kind),
                "at": t,
                "rebuilt": False,
                "created_at": t,
                "updated_at": t,
            }
        )
        say(
            card,
            t,
            ActivityKind.ADDED if manual_by else ActivityKind.ARRIVED,
            "",
            manual_by,
        )
        if manual_by:
            card.taken_at = t
            say(card, t, ActivityKind.ASSIGNED, by_user[who].full_name)
        course = unit.campaign if unit else CAMPAIGNS[0]
        chance = skill[who] * (unit.spec.pull if unit else 1.6)
        draw = rng.random()
        fate = sure or (
            "junk"
            if draw < 0.11 and not manual_by
            else "won"
            if draw < 0.11 + chance
            else "lost"
            if draw < 0.11 + chance + 0.46
            else "open"
        )
        # A board that is worked does not keep a month-old lead open: most
        # of those were let go in the end.
        if fate == "open" and (now - card.arrived).days > 9 and rng.random() < 0.82:
            fate = "lost"
        wait = rng.lognormvariate(math.log(speed[who]), 0.9)
        t = _working(t) + timedelta(minutes=min(wait, 60 * 30))
        t = _working(t)
        plan: list[tuple[datetime, str]] = []
        if fate == "junk":
            plan.append((t, "junk"))
        else:
            for _ in range(rng.choice((0, 0, 0, 1, 1, 2))):
                plan.append((t, "no_answer"))
                t = _working(t + timedelta(hours=rng.uniform(3, 22)))
            plan.append((t, "talk"))
            rest = {
                "won": 4,
                "lost": rng.choice((0, 1, 1, 2)),
                "open": rng.choice((0, 0, 1, 1, 2, 3)),
            }[fate]
            for name in ("told", "trial", "pay")[:rest]:
                if name == "trial" and fate == "won" and rng.random() < 0.3:
                    continue
                gap = {"told": (0.4, 20), "trial": (20, 80), "pay": (18, 90)}[name]
                t = _working(t + timedelta(hours=rng.uniform(*gap)))
                plan.append((t, name))
            if fate in ("won", "lost"):
                t = _working(t + timedelta(hours=rng.uniform(6, 90)))
                plan.append((t, fate))
            elif rng.random() < 0.75:
                plan.append((t + timedelta(minutes=3), "due"))
        for at, what in plan:
            if at > now:
                break
            if card.taken_at is None:
                card.taken_at = at
                say(card, at, ActivityKind.TAKEN, name_of[card.stage], who)
            if what == "no_answer":
                card.attempts += 1
                say(card, at, ActivityKind.NO_ANSWER, str(card.attempts), who)
            elif what == "junk":
                step(card, at, junk, who)
                say(card, at, ActivityKind.UNQUALIFIED, "", who)
                card.closed_at = card.junk_at = at
                card.qualified_at = None
            elif what in ("talk", "told", "trial", "pay"):
                target = {"talk": talk, "told": told, "trial": trial, "pay": pay}[what]
                step(card, at, target, who)
                texts = {
                    "talk": NOTES_TALK,
                    "told": NOTES_TALK,
                    "trial": NOTES_TRIAL,
                    "pay": NOTES_PAY,
                }[what]
                if rng.random() < 0.7:
                    card.note, card.note_at = (
                        rng.choice(texts),
                        at + timedelta(minutes=2),
                    )
                    say(card, card.note_at, ActivityKind.NOTE, card.note, who)
            elif what == "due":
                ahead = rng.choice((-30, -5, 2, 5, 20, 26, 44, 50, 70))
                card.due_at = _working(now + timedelta(hours=ahead))
                card.due_note = rng.choice(DUE_NOTES)
                when = _local(card.due_at).strftime("%d.%m.%Y %H:%M")
                say(card, at, ActivityKind.DUE_SET, f"{when} · {card.due_note}", who)
            elif what == "won":
                low, high = course.check or (1_500_000, 3_000_000)
                amount = rng.randrange(low, high + 1, 100_000) if high else 1_800_000
                card.won_minor = amount * 100
                card.closed_at = at
                card.due_at, card.due_note = None, ""
                step(card, at, won, who, told=False)
                note = rng.choice(NOTES_WON)
                if note:
                    card.note, card.note_at = note, at
                text = format_minor(amount_minor=card.won_minor, currency="UZS")
                say(
                    card,
                    at,
                    ActivityKind.WON,
                    f"{text} · {note}" if note else text,
                    who,
                )
            elif what == "lost":
                reason = rng.choices(reasons, weights=LOST_WEIGHTS)[0]
                card.reason, card.reason_name = reason.id, reason.name
                card.closed_at = at
                card.due_at, card.due_note = None, ""
                step(card, at, lost, who, told=False)
                say(card, at, ActivityKind.LOST, reason.name, who)

    turn = 0
    weights = [share for _, share, _, _ in MANAGERS]
    for unit in units:
        for day, count in sorted(unit.leads.items()):
            for _ in range(count):
                hour = rng.choices(
                    range(24),
                    weights=(
                        1,
                        1,
                        1,
                        1,
                        1,
                        1,
                        2,
                        3,
                        5,
                        6,
                        7,
                        7,
                        7,
                        6,
                        6,
                        6,
                        6,
                        7,
                        8,
                        9,
                        9,
                        8,
                        6,
                        3,
                    ),
                )[0]
                arrived = _at(day, hour + rng.random())
                if arrived > now:
                    arrived = now - timedelta(minutes=rng.uniform(3, 90))
                phone += rng.randrange(1, 200)
                first, last = rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES)
                if first[-1] == "a" or first in ("Gulnora", "Charos", "Yulduz"):
                    last += "a"
                name = f"{first} {last}"
                number = PHONE.format(phone)
                when = rng.choice(("Shu hafta", "Shu oy ichida", "Hali aniq emas"))
                lead_id = uuid.uuid4()
                leads.append(
                    {
                        "id": lead_id,
                        "owner_id": owner.id,
                        "provider": PROVIDER,
                        "leadgen_id": ids.next(),
                        "form_id": unit.form_id,
                        "campaign_external_id": unit.campaign_id,
                        "adset_external_id": unit.adset_id,
                        "ad_external_id": unit.ad_id,
                        "full_name": name,
                        "phone_e164": number,
                        "city": rng.choice(CITIES),
                        "field_data_raw": [
                            {"name": "full_name", "values": [name]},
                            {"name": "phone_number", "values": [number]},
                            {"name": "qachon", "values": [when]},
                        ],
                        "answers": {"qachon": [when]},
                        "submitted_at": arrived,
                        "received_at": arrived + timedelta(seconds=rng.uniform(2, 40)),
                        "fetched_at": arrived + timedelta(seconds=45),
                        "is_test": False,
                        "is_organic": False,
                        "created_at": arrived,
                        "updated_at": arrived,
                    }
                )
                who = (
                    rng.choices(members, weights=weights)[0]
                    if turn % 4
                    else members[turn % len(members)]
                )
                turn += 1
                card = _Card(
                    id=uuid.uuid4(),
                    lead_id=lead_id,
                    arrived=arrived,
                    stage=new.id,
                    assignee=who.id,
                    updated=arrived,
                )
                live(card, unit)
                cards.append(card)
    # A few customers who walked in or called: typed onto the board by hand.
    for back in (41, 33, 24, 17, 12, 9, 4, 1):
        arrived = _working(now - timedelta(days=back, hours=rng.uniform(1, 6)))
        if arrived > now:
            continue
        phone += rng.randrange(1, 200)
        who = rng.choice(members)
        lead_id = uuid.uuid4()
        leads.append(
            {
                "id": lead_id,
                "owner_id": owner.id,
                "provider": MANUAL_PROVIDER,
                "leadgen_id": f"manual:{uuid.uuid4().hex}",
                "form_id": None,
                "campaign_external_id": "",
                "adset_external_id": "",
                "ad_external_id": "",
                "full_name": f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}",
                "phone_e164": PHONE.format(phone),
                "city": "",
                "field_data_raw": [],
                "answers": {},
                "submitted_at": arrived,
                "received_at": arrived,
                "fetched_at": None,
                "is_test": False,
                "is_organic": True,
                "created_at": arrived,
                "updated_at": arrived,
            }
        )
        card = _Card(
            id=uuid.uuid4(),
            lead_id=lead_id,
            arrived=arrived,
            stage=new.id,
            assignee=who.id,
            updated=arrived,
        )
        live(card, None, manual_by=who.id, sure="won" if back in (24, 12) else "")
        cards.append(card)

    midnight = datetime.combine(_local(now).date(), time(0), tzinfo=TZ)
    advert_leads = {row["id"] for row in leads if not row["is_organic"]}
    sent_cards: dict[uuid.UUID, datetime] = {}
    for card in cards:
        if card.lead_id not in advert_leads:
            continue
        facts = (
            ("qualified", card.qualified_at, None),
            ("unqualified", card.junk_at, None),
            ("converted", card.closed_at if card.won_minor else None, card.won_minor),
        )
        for stage, at, value in facts:
            if at is None or at >= midnight:
                continue
            sent = datetime.combine(
                _local(at).date() + timedelta(days=1), time(2, 40), TZ
            )
            if sent > now:
                continue
            signals.append(
                {
                    "id": uuid.uuid4(),
                    "owner_id": owner.id,
                    "lead_id": card.lead_id,
                    "ad_account_id": account.id,
                    "stage": stage,
                    "source": str(SignalSource.INTERNAL),
                    "occurred_at": at,
                    "value_minor": value,
                    "currency": "UZS" if value else "",
                    "status": str(SignalStatus.SENT),
                    "sent_at": sent,
                    "attempts": 1,
                    "dataset_id": pixel.external_id,
                    "created_at": sent,
                    "updated_at": sent,
                }
            )
            sent_cards[card.id] = max(sent_cards.get(card.id, sent), sent)

    for start in range(0, len(leads), 500):
        db.execute(insert(Lead), leads[start : start + 500])
    rows = [
        {
            "id": card.id,
            **pair,
            "lead_id": card.lead_id,
            "stage_id": card.stage,
            "assignee_id": card.assignee if card.taken_at else None,
            "due_at": card.due_at,
            "due_note": card.due_note,
            "attempts": card.attempts,
            "last_note": card.note,
            "last_note_at": card.note_at,
            "returned": 0,
            "qualified_at": card.qualified_at,
            "won_amount_minor": card.won_minor,
            "currency": "UZS" if card.won_minor else "",
            "lost_reason_id": card.reason,
            "lost_reason_name": card.reason_name,
            "closed_at": card.closed_at,
            "taken_at": card.taken_at,
            "quality_sent_at": sent_cards.get(card.id),
            "created_at": card.arrived,
            "updated_at": card.updated,
        }
        for card in cards
    ]
    for start in range(0, len(rows), 500):
        db.execute(insert(CrmCard), rows[start : start + 500])
    for start in range(0, len(activities), 1000):
        db.execute(insert(CrmActivity), activities[start : start + 1000])
    for start in range(0, len(moves), 1000):
        db.execute(insert(CrmStageMove), moves[start : start + 1000])
    for start in range(0, len(signals), 1000):
        db.execute(insert(LeadSignal), signals[start : start + 1000])
    for form_id in {unit.form_id for unit in units if unit.form_id}:
        form = db.get(LeadForm, form_id)
        if form is not None:
            form.leads_count = sum(1 for row in leads if row["form_id"] == form_id)
    return len(leads), len(cards), sum(1 for card in cards if card.won_minor)
