"""What the assistant may look up about an account while it answers.

The context that travels with a question is chosen by
:func:`core.chat.route.route` and bounded by construction: ten campaigns, six
groups, the current ad account only. That keeps a greeting cheap, and it
leaves every question outside those bounds answered with "look at the
Reklama screen" - a second page, an older campaign, an id somebody pasted.
The look-ups are the other half: the model asks for what the question
needs, and only that is read.

**Read-only, every one.** Nothing here changes an account; a change is
still a proposal somebody presses. And nothing here returns a customer's
name, phone number, email or answers - counts only, for the rule the
prompt already states and the review checklist enforces.

**Declared here, answered in Django.** This file is the catalogue - names
and what each is for; the arguments are in :mod:`core.chat.lookup_arguments`
- and it has no database. :mod:`apps.chat.selectors.lookups` reads the
tables, always scoped to the owner the answer belongs to; the model never
names an owner and cannot reach another account's rows by any argument it
sends.

Descriptions are English for the reason the prompt is: they are read by the
model, not by a person.
"""

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

# How many look-ups one answer may make, and how many requests it may take.
# Eight is well past what a real question needs - "which page is this
# campaign on and how did it do" is two - and it bounds the bill of a model
# that goes looking for everything. Five rounds leaves room for a look-up
# that leads to another, and the last one is forced to answer.
MAX_LOOKUPS: Final = 8
MAX_ROUNDS: Final = 5

# How much of one result the model is handed. A result longer than this is
# cut with a line saying so, which tells the model to narrow the question
# rather than letting one look-up cost more than the rest of the answer.
OUTPUT_CHARS: Final = 8_000

# Row ceilings, per look-up.
FOUND_ROWS: Final = 20
CAMPAIGN_ROWS: Final = 40
ADSET_ROWS: Final = 15
AD_ROWS: Final = 25
FORM_ROWS: Final = 30
CHANGE_ROWS: Final = 30
PROPOSAL_ROWS: Final = 15
PROBLEM_ROWS: Final = 15
GROUP_ROWS: Final = 40
# Preparations, newest first. A fortnight of an active cabinet is a
# handful; the tail is old drafts nobody finished.
PREPARATION_ROWS: Final = 12
# Per cut of an audience. Age and gender is about twenty cells; a country's
# regions can be more, and the tail past this spent too little to matter.
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
