"""What each kind of result is called in the reports handed to the model."""

from typing import Final

# **English, like the prompts**, and for the reason the prompts are: these
# are instructions to a model rather than text for a person, and a label
# that changed with the reader's language would make two accounts' calls
# incomparable. The Uzbek the *reader* sees is carried on the figures
# themselves - see :attr:`core.chat.report.WeekFigures.result_label`.
#
# ``none`` is the account whose money went where this product cannot count
# a result. It has no count to hand over, so the reports
# never reaches this entry for it - it is written down anyway, because a
# lookup that has to be guarded at every call site is one somebody
# eventually calls unguarded.
RESULT_EN: Final[dict[str, tuple[str, str]]] = {
    "lead": ("Leads", "Cost per lead"),
    "chat": ("Conversations started", "Cost per conversation"),
    "call": ("Confirmed calls", "Cost per call"),
    "view": ("Times the ad was shown", "Cost per thousand times shown"),
    "click": ("Visits to the advertiser's own site", "Cost per visit"),
    "recall": ("People estimated to remember the ad", "Cost per one of them"),
    "profile": ("Visits to the Instagram profile", "Cost per visit"),
    "site_lead": (
        "Leads on the advertiser's website, as the provider counts them",
        "Cost per lead",
    ),
    "none": ("Results", "Cost per result"),
}


__all__ = ["RESULT_EN"]
