from app.common.exceptions import DomainError


class GuardrailBlocked(DomainError):
    def __init__(self, message: str = "") -> None:
        super().__init__(message or "Bu o'zgarishga ruxsat berilmadi.")


class SuggestionClosed(DomainError):
    def __init__(self, message: str = "") -> None:
        super().__init__(message or "Bu taklifga allaqachon javob berilgan.")


class SuggestionStale(DomainError):
    def __init__(self, message: str = "") -> None:
        super().__init__(
            message or "Raqamlar o'zgardi - bu taklif endi to'g'ri kelmaydi."
        )


class WordsNotShown(DomainError):
    def __init__(self, message: str = "") -> None:
        super().__init__(
            message or "Reklama matnini avval kabinetda o'qing, keyin tasdiqlang."
        )


class AgentDisabled(DomainError):
    def __init__(self, message: str = "") -> None:
        super().__init__(message or "Agent o'chirilgan. Sozlamalardan yoqing.")


class AgentAlreadyRunning(DomainError):
    def __init__(self, message: str = "") -> None:
        super().__init__(message or "Ko'rik hozir ketyapti. Tugashini kuting.")


class WatchMoved(DomainError):
    def __init__(self, message: str = "") -> None:
        super().__init__(
            message
            or "Reklama holati o'zgardi, bu tavsiya endi dolzarb emas. Ro'yxatni yangilang."
        )


class FrequencyAlertGone(DomainError):
    def __init__(self, message: str = "") -> None:
        super().__init__(
            message or "Bu ogohlantirish endi dolzarb emas. Ro'yxatni yangilang."
        )


class PriceAlertGone(DomainError):
    def __init__(self, message: str = "") -> None:
        super().__init__(
            message or "Bu ogohlantirish endi dolzarb emas. Ro'yxatni yangilang."
        )


class GuardAlertGone(DomainError):
    def __init__(self, message: str = "") -> None:
        super().__init__(
            message or "Bu ogohlantirish endi dolzarb emas. Ro'yxatni yangilang."
        )


class GuardAnswerUnknown(DomainError):
    def __init__(self, message: str = "") -> None:
        super().__init__(message or "Bu ogohlantirishga bunday javob yo'q.")


class GuardPairGone(DomainError):
    def __init__(self, message: str = "") -> None:
        super().__init__(
            message
            or "Bu guruh endi ulangan sahifa va reklama akkaunti juftligida emas. "
            "Hech narsa o'zgartirilmadi."
        )


class GuardChecking(DomainError):
    status_code = 409

    def __init__(self, message: str = "") -> None:
        super().__init__(
            message or "Hozirgi raqamlar tekshirilyapti. Bir daqiqadan keyin qarang."
        )
