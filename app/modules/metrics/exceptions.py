from app.common.exceptions import DomainError


class AccountUnreadable(DomainError):
    def __init__(self) -> None:
        super().__init__("Bu reklama akkauntini o'qib bo'lmadi.")
