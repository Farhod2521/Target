"""Dates the way Django's ``date_format`` printed them, in the reader's language."""

from datetime import date, datetime, tzinfo
from zoneinfo import ZoneInfo

from app.common.config import settings
from app.common.i18n import get_language

MONTHS: dict[str, tuple[str, ...]] = {
    "uz": (
        "yanvar",
        "fevral",
        "mart",
        "aprel",
        "may",
        "iyun",
        "iyul",
        "avgust",
        "sentabr",
        "oktabr",
        "noyabr",
        "dekabr",
    ),
    "ru": (
        "января",
        "февраля",
        "марта",
        "апреля",
        "мая",
        "июня",
        "июля",
        "августа",
        "сентября",
        "октября",
        "ноября",
        "декабря",
    ),
    "en": (
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December",
    ),
}
WEEKDAYS: dict[str, tuple[str, ...]] = {
    "uz": (
        "dushanba",
        "seshanba",
        "chorshanba",
        "payshanba",
        "juma",
        "shanba",
        "yakshanba",
    ),
    "ru": (
        "понедельник",
        "вторник",
        "среда",
        "четверг",
        "пятница",
        "суббота",
        "воскресенье",
    ),
    "en": (
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Sunday",
    ),
}


def office_zone() -> ZoneInfo:
    return ZoneInfo(settings.office_timezone)


def localtime(value: datetime, zone: tzinfo | str | None = None) -> datetime:
    if isinstance(zone, str):
        zone = ZoneInfo(zone) if zone else None
    return value.astimezone(zone or office_zone())


def date_format(value: date | datetime, fmt: str = "j F Y") -> str:
    language = get_language()
    months = MONTHS.get(language, MONTHS["uz"])
    weekdays = WEEKDAYS.get(language, WEEKDAYS["uz"])
    out: list[str] = []
    for char in fmt:
        if char == "j":
            out.append(str(value.day))
        elif char == "d":
            out.append(f"{value.day:02d}")
        elif char in ("F", "E"):
            out.append(months[value.month - 1])
        elif char == "m":
            out.append(f"{value.month:02d}")
        elif char == "n":
            out.append(str(value.month))
        elif char == "Y":
            out.append(str(value.year))
        elif char == "y":
            out.append(f"{value.year % 100:02d}")
        elif char == "l":
            out.append(weekdays[value.weekday()])
        elif char == "H" and isinstance(value, datetime):
            out.append(f"{value.hour:02d}")
        elif char == "i" and isinstance(value, datetime):
            out.append(f"{value.minute:02d}")
        else:
            out.append(char)
    return "".join(out)


def number_format(value, *, decimal_pos: int = 0) -> str:  # type: ignore[no-untyped-def]
    """django.utils.formats.number_format, which ported code imports from here."""
    from app.common.money import number_format as formatted

    return formatted(value, decimal_pos=decimal_pos)
