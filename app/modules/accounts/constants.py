from typing import Final

from app.common.choices import Choices

LOGIN_FAILURES_PER_EMAIL: Final = 10
LOGIN_FAILURES_PER_ADDRESS: Final = 50
LOGIN_WINDOW_SECONDS: Final = 15 * 60
SIGNUPS_PER_ADDRESS: Final = 5
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
PURGE_ORDER: tuple[str, ...] = (
    "businesses.CustomCategory",
    "audit.ErrorEvent",
    "leads.LeadOutcome",
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
    "surveys.SurveyResponse",
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
    "backoffice.StaffAction",
    "audit.ActionLog",
    "audit.Event",
    "audit.LLMCall",
    "montage.Montage",
    "montage.BrandKit",
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
REGISTERED_PIXEL_KEY: Final = "accounts:registered_pixel"
