from app.common.choices import Choices


class SpecialAdCategory(Choices):
    HOUSING = "housing"
    EMPLOYMENT = "employment"
    CREDIT = "credit"


class LinkKind(Choices):
    """What of a network a business is tied to."""

    META_PAIR = "meta_pair"
    AD_ACCOUNT = "ad_account"


class MemberRole(Choices):
    """What a person does in a business. A role is a ready set of grants,
    not a rule of its own: the grants are what is checked."""

    TARGETOLOG = "targetolog"
    SALES = "sales"


MEMBER_ROLE_LABELS = {
    MemberRole.TARGETOLOG: "Targetolog",
    MemberRole.SALES: "Sotuv manageri",
}


class GrantArea(Choices):
    ADS = "ads"
    CRM = "crm"


GRANT_AREA_LABELS = {
    GrantArea.ADS: "Reklama",
    GrantArea.CRM: "CRM",
}


class GrantLevel(Choices):
    VIEW = "view"
    EDIT = "edit"


GRANT_LEVEL_LABELS = {
    GrantLevel.VIEW: "Ko'rish",
    GrantLevel.EDIT: "O'zgartirish",
}

# The CRM grant for leads no network brought: typed in by hand, a site form,
# an import.
OTHER_SOURCE = "other"


SPECIAL_AD_CATEGORY_LABELS = {
    SpecialAdCategory.HOUSING: "Ko'chmas mulk",
    SpecialAdCategory.EMPLOYMENT: "Ish o'rni",
    SpecialAdCategory.CREDIT: "Kredit",
}
CATEGORY_TRANSLATIONS: dict[str, tuple[str, str]] = {
    "agriculture": ("Сельское хозяйство", "Agriculture"),
    "auto": ("Автосервис / автосалон", "Car service / dealership"),
    "beauty": ("Салон красоты", "Beauty salon"),
    "construction": ("Строительство / ремонт", "Construction / repairs"),
    "ecommerce": ("Интернет-магазин", "Online shop"),
    "education": ("Учебный центр", "Training centre"),
    "finance": ("Финансы", "Finance"),
    "fitness": ("Спортзал / фитнес", "Gym / fitness"),
    "furniture": ("Мебель", "Furniture"),
    "it_software": ("IT и программы", "IT and software"),
    "kids": ("Детские товары", "Children's products"),
    "logistics": ("Логистика", "Logistics"),
    "medical": ("Клиника / медуслуги", "Clinic / medical services"),
    "real_estate": ("Недвижимость", "Real estate"),
    "restaurant": ("Ресторан / кафе", "Restaurant / cafe"),
    "retail_store": ("Магазин / торговая точка", "Shop / retail outlet"),
    "services": ("Услуги", "Services"),
    "travel": ("Путешествия / туризм", "Travel / tourism"),
}


# Who a new advert is shown to unless the owner says otherwise there.
AUDIENCE_GENDERS: tuple[str, ...] = ("all", "female", "male")
GENDER_ALL = "all"
# As Meta numbers them on an ad set: 1 men, 2 women.
GENDER_CODES: dict[str, list[int]] = {"male": [1], "female": [2]}
# Where the business works, for reading only: an advert is never aimed there by itself.
MAX_REGIONS = 10


class AdvisedGoal(Choices):
    """A goal the office may advise a kind of business: the catalogue's goal
    keys, and ``telegram``, which is ``traffic`` to a Telegram link."""

    LEADS = "leads"
    MESSAGES = "messages"
    CALLS = "calls"
    TRAFFIC = "traffic"
    SITE_LEADS = "site_leads"
    TELEGRAM = "telegram"
    PROFILE_VISITS = "profile_visits"
    VIEWS = "views"


ADVISED_GOAL_LABELS = {
    AdvisedGoal.LEADS: "Ariza yig'ish (lid forma)",
    AdvisedGoal.MESSAGES: "Xabar yozishsin",
    AdvisedGoal.CALLS: "Qo'ng'iroq",
    AdvisedGoal.TRAFFIC: "Saytga tashrif",
    AdvisedGoal.SITE_LEADS: "Saytda ariza",
    AdvisedGoal.TELEGRAM: "Telegramga o'tsin",
    AdvisedGoal.PROFILE_VISITS: "Profilga o'tsin",
    AdvisedGoal.VIEWS: "Ko'proq odam ko'rsin",
}


class SubtypeOrigin(Choices):
    AI = "ai"
    STAFF = "staff"


class TypeState(Choices):
    """How sure a business's kind is: nobody said, we guessed it from the
    page, or the business said yes to it."""

    UNSET = "unset"
    GUESSED = "guessed"
    CONFIRMED = "confirmed"


class KnowledgeSource(Choices):
    """Who a piece of knowledge came from."""

    LAUNCH_AGENT = "launch_agent"
    ASSISTANT = "assistant"
    OWNER = "owner"
    MEMBER = "member"
    STAFF = "staff"
    PAGE = "page"


KNOWLEDGE_SOURCE_LABELS = {
    KnowledgeSource.LAUNCH_AGENT: "Reklama yaratish chati",
    KnowledgeSource.ASSISTANT: "AI chat",
    KnowledgeSource.OWNER: "Biznes egasi",
    KnowledgeSource.MEMBER: "Biznes xodimi",
    KnowledgeSource.STAFF: "Ofis xodimi",
    KnowledgeSource.PAGE: "Sahifadan olingan",
}


class ItemKind(Choices):
    PRODUCT = "product"
    SERVICE = "service"
    COURSE = "course"
    OTHER = "other"


ITEM_KIND_LABELS = {
    ItemKind.PRODUCT: "Mahsulot",
    ItemKind.SERVICE: "Xizmat",
    ItemKind.COURSE: "Kurs yoki yo'nalish",
    ItemKind.OTHER: "Boshqa",
}


class ItemStatus(Choices):
    ACTIVE = "active"
    ARCHIVED = "archived"


class FactKey(Choices):
    """The facts kept about a business. The list is closed so that two
    chats write the same thing under the same name."""

    CUSTOMERS = "customers"
    AREA = "area"
    DELIVERY = "delivery"
    GUARANTEE = "guarantee"
    PAYMENT = "payment"
    PRICES = "prices"
    HOURS = "hours"
    ADDRESS = "address"
    CONTACTS = "contacts"
    ADVANTAGES = "advantages"
    ANSWERS = "answers"
    OTHER = "other"


FACT_KEY_LABELS = {
    FactKey.CUSTOMERS: "Mijozlari kim",
    FactKey.AREA: "Qayerda ishlaydi",
    FactKey.DELIVERY: "Yetkazib berish",
    FactKey.GUARANTEE: "Kafolat",
    FactKey.PAYMENT: "To'lov sharti",
    FactKey.PRICES: "Narxlar",
    FactKey.HOURS: "Ish vaqti",
    FactKey.ADDRESS: "Manzil",
    FactKey.CONTACTS: "Aloqa",
    FactKey.ADVANTAGES: "Afzalliklari",
    FactKey.ANSWERS: "Mijozga kim va qancha tez javob beradi",
    FactKey.OTHER: "Boshqa",
}

# How much one business's knowledge may hold. A chat that keeps adding is
# told the list is full instead of growing a document nobody reads.
MAX_ITEMS = 60
MAX_PENDING = 20
ABOUT_CHARS = 600
ITEM_NAME_CHARS = 80
ITEM_PRICE_CHARS = 60
ITEM_NOTE_CHARS = 300
ITEM_LINK_CHARS = 300
FACT_CHARS = 400
SUBTYPE_NAME_CHARS = 80
SUBTYPE_SYNONYMS = 30
