from app.common.exceptions import DomainError
from app.modules.referrals.constants import FEEDBACK_MAX_BYTES, FeedbackKind


class ReferrerNotEligible(DomainError):
    def __init__(self) -> None:
        super().__init__("Taklif havolangiz yopilgan. Savol bo'lsa, yordamga yozing.")


class EarnerNotActive(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Mijozning obunasi faol emas. Pulni obuna yangilangandan keyin yechib olish mumkin."
        )


class InsufficientBalance(DomainError):
    def __init__(self) -> None:
        super().__init__("Balansda bu summa yo'q.")


class PayoutAlreadyVoided(DomainError):
    def __init__(self) -> None:
        super().__init__("Bu yozuv allaqachon bekor qilingan.")


class AccessReasonRequired(DomainError):
    def __init__(self) -> None:
        super().__init__("Sababini yozing - u audit yozuviga tushadi.")


class WithdrawalLocked(DomainError):
    def __init__(self) -> None:
        super().__init__("Pul yechish pullik obunangiz faol bo'lganda ochiladi.")


class WithdrawalsClosed(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Pul yechish vaqtincha yopiq. Yig'ilgan pul joyida qoladi - u obuna to'lovida ishlatiladi."
        )


class WithdrawalPending(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Oldingi so'rovingiz hali ko'rib chiqilmoqda. U hal bo'lgach, yangisini yuborishingiz mumkin."
        )


class CardNumberInvalid(DomainError):
    def __init__(self) -> None:
        super().__init__("Karta raqamini to'liq kiriting: 16 ta raqam.")


class CardHolderRequired(DomainError):
    def __init__(self) -> None:
        super().__init__("Karta egasining ismini kiriting.")


class WithdrawalAlreadyDecided(DomainError):
    def __init__(self) -> None:
        super().__init__("Bu so'rovga allaqachon javob berilgan.")


class PayoutNotPaid(DomainError):
    def __init__(self) -> None:
        super().__init__("Faqat to'langan yozuvni bekor qilish mumkin.")


class FeedbackClosed(DomainError):
    def __init__(self) -> None:
        super().__init__("Fikr qoldirish doimiy tarif faol bo'lganda ochiladi.")


class FeedbackAlreadySent(DomainError):
    def __init__(self) -> None:
        super().__init__("Fikringiz allaqachon yuborilgan.")


class FeedbackConsentRequired(DomainError):
    def __init__(self) -> None:
        super().__init__("Fikringizni ishlatishga rozilik belgisini qo'ying.")


class FeedbackTextTooShort(DomainError):
    def __init__(self, minimum: int) -> None:
        super().__init__(
            "Fikr kamida %(count)s belgidan iborat bo'lsin." % {"count": minimum}
        )


class FeedbackFileInvalid(DomainError):
    def __init__(self) -> None:
        audio, video = (
            FEEDBACK_MAX_BYTES[kind] // (1024 * 1024)
            for kind in (FeedbackKind.AUDIO, FeedbackKind.VIDEO)
        )
        super().__init__(
            "Faylni yuklang: audio %(audio)s MB gacha, video %(video)s MB gacha."
            % {"audio": audio, "video": video}
        )


class FeedbackAlreadyDecided(DomainError):
    def __init__(self) -> None:
        super().__init__("Bu fikrga allaqachon javob berilgan.")


class FeedbackAlreadyPaid(DomainError):
    def __init__(self) -> None:
        super().__init__("Mijozga fikr uchun mukofot allaqachon to'langan.")


class FeedbackNoPlan(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Mijozning doimiy tarifi hozir faol emas, tasdiqlab bo'lmaydi."
        )
