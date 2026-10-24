"""Why a campaign this product was preparing stopped, in one English line.

**For the model, not for the owner.** Every look-up result is written in
English and the model answers in the owner's own language, the same way
:func:`~apps.chat.selectors.lookups.common.outside` and its neighbours are.
The Uzbek the *screen* shows for these codes lives in the template beside
the fix buttons it draws, which is a different job: a screen has a link to
offer, and this has a sentence to explain.

The two must nevertheless agree about which codes exist, so a test reads
the template's list and fails on anything this does not answer for. That is
the whole guard against the drift two tables usually mean - a code added on
one side and forgotten on the other is a conversation saying "it failed"
about a failure the screen can already name.

**What each line has to carry is who can undo it.** "It failed" is the one
answer nobody can act on. Some of these are a field the owner fills in, some
are a permission only Meta's own screen grants, and some are nothing to do
with them at all - and the model picks a different reply for each.
"""

from typing import Final

# What each stored code means, as a sentence the model can rewrite.
#
# Grouped by who has to do something rather than by where the failure came
# from, because that is what decides the reply. Kept short: the model has
# the campaign's name and status beside this and does not need the
# provider's own wording, which is in ``error_message`` and is for support.
TROUBLE_WORDS: Final[dict[str, str]] = {
    # The connection, which the owner repairs on the connections screen.
    "reconnect": "the Meta connection expired - it has to be connected again",
    "no_provider": "no ad account was chosen for this preparation",
    "permissions": "the Meta profile is missing a permission this needs",
    "page_role": "the owner is not an administrator of the Facebook page",
    "page_terms": "the page has not accepted Meta's lead terms yet",
    # The ad account, which only Meta can put right.
    "account_disabled": "Meta has disabled the ad account",
    "account_action": "the ad account needs something done in Ads Manager first",
    # A card or a bill, which the owner sorts out on Meta's billing page.
    "payment_due": "the ad account has an unpaid bill Meta could not charge",
    "payment_missing": "the ad account has no payment method",
    # Something the preparation itself was missing.
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
    # Nothing wrong with the preparation; it is worth trying again.
    "rate_limited": "Meta was refusing calls at the time - worth trying again",
    "temporary": "Meta did not answer at the time - worth trying again",
    "stalled": "it stopped part way through and nothing finished it",
    # The rest.
    "refused": "Meta refused it and gave a reason",
    "not_launchable": "this campaign cannot be switched on as it stands",
    "subscription_expired": "the subscription had run out when it ran",
}

# What to say for a code nobody wrote a line for. A code reaching this is a
# gap in the table above and the test says so, but a conversation must not
# stop for it.
UNKNOWN_TROUBLE: Final = "it stopped and the reason was not recorded"


def trouble_of(code: str, *, provider_said: str = "") -> str:
    """One preparation's failure as a line, and what the provider added.

    ``provider_said`` is the message the provider wrote **for the
    advertiser** - not the developer string beside it - and it is quoted
    rather than summarised: a refusal Meta explained in its own words is
    the one thing here nobody else can express better.
    """
    words = TROUBLE_WORDS.get(code, UNKNOWN_TROUBLE) if code else UNKNOWN_TROUBLE
    said = " ".join(str(provider_said).split())
    return f"{words} (Meta said: {said})" if said else words


__all__ = ["TROUBLE_WORDS", "UNKNOWN_TROUBLE", "trouble_of"]
