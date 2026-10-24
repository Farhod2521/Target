from app.common.exceptions import DomainError


class SurveyNotFound(DomainError):
    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or "So'rovnoma topilmadi.")


class SurveyIsLive(DomainError):
    def __init__(self, message: str | None = None) -> None:
        super().__init__(
            message or "Faol so'rovnomani o'chirib bo'lmaydi. Avval uni yoping."
        )


class SurveyIsTranslating(DomainError):
    def __init__(self, message: str | None = None) -> None:
        super().__init__(
            message or "Tarjima hali tugamadi. Bir daqiqadan keyin qayta urining."
        )


class SurveyNotReady(DomainError):
    def __init__(self, message: str | None = None) -> None:
        super().__init__(
            message or "Avval hamma tillar to'ldirilsin, keyin e'lon qiling."
        )


class TranslationRefused(DomainError):
    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or "Tarjimani saqlab bo'lmadi.")


class SurveyAnswerInvalid(DomainError):
    def __init__(self, problems: dict[str, str]) -> None:
        super().__init__("Javoblarni tekshiring.")
        self.problems = problems


class SurveyNotDue(DomainError):
    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or "Bu so'rovnoma endi yopilgan. Sahifani yangilang.")


class SurveyHasAnswers(DomainError):
    def __init__(self, message: str | None = None) -> None:
        super().__init__(
            message
            or "Bu so'rovnomaga javob berilgan, savollarini o'zgartirib yoki o'chirib bo'lmaydi. Yangi so'rovnoma yarating."
        )
