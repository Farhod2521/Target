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
        super().__init__("Bu xodim Sotuv bo'limida ishlamaydi.")
