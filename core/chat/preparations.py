"""Why a campaign this product was preparing stopped, in one English line."""

from typing import Final

TROUBLE_WORDS: Final[dict[str, str]] = {
    "reconnect": "the Meta connection expired - it has to be connected again",
    "no_provider": "no ad account was chosen for this preparation",
    "permissions": "the Meta profile is missing a permission this needs",
    "page_role": "the owner is not an administrator of the Facebook page",
    "page_terms": "the page has not accepted Meta's lead terms yet",
    "account_disabled": "Meta has disabled the ad account",
    "account_action": "the ad account needs something done in Ads Manager first",
    "payment_due": "the ad account has an unpaid bill Meta could not charge",
    "payment_missing": "the ad account has no payment method",
    "media_missing": "no picture or video was chosen",
    "media_unsupported": "the picture or video is a kind Meta will not take",
    "media_too_large": "the picture or video is larger than Meta accepts",
    "media_foreign": "the picture belongs to another page",
    "video_not_ready": "the video was still being processed by Meta",
    "chat_channel": "no chat channel was set for a campaign that asks for messages",
    "phone_missing": "no telephone number was set for a campaign that asks for calls",
    "site_missing": "no website address was given",
    "site_unusable": "the website address cannot be advertised to",
    "site_unreachable": "the website did not answer when it was checked",
    "instagram_profile": "the page has no Instagram profile to send people to",
    "budget_low": "the daily budget is below what Meta allows for this goal",
    "bid_refused": (
        "Meta takes no cost cap for this goal; the cap is no longer sent and "
        "a retry goes out with automatic bidding"
    ),
    "location_invalid": "Meta did not recognise one of the places chosen",
    "location_overlap": (
        "two of the places chosen cover the same ground, such as a city and "
        "the region it lies in"
    ),
    "interest_retired": "Meta has retired one of the interests chosen",
    "form_privacy_missing": "the lead form chosen links to no privacy policy",
    "profile_incomplete": "the business profile is not filled in yet",
    "rate_limited": "Meta was refusing calls at the time - worth trying again",
    "temporary": "Meta did not answer at the time - worth trying again",
    "stalled": "it stopped part way through and nothing finished it",
    "refused": "Meta refused it and gave a reason",
    "not_launchable": "this campaign cannot be switched on as it stands",
    "subscription_expired": "the subscription had run out when it ran",
}

UNKNOWN_TROUBLE: Final = "it stopped and the reason was not recorded"


def trouble_of(code: str, *, provider_said: str = "") -> str:
    """One preparation's failure as a line, and what the provider added."""
    words = TROUBLE_WORDS.get(code, UNKNOWN_TROUBLE) if code else UNKNOWN_TROUBLE
    said = " ".join(str(provider_said).split())
    return f"{words} (Meta said: {said})" if said else words


__all__ = ["TROUBLE_WORDS", "UNKNOWN_TROUBLE", "trouble_of"]
