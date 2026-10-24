from app.common.exceptions import DomainError


class MiniAppRefused(DomainError):
    code = "refused"


class MiniAppUnavailable(MiniAppRefused):
    code = "unavailable"

    def __init__(self) -> None:
        super().__init__("Hozircha mavjud emas. Biroz keyinroq urinib ko'ring.")


class NotInsideTelegram(MiniAppRefused):
    code = "outside"

    def __init__(self) -> None:
        super().__init__("Bu sahifa Telegram ichida ochiladi.")


class ProofRefused(MiniAppRefused):
    code = "invalid"

    def __init__(self) -> None:
        super().__init__("Tekshiruvdan o'tmadi. Telegram'dan qayta oching.")


class ProofExpired(MiniAppRefused):
    code = "expired"

    def __init__(self) -> None:
        super().__init__("Seans eskirdi. Telegram'dan qayta oching.")


class ChatNotLinked(MiniAppRefused):
    code = "unlinked"

    def __init__(self) -> None:
        super().__init__(
            "Bu Telegram akkaunt kabinetga ulanmagan. Avval kabinetdan ulang."
        )


__all__ = [
    "ChatNotLinked",
    "MiniAppRefused",
    "MiniAppUnavailable",
    "NotInsideTelegram",
    "ProofExpired",
    "ProofRefused",
]
