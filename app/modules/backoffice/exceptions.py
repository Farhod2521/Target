from app.common.exceptions import DomainError


class CannotChangeOwnRoles(DomainError):
    def __init__(self) -> None:
        super().__init__("O'z rolingizni o'zgartira olmaysiz - hamkasbdan so'rang.")


class SuperuserRolesFixed(DomainError):
    def __init__(self) -> None:
        super().__init__("Super adminda hamma rol bor, ularni o'zgartirib bo'lmaydi.")


class StaffAccountMissing(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Bu email bilan akkaunt topilmadi. Avval xodim saytda ro'yxatdan o'tsin."
        )


class StaffAccountClosed(DomainError):
    def __init__(self) -> None:
        super().__init__("Bu akkaunt bloklangan. Avval blokdan chiqaring.")


class AlreadyStaff(DomainError):
    def __init__(self) -> None:
        super().__init__("Bu odam allaqachon jamoada.")


class CampaignNotMirrored(DomainError):
    status_code = 409
    code = "not_ready"

    def __init__(self) -> None:
        super().__init__(
            "Kampaniya hali sinxronlanmagan. Ishga tushirish ma'lumotlari pastda."
        )


class PromoCodeInUse(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Bu kod allaqachon ishlatilgan, uni o'chirib bo'lmaydi. O'chirish o'rniga uni o'chiq holatga o'tkazing."
        )


class RefusalAnswerEmpty(DomainError):
    def __init__(self) -> None:
        super().__init__("Kamida bitta tilda javob yozing.")


class DirectionInUse(DomainError):
    def __init__(self, *, count: int) -> None:
        super().__init__(
            "Bu yo'nalishni %(count)s ta biznes ishlatmoqda, uni o'chirib bo'lmaydi. O'chirish o'rniga uni nofaol qiling."
            % {"count": count}
        )


class EmailMismatch(DomainError):
    def __init__(self) -> None:
        super().__init__("Email mos kelmadi — akkaunt o'chirilmadi.")


class CrmEmailMismatch(DomainError):
    def __init__(self) -> None:
        super().__init__("Email mos kelmadi — CRM o'chirilmadi.")


class FacebookEmailMismatch(DomainError):
    def __init__(self) -> None:
        super().__init__("Email mos kelmadi — Facebook uzilmadi.")


class NothingToForget(DomainError):
    status_code = 409

    def __init__(self) -> None:
        super().__init__("Bu mijozda Facebook'dan kelgan hech narsa yo'q.")


class NothingToSend(DomainError):
    status_code = 409

    def __init__(self) -> None:
        super().__init__(
            "Yuborilmay qolgan signal yo'q: tugagan kunlar yuborilgan yoki muddati o'tgan."
        )


class AlreadyBlocked(DomainError):
    def __init__(self) -> None:
        super().__init__("Bu akkaunt allaqachon bloklangan.")


class NotBlocked(DomainError):
    def __init__(self) -> None:
        super().__init__("Bu akkaunt bloklanmagan.")


class SuperuserOnly(DomainError):
    def __init__(self) -> None:
        super().__init__("Parolni faqat super admin o'rnata oladi.")


class PasswordRefused(DomainError):
    pass


class InvoiceBeingPaid(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Bu hisob hozir to'lanmoqda. Avval uni bo'shating, keyin o'chiring."
        )


class InvoiceAlreadyArchived(DomainError):
    def __init__(self) -> None:
        super().__init__("Bu hisob allaqachon arxivda.")
