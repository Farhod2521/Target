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
