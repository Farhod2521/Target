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


class CodeExpired(DomainError):
    code = "code_expired"

    def __init__(self) -> None:
        super().__init__("Kodning muddati tugadi. Yangi kod oling.")


class CodeWrong(DomainError):
    code = "code_wrong"

    def __init__(self, *, left: int) -> None:
        super().__init__(f"Kod noto'g'ri. Yana {left} marta urinish mumkin.")


class CodeTriesSpent(DomainError):
    status_code = 429
    code = "code_tries_spent"

    def __init__(self) -> None:
        super().__init__("Urinishlar tugadi. Yangi kod oling.")


class ResendTooSoon(DomainError):
    status_code = 429
    code = "resend_too_soon"

    def __init__(self, *, seconds: int) -> None:
        super().__init__(f"Yangi kodni {seconds} soniyadan keyin so'rash mumkin.")
        self.seconds = seconds


class TooManyCodes(DomainError):
    status_code = 429
    code = "too_many_codes"

    def __init__(self) -> None:
        super().__init__(
            "Juda ko'p kod so'raldi. Bir soatdan keyin qayta urinib ko'ring."
        )


class MailUnavailable(DomainError):
    status_code = 503
    code = "mail_unavailable"

    def __init__(self) -> None:
        super().__init__(
            "Emailga xat yuborib bo'lmadi. Birozdan keyin qayta urinib ko'ring."
        )
