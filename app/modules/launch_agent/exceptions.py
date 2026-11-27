from app.common.exceptions import DomainError


class SessionNotFound(DomainError):
    status_code = 404
    code = "launch_agent_session_not_found"

    def __init__(self) -> None:
        super().__init__("Suhbat topilmadi.")


class SessionClosed(DomainError):
    status_code = 409
    code = "launch_agent_session_closed"

    def __init__(self) -> None:
        super().__init__("Bu suhbat yopilgan. Yangisini boshlang.")


class TooManyTurns(DomainError):
    status_code = 429
    code = "launch_agent_too_many_turns"

    def __init__(self) -> None:
        super().__init__(
            "Bu suhbat juda uzayib ketdi. Yangi suhbat boshlang yoki "
            "«Reklama berish» sahifasidan davom eting."
        )


class HeardLimit(DomainError):
    status_code = 429
    code = "launch_agent_daily_limit"

    def __init__(self) -> None:
        super().__init__(
            "Bugun yozma xabarlar chegarasiga yetdingiz. Tugmalar orqali "
            "davom eting yoki ertaga yozing."
        )


class TextTooLong(DomainError):
    status_code = 422
    code = "launch_agent_text_too_long"

    def __init__(self, limit: int) -> None:
        super().__init__(f"Xabar {limit} belgidan oshmasin.")


class VoiceOff(DomainError):
    status_code = 503
    code = "launch_agent_voice_off"

    def __init__(self) -> None:
        super().__init__("Ovozli xabar hozircha ishlamaydi. Yozib yuboring.")


class VoiceBusy(DomainError):
    status_code = 503
    code = "launch_agent_voice_busy"

    def __init__(self) -> None:
        super().__init__(
            "Ovozni matnga aylantirib bo'lmadi. Birozdan so'ng qayta urining "
            "yoki yozib yuboring."
        )


class VoiceRefused(DomainError):
    status_code = 422
    code = "launch_agent_voice_refused"

    def __init__(self) -> None:
        super().__init__("Bu yozuvni o'qib bo'lmadi. Qaytadan yozib oling.")


class VoiceSilent(DomainError):
    status_code = 422
    code = "launch_agent_voice_silent"

    def __init__(self) -> None:
        super().__init__("Yozuvda gap eshitilmadi. Qaytadan gapirib ko'ring.")


class VoiceTooBig(DomainError):
    status_code = 413
    code = "launch_agent_voice_too_big"

    def __init__(self, megabytes: int) -> None:
        super().__init__(f"Yozuv {megabytes} MB dan oshmasin.")


class VoiceLimit(DomainError):
    status_code = 429
    code = "launch_agent_voice_daily_limit"

    def __init__(self) -> None:
        super().__init__("Bugun ovozli xabarlar chegarasiga yetdingiz. Yozib yuboring.")


__all__ = [
    "HeardLimit",
    "SessionClosed",
    "SessionNotFound",
    "TextTooLong",
    "TooManyTurns",
    "VoiceBusy",
    "VoiceLimit",
    "VoiceOff",
    "VoiceRefused",
    "VoiceSilent",
    "VoiceTooBig",
]
