from app.common.exceptions import DomainError


class SetupNotReady(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Hamma qadamlar bajarilmagan. Ro'yxatda ochiq qolgan qadamni tekshiring."
        )
