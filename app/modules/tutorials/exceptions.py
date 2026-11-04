from app.common.exceptions import NotFound


class TutorialNotFound(NotFound):
    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or "Video darslik topilmadi.")
