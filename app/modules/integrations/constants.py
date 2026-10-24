from typing import Final

from app.common.choices import Choices


class ConnectionKind(Choices):
    USER_OAUTH = "user_oauth"
    SYSTEM_USER = "system_user"


CONNECTION_KIND_LABELS = {
    ConnectionKind.USER_OAUTH: "Foydalanuvchi ruxsati",
    ConnectionKind.SYSTEM_USER: "Tizim foydalanuvchisi",
}


class ConnectionStatus(Choices):
    ACTIVE = "active"
    EXPIRED = "expired"
    REVOKED = "revoked"
    INVALID = "invalid"


CONNECTION_STATUS_LABELS = {
    ConnectionStatus.ACTIVE: "Ulangan",
    ConnectionStatus.EXPIRED: "Muddati tugagan",
    ConnectionStatus.REVOKED: "Bekor qilingan",
    ConnectionStatus.INVALID: "Yaroqsiz",
}
USABLE_CONNECTION_STATUSES = (ConnectionStatus.ACTIVE,)
REFRESH_WINDOW_DAYS = 7
REFRESH_COOLDOWN_SECONDS = 15
MIN_AUDIENCE_MEMBERS = 100
USEFUL_AUDIENCE_MEMBERS = 1000
AUDIENCE_STALE_MINUTES = 30


class SourceKind(Choices):
    PIXEL = "pixel"
    PAGE = "page"
    LEAD_FORM = "lead_form"


SOURCE_KIND_LABELS = {
    SourceKind.PIXEL: "Sayt",
    SourceKind.PAGE: "Facebook sahifasi",
    SourceKind.LEAD_FORM: "Lid formasi",
}


class SourceAction(Choices):
    VISITED = "visited"
    VIEWED_ITEM = "viewed_item"
    ADDED_TO_CART = "added_to_cart"
    PURCHASED = "purchased"
    ENGAGED = "engaged"
    MESSAGED = "messaged"
    OPENED = "opened"
    SUBMITTED = "submitted"
    ABANDONED = "abandoned"
    VISITED_NOT_PURCHASED = "visited_not_purchased"
    ADDED_TO_CART_NOT_PURCHASED = "added_to_cart_not_purchased"
    ENGAGED_NOT_MESSAGED = "engaged_not_messaged"


SOURCE_ACTION_LABELS = {
    SourceAction.VISITED: "Kirganlar",
    SourceAction.VIEWED_ITEM: "Mahsulotni ko'rganlar",
    SourceAction.ADDED_TO_CART: "Savatga qo'shganlar",
    SourceAction.PURCHASED: "Xarid qilganlar",
    SourceAction.ENGAGED: "Aloqaga kirganlar",
    SourceAction.MESSAGED: "Xabar yozganlar",
    SourceAction.OPENED: "Formani ochganlar",
    SourceAction.SUBMITTED: "Formani topshirganlar",
    SourceAction.ABANDONED: "Formani tashlab ketganlar",
    SourceAction.VISITED_NOT_PURCHASED: "Kirgan, xarid qilmagan",
    SourceAction.ADDED_TO_CART_NOT_PURCHASED: "Savatga qo'shgan, xarid qilmagan",
    SourceAction.ENGAGED_NOT_MESSAGED: "Aloqaga kirgan, yozmagan",
}


class Breadth(Choices):
    CLOSEST = "closest"
    BALANCED = "balanced"
    BROAD = "broad"


BREADTH_LABELS = {
    Breadth.CLOSEST: "Eng o'xshash - kichik auditoriya",
    Breadth.BALANCED: "O'rtacha",
    Breadth.BROAD: "Keng - kamroq o'xshash",
}
BREADTH_NOTES = {
    Breadth.CLOSEST: "Mijozlaringizga eng o'xshash odamlar. Auditoriya kichik bo'ladi, lekin natija odatda yaxshiroq. Shundan boshlang.",
    Breadth.BALANCED: "O'xshashlik va hajm o'rtasida. Eng o'xshashi tugab qolganda keyingi qadam.",
    Breadth.BROAD: "Ko'proq odam, lekin o'xshashligi kamroq. Kichik auditoriyalar natija bermay qolganda ishlatiladi.",
}
ACTION_NOTES = {
    SourceAction.VISITED_NOT_PURCHASED: "Bu tanlov saytingiz Meta'ga «xarid» hodisasini yuborishiga bog'liq. Yuborilmasa hech kim chiqarilmaydi va auditoriya oddiy «kirganlar» bilan bir xil bo'ladi.",
    SourceAction.ADDED_TO_CART_NOT_PURCHASED: "Bu tanlov saytingiz Meta'ga «savatga qo'shish» va «xarid» hodisalarini yuborishiga bog'liq. Yuborilmasa auditoriya bo'sh yoki noto'g'ri bo'ladi.",
    SourceAction.ENGAGED_NOT_MESSAGED: "Xabar yozganlar chiqarib tashlanadi, shuning uchun bu auditoriya «aloqaga kirganlar» dan kichik bo'ladi.",
}
MIRROR_STALE_MINUTES: Final = 90
MIRROR_NIGHTLY_STALE_MINUTES: Final = 26 * 60
STALE_SAMPLE: Final = 10
MAX_IDENTITY_REFUSALS: Final = 2
BUSINESS_LOOKUP_SECONDS: Final = 600
NIGHT_LEADS_HOUR: Final = 0
NIGHT_FIGURES_HOUR: Final = 1
NIGHT_DIAGNOSIS_HOUR: Final = 3
NIGHT_AGENT_HOUR: Final = 4
