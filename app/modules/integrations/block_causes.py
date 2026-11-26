"""Why Meta stopped an ad account, in the owner's words.

Meta answers with two numbers, ``account_status`` and ``disable_reason``
(Ad Account reference, read 2026-11-26). The second is the only place the
cause is said, and a screen that drops it can only say "blocked" - which
sends an owner with a hacked profile to pay a bill, and one with a closed
account to ask for a review nobody will open.

A reason Meta names and does not explain is shown under Meta's own name:
a guess at what it means would be a second wrong answer.
"""

from dataclasses import dataclass
from typing import Any, Final

from metaads.accounts import ACCOUNT_QUALITY_URL, billing_url, manager_url

from app.modules.integrations.selectors.standing import StoppedKind, stopped_kind

# ``disable_reason``, as published.
REASON_NAMES: Final[dict[str, str]] = {
    "1": "ADS_INTEGRITY_POLICY",
    "2": "ADS_IP_REVIEW",
    "3": "RISK_PAYMENT",
    "4": "GRAY_ACCOUNT_SHUT_DOWN",
    "5": "ADS_AFC_REVIEW",
    "6": "BUSINESS_INTEGRITY_RAR",
    "7": "PERMANENT_CLOSE",
    "8": "UNUSED_RESELLER_ACCOUNT",
    "9": "UNUSED_ACCOUNT",
    "10": "UMBRELLA_AD_ACCOUNT",
    "11": "BUSINESS_MANAGER_INTEGRITY_POLICY",
    "12": "MISREPRESENTED_AD_ACCOUNT",
    "13": "AOAB_DESHARE_LEGAL_ENTITY",
    "14": "CTX_THREAD_REVIEW",
    "15": "COMPROMISED_AD_ACCOUNT",
}

REVIEW: Final = (
    "Meta'ning Account Quality sahifasida shu akkaunt yonidagi «Request review» "
    "(qayta ko'rib chiqish) ni bosing. Blokni faqat Meta ocha oladi."
)
ANOTHER: Final = (
    "Bu akkaunt qayta ochilmaydi. Sozlamalarda boshqa reklama akkauntini ulang."
)
PAY: Final = (
    "Meta'ning to'lov sahifasida qarzni to'lang yoki kartani yangilang — to'lov "
    "o'tishi bilan reklamalar o'zi davom etadi."
)

# reason -> (cause, fix, where the fix is: "review" | "billing" | "manager")
_BY_REASON: Final[dict[str, tuple[str, str, str]]] = {
    "ADS_INTEGRITY_POLICY": (
        "Meta akkauntni reklama qoidalari buzilgani uchun o'chirgan.",
        REVIEW,
        "review",
    ),
    "ADS_IP_REVIEW": (
        "Meta akkauntni mualliflik huquqi yoki tovar belgisi bo'yicha tekshiruv "
        "sababli o'chirgan.",
        REVIEW,
        "review",
    ),
    "RISK_PAYMENT": (
        "Meta akkauntni to'lov bilan bog'liq xavf sababli o'chirgan.",
        PAY,
        "billing",
    ),
    "PERMANENT_CLOSE": ("Meta akkauntni butunlay yopgan.", ANOTHER, "manager"),
    "UNUSED_RESELLER_ACCOUNT": (
        "Akkaunt ishlatilmagani uchun Meta uni yopgan.",
        ANOTHER,
        "manager",
    ),
    "UNUSED_ACCOUNT": (
        "Akkaunt uzoq vaqt ishlatilmagani uchun Meta uni o'chirgan.",
        "Ads Manager'da akkauntni oching: Meta qayta yoqishni taklif qilsa, "
        "yoqing. Taklif qilmasa, sozlamalarda boshqa reklama akkauntini ulang.",
        "manager",
    ),
    "BUSINESS_MANAGER_INTEGRITY_POLICY": (
        "Meta akkaunt tegishli bo'lgan biznes portfelni (Business Manager) "
        "qoidalar buzilgani uchun cheklagan, shu sababli akkaunt ham o'chirilgan.",
        "Meta'ning Account Quality sahifasida biznes portfel bo'yicha «Request "
        "review» (qayta ko'rib chiqish) ni bosing. Blokni faqat Meta ocha oladi.",
        "review",
    ),
    "MISREPRESENTED_AD_ACCOUNT": (
        "Meta akkaunt o'zi yoki biznesi haqida noto'g'ri ma'lumot bergan deb "
        "topib, uni o'chirgan.",
        REVIEW,
        "review",
    ),
    "COMPROMISED_AD_ACCOUNT": (
        "Meta akkauntga begona odam kirgan deb gumon qilib, uni xavfsizlik uchun "
        "o'chirgan.",
        "Facebook profilingiz parolini almashtiring va ikki bosqichli himoyani "
        "yoqing, keyin Account Quality sahifasida «Request review» ni bosing.",
        "review",
    ),
}

_TITLES: Final[dict[StoppedKind, str]] = {
    "payment": "«%(account)s» reklama akkauntida to'lov o'tmagan",
    "closed": "«%(account)s» reklama akkaunti yopilgan",
    "disabled": "Meta «%(account)s» reklama akkauntini bloklagan",
}
SHOWN_TO_NOBODY: Final = (
    "Bu akkauntdagi reklamalar yoqilgan bo'lsa ham hozir hech kimga ko'rsatilmayapti."
)


@dataclass(frozen=True, slots=True)
class BlockCause:
    """One stopped account: whose stop it is, why, and the way out."""

    kind: StoppedKind
    reason: str
    """Meta's own name for the cause; empty when it gave none."""
    title: str
    cause: str
    fix: str
    action: str
    href: str

    @property
    def body(self) -> str:
        return f"{self.cause} {SHOWN_TO_NOBODY} {self.fix}"


def block_cause(account: Any) -> BlockCause | None:
    """Why this account delivers nothing, or nothing when it may deliver."""
    from metaads import PROVIDER as META

    kind = stopped_kind(account)
    if kind is None:
        return None
    name = account.name or account.external_id
    if account.provider != META:
        return _elsewhere(account, kind=kind, name=name)
    reason = REASON_NAMES.get(str(account.disable_reason or "").strip(), "")
    cause, fix, where = _words(account, kind=kind, reason=reason)
    action, href = _door(account, where=where)
    return BlockCause(
        kind=kind,
        reason=reason,
        title=_TITLES[kind] % {"account": name},
        cause=cause,
        fix=fix,
        action=action,
        href=href,
    )


_NETWORKS: Final[dict[str, str]] = {"google": "Google Ads", "chatgpt": "ChatGPT Ads"}
_TITLES_ELSEWHERE: Final[dict[StoppedKind, str]] = {
    "payment": "«%(account)s» reklama akkauntida to'lov o'tmagan",
    "closed": "«%(account)s» reklama akkaunti yopilgan",
    "disabled": "«%(account)s» reklama akkaunti reklama bera olmayapti",
}


def _elsewhere(account: Any, *, kind: StoppedKind, name: str) -> BlockCause:
    """Another network's account: it gives no reason this product reads, so
    none is said, and nothing of Meta's is offered as the way out."""
    network = _NETWORKS.get(str(account.provider or ""), "Reklama tarmog'i")
    cause = {
        "payment": f"{network} bu akkauntdagi to'lovni o'tkaza olmagan.",
        "closed": f"Akkaunt {network} tomonida yopilgan.",
        "disabled": f"{network} bu akkauntga reklama berishga ruxsat bermayapti.",
    }[kind]
    return BlockCause(
        kind=kind,
        reason="",
        title=_TITLES_ELSEWHERE[kind] % {"account": name},
        cause=cause,
        fix=f"Buni faqat {network} kabinetining o'zida tuzatish mumkin.",
        action="",
        href="",
    )


def _words(account: Any, *, kind: StoppedKind, reason: str) -> tuple[str, str, str]:
    known = _BY_REASON.get(reason)
    if kind == "payment":
        if known is not None and known[2] == "billing":
            return known
        return (
            "Meta bu akkauntdagi qarzni kartadan yecha olmagan va reklamalarni "
            "to'xtatgan.",
            PAY,
            "billing",
        )
    if kind == "closed":
        closing = str(account.account_status or "") == "100"
        cause = (
            known[0]
            if known is not None
            else "Akkaunt Meta'da yopilish jarayonida."
            if closing
            else "Akkaunt Meta'da yopilgan."
        )
        return cause, ANOTHER, "manager"
    if known is not None:
        return known
    if reason:
        return (
            f"Meta akkauntni o'chirgan va sababini «{reason}» deb ko'rsatgan.",
            REVIEW,
            "review",
        )
    return ("Meta akkauntni o'chirgan, sababini ko'rsatmagan.", REVIEW, "review")


def _door(account: Any, *, where: str) -> tuple[str, str]:
    if where == "billing":
        return "To'lov sahifasini ochish", billing_url(account.external_id)
    if where == "review":
        return "Account Quality'ni ochish", ACCOUNT_QUALITY_URL
    return "Meta'da ochish", manager_url(account.external_id)


__all__ = ["REASON_NAMES", "BlockCause", "block_cause"]
