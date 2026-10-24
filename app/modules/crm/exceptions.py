from app.common.exceptions import DomainError, NotAllowed


class CrmClosed(NotAllowed):
    def __init__(self) -> None:
        super().__init__("CRM hozircha yopiq.")


class NotYours(NotAllowed):
    def __init__(self) -> None:
        super().__init__("Bu amal sizga ruxsat etilmagan.")


class UnknownCard(DomainError):
    def __init__(self) -> None:
        super().__init__("Karta topilmadi. Doskani yangilang.")


class AlreadyTaken(DomainError):
    def __init__(self) -> None:
        super().__init__("Bu lidni boshqa menejer oldi.")


class CardIsClosed(DomainError):
    def __init__(self) -> None:
        super().__init__("Bu karta yopilgan. Avval uni boshqa ustunga o'tkazing.")


class UseTheDialog(DomainError):
    def __init__(self) -> None:
        super().__init__("Natijani dialogda belgilang.")


class ReasonRequired(DomainError):
    def __init__(self) -> None:
        super().__init__("Rad etish sababini tanlang.")


class AmountRequired(DomainError):
    def __init__(self) -> None:
        super().__init__("Sotuv summasini kiriting.")


class DueInPast(DomainError):
    def __init__(self) -> None:
        super().__init__("Muddat o'tib ketgan vaqt bo'lishi mumkin emas.")


class NotConfigured(DomainError):
    def __init__(self) -> None:
        super().__init__("Avval ustunlarni sozlang.")


class StageLocked(DomainError):
    def __init__(self) -> None:
        super().__init__("Bu ustunni o'chirib bo'lmaydi.")


class TooManyStages(DomainError):
    def __init__(self) -> None:
        super().__init__("Ustunlar soni chegaraga yetdi.")


class TooManyMembers(DomainError):
    def __init__(self) -> None:
        super().__init__("Jamoada ko'pi bilan 10 ta menejer bo'lishi mumkin.")


class EmailTaken(DomainError):
    def __init__(self) -> None:
        super().__init__("Bu email bilan akkaunt bor. Boshqa email kiriting.")


class PasswordTooWeak(DomainError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)


class PasswordsDiffer(DomainError):
    def __init__(self) -> None:
        super().__init__("Ikki parol bir xil emas.")


class NameRequired(DomainError):
    def __init__(self) -> None:
        super().__init__("Nomini kiriting.")


class UnknownMember(DomainError):
    def __init__(self) -> None:
        super().__init__("Menejer topilmadi.")


class EmptyNote(DomainError):
    def __init__(self) -> None:
        super().__init__("Izoh bo'sh.")


class NotRunning(DomainError):
    def __init__(self) -> None:
        super().__init__("CRM o'chiq. Avval uni yoqing.")


class AlreadyOnBoard(DomainError):
    def __init__(self) -> None:
        super().__init__("Bu lid allaqachon CRM doskasida.")


class BadKpi(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Fix maosh va foizni raqam bilan yozing (foiz 0 dan 100 gacha)."
        )


class NoAdsChosen(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Hech bir lid tushmaydi: «Hammasi»ni belgilang yoki kamida bitta reklamani tanlang."
        )
