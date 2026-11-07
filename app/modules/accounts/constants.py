from typing import Final

from app.common.choices import Choices

LOGIN_FAILURES_PER_EMAIL: Final = 10
LOGIN_FAILURES_PER_ADDRESS: Final = 50
LOGIN_WINDOW_SECONDS: Final = 15 * 60
SIGNUPS_PER_ADDRESS: Final = 20
SIGNUP_WINDOW_SECONDS: Final = 60 * 60
PASSWORD_FAILURES_PER_USER: Final = 5
PASSWORD_WINDOW_SECONDS: Final = 15 * 60


class Language(Choices):
    UZ = "uz"
    RU = "ru"
    EN = "en"


LANGUAGE_LABELS = {
    Language.UZ: "O'zbekcha",
    Language.RU: "Ruscha",
    Language.EN: "Inglizcha",
}


class Role(Choices):
    """Who the owner said they are, asked at sign-up (or once, at the next
    sign-in, of an account opened before the question)."""

    BUSINESS_OWNER = "business_owner"
    TARGETOLOG = "targetolog"
    MARKETER = "marketer"
    AGENCY = "agency"
    OTHER = "other"


ROLE_LABELS = {
    Role.BUSINESS_OWNER: "Biznes egasi",
    Role.TARGETOLOG: "Targetolog",
    Role.MARKETER: "Marketolog / SMM",
    Role.AGENCY: "Agentlik",
    Role.OTHER: "Boshqa",
}


class SocialProvider(Choices):
    GOOGLE = "google"


SOCIAL_PROVIDER_LABELS = {SocialProvider.GOOGLE: "Google"}
# The Google round trip: the consent screen, a second account picked, a slow
# phone. The finishing form (phone and role) gets longer.
SOCIAL_STATE_TTL_SECONDS: Final = 15 * 60
SOCIAL_STATE_KEY: Final = "accounts:social:state:{state}"
SOCIAL_PENDING_TTL_SECONDS: Final = 30 * 60
SOCIAL_PENDING_KEY: Final = "accounts:social:pending:{token}"
SOCIAL_TOKEN_BYTES: Final = 32
PURGE_ORDER: tuple[str, ...] = (
    "businesses.CustomCategory",
    "audit.ErrorEvent",
    "leads.LeadOutcome",
    "leads.LeadSignal",
    "destinations.LeadDelivery",
    "destinations.FormSheet",
    "destinations.SheetLink",
    "crm.CrmActivity",
    "crm.CrmCard",
    "crm.CrmSetup",
    "crm.CrmStage",
    "crm.CrmLostReason",
    "crm.CrmMember",
    "leads.Lead",
    "leads.LeadForm",
    "leads.RawLeadEvent",
    "agent.AgentSuggestion",
    "agent.AgentFix",
    "agent.AdSetDiagnosis",
    "agent.FrequencyAlert",
    "agent.AgentRun",
    "agent.AgentPolicy",
    "chat.ChatMessage",
    "chat.ChatSession",
    "supportchat.SupportRelay",
    "supportchat.SupportAttachment",
    "supportchat.SupportMessage",
    "supportchat.SupportConversation",
    "surveys.SurveySighting",
    "surveys.SurveyResponse",
    "broadcasts.BroadcastDelivery",
    "broadcasts.BroadcastSeen",
    "broadcasts.BroadcastTarget",
    "notifications.InboxSeen",
    "notifications.TelegramNotice",
    "notifications.TelegramChat",
    "notifications.StaffChat",
    "sales.SalesActivity",
    "sales.ContactHold",
    "sales.SaleSource",
    "sales.SalesCommission",
    "sales.SalesMonth",
    "sales.SalesClaim",
    "accounts.SocialIdentity",
    "accounts.BlockSuggestion",
    "accounts.AccountBlock",
    "backoffice.StaffAction",
    "audit.ActionLog",
    "audit.Event",
    "audit.LLMCall",
    "montage.Montage",
    "montage.BrandKit",
    "ads.DeliveryStop",
    "ads.Ad",
    "ads.AdPreview",
    "ads.AdCreative",
    "ads.SiteCheck",
    "ads.AdSet",
    "ads.Campaign",
    "ads.LaunchCreative",
    "ads.CampaignLaunch",
    "ads.GoogleLaunch",
    "ads.GoalCampaign",
    "ads.MediaAsset",
    "ads.InterestTerm",
    "ads.LapseHold",
    "metrics.MetricsBreakdown",
    "metrics.MetricsDaily",
    "metrics.PeopleCount",
    "metrics.MetricsCheck",
    "metrics.MetricPreference",
    "referrals.Feedback",
    "referrals.FeedbackPrompt",
    "referrals.WithdrawalRequest",
    "referrals.WalletSpend",
    "referrals.ReferralReward",
    "referrals.ReferralBinding",
    "referrals.ReferralCode",
    "referrals.ReferralAccess",
    "billing.SubscriptionChange",
    "billing.PromoRedemption",
    "billing.PaymentTransaction",
    "billing.Invoice",
    "billing.Subscription",
    "integrations.CustomAudience",
    "integrations.PixelAccount",
    "integrations.PageInstagram",
    "integrations.PagePair",
    "integrations.PageAccount",
    "integrations.AdAccount",
    "integrations.ProviderConnection",
)
PURGE_EXEMPT: frozenset[str] = frozenset({"public.DeletionRequest"})
HANDOFF_TTL_SECONDS: Final = 300
HANDOFF_TOKEN_BYTES: Final = 32
HANDOFF_TOKEN_KEY: Final = "accounts:handoff:{token}"
# The bot's new-password link: one change, within a quarter hour, and dead
# once the password moves by any road.
RESET_TTL_SECONDS: Final = 15 * 60
RESET_TOKEN_BYTES: Final = 32
RESET_TOKEN_KEY: Final = "accounts:reset:{token}"
REGISTERED_PIXEL_KEY: Final = "accounts:registered_pixel"


class BlockCode(Choices):
    """Block reasons the code itself names; the rest are the super admin's."""

    META_IDENTITY_REUSED = "meta_identity_reused"
    GOOGLE_IDENTITY_REUSED = "google_identity_reused"
    OTHER = "other"


class SuggestionOutcome(Choices):
    BLOCKED = "blocked"
    DISMISSED = "dismissed"


# Said at sign-in when the block is not shown, or its reason has no words in
# the reader's language.
BLOCKED_MESSAGE: Final = {
    "uz": "Akkauntingiz bloklangan. Batafsil bilish uchun qo'llab-quvvatlash "
    "xizmatiga murojaat qiling.",
    "ru": "Ваш аккаунт заблокирован. Чтобы узнать подробности, обратитесь в "
    "службу поддержки.",
    "en": "Your account is blocked. Please contact Support to learn more.",
}
BLOCKED_REASON_HEAD: Final = {
    "uz": "Akkauntingiz bloklangan. Sabab:",
    "ru": "Ваш аккаунт заблокирован. Причина:",
    "en": "Your account is blocked. Reason:",
}
OWNER_BLOCKED_MESSAGE: Final = {
    "uz": "Kabinet egasining akkaunti bloklangan, shuning uchun CRM'ga kirib "
    "bo'lmaydi.",
    "ru": "Аккаунт владельца кабинета заблокирован, поэтому вход в CRM невозможен.",
    "en": "The cabinet owner's account is blocked, so the CRM cannot be opened.",
}
