from app.common.exceptions import Conflict, DomainError, NotAllowed, NotFound


class UnknownBusiness(NotFound):
    code = "unknown_business"
    def __init__(self) -> None:
        super().__init__("Biznes topilmadi.")


class NoAccess(NotAllowed):
    code = "no_access"
    def __init__(self) -> None:
        super().__init__("Bu amal sizga ruxsat etilmagan.")


class UnknownMember(NotFound):
    code = "unknown_member"
    def __init__(self) -> None:
        super().__init__("Xodim topilmadi.")


class MemberExists(Conflict):
    code = "member_exists"
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


class NoSeat(Conflict):
    code = "no_seat"
    def __init__(self) -> None:
        super().__init__("Bo'sh joy yo'q. Yangi xodim uchun joy sotib oling.")


class SalesThroughCrm(Conflict):
    code = "sales_through_crm"
    def __init__(self) -> None:
        super().__init__(
            "Sotuv manageri hozircha CRM bo'limida qo'shiladi. "
            "Qo'shilgach, u shu ro'yxatda o'zi paydo bo'ladi."
        )


class ManagedByCrm(Conflict):
    code = "managed_by_crm"
    def __init__(self) -> None:
        super().__init__("Bu sotuv manageri. Uni CRM bo'limidan o'chiring.")


class LoginRequired(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Xodimni tanlang yoki uning ismi, emaili va parolini kiriting."
        )
