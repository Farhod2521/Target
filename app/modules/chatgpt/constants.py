from typing import Final

# The screen's periods, in days ending today in the account's timezone.
PERIODS: Final[dict[str, int]] = {"today": 1, "7": 7, "30": 30}
DEFAULT_PERIOD: Final = "7"

API_KEY_MAX: Final = 512
PLACE_QUERY_MAX: Final = 100
PLACES_SHOWN: Final = 20
# What an owner may upload as the card's picture. OpenAI asks for at least
# 640×640; the size is OpenAI's to refuse, the weight is ours.
IMAGE_TYPES: Final = frozenset({"image/jpeg", "image/png", "image/webp"})
IMAGE_MAX_BYTES: Final = 8 * 1024 * 1024
CAMPAIGN_NAME_MAX: Final = 200

REVIEW_LABELS: Final[dict[str, str]] = {
    "approved": "Tasdiqlangan",
    "in_review": "Tekshiruvda",
    "rejected": "Rad etilgan",
}

# OpenAI's serving issues the owner can act on, in their words. Codes not
# listed are shown as OpenAI wrote them.
ISSUE_LABELS: Final[dict[str, str]] = {
    "ad_account_suspended": "Akkaunt OpenAI tomonidan to'xtatilgan.",
    "ad_account_brand_review_missing_favicon": "Ads Manager'da brend logotipini (favicon) yuklang.",
    "ad_account_brand_review_in_progress": "Brend OpenAI tekshiruvida.",
    "ad_account_brand_review_escalated_review": "Brend qo'shimcha tekshiruvda.",
    "ad_account_brand_review_rejected": "Brend tekshiruvdan o'tmadi.",
    "ad_account_payment_method_missing_or_unauthorized": "Ads Manager'da to'lov usulini qo'shing.",
    "ad_account_threshold_payment_failed": "To'lov o'tmadi - kartani tekshiring.",
    "ad_account_persona_verification_not_approved": "Shaxsni tasdiqlash o'tmadi.",
    "ad_account_persona_verification_step_up_required": "Ads Manager'da shaxsingizni tasdiqlang.",
    "campaign_not_active": "Kampaniya o'chirilgan.",
    "campaign_not_started": "Kampaniya hali boshlanmagan.",
    "campaign_ended": "Kampaniya muddati tugagan.",
    "campaign_has_no_ad_groups": "Kampaniyada reklama guruhi yo'q.",
    "campaign_has_no_serving_ready_ad_groups": "Ko'rsatishga tayyor reklama guruhi yo'q.",
    "ad_group_not_active": "Reklama guruhi o'chirilgan.",
    "ad_group_has_no_ads": "Guruhda reklama yo'q.",
    "campaign_budget_exhausted": "Kampaniya byudjeti tugadi.",
    "ad_account_budget_exhausted": "Akkaunt byudjeti tugadi.",
    "review_not_approved": "Reklama tekshiruvdan o'tmadi.",
    "landing_page_crawl_issue": "OpenAI saytni ocha olmadi - havolani tekshiring.",
    "ad_in_review": "Reklama OpenAI tekshiruvida.",
    "ad_not_active": "Reklama o'chirilgan.",
    "target_url_invalid": "Havola noto'g'ri.",
    "image_or_favicon_missing": "Rasm yoki logotip yo'q.",
    "policy_country_targeting_blocked": "Bu davlatda reklama qilib bo'lmaydi.",
    "policy_country_targeting_limited": "Bu davlatda reklama cheklangan.",
}

# The AI's chat card, and why: it is read by people asking ChatGPT.
PROMPT: Final = "chatgpt_card_draft"
TURN: Final = "Write the ChatGPT advert for the business described above."
DRAFT_RELATED_TYPE: Final = "chatgpt_draft"
DRAFT_TIMEOUT_SECONDS: Final = 90
