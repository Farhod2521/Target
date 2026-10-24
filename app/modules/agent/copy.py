from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True, slots=True)
class StrategyCopy:
    title: str
    body: str
    route: str
    link: str


STRATEGY_COPY: Final[dict[str, StrategyCopy]] = {
    "choose_goal": StrategyCopy(
        title="Hozircha hech narsa ishlamayapti",
        body="Reklama akkauntingizda ishlayotgan kampaniya yo'q. Birinchi qadam - nima uchun reklama berayotganingizni tanlash.",
        route="ads:launch_start",
        link="Reklama berishni boshlash",
    ),
    "warm_start": StrategyCopy(
        title="Boshida keng oling",
        body="Akkaunt hali kimga ko'rsatish kerakligini o'rganmagan. Bir-ikki qiziqish yetarli - torroq qilsangiz, Meta o'rganadigan odam qolmaydi.",
        route="ads:launch_start",
        link="Yangi kampaniya",
    ),
    "go_broad": StrategyCopy(
        title="Qiziqishlar endi cheklab turibdi",
        body="Akkauntingiz yetarlicha natija to'pladi. Endi qiziqishlar bo'yicha cheklov ko'proq odamga yetishga to'sqinlik qiladi.",
        route="ads:campaigns",
        link="Kampaniyalarni ko'rish",
    ),
    "build_lookalike": StrategyCopy(
        title="Mijozlaringizga o'xshash odamlar",
        body="Sizda mijozlar ro'yxati bor. Meta shunga o'xshash odamlarni topa oladi - bu o'zi topa olmaydigan yagona narsa.",
        route="integrations:audiences",
        link="Auditoriyalar",
    ),
    "retarget": StrategyCopy(
        title="Bir marta kelganlarni qaytaring",
        body="Saytingizga yoki sahifangizga kirgan odamlarni qaytarish yangi odam topishdan arzonroq.",
        route="integrations:audiences",
        link="Auditoriyalar",
    ),
    "creative_test": StrategyCopy(
        title="Taqqoslash uchun ikkinchi reklama",
        body="Ba'zi guruhlarda bitta reklama ishlayapti. Ikkitasi bo'lsa - qaysi biri yaxshiroq ekanini ayta olamiz.",
        route="ads:campaigns",
        link="Kampaniyalarni ko'rish",
    ),
    "scale_up": StrategyCopy(
        title="Ishlayotganiga ko'proq bering",
        body="Bir nechta guruh o'zini isbotladi. Ularga sekin-asta ko'proq byudjet berish mumkin.",
        route="ads:campaigns",
        link="Kampaniyalarni ko'rish",
    ),
}
NEED_COPY: Final[dict[str, StrategyCopy]] = {
    "seed_audience": StrategyCopy(
        title="Buning uchun kerak",
        body="Mijozlaringiz ro'yxati - telefon raqamlari yoki email'lar. Ro'yxatni yuklaganingizdan keyin o'xshash auditoriya quriladi.",
        route="integrations:create_audience",
        link="Ro'yxat yuklash",
    ),
    "traffic_source": StrategyCopy(
        title="Buning uchun kerak",
        body="Saytingizdagi tashrifchilarni sanaydigan hisoblagich. Usiz kim kelganini bilib bo'lmaydi, demak qaytarib ham bo'lmaydi.",
        route="integrations:select_pixel",
        link="Hisoblagichni ulash",
    ),
}
MATURITY_LABELS: Final[dict[str, str]] = {
    "new": "Akkauntingiz hali o'rganmoqda",
    "growing": "Akkauntingiz natija to'plamoqda",
    "proven": "Akkauntingizda yetarli tajriba bor",
}
__all__ = ["MATURITY_LABELS", "NEED_COPY", "STRATEGY_COPY", "StrategyCopy"]
