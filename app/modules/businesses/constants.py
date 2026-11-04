from app.common.choices import Choices


class SpecialAdCategory(Choices):
    HOUSING = "housing"
    EMPLOYMENT = "employment"
    CREDIT = "credit"


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
# Where the business works: as many places as a launch may target.
MAX_REGIONS = 10
REGION_KINDS: tuple[str, ...] = ("city", "region", "country")
