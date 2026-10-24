from app.common.exceptions import DomainError


class EmptyMessage(DomainError):
    def __init__(self) -> None:
        super().__init__("Xabar bo'sh. Matn yozing yoki fayl tanlang.")


class MessageTooLong(DomainError):
    def __init__(self, limit: int) -> None:
        super().__init__(
            "Xabar juda uzun. Eng ko'pi %(limit)s belgi." % {"limit": limit}
        )


class UploadTooLarge(DomainError):
    def __init__(self, limit_mb: int) -> None:
        super().__init__(
            "Fayl juda katta. Eng ko'pi %(limit)s MB." % {"limit": limit_mb}
        )


class UnsupportedFileType(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Bu turdagi faylni yuborib bo'lmaydi. Rasm, video yoki hujjat tanlang."
        )


class TooManyFiles(DomainError):
    def __init__(self, limit: int) -> None:
        super().__init__(
            "Bitta xabarda eng ko'pi %(limit)s ta fayl." % {"limit": limit}
        )


class SendTooLarge(DomainError):
    def __init__(self, limit_mb: int) -> None:
        super().__init__(
            "Fayllar birgalikda juda katta. Eng ko'pi %(limit)s MB."
            % {"limit": limit_mb}
        )


class VoiceRefused(DomainError):
    def __init__(self, limit_seconds: int) -> None:
        super().__init__(
            "Ovozli xabarni yuborib bo'lmadi. Eng ko'pi %(limit)s daqiqa."
            % {"limit": limit_seconds // 60}
        )


class UnknownSticker(DomainError):
    def __init__(self) -> None:
        super().__init__("Bunday stiker yo'q.")


class MixedMessage(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Ovozli xabar va stiker alohida yuboriladi, matn yoki fayl bilan emas."
        )


class ReplyTargetMissing(DomainError):
    def __init__(self) -> None:
        super().__init__("Javob berilayotgan xabar topilmadi.")


class MessageNotYours(DomainError):
    def __init__(self) -> None:
        super().__init__("Faqat o'z xabaringizni o'zgartira olasiz.")


class EditWindowClosed(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Bu xabarni endi o'zgartirib bo'lmaydi: 24 soatdan ko'p vaqt o'tgan."
        )


class MessageGone(DomainError):
    def __init__(self) -> None:
        super().__init__("Bu xabar o'chirilgan.")


class NothingToEdit(DomainError):
    def __init__(self) -> None:
        super().__init__("Bu xabarni tahrirlab bo'lmaydi.")


class TooManyMessages(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Juda tez yozyapsiz. Bir daqiqadan keyin qayta urinib ko'ring."
        )


class ThreadNotFound(DomainError):
    def __init__(self) -> None:
        super().__init__("Suhbat topilmadi.")


class AlreadySent(DomainError):
    def __init__(self) -> None:
        super().__init__("Bu xabar allaqachon yuborilgan.")
