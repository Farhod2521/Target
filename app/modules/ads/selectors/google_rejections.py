"""Why Google will not run an advert, in the shape every refusal is drawn in.

Google names its policy by a stable code (``DESTINATION_NOT_WORKING``,
``PUNCTUATION``), so the cause is read from that code and never asked of
the AI: the answers kept for Meta's reviews speak of Meta's rules.
"""

from typing import Any, Final

from app.common.contract import Refusal, RefusalFix
from app.modules.ads.selectors.failures import feedback_text

TITLE: Final = "Google reklamani rad etdi"
NOT_RUNNING: Final = "Google reklamani ishga tushirmayapti"
POLICY_MANAGER: Final = "https://ads.google.com/aw/policymanager"
OPEN_LABEL: Final = "Google Ads'da ochish"
APPEAL: Final = (
    "Xato deb hisoblasangiz, Google Ads'ning «Policy manager» bo'limida "
    "qayta ko'rib chiqishni so'rang."
)
# A policy code's part that tells which part of the advert is at fault.
SITE_MARKS: Final = ("DESTINATION", "LANDING", "URL", "MALWARE")
WORD_MARKS: Final = (
    "PUNCTUATION",
    "CAPITALIZATION",
    "SPELLING",
    "GRAMMAR",
    "REPETITION",
    "SYMBOL",
    "SPACING",
    "GIMMICK",
    "EDITORIAL",
    "TRADEMARK",
    "PHONE",
)
GUIDES: Final[dict[str, tuple[str, tuple[str, ...]]]] = {
    "site": (
        "Sabab — reklama olib boradigan sayt.",
        (
            "Sayt ochilishini va xato bermasligini tekshiring.",
            "Reklamadagi manzil to'g'ri ekanini tekshiring.",
            "Tuzatgach, Google reklamani qayta tekshiradi.",
        ),
    ),
    "words": (
        "Sabab — reklama matni (sarlavha yoki tavsif).",
        (
            "Pastda Google ko'rsatgan qoida va matnni o'qing.",
            "Shu sarlavha yoki tavsifni Google Ads'da tuzating.",
            APPEAL,
        ),
    ),
    "unknown": (
        "Google bu reklamani o'z qoidalariga zid deb topdi.",
        (
            "Pastda Google ko'rsatgan qoidani o'qing.",
            "Shu qismni Google Ads'da tuzating.",
            APPEAL,
        ),
    ),
}
SILENT_STEPS: Final = (
    "Google Ads'da reklamani oching va «Policy manager» bo'limida sababini o'qing.",
    "Shu qismni tuzating.",
    APPEAL,
)


def cause_of(policies: list[str]) -> str:
    """The part at fault, read from the first policy that names one."""
    for policy in policies:
        if any(mark in policy for mark in SITE_MARKS):
            return "site"
        if any(mark in policy for mark in WORD_MARKS):
            return "words"
    return "unknown"


def google_rejection(ad: Any) -> dict[str, Any]:
    """The refusal of one Google advert. No key: no written answer is asked."""
    feedback = ad.review_feedback if isinstance(ad.review_feedback, dict) else {}
    overall = feedback.get("overall") if isinstance(feedback, dict) else None
    policies = [str(name) for name in (overall or {})]
    said = feedback_text(feedback)
    fix = RefusalFix(label=OPEN_LABEL, url=POLICY_MANAGER)
    if not said:
        return Refusal(
            title=NOT_RUNNING,
            cause="Google bu reklamani ishga tushirmayapti, lekin sababini bizga yozmadi.",
            steps=list(SILENT_STEPS),
            fix=fix,
        ).model_dump(by_alias=True)
    sentence, steps = GUIDES[cause_of(policies)]
    return Refusal(
        title=TITLE,
        cause=sentence,
        steps=list(steps),
        provider_words=said,
        fix=fix,
    ).model_dump(by_alias=True)


__all__ = ["cause_of", "google_rejection"]
