from app.common.exceptions import DomainError


class BotNotConfigured(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Telegram bot hozircha sozlanmagan. Biroz keyinroq urinib ko'ring."
        )


class LinkTokenInvalid(DomainError):
    def __init__(self) -> None:
        super().__init__("Havola eskirgan. Kabinetdan yangisini oling.")


class ChatTakenByAnother(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Bu Telegram akkaunt boshqa kabinetga ulangan. Avval o'sha kabinetdan uzing."
        )


class NotLinked(DomainError):
    def __init__(self) -> None:
        super().__init__("Telegram ulanmagan.")


class StaffLinkInvalid(DomainError):
    def __init__(self) -> None:
        super().__init__("Havola eskirgan. Ofisdan yangisini oling.")


class StaffChatTaken(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Bu Telegram akkaunt boshqa xodimga ulangan. Avval o'sha yerda uzing."
        )


__all__ = [
    "BotNotConfigured",
    "ChatTakenByAnother",
    "LinkTokenInvalid",
    "NotLinked",
    "StaffChatTaken",
    "StaffLinkInvalid",
]
