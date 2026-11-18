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


class ContactReasonRequired(DomainError):
    status_code = 422

    def __init__(self) -> None:
        super().__init__("Bog'lanib bo'lmaslik sababini tanlang.")


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


class DueRequired(DomainError):
    status_code = 422

    def __init__(self) -> None:
        super().__init__("Muddatni belgilang.")


class DuePast(DomainError):
    status_code = 422

    def __init__(self) -> None:
        super().__init__("Muddat o'tib ketgan vaqtga qo'yilmaydi.")


class DueInvalid(DomainError):
    status_code = 422

    def __init__(self) -> None:
        super().__init__("Muddat noto'g'ri.")


class ClientNotFound(DomainError):
    status_code = 422

    def __init__(self) -> None:
        super().__init__("Bunday mijoz topilmadi.")


class ClientPaid(DomainError):
    status_code = 409

    def __init__(self) -> None:
        super().__init__("Bu mijoz tarif sotib olgan, u lid emas.")


class CardExists(DomainError):
    status_code = 409

    def __init__(self) -> None:
        super().__init__("Bu mijozning kartasi allaqachon bor.")


class NoTicketToTake(DomainError):
    status_code = 409

    def __init__(self) -> None:
        super().__init__("Hozir navbatda yangi zayavka yo'q.")


class TakeLimit(DomainError):
    status_code = 409

    def __init__(self, limit: int) -> None:
        super().__init__(
            f"Sizda {limit} ta zayavka ishlanmoqda. Yangisini olish uchun "
            "avval birini yakunlang."
        )


class LeadTakeLimit(DomainError):
    status_code = 409

    def __init__(self, limit: int) -> None:
        super().__init__(
            f"Sizda {limit} ta olingan, hali qo'ng'iroq qilinmagan lid bor "
            "(«Yangi lead»). Yangisini olish uchun avval ularga qo'ng'iroq qiling."
        )


class ReportPeriodInvalid(DomainError):
    status_code = 422

    def __init__(self) -> None:
        super().__init__("Hisobot davri noto'g'ri: ko'pi bilan bir yil.")


class ChatHeld(DomainError):
    status_code = 409

    def __init__(self, name: str) -> None:
        super().__init__(f"Bu chatda {name} javob beryapti.")


class TicketOfAnother(DomainError):
    """Code ``chat_held`` too: the page reads both as «somebody else has
    this client»."""

    status_code = 409
    code = "chat_held"

    def __init__(self, name: str) -> None:
        super().__init__(
            f"Bu mijozning zayavkasi {name} da. Faqat u yoki Owner javob bera oladi."
        )


class ChatNotTaken(DomainError):
    status_code = 409

    def __init__(self) -> None:
        super().__init__("Avval «Men javob beraman» tugmasini bosing.")


class ChatWithPerson(DomainError):
    """The client asked the assistant while a person has their chat: the
    page writes to Support instead (``code`` ``chat_with_person``)."""

    status_code = 409

    def __init__(self) -> None:
        super().__init__(
            "Hozir sizga Support xodimi javob beryapti. Xabaringiz unga yuboriladi."
        )
