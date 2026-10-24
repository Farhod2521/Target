from app.common.exceptions import DomainError


class SheetsUnavailable(DomainError):
    def __init__(self) -> None:
        super().__init__("Google jadval hozircha mavjud emas.")


class SheetSubscriptionRequired(DomainError):
    def __init__(self) -> None:
        super().__init__("Google jadvalni ulash uchun faol obuna kerak.")


class GoogleStateMismatch(DomainError):
    def __init__(self) -> None:
        super().__init__("Ulanish eskirgan. Tugmani qaytadan bosing.")


class GoogleDeclined(DomainError):
    def __init__(self) -> None:
        super().__init__("Google ruxsat bermadi. Jadvalga yozish uchun ruxsat kerak.")


class DrivePermissionMissing(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Google oynasida jadvalga yozish belgisini qoldiring va qaytadan urinib ko'ring."
        )


class GoogleUnreachable(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Google bilan bog'lanib bo'lmadi. Birozdan keyin qaytadan urinib ko'ring."
        )


class NoSheetLink(DomainError):
    def __init__(self) -> None:
        super().__init__("Google jadval ulanmagan.")


class NothingToRecreate(DomainError):
    def __init__(self) -> None:
        super().__init__("Jadval joyida - yangisini yaratish shart emas.")


class OwnFileUnavailable(DomainError):
    def __init__(self) -> None:
        super().__init__("O'z faylingizga yozish hozircha mavjud emas.")


class FormNotFound(DomainError):
    def __init__(self) -> None:
        super().__init__("Tanlangan forma topilmadi. Ro'yxatdan qaytadan tanlang.")


class NotChoosingFile(DomainError):
    def __init__(self) -> None:
        super().__init__("Fayl tanlash vaqti o'tgan. Jadvalni qaytadan ulang.")


class PickerExpired(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Google bilan kirish eskirdi. Faylni tanlash uchun qaytadan kiring."
        )


class BadFileChoice(DomainError):
    def __init__(self) -> None:
        super().__init__("Bu faylni tanlab bo'lmadi. Boshqa jadvalni tanlang.")


class SheetModeUnchanged(DomainError):
    def __init__(self) -> None:
        super().__init__("Bu usul hozir ham ishlayapti.")


class SheetModeLocked(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Yozish usulini hozir o'zgartirib bo'lmaydi. Sahifani yangilab, qaytadan urinib ko'ring."
        )
