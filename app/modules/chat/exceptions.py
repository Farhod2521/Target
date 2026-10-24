from app.common.exceptions import DomainError


class QuestionTooLong(DomainError):
    def __init__(self, limit: int) -> None:
        super().__init__(
            "Savol juda uzun. Eng ko'pi %(limit)s belgi." % {"limit": limit}
        )


class FreeQuestionsSpent(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Bugungi bepul savollar tugadi. Obuna bo'lsangiz, kampaniyalaringiz haqida ancha ko'proq so'ray olasiz."
        )


class ChatNeedsSubscription(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "AI yordamchi faqat tarif bilan ishlaydi. Tarifni oching yoki yangilang - suhbat darhol ochiladi."
        )


class ChatQuestionsSpent(DomainError):
    def __init__(self, limit: int) -> None:
        super().__init__(
            "Bugungi suhbat so'rovlari tugadi (%(limit)s ta). Ertaga yana shuncha savol beriladi."
            % {"limit": limit}
        )


class ChatBudgetSpent(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Bu oyda AI uchun ajratilgan mablag' tugadi. Agent ishlashda davom etadi; suhbat keyingi oyda ochiladi."
        )


class AnswerUnavailable(DomainError):
    def __init__(self) -> None:
        super().__init__("Javob olinmadi. Birozdan so'ng qayta urining.")


class RefusalNotFound(DomainError):
    def __init__(self) -> None:
        super().__init__("Bu reklama endi xato holatida emas.")
