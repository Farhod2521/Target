from typing import Any, ClassVar

from app.common.exceptions import DomainError
from app.common.money import format_minor


class NoAdAccount(DomainError):
    def __init__(self) -> None:
        super().__init__("Avval reklama akkauntini ulang va tanlang.")


class SyncAlreadyRunning(DomainError):
    def __init__(self) -> None:
        super().__init__("Yangilanish allaqachon ketmoqda. Biroz kuting.")


class ConnectionUnusable(DomainError):
    def __init__(self) -> None:
        super().__init__("Meta ruxsati tugagan. Akkauntni qayta ulang.")


class SyncFailed(DomainError):
    def __init__(self, *, cause: str = "") -> None:
        super().__init__(
            "Ma'lumotlarni yangilab bo'lmadi. Birozdan keyin qayta urinib ko'ring."
        )
        self.cause = cause


class ProfileIncomplete(DomainError):
    def __init__(self) -> None:
        super().__init__("Avval biznes profilini to'ldiring.")


class FreeProposalsUsed(DomainError):
    def __init__(self, *, limit: int) -> None:
        super().__init__(
            "Tarifsiz %(limit)s ta reklama taklifi tayyorlanadi va ular ishlatib bo'lindi. Yangisi uchun tarifni tanlang - tayyor reklamalaringiz joyida."
            % {"limit": limit}
        )


class AnswersIncomplete(DomainError):
    def __init__(self) -> None:
        super().__init__("Avval barcha savollarga javob bering.")


class PreparationRunning(DomainError):
    def __init__(self) -> None:
        super().__init__("AI hozir tayyorlamoqda. Biroz kuting.")


class DraftNotReady(DomainError):
    def __init__(self) -> None:
        super().__init__("Avval AI taklifini kutib turing.")


class AlreadyRegenerated(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Bu bo'lim bir marta qayta yaratilgan. Endi qo'lda tahrirlang."
        )


class NoInterestChosen(DomainError):
    def __init__(self) -> None:
        super().__init__("Kamida bitta qiziqishni belgilang.")


class UnknownMedia(DomainError):
    def __init__(self) -> None:
        super().__init__("Bu kreativ topilmadi. Ro'yxatni yangilang.")


class UnknownVariant(DomainError):
    def __init__(self) -> None:
        super().__init__("Bu reklama varianti topilmadi. Sahifani yangilang.")


class TooManyCreatives(DomainError):
    def __init__(self, *, limit: int, chosen: int) -> None:
        super().__init__(
            "Ko'pi bilan %(limit)s ta rasm. Hozir %(chosen)s ta tanlangan."
            % {"limit": limit, "chosen": chosen}
        )


class UploadTooLarge(DomainError):
    def __init__(self, *, limit_mb: int) -> None:
        super().__init__(
            "Fayl juda katta. Eng ko'pi %(limit)s MB." % {"limit": limit_mb}
        )


class MediaNotStored(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Faylni saqlab bo'lmadi. Biroz kuting va qayta urinib ko'ring."
        )


class MediaNotUploaded(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Faylni Meta kutubxonasiga yuklab bo'lmadi. Qayta urinib ko'ring."
        )


class MediaStillUploading(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Fayl hali Meta kutubxonasiga yuklanmoqda. Bir oz kutib, qayta bosing."
        )


class ChunkOutOfPlace(DomainError):
    def __init__(self, *, offset: int) -> None:
        super().__init__("Faylning bir qismi qayta yuboriladi.")
        self.offset = offset


class ChunkRefused(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Faylni qabul qilib bo'lmadi. Sahifani yangilab, qayta urinib ko'ring."
        )


class ChunkTooLarge(DomainError):
    status_code = 413
    code = "chunk_too_large"

    def __init__(self) -> None:
        super().__init__(
            "Faylning bir qismi juda katta keldi. Sahifani yangilab, qayta urinib ko'ring."
        )


class UploadIncomplete(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Fayl to'liq yetib kelmadi. Qayta tanlang, yuklash davom etadi."
        )


class MediaInUse(DomainError):
    def __init__(self, *, count: int) -> None:
        super().__init__(
            "Bu fayl %(count)s ta reklamada ishlatilmoqda — o'chirib bo'lmaydi."
            % {"count": count}
        )
        self.count = count


class MediaDeleteRunning(DomainError):
    def __init__(self) -> None:
        super().__init__("Bu fayl allaqachon o'chirilmoqda.")


class AdTextMissing(DomainError):
    def __init__(self, *, missing: int, each: bool) -> None:
        if each:
            message = (
                "Yana %(count)s ta faylga matn yozing — har bir reklamada matn bo'lishi kerak."
                % {"count": missing}
            )
        else:
            message = "Kamida bitta matn yozing — busiz «Davom etish» ishlamaydi."
        super().__init__(message)


class LaunchNotReady(DomainError):
    def __init__(self) -> None:
        super().__init__("Bu reklama hali tayyor emas.")


class IdentityHoldPending(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Meta akkauntingizni tasdiqlashni so'rayapti. Ads Manager'ga kirib tasdiqlang, keyin qayta urinib ko'ring."
        )


class NoPage(DomainError):
    def __init__(self) -> None:
        super().__init__("Avval Facebook sahifasini tanlang.")


class PlacesNotFound(DomainError):
    def __init__(self, names: list[str]) -> None:
        self.names = names
        super().__init__(
            "Tanlangan joy Meta'da topilmadi yoki hali tekshirilmoqda: %(names)s. Joylashuvni o'zgartiring yoki birozdan keyin qayta urinib ko'ring."
            % {"names": ", ".join(names)}
        )


class LaunchPageGone(NoPage):
    def __init__(self) -> None:
        DomainError.__init__(
            self,
            "Bu reklama tayyorlangan Facebook sahifasi endi obunangizda yo'q. Sahifani obunaga qayta qo'shing yoki boshqa sahifada yangi reklama boshlang.",
        )


class NoConfirmedInterest(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Tanlangan qiziqishlarni Meta tanimadi. Boshqa nomlarni belgilang yoki o'zingiz qo'shing."
        )


class AudienceNotAllowed(DomainError):
    def __init__(self, names: tuple[str, ...] = ()) -> None:
        listed = ", ".join(name for name in names if name)
        super().__init__(
            "Bu turdagi reklamada o'xshash auditoriya ishlatilmaydi: %(names)s. Auditoriya bo'limidan olib tashlang."
            % {"names": listed}
            if listed
            else "Bu turdagi reklamada o'xshash auditoriya ishlatilmaydi. Auditoriya bo'limidan olib tashlang."
        )


class AudienceWaiting(DomainError):
    def __init__(self, names: tuple[str, ...] = ()) -> None:
        listed = ", ".join(name for name in names if name)
        super().__init__(
            "Bu auditoriyalar hozircha tayyor emas: %(names)s. Auditoriya bo'limida sababi yozilgan."
            % {"names": listed}
            if listed
            else "Tanlangan auditoriya hozircha tayyor emas."
        )


class ConversionSourceMissing(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Bu maqsad uchun sayt pixeli kerak. Uni ulanishlar sahifasida tanlang."
        )


class CampaignTypeNotOffered(DomainError):
    def __init__(self) -> None:
        super().__init__("Bu maqsad uchun bunday kampaniya turini tanlab bo'lmaydi.")


class CampaignTypeLocked(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Reklama yaratilgan, kampaniya turini endi o'zgartirib bo'lmaydi. Boshqa tur kerak bo'lsa, yangi reklama yarating."
        )


class ConversionEventNotOffered(DomainError):
    def __init__(self) -> None:
        super().__init__("Bunday natija hodisasini tanlab bo'lmaydi.")


class PixelNotOffered(DomainError):
    def __init__(self) -> None:
        super().__init__("Bu pikselni tanlab bo'lmaydi.")


class DeliveryOptionUnusable(DomainError):
    def __init__(self) -> None:
        super().__init__("Bu sozlamani shu reklamaga qo'llab bo'lmaydi.")


class DeliveryOptionLocked(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Reklama yaratilgan, bu sozlamalarni endi o'zgartirib bo'lmaydi."
        )


class SpendLimitsUnusable(DomainError):
    REASONS: ClassVar[dict[str, Any]] = {
        "cap_below_daily": "Jami sarf chegarasi kunlik byudjetdan kichik — reklama boshlangan kuni to'xtaydi."
    }

    def __init__(self, *, reason: str) -> None:
        super().__init__(
            self.REASONS.get(reason, "Sarf chegaralari bir-biriga to'g'ri kelmadi.")
        )


class SpendLimitsLocked(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Reklama yaratilgan. Sarf chegaralarini reklama sahifasidan o'zgartirasiz."
        )


class EndDateUnusable(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Tugash kuni boshlanish kunidan kamida bir kun keyin bo'lishi kerak."
        )


class EndDateLocked(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Reklama yaratilgan. Tugash kunini reklama sahifasidan o'zgartirasiz."
        )


class ButtonNotOffered(DomainError):
    def __init__(self) -> None:
        super().__init__("Bu reklamaga bunday tugma qo'yib bo'lmaydi.")


class ButtonLocked(DomainError):
    def __init__(self) -> None:
        super().__init__("Reklama yaratilgan, tugmani endi o'zgartirib bo'lmaydi.")


class UrlTagsUnusable(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Manzil parametrlari noto'g'ri. «nom=qiymat» juftliklarini «&» bilan yozing, boshida «?» bo'lmasin."
        )


class UrlTagsLocked(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Reklama yaratilgan, manzil parametrlarini endi o'zgartirib bo'lmaydi."
        )


class PixelLocked(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Reklama yaratilgan, pikselni endi o'zgartirib bo'lmaydi. Boshqa piksel kerak bo'lsa, yangi reklama yarating."
        )


class ConversionEventLocked(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Reklama yaratilgan, natija hodisasini endi o'zgartirib bo'lmaydi. Boshqa hodisa kerak bo'lsa, yangi reklama yarating."
        )


class CostCapTooLow(DomainError):
    def __init__(self, *, needed: str = "") -> None:
        super().__init__(
            "Bitta natija narxi kunlik byudjetga nisbatan juda yuqori. Kunlik byudjetni kamida %(needed)s ga oshiring yoki chegarani pasaytiring."
            % {"needed": needed}
            if needed
            else "Bitta natija narxi kunlik byudjetga nisbatan juda yuqori. Kunlik byudjetni oshiring yoki chegarani pasaytiring."
        )


class CostCapNotOffered(DomainError):
    def __init__(self) -> None:
        super().__init__("Bu maqsadda bitta natija narxiga chegara qo'yilmaydi.")


class DestinationLinkMissing(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Bu maqsad odamlarni saytingizga olib boradi. Sayt manzilini kiriting."
        )


class CallNumberMissing(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Bu maqsad qo'ng'iroq keltiradi. Qaysi raqamga qo'ng'iroq qilishlarini kiriting."
        )


class DestinationLinkUnusable(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Sayt manzili Facebook yoki Instagram sahifasi bo'lishi mumkin emas. O'z saytingiz manzilini kiriting."
        )


class PermissionsMissing(DomainError):
    def __init__(self, missing: tuple[str, ...] = ()) -> None:
        self.missing = missing
        super().__init__(
            "Meta bergan ruxsatlar yetarli emas. Akkauntni qayta ulang va so'ralgan ruxsatlarni bekor qilmang."
        )


class AdAccountUnavailable(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Reklama akkauntingiz Meta'da faol emas. Ads Manager'da holatini tekshiring."
        )


class AdAccountPaymentDue(AdAccountUnavailable):
    def __init__(self) -> None:
        DomainError.__init__(
            self,
            "Reklama akkauntingizda to'lanmagan qarz bor. Meta'ning to'lov sahifasida kartani tekshiring va qarzni to'lang.",
        )


class PageRoleMissing(DomainError):
    def __init__(self, tasks: tuple[str, ...] = ()) -> None:
        self.tasks = tasks
        super().__init__(
            "Bu Facebook sahifasida reklama yaratish huquqingiz yo'q. Sahifa egasidan admin huquqini so'rang."
        )


class PageTermsNotAccepted(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Facebook sahifangiz lid yig'ish shartlarini hali qabul qilmagan. Sahifa egasi Meta'da bir marta rozilik berishi kerak."
        )


class ChatChannelUnavailable(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Instagram akkaunti Facebook sahifangizga ulanmagan. Uni ulang yoki suhbatni Messenger'ga o'zgartiring."
        )


class InstagramProfileUnavailable(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Bu reklama odamni Instagram profilingizga olib boradi, lekin Instagram akkaunti Facebook sahifangizga ulanmagan. Uni ulang yoki boshqa maqsad tanlang."
        )


class BudgetBelowMinimum(DomainError):
    def __init__(
        self, *, minimum_minor: int, currency: str, places: int | None = None
    ) -> None:
        super().__init__(
            "Kuniga eng kamida %(least)s bo'lishi kerak."
            % {
                "least": format_minor(
                    amount_minor=minimum_minor, currency=currency, places=places
                )
            }
        )


class GroupBudgetBelowMinimum(DomainError):
    def __init__(
        self, *, minimum_minor: int, currency: str, places: int | None = None
    ) -> None:
        super().__init__(
            "Kuniga eng kamida %(least)s kerak. Byudjetni oshiring yoki reklamalar sonini kamaytiring."
            % {
                "least": format_minor(
                    amount_minor=minimum_minor, currency=currency, places=places
                )
            }
        )


class NotLaunchable(DomainError):
    def __init__(self) -> None:
        super().__init__("Reklamani yoqib bo'lmadi. Taklifni tekshirib chiqing.")


class LaunchMediaMissing(DomainError):
    def __init__(self) -> None:
        super().__init__("Reklama uchun rasm yoki video tanlang.")


class CopyMissing(DomainError):
    def __init__(self) -> None:
        super().__init__("Reklamalardan birida asosiy matn yo'q. Matnni yozing.")


class LaunchMediaUnsupported(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Sahifa posti bilan forma ishlamaydi. Rasm yoki video tanlang."
        )


class LaunchMediaOffPage(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Bu post boshqa profilga tegishli. Reklama yuritilayotgan sahifaning postini tanlang yoki sahifani almashtiring."
        )


class LaunchMediaBlocked(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Bu Instagram postini reklama qilib bo'lmaydi - odatda musiqasi tufayli. Boshqa rasm yoki video tanlang."
        )


class MediaAskedRecently(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Ro'yxat hozirgina so'raldi. Bir daqiqadan keyin urinib ko'ring."
        )


class VideoNotReady(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Video hali tayyorlanmoqda. Bir necha daqiqadan keyin urinib ko'ring."
        )


class LaunchMediaTooLarge(DomainError):
    def __init__(self, *, file_name: str) -> None:
        self.file_name = file_name
        super().__init__(
            "«%(name)s» fayli Meta bir martada qabul qiladigan hajmdan katta. Uni kichikroq yoki qisqaroq faylga almashtiring."
            % {"name": file_name}
        )


class LaunchMediaForeign(DomainError):
    def __init__(self, *, file_name: str) -> None:
        self.file_name = file_name
        super().__init__(
            "«%(name)s» rasmi bu reklama akkauntiga tegishli emas - Meta uni reklamada ko'rsatmaydi. Boshqa rasm tanlang."
            % {"name": file_name}
        )


class AudienceEmpty(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Bu sozlamalar bilan reklamani hech kim ko'rmaydi. Xaritadagi joyni tekshiring yoki masofani kengaytiring."
        )


class LaunchUnchanged(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Reklamada hech narsa o'zgarmagan - Meta uni yana xuddi shunday rad etadi. Avval xatoda aytilgan joyni o'zgartiring."
        )


class LaunchNotDiscardable(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Bu reklama allaqachon yaratilgan — avval uni to'xtatish kerak."
        )


class NothingToCleanUp(DomainError):
    def __init__(self) -> None:
        super().__init__("Meta tomonida o'chiriladigan narsa qolmagan.")


class UnknownTarget(DomainError):
    def __init__(self) -> None:
        super().__init__("Bu reklama topilmadi. Ro'yxatni yangilang.")


class AccountNotConnected(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Bu reklama obunangizga ulanmagan akkauntdan yuritilyapti. Uni faqat ko'rsatamiz - o'zgartirish uchun o'sha akkauntni «Ulanishlar» bo'limida yoqing."
        )


class ChangeInFlight(DomainError):
    def __init__(self) -> None:
        super().__init__("Oldingi o'zgarish hali bajarilmoqda. Biroz kuting.")


class AlreadyInState(DomainError):
    def __init__(self) -> None:
        super().__init__("Bu allaqachon shu holatda. Sahifani yangilang.")


class CampaignFinished(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Bu reklama tugagan. Uni qayta yoqib bo'lmaydi — yangisini yarating."
        )


class LearningInProgress(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Bu guruh hali o'rganmoqda. Byudjetni hozir o'zgartirish natijani yomonlashtiradi — bir-ikki kundan keyin urinib ko'ring."
        )


class GroupStillLearning(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Bu guruh hali o'rganmoqda. Reklamani hozir o'chirish natijani yomonlashtirishi mumkin — bir-ikki kundan keyin urinib ko'ring."
        )


class LastAdInGroup(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Bu guruhda ishlayotgan boshqa reklama qolmagan. Uni o'chirsangiz guruh butunlay to'xtaydi — buni guruhning o'zidan to'xtatgan ma'qul."
        )


class ChangeRefused(DomainError):
    def __init__(self) -> None:
        super().__init__("Bu o'zgarishni amalga oshirib bo'lmadi.")


class ForeignAudience(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Bu kampaniya Meta'da yaratilgan - uning auditoriyasini shu yerdan o'zgartirib bo'lmaydi. To'xtatish va byudjet esa ishlaydi."
        )


class CreativeNotEditable(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Bu reklamaning matni postning o'zida turibdi. Uni shu yerdan o'zgartirib bo'lmaydi."
        )


class NothingChanged(DomainError):
    def __init__(self) -> None:
        super().__init__("Hech narsa o'zgarmadi.")


class NothingToRevert(DomainError):
    def __init__(self) -> None:
        super().__init__("Bu o'zgarishni qaytarib bo'lmaydi.")


class PreviewUnavailable(DomainError):
    def __init__(self) -> None:
        super().__init__("Reklama ko'rinishini hozir olib bo'lmadi.")


class NothingToStart(DomainError):
    def __init__(self) -> None:
        super().__init__("Bu reklama allaqachon ishlayapti.")


class UnknownLeadForm(DomainError):
    def __init__(self) -> None:
        super().__init__("Bu forma endi mavjud emas. Ro'yxatni yangilang.")


class GoalReadingsExhausted(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Juda ko'p urinish. Birozdan keyin qayta urinib ko'ring yoki ro'yxatdan tanlang."
        )


class ChatQuestionsExhausted(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Juda ko'p urinish. Hozircha tayyor savollarni o'zingiz tahrirlang."
        )


class UnknownGoal(DomainError):
    def __init__(self) -> None:
        super().__init__("Bu maqsad endi yo'q. Ro'yxatdan tanlang.")


class UploadInterrupted(Exception):
    pass


class StillNotReady(Exception):
    pass


class ProposalLocked(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Reklama yaratilgan. Taklifni endi bu yerda o'zgartirib bo'lmaydi."
        )


class CampaignNameTooLong(DomainError):
    def __init__(self, *, limit: int) -> None:
        super().__init__(
            "Kampaniya nomi %(limit)s belgidan oshmasin." % {"limit": limit}
        )


class GoogleWebsiteRequired(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Google qidiruv reklamasi uchun sayt kerak. Sayt manzilini yozing (https:// bilan)."
        )


class GooglePhoneRequired(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "Qo'ng'iroq uchun telefon raqamini xalqaro shaklda yozing (masalan +998901234567). Raqam saytingizda ham bo'lishi kerak."
        )


class GooglePlacesTooMany(DomainError):
    def __init__(self, *, limit: int) -> None:
        super().__init__("Ko'pi bilan %(limit)s ta hudud tanlang." % {"limit": limit})


class GoogleGoalUnknown(DomainError):
    def __init__(self) -> None:
        super().__init__("Maqsadni tanlang.")


class GoogleLaunchClosed(DomainError):
    def __init__(self) -> None:
        super().__init__("Bu reklama allaqachon yaratilmoqda yoki yaratilgan.")


class GoogleBudgetRequired(DomainError):
    def __init__(self) -> None:
        super().__init__("Kunlik byudjetni yozing.")


class GoogleWordsInvalid(DomainError):
    def __init__(self, message: str) -> None:
        super().__init__(message)


class GoogleLaunchNotReady(DomainError):
    def __init__(self) -> None:
        super().__init__("Reklama hali tayyor emas. Bir oz kuting.")


class FormVariantNotReady(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "AI hali savollarni yozyapti. Bir necha soniyadan keyin saqlang."
        )
