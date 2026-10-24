from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True, slots=True)
class Trouble:
    headline: str
    detail: str


_KNOWN: Final[dict[str, Trouble]] = {
    "1815869": Trouble(
        headline="Reklama to'xtab qolgan",
        detail="Reklama o'chirib yuborilgan auditoriyaga qarab ishlayotgan edi. Meta uni to'xtatib qo'ygan.",
    ),
    "1870068": Trouble(
        headline="Reklama to'xtab qolgan",
        detail="Reklamadagi auditoriyalardan biri o'chirilgan akkauntdan ulashilgan. Meta reklamani to'xtatib qo'ygan.",
    ),
    "2460003": Trouble(
        headline="Auditoriya bloklangan",
        detail="Meta reklamadagi auditoriyalardan birini o'z qoidalari bo'yicha bloklagan. Reklama ko'rsatilmayapti.",
    ),
    "2460004": Trouble(
        headline="Hisoblash bloklangan",
        detail="Meta reklama natijasini sanaydigan sozlamani bloklagan. Reklama ko'rsatilmayapti.",
    ),
}


def known(code: str) -> Trouble | None:
    return _KNOWN.get(code.strip()) if code else None


def first_known(codes: list[str] | tuple[str, ...]) -> Trouble | None:
    for code in codes or ():
        found = known(str(code))
        if found is not None:
            return found
    return None


__all__ = ["Trouble", "first_known", "known"]
