from dataclasses import dataclass
from typing import Final

from app.common.text import slugify


@dataclass(frozen=True, slots=True)
class SeedName:
    uz: str
    ru: str
    en: str


@dataclass(frozen=True, slots=True)
class SeedRegion:
    name: SeedName
    cities: tuple[SeedName, ...]


@dataclass(frozen=True, slots=True)
class SeedCountry:
    regions: tuple[SeedRegion, ...]
    cities: tuple[SeedName, ...] = ()


def key_for(*, country_code: str, name: SeedName) -> str:
    return f"{country_code.lower()}-{slugify(name.uz)}"


def _n(uz: str, ru: str, en: str) -> SeedName:
    return SeedName(uz=uz, ru=ru, en=en)


UZBEKISTAN = SeedCountry(
    cities=(_n("Toshkent", "Ташкент", "Tashkent"),),
    regions=(
        SeedRegion(
            _n("Toshkent viloyati", "Ташкентская область", "Tashkent Region"),
            (
                _n("Nurafshon", "Нурафшон", "Nurafshon"),
                _n("Angren", "Ангрен", "Angren"),
                _n("Bekobod", "Бекабад", "Bekabad"),
                _n("Bo'ka", "Бука", "Buka"),
                _n("Chinoz", "Чиназ", "Chinaz"),
                _n("Chirchiq", "Чирчик", "Chirchiq"),
                _n("Do'stobod", "Дустабад", "Dustabad"),
                _n("G'azalkent", "Газалкент", "Gazalkent"),
                _n("Keles", "Келес", "Keles"),
                _n("Ohangaron", "Ахангаран", "Ohangaron"),
                _n("Olmaliq", "Алмалык", "Olmaliq"),
                _n("Oqqo'rg'on", "Аккурган", "Akkurgan"),
                _n("Parkent", "Паркент", "Parkent"),
                _n("Piskent", "Пскент", "Piskent"),
                _n("Yangiobod", "Янгиабад", "Yangiobod"),
                _n("Yangiyo'l", "Янгиюль", "Yangiyul"),
            ),
        ),
        SeedRegion(
            _n("Andijon viloyati", "Андижанская область", "Andijan Region"),
            (
                _n("Andijon", "Андижан", "Andijan"),
                _n("Asaka", "Асака", "Asaka"),
                _n("Jalaquduq", "Джалакудук", "Jalakuduk"),
                _n("Marhamat", "Мархамат", "Markhamat"),
                _n("Paxtaobod", "Пахтаабад", "Pakhtaabad"),
                _n("Poytug'", "Пайтуг", "Paytug"),
                _n("Qo'rg'ontepa", "Кургантепа", "Kurgantepa"),
                _n("Qorasuv", "Карасу", "Karasu"),
                _n("Shahrixon", "Шахрихан", "Shahrikhan"),
                _n("Xo'jaobod", "Ходжаабад", "Khodjaabad"),
                _n("Xonobod", "Ханабад", "Khanabad"),
            ),
        ),
        SeedRegion(
            _n("Buxoro viloyati", "Бухарская область", "Bukhara Region"),
            (
                _n("Buxoro", "Бухара", "Bukhara"),
                _n("Galaosiyo", "Галаасия", "Galaosiyo"),
                _n("Gazli", "Газли", "Gazli"),
                _n("G'ijduvon", "Гиждуван", "Gijduvan"),
                _n("Kogon", "Каган", "Kagan"),
                _n("Olot", "Алат", "Alat"),
                _n("Qorako'l", "Каракуль", "Karakul"),
                _n("Qorovulbozor", "Караулбазар", "Karaulbazar"),
                _n("Romitan", "Ромитан", "Romitan"),
                _n("Shofirkon", "Шафиркан", "Shafirkan"),
                _n("Vobkent", "Вабкент", "Vabkent"),
            ),
        ),
        SeedRegion(
            _n("Farg'ona viloyati", "Ферганская область", "Fergana Region"),
            (
                _n("Farg'ona", "Фергана", "Fergana"),
                _n("Beshariq", "Бешарык", "Beshariq"),
                _n("Marg'ilon", "Маргилан", "Margilan"),
                _n("Qo'qon", "Коканд", "Kokand"),
                _n("Quva", "Кува", "Kuva"),
                _n("Quvasoy", "Кувасай", "Kuvasay"),
                _n("Rishton", "Риштан", "Rishtan"),
                _n("Tinchlik", "Тинчлик", "Tinchlik"),
                _n("Yaypan", "Яйпан", "Yaypan"),
            ),
        ),
        SeedRegion(
            _n("Jizzax viloyati", "Джизакская область", "Jizzakh Region"),
            (
                _n("Jizzax", "Джизак", "Jizzakh"),
                _n("Dashtobod", "Даштабад", "Dashtobod"),
                _n("Do'stlik", "Дустлик", "Dustlik"),
                _n("Gagarin", "Гагарин", "Gagarin"),
                _n("G'allaorol", "Галляарал", "Gallaorol"),
                _n("Paxtakor", "Пахтакор", "Pakhtakor"),
            ),
        ),
        SeedRegion(
            _n("Namangan viloyati", "Наманганская область", "Namangan Region"),
            (
                _n("Namangan", "Наманган", "Namangan"),
                _n("Chortoq", "Чартак", "Chartak"),
                _n("Chust", "Чуст", "Chust"),
                _n("Haqqulobod", "Хаккулабад", "Khakkulabad"),
                _n("Kosonsoy", "Касансай", "Kosonsoy"),
                _n("Pop", "Пап", "Pop"),
                _n("To'raqo'rg'on", "Туракурган", "Turakurgan"),
                _n("Uchqo'rg'on", "Учкурган", "Uchkurgan"),
            ),
        ),
        SeedRegion(
            _n("Navoiy viloyati", "Навоийская область", "Navoiy Region"),
            (
                _n("Navoiy", "Навои", "Navoiy"),
                _n("G'ozg'on", "Газган", "Gazgan"),
                _n("Nurota", "Нурата", "Nurata"),
                _n("Qiziltepa", "Кызылтепа", "Kyzyltepa"),
                _n("Uchquduq", "Учкудук", "Uchkuduk"),
                _n("Yangirabot", "Янгирабад", "Yangirabad"),
                _n("Zarafshon", "Зарафшан", "Zarafshan"),
            ),
        ),
        SeedRegion(
            _n("Qashqadaryo viloyati", "Кашкадарьинская область", "Kashkadarya Region"),
            (
                _n("Qarshi", "Карши", "Qarshi"),
                _n("Beshkent", "Бешкент", "Beshkent"),
                _n("Chiroqchi", "Чиракчи", "Chirakchi"),
                _n("G'uzor", "Гузар", "Guzar"),
                _n("Kitob", "Китаб", "Kitab"),
                _n("Koson", "Касан", "Koson"),
                _n("Muborak", "Мубарек", "Mubarek"),
                _n("Qamashi", "Камаши", "Kamashi"),
                _n("Shahrisabz", "Шахрисабз", "Shahrisabz"),
                _n("Tallimarjon", "Талимарджан", "Talimarjan"),
                _n("Yakkabog'", "Яккабаг", "Yakkabag"),
                _n("Yangi Nishon", "Янги-Нишан", "Yangi Nishon"),
            ),
        ),
        SeedRegion(
            _n(
                "Qoraqalpog'iston Respublikasi",
                "Республика Каракалпакстан",
                "Republic of Karakalpakstan",
            ),
            (
                _n("Nukus", "Нукус", "Nukus"),
                _n("Beruniy", "Беруни", "Beruniy"),
                _n("Bo'ston", "Бустан", "Boston"),
                _n("Chimboy", "Чимбай", "Chimbay"),
                _n("Mang'it", "Мангит", "Mangit"),
                _n("Mo'ynoq", "Муйнак", "Muynak"),
                _n("Qo'ng'irot", "Кунград", "Kungrad"),
                _n("Shumanay", "Шуманай", "Shumanay"),
                _n("Taxiatosh", "Тахиаташ", "Takhiatosh"),
                _n("To'rtko'l", "Турткуль", "Turtkul"),
                _n("Xalqobod", "Халкабад", "Khalkabad"),
                _n("Xo'jayli", "Ходжейли", "Khojeli"),
            ),
        ),
        SeedRegion(
            _n("Samarqand viloyati", "Самаркандская область", "Samarkand Region"),
            (
                _n("Samarqand", "Самарканд", "Samarkand"),
                _n("Bulung'ur", "Булунгур", "Bulungur"),
                _n("Chelak", "Челек", "Chelak"),
                _n("Ishtixon", "Иштыхан", "Ishtikhon"),
                _n("Jomboy", "Джамбай", "Jomboy"),
                _n("Juma", "Джума", "Juma"),
                _n("Kattaqo'rg'on", "Каттакурган", "Kattakurgan"),
                _n("Nurobod", "Нурабад", "Nurabad"),
                _n("Oqtosh", "Акташ", "Aktash"),
                _n("Payariq", "Пайарык", "Payariq"),
                _n("Urgut", "Ургут", "Urgut"),
            ),
        ),
        SeedRegion(
            _n("Sirdaryo viloyati", "Сырдарьинская область", "Syrdarya Region"),
            (
                _n("Guliston", "Гулистан", "Gulistan"),
                _n("Baxt", "Бахт", "Bakht"),
                _n("Shirin", "Ширин", "Shirin"),
                _n("Sirdaryo", "Сырдарья", "Syrdarya"),
                _n("Yangiyer", "Янгиер", "Yangiyer"),
            ),
        ),
        SeedRegion(
            _n(
                "Surxondaryo viloyati",
                "Сурхандарьинская область",
                "Surkhandarya Region",
            ),
            (
                _n("Termiz", "Термез", "Termez"),
                _n("Boysun", "Байсун", "Boysun"),
                _n("Denov", "Денау", "Denov"),
                _n("Jarqo'rg'on", "Джаркурган", "Jarkurgan"),
                _n("Qumqo'rg'on", "Кумкурган", "Kumkurgan"),
                _n("Sharg'un", "Шаргунь", "Shargun"),
                _n("Sherobod", "Шерабад", "Sherabad"),
                _n("Sho'rchi", "Шурчи", "Shurchi"),
            ),
        ),
        SeedRegion(
            _n("Xorazm viloyati", "Хорезмская область", "Khorezm Region"),
            (
                _n("Urganch", "Ургенч", "Urgench"),
                _n("Pitnak", "Питнак", "Pitnak"),
                _n("Xiva", "Хива", "Khiva"),
            ),
        ),
    ),
)
CATALOGUES: Final[dict[str, SeedCountry]] = {"UZ": UZBEKISTAN}
