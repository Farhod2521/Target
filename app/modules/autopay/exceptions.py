from app.common.exceptions import DomainError, NotFound


class AutopayUnavailable(NotFound):
    code = "autopay_unavailable"

    def __init__(self) -> None:
        super().__init__("Avtomatik to'lov hozircha yoqilmagan.")


class ConsentRequired(DomainError):
    code = "autopay_consent_required"

    def __init__(self) -> None:
        super().__init__(
            "Kartani bog'lash uchun obuna har muddatda shu kartadan avtomatik "
            "yechilishiga rozilik bering."
        )


class PhoneRequired(DomainError):
    code = "autopay_phone_required"

    def __init__(self) -> None:
        super().__init__(
            "Karta egasining telefon raqamini 998XXXXXXXXX ko'rinishida kiriting."
        )


class CardNotFound(NotFound):
    code = "autopay_card_not_found"

    def __init__(self) -> None:
        super().__init__("Bog'langan karta topilmadi.")


class CardServiceDown(DomainError):
    code = "autopay_unreachable"
    status_code = 503

    def __init__(self) -> None:
        super().__init__(
            "Rahmat hozir javob bermayapti. Birozdan so'ng urinib ko'ring."
        )


class CardDeclined(DomainError):
    code = "card_declined"

    def __init__(self, reason: str = "") -> None:
        super().__init__(reason or "Karta to'lovni rad etdi.")


class CardCodeWrong(DomainError):
    code = "card_code_wrong"

    def __init__(self) -> None:
        super().__init__("SMS kod noto'g'ri. Qaytadan kiriting.")


class CardCodeStale(DomainError):
    code = "card_code_stale"

    def __init__(self) -> None:
        super().__init__("Bu to'lovni tasdiqlab bo'lmadi. To'lovni qaytadan boshlang.")


class CardCodeTooSoon(DomainError):
    code = "card_code_too_soon"
    status_code = 429

    def __init__(self, seconds: int) -> None:
        self.seconds = seconds
        super().__init__(f"Yangi kodni {seconds} soniyadan so'ng so'rash mumkin.")


class CardCodeLimit(DomainError):
    code = "card_code_limit"

    def __init__(self) -> None:
        super().__init__(
            "Kod ko'p marta so'raldi. To'lovni qaytadan boshlang yoki "
            "boshqa usulda to'lang."
        )
