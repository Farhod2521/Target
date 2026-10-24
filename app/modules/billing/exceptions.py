from datetime import datetime

from app.common.dates import date_format, localtime
from app.common.exceptions import DomainError


class NoEntitlement(DomainError):
    pass


class SubscriptionExpired(NoEntitlement):
    def __init__(self) -> None:
        super().__init__(
            "Obuna muddati tugagan. Reklamani boshqarish uchun uni yangilang - yig'ilgan ma'lumot va yarim tayyor reklama joyida qoladi."
        )


class PlanNotOpened(NoEntitlement):
    def __init__(self) -> None:
        super().__init__(
            "Tarif hali ochilmagan. Reklama berish uchun tarifni oching - taklif havolangiz esa hozir ham ishlaydi."
        )


class TrialLimitReached(DomainError):
    def __init__(self, *, limit: int) -> None:
        super().__init__(
            "Sinov muddatida %(limit)s tagacha kampaniya yoqish mumkin, va hammasi ishlatilgan. Yana reklama berish uchun tarifni tanlang."
            % {"limit": limit}
        )


class PlanSizeReached(DomainError):
    def __init__(self, *, limit: int) -> None:
        super().__init__(
            "Tarifingizda har sahifada bir vaqtda %(limit)s tagacha reklama ishlashi mumkin. Keraksizini to'xtating yoki kengroq tarifga o'ting."
            % {"limit": limit}
        )


class SetupIncomplete(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Avval tayyorgarlikni yakunlang - tayyorgarlik sahifasidagi «Yakunlash» tugmasini bosing."
        )


class PlanNotSellable(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Bu tarif hozir sotuvda emas. Sahifani yangilang yoki biz bilan bog'laning."
        )


class PlanAlreadyBought(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Bu tarif bir marta sotiladi va siz uni allaqachon sotib olgansiz. Boshqa tarifni tanlang."
        )


class PaymentUnavailable(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Onlayn to'lov hozircha ishlamayapti. Boshqa usulni tanlang yoki biz bilan bog'laning."
        )


class InvoiceNotPayable(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Bu hisobning muddati o'tgan. Yangi hisob chiqarish uchun tarifni qaytadan tanlang."
        )


class NothingToExtend(DomainError):
    def __init__(self) -> None:
        super().__init__("Bu akkauntda obuna yo'q. Avval nima bo'lganini tekshiring.")


class CheaperPlanWaits(DomainError):
    def __init__(self, *, until: datetime) -> None:
        day = date_format(localtime(until), "j F Y")
        super().__init__(
            "Arzonroq tarifga joriy obuna tugagach o'tish mumkin: %(day)s."
            % {"day": day}
        )


class PaymentAmountMissing(DomainError):
    def __init__(self) -> None:
        super().__init__("To'lov summasini kiriting.")


class DaysOutOfRange(DomainError):
    def __init__(self, *, limit: int) -> None:
        super().__init__(
            "Kun soni 1 dan %(limit)s gacha bo'lishi kerak." % {"limit": limit}
        )


class PromoNotFound(DomainError):
    def __init__(self) -> None:
        super().__init__("Bunday promo kod topilmadi yoki muddati tugagan.")


class PromoAlreadyUsed(DomainError):
    def __init__(self) -> None:
        super().__init__("Siz bu promo kodni allaqachon ishlatgansiz.")


class PromoUsedUp(DomainError):
    def __init__(self) -> None:
        super().__init__("Bu promo kod bo'yicha limit tugagan.")


class RedemptionNotPending(DomainError):
    def __init__(self, *, decision: str) -> None:
        super().__init__(
            "Bu so'rov allaqachon hal qilingan: %(decision)s." % {"decision": decision}
        )


class PromoNotRedeemable(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Bu promo kod to'lov paytida ishlatiladi, obunaga qo'shilmaydi."
        )


class PromoNotApplicable(DomainError):
    def __init__(self) -> None:
        super().__init__("Bu promo kodni bu hisobga qo'llab bo'lmaydi.")


class ReasonRequired(DomainError):
    def __init__(self) -> None:
        super().__init__("Sababini yozing - u audit yozuviga tushadi.")


class SlotsOutOfRange(DomainError):
    def __init__(self, *, limit: int) -> None:
        super().__init__(
            "O'rin soni 1 dan %(limit)s gacha bo'lishi kerak." % {"limit": limit}
        )


class NoSlotsToTake(DomainError):
    def __init__(self, *, held: int) -> None:
        super().__init__(
            "Bu akkauntda %(held)s ta qo'shimcha o'rin bor, undan ko'pini olib bo'lmaydi."
            % {"held": held}
        )


class NothingHeld(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Bu urinish endi hisobni ushlab turmayapti - sahifani yangilang."
        )


class PagesNeedPaidPlan(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Qo'shimcha sahifa faqat pullik obunada sotiladi. Avval tarifni yoqing."
        )


class PagesNotSold(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Bu tarifda qo'shimcha sahifa sotilmaydi. Savol bo'lsa, yordamga yozing."
        )


class PageCountOutOfRange(DomainError):
    def __init__(self, *, limit: int) -> None:
        super().__init__(
            "Bir marta 1 dan %(limit)s tagacha sahifa qo'shish mumkin."
            % {"limit": limit}
        )


class ReceiptNotOrphaned(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Faqat o'chirilgan akkauntdan qolgan chekni biriktirish mumkin."
        )
