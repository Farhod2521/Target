from app.common.choices import Choices


class ActorType(Choices):
    USER = "user"
    SYSTEM = "system"
    AGENT = "agent"


ACTOR_TYPE_LABELS = {
    ActorType.USER: "Foydalanuvchi",
    ActorType.SYSTEM: "Tizim",
    ActorType.AGENT: "Agent",
}


class ActionType(Choices):
    PAUSE = "pause"
    RESUME = "resume"
    BUDGET_UP = "budget_up"
    BUDGET_DOWN = "budget_down"
    TARGETING_SWAP = "targeting_swap"
    END_TIME_SET = "end_time_set"
    SPEND_CAP_SET = "spend_cap_set"
    CREATIVE_SWAP = "creative_swap"
    CREATE_ADSET = "create_adset"
    CREATE_CAMPAIGN = "create_campaign"
    DELETE_CAMPAIGN = "delete_campaign"
    DELETE_AD = "delete_ad"
    DELETE_ADSET = "delete_adset"
    CREATE_AUDIENCE = "create_audience"
    FILL_AUDIENCE = "fill_audience"
    DELETE_AUDIENCE = "delete_audience"
    FORGET_MEMBERS = "forget_members"
    ANONYMIZE_LEADS = "anonymize_leads"
    RELINK_PAGE = "relink_page"
    RECOVER_LEADS = "recover_leads"
    MEDIA_UPLOAD = "media_upload"
    MEDIA_DELETE = "media_delete"
    SHEET_CONNECT = "sheet_connect"
    SHEET_DISCONNECT = "sheet_disconnect"
    SHEET_RECREATE = "sheet_recreate"
    SHEET_PICK = "sheet_pick"
    SUPPORT_OPEN = "support_open"
    SUPPORT_REPLY = "support_reply"
    SUPPORT_SETTLE = "support_settle"
    SUPPORT_EDIT = "support_edit"
    SUPPORT_DELETE = "support_delete"
    MONTAGE_REQUEST = "montage_request"
    MONTAGE_BRAND = "montage_brand"
    MONTAGE_DELETE = "montage_delete"
    SALES_ADOPT = "sales_adopt"
    CRM_CHANGE = "crm_change"


ACTION_TYPE_LABELS = {
    ActionType.PAUSE: "To'xtatish",
    ActionType.RESUME: "Davom ettirish",
    ActionType.BUDGET_UP: "Byudjetni oshirish",
    ActionType.BUDGET_DOWN: "Byudjetni kamaytirish",
    ActionType.TARGETING_SWAP: "Auditoriyani almashtirish",
    ActionType.END_TIME_SET: "Tugash sanasini belgilash",
    ActionType.SPEND_CAP_SET: "Umumiy chegarani belgilash",
    ActionType.CREATIVE_SWAP: "Reklama mazmunini almashtirish",
    ActionType.CREATE_ADSET: "Yangi guruh yaratish",
    ActionType.CREATE_CAMPAIGN: "Kampaniya yaratish",
    ActionType.DELETE_CAMPAIGN: "Kampaniyani o'chirish",
    ActionType.DELETE_AD: "Reklamani o'chirish",
    ActionType.DELETE_ADSET: "Guruhni o'chirish",
    ActionType.CREATE_AUDIENCE: "Auditoriya yaratish",
    ActionType.FILL_AUDIENCE: "Auditoriyani to'ldirish",
    ActionType.DELETE_AUDIENCE: "Auditoriyani o'chirish",
    ActionType.FORGET_MEMBERS: "Auditoriyadan chiqarish",
    ActionType.ANONYMIZE_LEADS: "Lid ma'lumotini o'chirish",
    ActionType.RELINK_PAGE: "Sahifani qayta ulash",
    ActionType.RECOVER_LEADS: "Yig'ilmagan mijozlarni tiklash",
    ActionType.MEDIA_UPLOAD: "Kutubxonaga yuklash",
    ActionType.MEDIA_DELETE: "Kutubxonadan o'chirish",
    ActionType.SHEET_CONNECT: "Google jadvalni ulash",
    ActionType.SHEET_DISCONNECT: "Google jadvalni uzish",
    ActionType.SHEET_RECREATE: "Yangi Google jadval",
    ActionType.SHEET_PICK: "O'z Google jadvalini tanlash",
    ActionType.SUPPORT_OPEN: "Yordam suhbati ochildi",
    ActionType.SUPPORT_REPLY: "Yordam suhbatiga javob",
    ActionType.SUPPORT_SETTLE: "Yordam: javob shart emas",
    ActionType.SUPPORT_EDIT: "Yordam xabari tahrirlandi",
    ActionType.SUPPORT_DELETE: "Yordam xabari o'chirildi",
    ActionType.MONTAGE_REQUEST: "Video montaj so'raldi",
    ActionType.MONTAGE_BRAND: "Montaj brendi saqlandi",
    ActionType.MONTAGE_DELETE: "Video montaj o'chirildi",
    ActionType.SALES_ADOPT: "Ariza kartalari hisobga o'tdi",
    ActionType.CRM_CHANGE: "CRM o'zgarishi",
}


class ActionStatus(Choices):
    PENDING = "pending"
    APPLIED = "applied"
    FAILED = "failed"
    REVERTED = "reverted"


ACTION_STATUS_LABELS = {
    ActionStatus.PENDING: "Navbatda",
    ActionStatus.APPLIED: "Qo'llandi",
    ActionStatus.FAILED: "Xato",
    ActionStatus.REVERTED: "Qaytarildi",
}


class EventStatus(Choices):
    PENDING = "pending"
    PUBLISHED = "published"
    FAILED = "failed"


EVENT_STATUS_LABELS = {
    EventStatus.PENDING: "Navbatda",
    EventStatus.PUBLISHED: "Yuborildi",
    EventStatus.FAILED: "Xato",
}


class EventName(Choices):
    USER_REGISTERED = "user.registered"
    USER_PROFILE_UPDATED = "user.profile_updated"
    USER_PASSWORD_CHANGED = "user.password_changed"
    SUBSCRIPTION_TRIAL_STARTED = "subscription.trial_started"
    INVOICE_CREATED = "invoice.created"
    INVOICE_PRICED = "invoice.priced"
    PAYMENT_RECEIVED = "payment.received"
    PAYMENT_REFUNDED = "payment.refunded"
    SUBSCRIPTION_ACTIVATED = "subscription.activated"
    PAGES_ADDED = "subscription.pages_added"
    SUBSCRIPTION_SHORTENED = "subscription.shortened"
    SUBSCRIPTION_EXTENDED = "subscription.extended"
    SUBSCRIPTION_PLAN_CHANGED = "subscription.plan_changed"
    SUBSCRIPTION_SLOTS_CHANGED = "subscription.slots_changed"
    SETUP_COMPLETED = "setup.completed"
    PROMO_REDEEMED = "promo.redeemed"
    PROMO_RELEASED = "promo.released"
    PROMO_REQUESTED = "promo.requested"
    PROMO_REJECTED = "promo.rejected"
    REFERRAL_REWARDED = "referral.rewarded"
    REFERRAL_CODE_ISSUED = "referral.code_issued"
    REFERRAL_BOUND = "referral.bound"
    REFERRAL_ACCESS_CHANGED = "referral.access_changed"
    WALLET_APPLIED = "wallet.applied"
    WITHDRAWAL_REQUESTED = "withdrawal.requested"
    WITHDRAWAL_REJECTED = "withdrawal.rejected"
    WITHDRAWAL_PAID = "withdrawal.paid"
    WITHDRAWAL_VOIDED = "withdrawal.voided"
    FEEDBACK_SUBMITTED = "feedback.submitted"
    FEEDBACK_APPROVED = "feedback.approved"
    FEEDBACK_REJECTED = "feedback.rejected"
    FEEDBACK_PROMPT_ANSWERED = "feedback_prompt.answered"
    SURVEY_ANSWERED = "survey.answered"
    SALES_CLAIMED = "sales.claimed"
    SALES_CARD_MOVED = "sales.card_moved"
    SALES_CARD_CLOSED = "sales.card_closed"
    SALES_CREDITED = "sales.credited"
    SALES_HOLD_LIFTED = "sales.hold_lifted"
    SALES_SETTINGS_CHANGED = "sales.settings_changed"
    SALES_MONTH_CLOSED = "sales.month_closed"
    SALES_ARIZAS_ADOPTED = "sales.arizas_adopted"
    BUSINESS_CREATED = "business.created"
    CONNECTION_ADDED = "connection.added"
    CONNECTION_REMOVED = "connection.removed"
    CONNECTION_REFUSED_DUPLICATE = "connection.refused_duplicate"
    USER_BLOCKED = "user.blocked"
    ACCOUNT_REBOUND = "account.rebound"
    PAGE_REBOUND = "page.rebound"
    PAGE_RELEASED = "page.released"
    PAGE_ENABLED = "page.enabled"
    INSTAGRAM_ENABLED = "instagram.enabled"
    INSTAGRAM_DISABLED = "instagram.disabled"
    PAGE_CLAIMED = "page.claimed"
    PAGE_HANDED_OVER = "page.handed_over"
    PAGE_PAYER_CHOSEN = "page.payer_chosen"
    PAGE_PAIR_ADDED = "page.pair_added"
    PAGE_PAIR_CHANGED = "page.pair_changed"
    PAGE_PAIR_REMOVED = "page.pair_removed"
    GOOGLE_ACCOUNT_ENABLED = "google_account.enabled"
    GOOGLE_ACCOUNT_RELEASED = "google_account.released"
    LEAD_CREATED = "lead.created"
    SHEET_CONNECTED = "sheet.connected"
    SHEET_DISCONNECTED = "sheet.disconnected"
    SHEET_RECREATED = "sheet.recreated"
    SHEET_PICKED = "sheet.picked"
    CAMPAIGN_CREATED = "campaign.created"
    CRM_SETUP_SAVED = "crm.setup_saved"
    CRM_ENABLED = "crm.enabled"
    CRM_DISABLED = "crm.disabled"
    CRM_MEMBER_SAVED = "crm.member_saved"
    CRM_MEMBER_REMOVED = "crm.member_removed"
    CRM_CARD_PLACED = "crm.card_placed"
    CRM_CARD_CHANGED = "crm.card_changed"
    CRM_CARD_WON = "crm.card_won"
    CRM_CARD_LOST = "crm.card_lost"
    CAMPAIGN_ACTIVATED = "campaign.activated"
    CAMPAIGN_PAUSED = "campaign.paused"
    CAMPAIGN_DELETED = "campaign.deleted"
    ADS_LAPSE_HELD = "ads.lapse_held"
    ADS_LAPSE_RESUMED = "ads.lapse_resumed"
    ADS_LAPSE_REMOVED = "ads.lapse_removed"
    AD_DELETED = "ad.deleted"
    ADSET_DELETED = "adset.deleted"
    BUDGET_CHANGED = "budget.changed"
    LAUNCH_ROLLED_BACK = "launch.rolled_back"
    LAUNCH_DISCARDED = "launch.discarded"
    LAUNCH_CLEANUP_REQUESTED = "launch.cleanup_requested"
    LAUNCH_COPY_EDITED = "launch.copy_edited"
    LAUNCH_RENAMED = "launch.renamed"
    LAUNCH_BUDGET_FITTED = "launch.budget_fitted"
    LAUNCH_ADS_TRIMMED = "launch.ads_trimmed"
    TARGETING_CHANGED = "targeting.changed"
    CREATIVE_CHANGED = "creative.changed"
    AUDIENCE_CREATED = "audience.created"
    AUDIENCE_FILLED = "audience.filled"
    AUDIENCE_DELETED = "audience.deleted"
    AUDIENCE_MEMBERS_REMOVED = "audience.members_removed"
    LEADS_ANONYMIZED = "leads.anonymized"
    AGENT_FIX_APPLIED = "agent.fix_applied"
    FREQUENCY_ALERTED = "agent.frequency_alerted"
    FREQUENCY_ANSWERED = "agent.frequency_answered"
    MEDIA_UPLOADED = "media.uploaded"
    MEDIA_DELETED = "media.deleted"
    DELIVERY_STOPPED = "delivery.stopped"
    SUPPORT_CONVERSATION_OPENED = "support.conversation_opened"
    SUPPORT_MESSAGE_POSTED = "support.message_posted"
    SUPPORT_CONVERSATION_SETTLED = "support.conversation_settled"
    SUPPORT_MESSAGE_EDITED = "support.message_edited"
    SUPPORT_MESSAGE_DELETED = "support.message_deleted"
    MONTAGE_REQUESTED = "montage.requested"
    MONTAGE_FINISHED = "montage.finished"
    MONTAGE_FAILED = "montage.failed"
    MONTAGE_BRAND_SAVED = "montage.brand_saved"
    MONTAGE_DELETED = "montage.deleted"


EVENT_NAME_LABELS = {
    EventName.USER_REGISTERED: "Akkaunt ochildi",
    EventName.USER_PROFILE_UPDATED: "Shaxsiy ma'lumot yangilandi",
    EventName.USER_PASSWORD_CHANGED: "Parol o'zgartirildi",
    EventName.SUBSCRIPTION_TRIAL_STARTED: "Sinov muddati boshlandi",
    EventName.INVOICE_CREATED: "Hisob chiqarildi",
    EventName.INVOICE_PRICED: "Hisob summasi hisoblandi",
    EventName.PAYMENT_RECEIVED: "To'lov qabul qilindi",
    EventName.PAYMENT_REFUNDED: "To'lov qaytarildi",
    EventName.SUBSCRIPTION_ACTIVATED: "Obuna faollashtirildi",
    EventName.PAGES_ADDED: "Qo'shimcha sahifa qo'shildi",
    EventName.SUBSCRIPTION_SHORTENED: "Obuna muddati qisqardi",
    EventName.SUBSCRIPTION_EXTENDED: "Muddat qo'lda uzaytirildi",
    EventName.SUBSCRIPTION_PLAN_CHANGED: "Tarif almashtirildi",
    EventName.SUBSCRIPTION_SLOTS_CHANGED: "Qo'shimcha o'rinlar o'zgardi",
    EventName.SETUP_COMPLETED: "Sozlash yakunlandi",
    EventName.PROMO_REDEEMED: "Promo kod ishlatildi",
    EventName.PROMO_RELEASED: "Chegirma hisobdan olindi",
    EventName.PROMO_REQUESTED: "Promo so'rovi yuborildi",
    EventName.PROMO_REJECTED: "Promo so'rovi rad etildi",
    EventName.REFERRAL_REWARDED: "Referal mukofot hisoblandi",
    EventName.REFERRAL_CODE_ISSUED: "Taklif havolasi berildi",
    EventName.REFERRAL_BOUND: "Taklif orqali ro'yxatdan o'tildi",
    EventName.REFERRAL_ACCESS_CHANGED: "Referal ruxsati o'zgartirildi",
    EventName.WALLET_APPLIED: "Hamyon obunaga ishlatildi",
    EventName.WITHDRAWAL_REQUESTED: "Pul yechish so'raldi",
    EventName.WITHDRAWAL_REJECTED: "Pul yechish rad etildi",
    EventName.WITHDRAWAL_PAID: "Hamyon'dan to'lov",
    EventName.WITHDRAWAL_VOIDED: "To'lov yozuvi bekor qilindi",
    EventName.FEEDBACK_SUBMITTED: "Fikr yuborildi",
    EventName.FEEDBACK_APPROVED: "Fikr tasdiqlandi",
    EventName.FEEDBACK_REJECTED: "Fikr rad etildi",
    EventName.FEEDBACK_PROMPT_ANSWERED: "Fikr eslatmasiga javob",
    EventName.SURVEY_ANSWERED: "So'rovnomaga javob berildi",
    EventName.SALES_CLAIMED: "Mijoz sotuvga olindi",
    EventName.SALES_CARD_MOVED: "Sotuv kartasi ko'chdi",
    EventName.SALES_CARD_CLOSED: "Sotuv kartasi yopildi",
    EventName.SALES_CREDITED: "To'lov sotuvga yozildi",
    EventName.SALES_HOLD_LIFTED: "Qo'ng'iroq taqiqi olindi",
    EventName.SALES_SETTINGS_CHANGED: "Sotuv sozlamalari o'zgardi",
    EventName.SALES_MONTH_CLOSED: "Sotuv oyi yopildi",
    EventName.SALES_ARIZAS_ADOPTED: "Ariza kartalari hisobga o'tdi",
    EventName.BUSINESS_CREATED: "Biznes profili to'ldirildi",
    EventName.CONNECTION_ADDED: "Reklama akkaunti ulandi",
    EventName.CONNECTION_REMOVED: "Reklama akkaunti uzildi",
    EventName.CONNECTION_REFUSED_DUPLICATE: "Ulanish rad etildi: akkaunt band",
    EventName.USER_BLOCKED: "Akkaunt bloklandi",
    EventName.ACCOUNT_REBOUND: "Reklama akkaunti almashtirildi",
    EventName.PAGE_REBOUND: "Sahifa almashtirildi",
    EventName.PAGE_RELEASED: "Sahifa uzildi",
    EventName.PAGE_ENABLED: "Sahifa qo'shildi",
    EventName.INSTAGRAM_ENABLED: "Instagram qo'shildi",
    EventName.INSTAGRAM_DISABLED: "Instagram olib tashlandi",
    EventName.PAGE_CLAIMED: "Sahifa boshqa kabinetdan olindi",
    EventName.PAGE_HANDED_OVER: "Sahifa boshqa kabinetga o'tdi",
    EventName.PAGE_PAYER_CHOSEN: "Sahifaning to'lov akkaunti tanlandi",
    EventName.PAGE_PAIR_ADDED: "Sahifaga reklama akkaunti qo'shildi",
    EventName.PAGE_PAIR_CHANGED: "Sahifa juftligidagi reklama akkaunti almashtirildi",
    EventName.PAGE_PAIR_REMOVED: "Sahifa juftligi o'chirildi",
    EventName.GOOGLE_ACCOUNT_ENABLED: "Google Ads akkaunti qo'shildi",
    EventName.GOOGLE_ACCOUNT_RELEASED: "Google Ads akkaunti uzildi",
    EventName.LEAD_CREATED: "Lid keldi",
    EventName.SHEET_CONNECTED: "Google jadval ulandi",
    EventName.SHEET_DISCONNECTED: "Google jadval uzildi",
    EventName.SHEET_RECREATED: "Yangi Google jadval yaratildi",
    EventName.SHEET_PICKED: "O'z Google jadvali tanlandi",
    EventName.CAMPAIGN_CREATED: "Kampaniya yaratildi",
    EventName.CRM_SETUP_SAVED: "CRM sozlamasi saqlandi",
    EventName.CRM_ENABLED: "CRM yoqildi",
    EventName.CRM_DISABLED: "CRM o'chirildi",
    EventName.CRM_MEMBER_SAVED: "CRM menejeri saqlandi",
    EventName.CRM_MEMBER_REMOVED: "CRM menejeri o'chirildi",
    EventName.CRM_CARD_PLACED: "Lid CRM doskasiga tushdi",
    EventName.CRM_CARD_CHANGED: "CRM kartasi o'zgardi",
    EventName.CRM_CARD_WON: "CRM kartasi sotildi",
    EventName.CRM_CARD_LOST: "CRM kartasi rad etildi",
    EventName.CAMPAIGN_ACTIVATED: "Kampaniya yoqildi",
    EventName.CAMPAIGN_PAUSED: "Kampaniya to'xtatildi",
    EventName.CAMPAIGN_DELETED: "Kampaniya o'chirildi",
    EventName.ADS_LAPSE_HELD: "Obuna tugadi: reklamalar to'xtatildi",
    EventName.ADS_LAPSE_RESUMED: "To'lovdan keyin reklamalar yoqildi",
    EventName.ADS_LAPSE_REMOVED: "To'lanmagani uchun reklamalar o'chirildi",
    EventName.AD_DELETED: "Reklama o'chirildi",
    EventName.ADSET_DELETED: "Guruh o'chirildi",
    EventName.BUDGET_CHANGED: "Byudjet o'zgartirildi",
    EventName.LAUNCH_ROLLED_BACK: "Yaratilgan narsalar o'chirildi",
    EventName.LAUNCH_DISCARDED: "Tayyorlash o'chirildi",
    EventName.LAUNCH_CLEANUP_REQUESTED: "Meta'dagi qoldiqni o'chirish so'raldi",
    EventName.LAUNCH_COPY_EDITED: "Reklama matni tahrirlandi",
    EventName.LAUNCH_RENAMED: "Kampaniya nomi o'zgartirildi",
    EventName.LAUNCH_BUDGET_FITTED: "Byudjet reklamalar soniga moslandi",
    EventName.LAUNCH_ADS_TRIMMED: "Ortiqcha reklamalar olib tashlandi",
    EventName.TARGETING_CHANGED: "Auditoriya o'zgartirildi",
    EventName.CREATIVE_CHANGED: "Reklama mazmuni o'zgartirildi",
    EventName.AUDIENCE_CREATED: "Auditoriya yaratildi",
    EventName.AUDIENCE_FILLED: "Auditoriyaga odam yuklandi",
    EventName.AUDIENCE_DELETED: "Auditoriya o'chirildi",
    EventName.AUDIENCE_MEMBERS_REMOVED: "Auditoriyadan odam chiqarildi",
    EventName.LEADS_ANONYMIZED: "Lid ma'lumoti o'chirildi",
    EventName.AGENT_FIX_APPLIED: "Agent o'zi tuzatdi",
    EventName.FREQUENCY_ALERTED: "Chastota ogohlantirishi",
    EventName.FREQUENCY_ANSWERED: "Chastotaga javob",
    EventName.MEDIA_UPLOADED: "Fayl kutubxonaga yuklandi",
    EventName.MEDIA_DELETED: "Fayl kutubxonadan o'chirildi",
    EventName.DELIVERY_STOPPED: "Reklama to'xtadi",
    EventName.SUPPORT_CONVERSATION_OPENED: "Yordam suhbati ochildi",
    EventName.SUPPORT_MESSAGE_POSTED: "Yordam xabari yuborildi",
    EventName.SUPPORT_CONVERSATION_SETTLED: "Yordam suhbati: javob shart emas",
    EventName.SUPPORT_MESSAGE_EDITED: "Yordam xabari tahrirlandi",
    EventName.SUPPORT_MESSAGE_DELETED: "Yordam xabari o'chirildi",
    EventName.MONTAGE_REQUESTED: "Video montaj so'raldi",
    EventName.MONTAGE_FINISHED: "Video montaj tayyor",
    EventName.MONTAGE_FAILED: "Video montaj bo'lmadi",
    EventName.MONTAGE_BRAND_SAVED: "Montaj brendi saqlandi",
    EventName.MONTAGE_DELETED: "Video montaj o'chirildi",
}


class LLMPurpose(Choices):
    ONBOARDING = "onboarding"
    DECISION = "decision"
    EXPLAIN = "explain"
    FORM_BUILD = "form_build"
    CHAT = "chat"
    REPORT = "report"
    DAILY_REPORT = "daily_report"
    REFUSAL = "refusal"
    MONTAGE = "montage"
    BRAND_LOGO = "brand_logo"
    SURVEY = "survey"


LLM_PURPOSE_LABELS = {
    LLMPurpose.ONBOARDING: "Tanishuv",
    LLMPurpose.DECISION: "Qaror",
    LLMPurpose.EXPLAIN: "Izoh",
    LLMPurpose.FORM_BUILD: "Forma yig'ish",
    LLMPurpose.CHAT: "Suhbat",
    LLMPurpose.REPORT: "Haftalik hisobot",
    LLMPurpose.DAILY_REPORT: "Kunlik hisobot",
    LLMPurpose.REFUSAL: "Rad etish izohi",
    LLMPurpose.MONTAGE: "Video montaj",
    LLMPurpose.BRAND_LOGO: "Logo tahlili",
    LLMPurpose.SURVEY: "So'rovnoma tarjimasi",
}


class LLMCallStatus(Choices):
    OK = "ok"
    SCHEMA_ERROR = "schema_error"
    RATE_LIMITED = "rate_limited"
    FAILED = "failed"


LLM_CALL_STATUS_LABELS = {
    LLMCallStatus.OK: "Muvaffaqiyatli",
    LLMCallStatus.SCHEMA_ERROR: "Javob sxemaga mos emas",
    LLMCallStatus.RATE_LIMITED: "Limit oshdi",
    LLMCallStatus.FAILED: "Xato",
}
UNRESOLVED_AFTER_MINUTES = 60
UNRESOLVED_REPORT_HOURS = 24
UNRESOLVED_REPORT_ACTIONS = 10
ERROR_RETENTION_DAYS = 30
ERROR_REFERENCE_ALPHABET = "ABCDEFGHJKLMNPQRTUVWXYZ2346789"
ERROR_REFERENCE_LENGTH = 6
ERROR_TRACE_CHARS = 8000
ERROR_REFERENCE_HEADER = "X-Error-Reference"
