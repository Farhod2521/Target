from app.common.exceptions import DomainError


class UnknownLead(DomainError):
    def __init__(self) -> None:
        super().__init__("Bu lid topilmadi. Ro'yxatni yangilang.")


class NoPageConnected(DomainError):
    def __init__(self) -> None:
        super().__init__("Avval Facebook sahifasini ulang.")


class FormsAskedRecently(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Formalar hozirgina so'ralgan. Bir daqiqadan keyin urinib ko'ring."
        )


class NothingToRecover(DomainError):
    def __init__(self) -> None:
        super().__init__("Tiklanadigan ariza yo'q — hammasi joyida.")


class RecoveryImpossible(DomainError):
    def __init__(self, *, lost: int) -> None:
        super().__init__(
            "%(count)s ta arizani tiklashning imkoni bo'lmadi: ular 90 kundan oshgan va Meta bunday arizalarni endi bermaydi."
            % {"count": lost}
        )


class RecoveryNeedsConnection(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Meta ulanishi uzilgani uchun tiklashning imkoni bo'lmadi. Avval ulanishni tiklang, keyin qaytadan urinib ko'ring."
        )


class RecoveryTooSoon(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Tiklash boshlandi. Bir necha daqiqadan keyin natijani ko'rasiz."
        )
