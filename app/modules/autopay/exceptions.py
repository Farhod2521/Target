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
