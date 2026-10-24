from app.common.exceptions import Conflict, DomainError


class UnsupportedLanguage(DomainError):
    def __init__(self) -> None:
        super().__init__("Bu til qo'llab-quvvatlanmaydi.")


class WrongPassword(DomainError):
    def __init__(self) -> None:
        super().__init__("Joriy parol noto'g'ri.")


class EmailTaken(Conflict):
    def __init__(self) -> None:
        super().__init__("Bu email bilan akkaunt allaqachon bor.")


class BadCredentials(DomainError):
    status_code = 401
    code = "bad_credentials"

    def __init__(self) -> None:
        super().__init__("Email yoki parol noto'g'ri.")


class BadPhone(DomainError):
    status_code = 422
    code = "bad_phone"
