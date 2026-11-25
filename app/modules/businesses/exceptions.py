from app.common.exceptions import DomainError, NotAllowed


class UnknownBusiness(DomainError):
    def __init__(self) -> None:
        super().__init__("Biznes topilmadi.")


class NoAccess(NotAllowed):
    def __init__(self) -> None:
        super().__init__("Bu amal sizga ruxsat etilmagan.")


class UnknownMember(DomainError):
    def __init__(self) -> None:
        super().__init__("Xodim topilmadi.")


class MemberExists(DomainError):
    def __init__(self) -> None:
        super().__init__("Bu xodim biznesga allaqachon qo'shilgan.")


class OwnerIsNotMember(DomainError):
    def __init__(self) -> None:
        super().__init__("Biznes egasi xodim sifatida qo'shilmaydi.")


class NotYourStaff(DomainError):
    def __init__(self) -> None:
        super().__init__("Bu foydalanuvchi sizning xodimingiz emas.")


class RoleRequired(DomainError):
    def __init__(self) -> None:
        super().__init__("Kamida bitta rol tanlang.")


class UnknownRole(DomainError):
    def __init__(self) -> None:
        super().__init__("Bunday rol yo'q.")


class RopNeedsSales(DomainError):
    def __init__(self) -> None:
        super().__init__("ROP belgisi faqat sotuv manageriga beriladi.")


class BadGrant(DomainError):
    def __init__(self, reason: str = "") -> None:
        super().__init__(reason or "Ruxsat noto'g'ri berilgan.")
