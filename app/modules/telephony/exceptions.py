from app.common.exceptions import DomainError, NotFound


class NotConnected(DomainError):
    status_code = 409

    def __init__(self) -> None:
        super().__init__("Telefoniya ulanmagan.")


class TenantShape(DomainError):
    status_code = 422

    def __init__(self) -> None:
        super().__init__("UTeL manzili noto'g'ri. Masalan: utc181 yoki utc181.utel.uz.")


class ExchangeRefusedLogin(DomainError):
    status_code = 422

    def __init__(self) -> None:
        super().__init__("UTeL login yoki parolni qabul qilmadi.")


class ExchangeSessionEnded(DomainError):
    status_code = 409

    def __init__(self) -> None:
        super().__init__(
            "UTeL kirish kalitini qabul qilmayapti. Login va parolni qayta kiriting."
        )


class ExchangeUnreachable(DomainError):
    status_code = 502

    def __init__(self) -> None:
        super().__init__("UTeL javob bermadi. Birozdan keyin qayta urining.")


class ExtensionNotFound(NotFound):
    code = "extension_not_found"

    def __init__(self) -> None:
        super().__init__("Ichki nomer topilmadi.")


class ExtensionGone(DomainError):
    status_code = 409

    def __init__(self) -> None:
        super().__init__("Bu ichki nomer UTeL'da endi yo'q.")


class NotStaff(DomainError):
    status_code = 422

    def __init__(self) -> None:
        super().__init__("Bu foydalanuvchi faol xodim emas.")


class CallNotFound(NotFound):
    code = "call_not_found"

    def __init__(self) -> None:
        super().__init__("Qo'ng'iroq topilmadi.")


class NoRecording(NotFound):
    code = "no_recording"

    def __init__(self) -> None:
        super().__init__("Bu qo'ng'iroqning yozuvi yo'q.")
