from app.common.exceptions import Conflict, NotFound


class BroadcastNotFound(NotFound):
    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or "Rassilka topilmadi.")


class BroadcastLocked(Conflict):
    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or "Yuborilgan rassilkani o'zgartirib bo'lmaydi.")
