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


class NoPairForCrm(Conflict):
    code = "no_pair_for_crm"

    def __init__(self) -> None:
        super().__init__(
            "Bu biznesning sahifa va reklama akkaunti juftligi topilmadi. "
            "Ulanishni tekshiring."
        )


class LoginRequired(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Xodimni tanlang yoki uning ismi, emaili va parolini kiriting."
        )


class UnknownAccount(NotFound):
    code = "unknown_account"

    def __init__(self) -> None:
        super().__init__("Reklama akkaunti topilmadi.")


class UnknownNetwork(NotFound):
    code = "unknown_network"

    def __init__(self) -> None:
        super().__init__("Bu tarmoq biznesga ulanmagan.")


class MetaIsPair(DomainError):
    code = "meta_is_pair"

    def __init__(self) -> None:
        super().__init__(
            "Meta sahifa va reklama akkaunti juftligi «Ulanishlar» bo'limida "
            "boshqariladi."
        )


class AccountNotInUse(DomainError):
    code = "account_not_in_use"

    def __init__(self) -> None:
        super().__init__("Avval bu akkauntni «Ulanishlar» bo'limida yoqing.")


class NetworkTaken(Conflict):
    code = "network_taken"

    def __init__(self) -> None:
        super().__init__(
            "Bu biznesga shu tarmoqning akkaunti allaqachon ulangan. Avval uni uzing."
        )


class AccountBound(Conflict):
    code = "account_bound"

    def __init__(self) -> None:
        super().__init__("Bu akkaunt boshqa biznesga ulangan.")
