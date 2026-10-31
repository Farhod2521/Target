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
