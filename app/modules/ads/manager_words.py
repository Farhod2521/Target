"""Meta's own setting names in the words the office reads them in.

The raw value goes out beside the word: staff compare it with Ads Manager, and
a value Meta adds later is still printed rather than lost.
"""

from typing import Final

OBJECTIVE_LABELS: Final[dict[str, str]] = {
    "OUTCOME_LEADS": "Lidlar",
    "OUTCOME_SALES": "Sotuvlar",
    "OUTCOME_TRAFFIC": "Trafik",
    "OUTCOME_ENGAGEMENT": "Faollik",
    "OUTCOME_AWARENESS": "Xabardorlik",
    "OUTCOME_APP_PROMOTION": "Ilova reklamasi",
}
OPTIMIZATION_LABELS: Final[dict[str, str]] = {
    "LEAD_GENERATION": "Lid formalar",
    "QUALITY_LEAD": "Sifatli lidlar",
    "CONVERSATIONS": "Suhbatlar",
    "OFFSITE_CONVERSIONS": "Saytdagi konversiyalar",
    "LINK_CLICKS": "Havola bosishlar",
    "LANDING_PAGE_VIEWS": "Sahifa ochilishlari",
    "REACH": "Qamrov",
    "IMPRESSIONS": "Ko'rsatishlar",
    "AD_RECALL_LIFT": "Eslab qolish",
    "THRUPLAY": "Video ko'rish (ThruPlay)",
    "TWO_SECOND_CONTINUOUS_VIDEO_VIEWS": "2 soniyalik video ko'rish",
    "QUALITY_CALL": "Sifatli qo'ng'iroqlar",
    "VISIT_INSTAGRAM_PROFILE": "Instagram profiliga kirish",
    "PROFILE_VISIT": "Profilga kirish",
    "POST_ENGAGEMENT": "Post faolligi",
    "PAGE_LIKES": "Sahifa obunachilari",
}
BILLING_LABELS: Final[dict[str, str]] = {
    "IMPRESSIONS": "Ko'rsatish uchun",
    "LINK_CLICKS": "Havola bosilishi uchun",
    "THRUPLAY": "Video ko'rilishi uchun",
    "POST_ENGAGEMENT": "Post faolligi uchun",
    "PAGE_LIKES": "Obuna uchun",
}
DESTINATION_LABELS: Final[dict[str, str]] = {
    "ON_AD": "Reklama ichidagi forma",
    "WEBSITE": "Sayt",
    "MESSENGER": "Messenger",
    "INSTAGRAM_DIRECT": "Instagram Direct",
    "WHATSAPP": "WhatsApp",
    "PHONE_CALL": "Qo'ng'iroq",
    "INSTAGRAM_PROFILE": "Instagram profili",
    "ON_POST": "Post ichida",
    "ON_VIDEO": "Video ichida",
    "ON_PAGE": "Facebook sahifasi",
}
BID_LABELS: Final[dict[str, str]] = {
    "LOWEST_COST_WITHOUT_CAP": "Eng past narx, chegarasiz",
    "COST_CAP": "Natija narxi chegarasi",
    "LOWEST_COST_WITH_BID_CAP": "Stavka chegarasi",
}
BUDGET_LEVEL_LABELS: Final[dict[str, str]] = {
    "campaign": "Kampaniya darajasida",
    "adset": "Reklama guruhi darajasida",
}
