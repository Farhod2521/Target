"""What each kind of result is called in the reports handed to the model."""

from typing import Final

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
