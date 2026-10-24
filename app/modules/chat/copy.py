"""The sentences the product writes when Claude does not."""

from typing import Any, Final

SILENCE_COPY: Final[dict[str, Any]] = {
    "empty": "O'tgan hafta murojaat bo'lmadi — taqqoslash uchun hali ma'lumot yo'q.",
    "noise": (
        "Farq kichik — bir haftada bu tasodif bo'lishi mumkin, "
        "shuning uchun sabab aytilmaydi."
    ),
    "no_change": (
        "Raqamlar o'zgardi, lekin o'tgan hafta reklamangizda "
        "hech narsa o'zgartirilmagan."
    ),
}

HEADLINE_COPY: Final[dict[str, Any]] = {
    "cpql": "Sifatli murojaat narxi",
    "cpl": "Murojaat narxi",
}

ASK_ABOUT_ITEM: Final[Any] = "Bu nima degani va nima qilishim kerak?"

CUT_SHORT: Final[Any] = "Javob uzun chiqdi va oxiri sig'madi."
CARRY_ON: Final[Any] = "Davom et"

__all__ = ["ASK_ABOUT_ITEM", "CARRY_ON", "CUT_SHORT", "HEADLINE_COPY", "SILENCE_COPY"]
