from app.common.exceptions import DomainError


class CannotChangeOwnRoles(DomainError):
    def __init__(self) -> None:
        super().__init__("O'z rolingizni o'zgartira olmaysiz - hamkasbdan so'rang.")


class PromoCodeInUse(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Bu kod allaqachon ishlatilgan, uni o'chirib bo'lmaydi. O'chirish o'rniga uni o'chiq holatga o'tkazing."
        )


class EmailMismatch(DomainError):
    def __init__(self) -> None:
        super().__init__("Email mos kelmadi — akkaunt o'chirilmadi.")


class SuperuserOnly(DomainError):
    def __init__(self) -> None:
        super().__init__("Parolni faqat super admin o'rnata oladi.")
