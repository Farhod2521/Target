from app.common.exceptions import DomainError


class AlreadyClaimed(DomainError):
    def __init__(self) -> None:
        super().__init__("Bu mijozni boshqa menejer oldi.")


class NotInQueue(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Bu mijoz navbatda emas: to'lov qilgan yoki unga qo'ng'iroq qilinmaydi."
        )


class CardClosed(DomainError):
    def __init__(self) -> None:
        super().__init__("Bu karta yopilgan. Doskani yangilang.")


class NothingToReopen(DomainError):
    def __init__(self) -> None:
        super().__init__("Bu karta endi «Rad etdi»da emas. Doskani yangilang.")


class NotYourCard(DomainError):
    def __init__(self) -> None:
        super().__init__("Bu mijoz sizda emas.")


class CallbackRequired(DomainError):
    def __init__(self) -> None:
        super().__init__("Qayta qo'ng'iroq vaqtini kiriting.")


class CallbackInPast(DomainError):
    def __init__(self) -> None:
        super().__init__("Qayta qo'ng'iroq vaqti kelajakda bo'lishi kerak.")


class ReasonRequired(DomainError):
    def __init__(self) -> None:
        super().__init__("Sababni tanlang.")


class NoteRequired(DomainError):
    def __init__(self) -> None:
        super().__init__("Izoh bo'sh.")


class AlreadyContacted(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Bu mijoz bilan gaplashilgan. Qaytarish o'rniga «Rad etdi» bilan sabab va muddatni belgilang."
        )


class HoldGone(DomainError):
    def __init__(self) -> None:
        super().__init__("Bu taqiq allaqachon olingan.")
