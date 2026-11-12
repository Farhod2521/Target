from app.common.exceptions import DomainError


class SubscriptionRequired(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Obuna muddati tugagan. Reklama akkauntini ulash uchun obunani yangilang."
        )


class AccountLocked(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Tayyorgarlik yakunlangan - reklama akkauntini o'zgartirib bo'lmaydi. O'zgartirish uchun qo'llab-quvvatlashga murojaat qiling."
        )


class PageLocked(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Tayyorgarlik yakunlangan - sahifani almashtirib bo'lmaydi. Yangi sahifa qo'shish uchun qo'shimcha o'rin kerak."
        )


class PairLocked(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Bu sahifaning reklama akkaunti tanlangan. Almashtirish uchun yordamga yozing."
        )


class PairExists(DomainError):
    def __init__(self) -> None:
        super().__init__("Bu akkaunt sahifaga allaqachon qo'shilgan.")


class NoFreeSlot(DomainError):
    def __init__(self, *, noun: str) -> None:
        super().__init__(
            "Bo'sh o'rin yo'q: obunangizda %(noun)s uchun joy qolmagan. Birini o'chiring yoki qo'shimcha o'rin oling."
            % {"noun": noun}
        )


class AlreadyEnabled(DomainError):
    def __init__(self) -> None:
        super().__init__("Bu allaqachon obunangizga qo'shilgan.")


class NoPageChosen(DomainError):
    def __init__(self) -> None:
        super().__init__("Hech qaysi sahifa belgilanmadi.")


class PageNotInCabinet(DomainError):
    def __init__(self) -> None:
        super().__init__("Bu sahifa obunaga kiritilmagan — uziladigan narsa yo'q.")


class NothingToRebind(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Bu akkauntda biriktirilgan obuna yo'q — avval oddiy tanlash orqali akkaunt ulanishi kerak."
        )


class AccountAlreadyBound(DomainError):
    def __init__(self) -> None:
        super().__init__("Bu akkaunt allaqachon biriktirilgan.")


class PageAlreadyChosen(DomainError):
    def __init__(self) -> None:
        super().__init__("Bu sahifa allaqachon tanlangan.")


class ConnectionFailed(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Meta bilan ulanib bo'lmadi. Birozdan keyin qayta urinib ko'ring."
        )


class IdentityTaken(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Bu Facebook akkaunt boshqa kabinetga ulangan. Bitta Facebook akkaunt bitta kabinetda ishlaydi - avvalgi kabinetingizga kiring yoki qo'llab-quvvatlashga murojaat qiling."
        )


class StateMismatch(DomainError):
    def __init__(self) -> None:
        super().__init__("Ulanish so'rovi eskirgan. Qaytadan boshlang.")


class NoConnection(DomainError):
    def __init__(self) -> None:
        super().__init__("Avval Meta akkauntini ulang.")


class UnknownAccount(DomainError):
    def __init__(self) -> None:
        super().__init__("Bunday akkaunt topilmadi.")


class AccountCannotAdvertise(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Bu reklama akkaunti Meta'da faol emas, shuning uchun uni tanlab bo'lmaydi. Ads Manager'da holatini tekshiring yoki boshqa akkauntni tanlang."
        )


class NoActivePage(DomainError):
    def __init__(self) -> None:
        super().__init__("Avval sahifani tanlang.")


class UnknownPage(DomainError):
    def __init__(self) -> None:
        super().__init__("Bu sahifa topilmadi. Ulanishlar ro'yxatini yangilang.")


class ConnectionTooNarrow(DomainError):
    def __init__(self, missing: tuple[str, ...] = ()) -> None:
        self.missing = missing
        super().__init__(
            "Meta bergan ruxsatlar yetarli emas. Akkauntni qayta ulang va so'ralgan ruxsatlarni bekor qilmang."
        )


class RefreshTooSoon(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Tekshirilmoqda. Bir necha soniyadan keyin qayta urinib ko'ring."
        )


class NoInstagram(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Bu sahifaga Instagram akkaunti ulanmagan. Uni Facebook sahifa sozlamalarida ulang."
        )


class UnknownInstagram(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Bu Instagram akkaunti sahifaga ulanmagan. Sahifalarni yangilab, qayta urinib ko'ring."
        )


class InstagramLocked(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Tayyorgarlik yakunlangan - tanlangan Instagram akkauntini olib tashlab bo'lmaydi. O'zgartirish uchun qo'llab-quvvatlashga yozing."
        )


class InstagramNotGranted(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Instagram'ga ruxsat berilmagan. Qayta ulang va Instagram belgisini olib tashlamang."
        )


class ConsoleUnavailable(DomainError):
    pass


class AudienceTermsRequired(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Mijozlar ro'yxatini yuklash uchun Meta'ning shartlariga rozilik kerak. Rozilikni Meta sahifasida bering."
        )


class AudienceNotFillable(DomainError):
    def __init__(self) -> None:
        super().__init__("Bu auditoriyaga odam yuklab bo'lmaydi.")


class NobodyToUpload(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Yuklash uchun yaroqli mijoz ma'lumoti topilmadi. Lidlarda telefon yoki email bo'lishi kerak."
        )


class RehearsalCannotErase(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Sinov rejimi yoqilgan - shaxsiy ma'lumotni o'chirib bo'lmaydi."
        )


class UnknownAudienceSource(DomainError):
    def __init__(self) -> None:
        super().__init__("Bu manba endi mavjud emas. Ro'yxatni yangilang.")


class AudienceSourceUnusable(DomainError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)


class AudienceRuleRefused(DomainError):
    def __init__(self, message: str) -> None:
        super().__init__(message)


class UnknownAudienceSeed(DomainError):
    def __init__(self) -> None:
        super().__init__("Bu auditoriya endi mavjud emas. Ro'yxatni yangilang.")


class AudienceSeedUnusable(DomainError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)


class BusinessCountryMissing(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Profilingizda mamlakat ko'rsatilmagan. Bunday auditoriya bitta mamlakat ichida quriladi."
        )


class LookalikeRefused(DomainError):
    def __init__(self, message: str) -> None:
        super().__init__(message)


class GoogleAdsUnavailable(DomainError):
    def __init__(self) -> None:
        super().__init__("Google Ads hozircha mavjud emas.")


class GoogleConnectionFailed(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Google bilan ulanib bo'lmadi. Birozdan keyin qayta urinib ko'ring."
        )


class GoogleAdsNotGranted(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Google Ads uchun ruxsat berilmadi. Qayta ulang va Google oynasida Google Ads belgisini qoldiring."
        )


class GoogleIdentityTaken(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Bu Google akkaunt boshqa kabinetga ulangan. Bitta Google akkaunt bitta kabinetda ishlaydi - avvalgi kabinetingizga kiring yoki qo'llab-quvvatlashga murojaat qiling."
        )


class GoogleAccountCannotAdvertise(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Bu Google Ads akkauntida reklama berib bo'lmaydi: u yopilgan yoki boshqaruvchi (manager) akkaunt. Boshqasini tanlang."
        )


class GoogleNotConnected(DomainError):
    def __init__(self) -> None:
        super().__init__("Avval Google Ads akkauntini ulang.")


class GoogleNoFreeSlot(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Tarifingizda Google Ads akkaunti uchun joy qolmagan. Tarifni oshiring yoki biz bilan bog'laning."
        )


class GoogleAccountNotInSubscription(DomainError):
    def __init__(self) -> None:
        super().__init__("Bu Google Ads akkaunti obunaga qo'shilmagan.")


class PixelRehearsed(DomainError):
    def __init__(self) -> None:
        super().__init__("Sinov rejimi yoqiq: piksel Meta'da yaratilmadi.")


class PixelAlreadyThere(DomainError):
    def __init__(self) -> None:
        super().__init__("Bu akkauntda piksel allaqachon bor. Ro'yxatdan tanlang.")


class PixelNotAllowed(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Meta piksel yaratishga ruxsat bermadi. Reklama akkauntidagi "
            "rolingizni tekshiring yoki pikselni Events Manager'da yarating."
        )


class PixelNotCreated(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Pikselni yaratib bo'lmadi. Meta ulanishini tekshirib, qayta urining."
        )


class AccountNotForPage(DomainError):
    """A new pair whose ad account is not in the page's portfolio."""

    def __init__(self, reason: str = "") -> None:
        from app.modules.integrations.selectors.portfolio import (
            OTHER_PORTFOLIO,
            REASONS,
        )

        self.reason = reason or OTHER_PORTFOLIO
        super().__init__(
            "Bu reklama akkauntini sahifaga ulab bo'lmaydi. "
            + REASONS.get(self.reason, REASONS[OTHER_PORTFOLIO])
        )


class AdAccountRehearsed(DomainError):
    def __init__(self) -> None:
        super().__init__("Sinov rejimi yoqiq: reklama akkaunti Meta'da yaratilmadi.")


class AdAccountNoPortfolio(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Yangi reklama akkaunti faqat biznes portfoliosidagi sahifa uchun "
            "yaratiladi. Bu sahifa shaxsiy yoki portfoliosi noma'lum."
        )


class AdAccountLimit(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Meta bu biznes portfoliosida yangi reklama akkaunti ochishga ruxsat "
            "bermadi: akkauntlar soni chegarasiga yetilgan."
        )


class AdAccountBadStanding(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Portfoliodagi reklama akkauntlaridan biri bloklangan yoki "
            "tekshiruvda - Meta yangisini ochmaydi. Avval o'shani hal qiling."
        )


class AdAccountTwoFactor(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Meta ikki bosqichli tasdiqlashni talab qildi. Facebook profilingizda "
            "uni yoqing va qayta urinib ko'ring."
        )


class AdAccountNotAllowed(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Meta reklama akkaunti yaratishga ruxsat bermadi. Biznes "
            "portfoliosida admin ekaningizni tekshiring."
        )


class AdAccountNotCreated(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Reklama akkauntini yaratib bo'lmadi. Birozdan so'ng qayta urinib ko'ring."
        )
