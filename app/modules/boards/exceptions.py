from app.common.exceptions import DomainError, NotFound


class CardNotFound(NotFound):
    def __init__(self) -> None:
        super().__init__("Karta topilmadi.")


class NothingToTake(DomainError):
    status_code = 409

    def __init__(self) -> None:
        super().__init__("Hozir olinadigan yangi lid yo'q.")


class ActionNotHere(DomainError):
    status_code = 409

    def __init__(self) -> None:
        super().__init__("Bu ustunda bu tugma yo'q. Sahifani yangilang.")


class CardClosed(DomainError):
    status_code = 409

    def __init__(self) -> None:
        super().__init__("Karta yopilgan.")


class ReasonRequired(DomainError):
    status_code = 422

    def __init__(self) -> None:
        super().__init__("Yopish sababini tanlang.")


class NoteRequired(DomainError):
    status_code = 422

    def __init__(self) -> None:
        super().__init__("Izoh yozing.")


class NotOnBoard(DomainError):
    status_code = 422

    def __init__(self) -> None:
        super().__init__("Bu xodim shu bo'limda ishlamaydi.")


class TicketHeld(DomainError):
    status_code = 409

    def __init__(self) -> None:
        super().__init__("Bu mijoz bilan boshqa xodim ishlayapti.")


class ColumnsMismatch(DomainError):
    status_code = 422

    def __init__(self) -> None:
        super().__init__("Ustunlar ro'yxati to'liq emas. Sahifani yangilang.")


class ColumnNameRequired(DomainError):
    status_code = 422

    def __init__(self) -> None:
        super().__init__("Ustun nomini yozing.")


class NoSuchColumn(DomainError):
    status_code = 422

    def __init__(self) -> None:
        super().__init__("Bunday ustun yo'q.")


class MoveReasonRequired(DomainError):
    status_code = 422

    def __init__(self) -> None:
        super().__init__("Nega ko'chirilayotganini yozing.")


class OfferGiven(DomainError):
    status_code = 409

    def __init__(self) -> None:
        super().__init__("Bu mijozga chegirma allaqachon berilgan.")
