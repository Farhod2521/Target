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
    "auto": ("Автосервис / автосалон", "Car service / dealership"),
    "beauty": ("Салон красоты", "Beauty salon"),
    "construction": ("Строительство / ремонт", "Construction / repairs"),
    "ecommerce": ("Интернет-магазин", "Online shop"),
    "education": ("Учебный центр", "Training centre"),
    "fitness": ("Спортзал / фитнес", "Gym / fitness"),
    "medical": ("Клиника / медуслуги", "Clinic / medical services"),
    "real_estate": ("Недвижимость", "Real estate"),
    "restaurant": ("Ресторан / кафе", "Restaurant / cafe"),
    "retail_store": ("Магазин / торговая точка", "Shop / retail outlet"),
    "services": ("Услуги", "Services"),
    "travel": ("Путешествия / туризм", "Travel / tourism"),
}
