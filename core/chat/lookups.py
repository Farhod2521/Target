"""What the assistant may look up about an account while it answers."""

from typing import Final

from llmkit import Tool

from core.chat.lookup_arguments import (
    DEFAULT_DAYS,
    MAX_DAYS,
    AdLookup,
    AdSetLookup,
    CampaignList,
    CampaignLookup,
    DailyFigures,
    FormList,
    LeadCounts,
    Nothing,
    Proposals,
    Search,
    Window,
)

MAX_LOOKUPS: Final = 8
MAX_ROUNDS: Final = 5

OUTPUT_CHARS: Final = 8_000

FOUND_ROWS: Final = 20
CAMPAIGN_ROWS: Final = 40
ADSET_ROWS: Final = 15
AD_ROWS: Final = 25
FORM_ROWS: Final = 30
CHANGE_ROWS: Final = 30
PROPOSAL_ROWS: Final = 15
PROBLEM_ROWS: Final = 15
GROUP_ROWS: Final = 40
PREPARATION_ROWS: Final = 12
SLICE_ROWS: Final = 25


def _tool(name: str, arguments: type, *lines: str) -> Tool:
    return Tool(name=name, description=" ".join(lines), arguments=arguments)


TOOLS: Final[tuple[Tool, ...]] = (
    _tool(
        "account_overview",
        Nothing,
        "Every ad account and Facebook page in the owner's subscription:",
        "which is current, whether a page is connected for leads, its",
        "Instagram account, how many lead forms it has, plus the plan and",
        "days left. Use for questions about pages, ad accounts, Instagram or",
        "the subscription, and to learn an id.",
    ),
    _tool(
        "find",
        Search,
        "Find ad accounts, pages, campaigns, ad groups, adverts and lead forms",
        "by name or id. Use when the person names something or pastes a long",
        "number.",
    ),
    _tool(
        "list_campaigns",
        CampaignList,
        "Campaigns across the subscription's ad accounts, biggest spender",
        "first: status, what it is optimised for, daily budget, spend, results",
        "and cost per result over the window.",
    ),
    _tool(
        "campaign_details",
        CampaignLookup,
        "One campaign in depth: its ad groups (who they are shown to, budget,",
        "learning, the product's diagnosis, the provider's issues, their ids)",
        "and its adverts, each with figures over the window.",
    ),
    _tool(
        "audience_details",
        AdSetLookup,
        "One ad group's targeting spelled out by name - places, ages, genders,",
        "interests, saved audiences, placements, whether the provider may widen",
        "it - and how its money and the provider's leads split by age and",
        "gender, region and placement, each slice marked with the product's",
        "verdict. Use for any question about targeting or who the adverts reach.",
    ),
    _tool(
        "ad_details",
        AdLookup,
        "One advert: its headline, words, button, link or lead form, the",
        "provider's ratings, review problems and figures.",
    ),
    _tool(
        "daily_figures",
        DailyFigures,
        "Day by day spend, impressions, link clicks, provider results and",
        "leads received, for one campaign, ad group or advert.",
    ),
    _tool(
        "lead_counts",
        LeadCounts,
        "How many leads arrived, grouped by day, campaign, ad group, form or",
        "page. Counts only: names, phone numbers and answers are never",
        "available.",
    ),
    _tool(
        "lead_forms",
        FormList,
        "Lead forms of the subscription's pages: questions, status, how many",
        "leads each collected and when the last one arrived.",
    ),
    _tool(
        "recent_changes",
        Window,
        "Changes made to campaigns over the window - stops, budget and",
        "audience changes - by whom (the owner, the agent, the product) and",
        "whether they went through.",
    ),
    _tool(
        "agent_proposals",
        Proposals,
        "The agent's proposals: what, about which object, the cause, the",
        "status and what happened after an approved one.",
    ),
    _tool(
        "open_problems",
        Nothing,
        "What the cabinet's list of things waiting holds right now: broken",
        "connections, spend with no result, leads not arriving, rejected",
        "adverts, unfinished setup.",
    ),
    _tool(
        "preparations",
        Window,
        "Campaigns this product was preparing over the window: what stage",
        "each reached, whether it was switched on, and - for one that",
        "stopped - why, in words. Use it for 'why was my campaign not",
        "created', 'what happened to the one I started' and any question",
        "about an advert that never appeared.",
    ),
    _tool(
        "audiences",
        Nothing,
        "Saved audiences - customer lists, lookalikes, retargeting - with",
        "their size and whether they are ready to use.",
    ),
)


def clipped(text: str, *, limit: int = OUTPUT_CHARS) -> str:
    """The result, cut at a line when it is longer than a result may be."""
    if len(text) <= limit:
        return text
    kept = text[:limit].rsplit("\n", 1)[0]
    return f"{kept}\n(cut here: the rest was too long - ask a narrower question)"


__all__ = [
    "ADSET_ROWS",
    "AD_ROWS",
    "CAMPAIGN_ROWS",
    "CHANGE_ROWS",
    "DEFAULT_DAYS",
    "FORM_ROWS",
    "FOUND_ROWS",
    "GROUP_ROWS",
    "MAX_DAYS",
    "MAX_LOOKUPS",
    "MAX_ROUNDS",
    "OUTPUT_CHARS",
    "PREPARATION_ROWS",
    "PROBLEM_ROWS",
    "PROPOSAL_ROWS",
    "SLICE_ROWS",
    "TOOLS",
    "AdLookup",
    "AdSetLookup",
    "CampaignList",
    "CampaignLookup",
    "DailyFigures",
    "FormList",
    "LeadCounts",
    "Nothing",
    "Proposals",
    "Search",
    "Window",
    "clipped",
]
