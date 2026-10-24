from app.common.exceptions import DomainError


class InvalidSignedRequest(DomainError):
    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or "So'rov imzosi tekshiruvdan o'tmadi.")


class DeletionRequestNotFound(DomainError):
    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or "Bunday tasdiqlash kodi topilmadi.")


class ConsultRequestNotFound(DomainError):
    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or "Bu ariza topilmadi.")


class FeedbackNotPublishable(DomainError):
    def __init__(self, message: str | None = None) -> None:
        super().__init__(
            message or "Faqat tasdiqlangan fikrni saytga chiqarish mumkin."
        )


class FeedbackAlreadyOnSite(DomainError):
    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or "Bu fikr saytda bor.")


class TestimonialNotFound(DomainError):
    __test__ = False

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or "Bu fikr topilmadi.")
