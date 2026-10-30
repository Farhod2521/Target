"""What a failed press on a switch or a bin says, and what a refusal was about."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final

from metaads.accounts import billing_url, manager_url

from app.modules.ads.selectors.actions import account_of
from app.modules.audit.constants import ActionStatus, ActionType
from app.modules.audit.models import ActionLog
from core.agent.refusal_cause import RefusalCause, refusal_cause

DELETE_FAILURE_SHOWN = timedelta(hours=1)
DELETES: frozenset[str] = frozenset(
    {ActionType.DELETE_CAMPAIGN, ActionType.DELETE_ADSET, ActionType.DELETE_AD}
)
RECONNECT = "reconnect"
BILLING = "billing"
ADS_MANAGER = "ads_manager"
_RECONNECT_SAID = "Meta ulanishi uzilgan yoki muddati tugagan. Meta'ni qayta ulang, keyin yana bosing."
SENTENCES: Final[dict[str, tuple[str, str]]] = {
    "reconnect": (_RECONNECT_SAID, RECONNECT),
    "connection": (_RECONNECT_SAID, RECONNECT),
    "permission": (
        "Ulangan Facebook profilida bu reklama akkauntini boshqarish huquqi yo'q. "
        "Business Manager'da profilga akkaunt ustidan to'liq huquq bering yoki "
        "Meta'ni qayta ulang.",
        RECONNECT,
    ),
    "account_blocked": (
        "Meta bu reklama akkauntiga hozir hech qanday o'zgarish kiritishga ruxsat "
        "bermayapti — akkaunt holatida muammo bor, ko'pincha to'lanmagan qarz yoki "
        "karta. Qarzni to'lang yoki kartani yangilang; akkaunt tiklangach, yana bosing.",
        BILLING,
    ),
    "account_action": (
        "Meta Facebook profilingizni tasdiqlashni kutmoqda. Ads Manager'ga kirib "
        "tasdiqlang, keyin yana bosing.",
        ADS_MANAGER,
    ),
    "payment_missing": (
        "Reklama akkauntida ishlaydigan to'lov kartasi yo'q. Kartani tekshiring yoki "
        "yangisini qo'shing, keyin yana bosing.",
        BILLING,
    ),
    "temporary": (
        "Meta hozir javob bermayapti. Bir-ikki daqiqadan keyin yana bosing.",
        "",
    ),
    "read": (
        "Meta'dan reklama holatini o'qib bo'lmadi. Bir daqiqadan keyin yana bosing.",
        "",
    ),
    "not_found": (
        "Bu reklama Meta'da topilmadi — u Ads Manager'da o'chirilgan bo'lishi mumkin. "
        "Sahifani yangilang.",
        ADS_MANAGER,
    ),
    "gone": ("Bu reklama endi ro'yxatda yo'q. Sahifani yangilang.", ""),
    "changed_elsewhere": (
        "Bu guruhning auditoriyasi platformadan tashqarida — Ads Manager'da yoki "
        "Meta tomonidan — o'zgartirilgan, shuning uchun hech narsa yuborilmadi. "
        "Yangi holati yuklandi: tahrirni qayta ochib, ko'rib chiqing va yana saqlang.",
        "",
    ),
    "learning": (
        "Guruh hali o'rganmoqda — hozir reklamani to'xtatish o'rganishni noldan "
        "boshlaydi. O'rganish tugagach to'xtating yoki butun guruhni to'xtating.",
        "",
    ),
    "last_ad": (
        "Guruhda boshqa ishlayotgan reklama yo'q. Uning o'rniga butun guruhni to'xtating.",
        "",
    ),
    "already": ("Bu allaqachon shu holatda. Sahifani yangilang.", ""),
    "finished": ("Kampaniya muddati tugagan — uni qayta yoqib bo'lmaydi.", ""),
    "not_applied": (
        "Meta so'rovni qabul qilmadi va hech narsa o'zgarmadi. Holatini Ads "
        "Manager'da tekshiring.",
        ADS_MANAGER,
    ),
}
FALLBACK: Final = (
    "Meta bu o'zgarishni rad etdi. Sababi pastda; tuzatib bo'lmasa, Ads Manager'da "
    "tekshiring.",
    ADS_MANAGER,
)
CAUSE_LINES: Final[dict[RefusalCause, str]] = {
    "words": "Sabab — reklama matni. Matnni Meta qoidasiga moslab o'zgartiring.",
    "picture": (
        "Sabab — rasm yoki video. Boshqasini qo'ying: matnni o'zgartirish yordam bermaydi."
    ),
    "site": (
        "Sabab — reklama olib boradigan sayt. Sayt ochilishini va reklamadagi va'da "
        "saytda ham borligini tekshiring."
    ),
    "offer": (
        "Sabab — mahsulot yoki xizmatning o'zi Meta qoidalarida cheklangan. Matn yoki "
        "rasmni o'zgartirish yordam bermaydi. Xato deb hisoblasangiz, Meta'dan qayta "
        "ko'rib chiqishni so'rang."
    ),
    "account": (
        "Sabab — reklama akkaunti yoki sahifa. Meta'ning «Account Quality» sahifasida "
        "holatini tekshiring."
    ),
    "unknown": (
        "Meta aniq qismini ko'rsatmagan. «AI dan so'rash» — AI Meta'ning so'zlarini "
        "tahlil qilib, sababini aytib beradi."
    ),
}


@dataclass(frozen=True, slots=True)
class FailureNote:
    sentence: str
    fix: str = ""
    fix_label: str = ""
    fix_url: str = ""
    provider_words: str = ""


def failure_note(*, action: ActionLog, target: Any, level: str) -> FailureNote:
    """The sentence and the button for one failed audit row."""
    sentence, fix = SENTENCES.get(action.error_code, FALLBACK)
    account = account_of(target=target, level=level).external_id
    links = {
        RECONNECT: ("Meta'ni qayta ulash", ""),
        BILLING: ("To'lov sahifasini ochish", billing_url(account)),
        ADS_MANAGER: ("Ads Manager'ni ochish", manager_url(account)),
    }
    label, url = links.get(fix, ("", ""))
    said = action.result_payload or {}
    words = " ".join(
        part
        for part in (str(said.get("user_title", "")), str(said.get("user_message", "")))
        if part
    )
    return FailureNote(
        sentence=sentence, fix=fix, fix_label=label, fix_url=url, provider_words=words
    )


def recent_delete_failure(
    *, action: ActionLog | None, target: Any, level: str, now: datetime
) -> FailureNote | None:
    """A bin pressed on this row lately that did not delete anything."""
    if (
        action is None
        or action.action not in DELETES
        or action.status != ActionStatus.FAILED
        or action.updated_at < now - DELETE_FAILURE_SHOWN
    ):
        return None
    return failure_note(action=action, target=target, level=level)


def feedback_text(feedback: Any) -> str:
    """The provider's policy names and sentences, every placement included."""
    if not isinstance(feedback, dict):
        return ""
    parts: list[str] = []
    for key, value in feedback.items():
        if not isinstance(value, dict):
            continue
        if key == "by_placement":
            for policies in value.values():
                if isinstance(policies, dict):
                    parts += [f"{name}: {why}" for name, why in policies.items()]
        else:
            parts += [f"{name}: {why}" for name, why in value.items()]
    return "\n".join(parts)


def cause_line(text: str) -> str:
    return CAUSE_LINES[refusal_cause(text)]
