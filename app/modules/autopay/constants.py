from datetime import timedelta
from typing import Final

from app.common.choices import Choices


class CardStatus(Choices):
    # A Multicard page was opened; no card came back from it yet.
    PENDING = "pending"
    ACTIVE = "active"
    REVOKED = "revoked"


PROVIDER: Final = "multicard"

# Charging starts this long before the plan runs out, and goes on this long
# after it, a day apart each time, at most MAX_ATTEMPTS times a term.
CHARGE_LEAD: Final = timedelta(days=1)
CHARGE_GRACE: Final = timedelta(days=2)
RETRY_GAP: Final = timedelta(hours=23)
MAX_ATTEMPTS: Final = 3

# Multicard's own phone format for the card's owner.
PHONE_DIGITS: Final = 12
PHONE_PREFIX: Final = "998"

# Where Multicard sends the payer back after its card page.
CARD_DONE_PATH: Final = "/app/billing?card=bound"
CARD_DECLINED_PATH: Final = "/app/billing?card=declined"

# Multicard's refusals, in the owner's words. Others are shown as sent.
CHARGE_ERRORS: Final[dict[str, str]] = {
    "needs_code": (
        "Karta har to'lovda SMS kod so'raydi, avtomatik yechib bo'lmadi. "
        "Obunani qo'lda to'lang."
    ),
    "ERROR_INSUFFICIENT_FUNDS": "Kartada mablag' yetarli emas.",
    "ERROR_CARD_NOT_FOUND": "Karta topilmadi yoki muddati o'tgan. Kartani qayta bog'lang.",
    "ERROR_CARD_BLOCKED": "Karta bloklangan.",
    "invoice": "Obuna uchun hisob ochib bo'lmadi.",
    "unreachable": "Rahmat javob bermadi, keyinroq yana urinamiz.",
}
CHARGE_ERROR_MAX: Final = 300
