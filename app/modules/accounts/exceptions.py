from app.common.exceptions import Conflict, DomainError, InputRefused, NotFound


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


class EmailAlreadyVerified(Conflict):
    code = "email_already_verified"

    def __init__(self) -> None:
        super().__init__("Email allaqachon tasdiqlangan.")


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


class TooManyAttempts(DomainError):
    """One sentence for every limit: which one was met, and whether the email
    named an account, are what somebody guessing would like to know."""

    status_code = 429
    code = "too_many_attempts"

    def __init__(self) -> None:
        super().__init__("Juda ko'p urinish. Bir oz kuting va qayta urinib ko'ring.")


class HandoffExpired(DomainError):
    code = "expired"

    def __init__(self) -> None:
        super().__init__(
            "Havola eskirgan yoki ishlatilgan. Telegramdagi tugmani qaytadan bosing."
        )


class AccountBlocked(DomainError):
    """Said only after the password matched: the words are the block's own
    (``blocked_message``), so a stranger typing an address learns nothing."""

    status_code = 403
    code = "account_blocked"


class HandoffBlocked(DomainError):
    status_code = 403
    code = "blocked"

    def __init__(self) -> None:
        super().__init__("Kirish mumkin emas.")


class ResetLinkInvalid(DomainError):
    """The new-password link is unknown, over a quarter hour old, already
    used, or the password moved since it was issued. Not told apart: each is
    the same next move, and naming which would tell whoever holds the link
    how close they got."""

    code = "reset_link_invalid"

    def __init__(self) -> None:
        super().__init__("Havola eskirgan yoki ishlatilgan. Botdan yangi havola oling.")


class SocialSignInOff(NotFound):
    code = "social_unavailable"

    def __init__(self) -> None:
        super().__init__("Bu usul bilan kirish hozircha yoqilmagan.")


class SocialPendingExpired(DomainError):
    """The finishing form (phone and role) outlived its half hour, or was
    already spent: the Google button has to be pressed again."""

    status_code = 410
    code = "social_expired"

    def __init__(self) -> None:
        super().__init__("Vaqt tugadi. Google orqali qaytadan kiring.")


class PhoneTaken(InputRefused):
    """A new account by Google for a number another account holds: one
    person opening a second account by mistake, far more often than not."""

    code = "phone_taken"

    def __init__(self) -> None:
        super().__init__(
            {
                "phone": "Bu raqam bilan akkaunt bor. Parol bilan kiring va "
                "Google'ni Sozlamalardan ulang."
            }
        )


class SocialLastWay(Conflict):
    """Unlinking the only way in: an account opened by Google has no password."""

    code = "social_last_way"

    def __init__(self) -> None:
        super().__init__("Avval parol o'rnating: aks holda akkauntga kira olmaysiz.")
