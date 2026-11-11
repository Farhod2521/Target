"""What the one chat's assistant may call while it answers.

The fifteen look-ups of the old chat are used as they are
(``core/chat/lookups.py``). Three are new: a check of the account's own
state, a search of known problems and their steps, and a ticket for a person
in Support - prepared, never sent, until the client presses its button.

How to read a result travels with the result (``READING``), not in the
prompt: the model is told about a look-up's output when it has one in hand,
and the prompt stays short for the questions that never call it.
"""

from typing import Final

from llmkit import Tool
from pydantic import Field

from core.chat.lookup_arguments import Arguments, Nothing
from core.chat.lookups import CHANGE_TOOL
from core.chat.lookups import TOOLS as LOOKUPS

HEALTH_TOOL: Final = "account_health"
HELP_TOOL: Final = "help_search"
TICKET_TOOL: Final = "create_ticket"

MAX_TICKETS: Final = 1


class HelpSearch(Arguments):
    query: str = Field(
        min_length=2,
        max_length=160,
        description=(
            "The problem in a few plain words, in the person's language - "
            "what does not work, or what they are trying to do."
        ),
    )


class TicketDraft(Arguments):
    """A request for a person in Support, for the client to confirm."""

    summary: str = Field(
        min_length=10,
        max_length=600,
        description=(
            "The problem in two or three sentences, in the person's language, "
            "written for the Support specialist who has not seen this "
            "conversation: what is wrong, since when, what the person wants."
        ),
    )
    checked: list[str] = Field(
        default_factory=list,
        max_length=8,
        description=(
            "What you already checked and what each showed, one short line "
            "each - 'Tarif: faol, 12 kun qoldi', 'Facebook ulanishi: uzilgan'. "
            "Only what a look-up actually returned."
        ),
    )


def _tool(name: str, arguments: type, *lines: str) -> Tool:
    return Tool(name=name, description=" ".join(lines), arguments=arguments)


NEW_TOOLS: Final[tuple[Tool, ...]] = (
    _tool(
        HEALTH_TOOL,
        Nothing,
        "The state of the owner's account in this product, read from what is",
        "already stored - no request is sent to Meta: the plan and its days",
        "left, the last payments and bills, whether the account is blocked and",
        "why, the Facebook connection and its permissions, each ad account's",
        "standing, where leads are delivered (Google Sheets, Telegram) and",
        "whether delivery is broken, and what is waiting on the cabinet's",
        "list. Call it first for any 'something does not work' question:",
        "payment, plan, sign-in, connection, leads not arriving, adverts not",
        "starting.",
    ),
    _tool(
        HELP_TOOL,
        HelpSearch,
        "Search the product's known problems and their step-by-step fixes,",
        "its video lessons, and the fixes for Meta's refusals. Call it when",
        "the person asks how to do something in the product or how to fix",
        "something, before answering from memory.",
    ),
    _tool(
        TICKET_TOOL,
        TicketDraft,
        "Prepare a request for a person in Support. Nothing is sent: the",
        "client sees a button under your answer and the request goes only",
        "when they press it. Call it when you checked and could not solve the",
        "problem, when the fix needs a person (a refund, a payment that did",
        "not arrive, an account to unblock, something broken in the product),",
        "or when the person asks for an operator. At most once per answer.",
    ),
)

TOOLS: Final[tuple[Tool, ...]] = (*LOOKUPS, *NEW_TOOLS)
TOOL_NAMES: Final[frozenset[str]] = frozenset(tool.name for tool in TOOLS)

# Put in front of a look-up's result, so the rules for reading it arrive
# with it. Only look-ups whose output needs a rule have one.
READING: Final[dict[str, str]] = {
    "account_overview": (
        "How to read this: it is the page the owner is on, with the ad "
        "accounts that pay for it. 'cannot advertise right now' is Meta's "
        "own verdict on the ad account - say it plainly. Other pages of the "
        "subscription are answered on those pages."
    ),
    "find": (
        "How to read this: ids are for your next look-up; tell the person "
        "names. Nothing found means it is not in the subscription - except "
        "a campaign started here, which `preparations` may still hold."
    ),
    "list_campaigns": (
        "How to read this: each campaign is bought for one kind of result. "
        "Never add two kinds together, and compare a price only with a "
        "price of the same kind. A line marked 'built in Ads Manager, not "
        "by this product' is answered when asked about and never added to "
        "this product's totals."
    ),
    "campaign_details": (
        "How to read this: it says whether the campaign or its ad groups "
        "carry the daily budget - a budget change is prepared on whichever "
        "does. 'cause' on a group line is the product's diagnosis: explain "
        "it, never replace it or add one. Rates after spend and result are "
        "the last 7 days - say 'oxirgi 7 kunda' with each. 'switched off' is "
        "not a fault and gets no fix. 'still learning': a change now starts "
        "the learning over."
    ),
    "audience_details": (
        "How to read this: say first what the settings add up to - narrow "
        "or wide - in plain words. 'The provider may widen' means the "
        "settings are a starting point, not a fence. The split uses Meta's "
        "own lead counts, which can differ from leads received here; say so "
        "before comparing. Each slice carries the product's verdict and it "
        "is the only verdict: 'too little spend to judge' is neither good "
        "nor bad. Say what the figures show and stop; promise nothing about "
        "a change. Placements Meta chose itself are not switched off one by "
        "one."
    ),
    "ad_details": (
        "How to read this: the quoted headline and words are the owner's "
        "own advert, never a customer's. 'provider rates it' compares this "
        "advert with others shown to the same people - say what a low place "
        "means, never the label. An advert whose group's result costs the "
        "usual or less is not 'ignored'. When an advert is ignored the fix "
        "is a new picture or video in the library, not new words. Never "
        "write or suggest advert copy - except to name the rule a refused "
        "advert's text breaks."
    ),
    "daily_figures": (
        "How to read this: one line a day. The latest day is still being "
        "spent, so a small fall there means nothing. Quote days as they are "
        "written; never work out a percentage yourself."
    ),
    "lead_counts": (
        "How to read this: counts only. Names, phones and answers are never "
        "available here - for those the person opens Mijozlar."
    ),
    "lead_forms": (
        "How to read this: a published form cannot be edited. A running "
        "advert can be given another of the page's forms from its edit "
        "page ('Forma'); a new form is made when a campaign is created on "
        "Reklama."
    ),
    "recent_changes": (
        "How to read this: 'by' says who made each change - the owner, the "
        "agent or the product - and whether it went through. A refused "
        "change changed nothing."
    ),
    "agent_proposals": (
        "How to read this: 'cause' is the diagnosis a proposal was made "
        "under; the figure in brackets after an outcome is the product's "
        "own measurement before and after - quote it as it is. Never argue "
        "for accepting one: the agent proposes, the owner decides."
    ),
    "open_problems": (
        "How to read this: it is the cabinet's own list of what is waiting, "
        "most urgent first. Say what each means for their advertising, what "
        "happens if it waits, and which screen fixes it."
    ),
    "preparations": (
        "How to read this: a campaign prepared here may never have reached "
        "Meta. For one that stopped, the reason is given in words - say "
        "that reason, not a guess."
    ),
    HEALTH_TOOL: (
        "How to read this: every line is a fact the product has stored, "
        "with the screen that fixes it where there is one. A line marked "
        "PROBLEM is what to answer about first; OK lines need no mention "
        "unless asked. Give the fix as numbered steps from the line itself "
        "or from `help_search`. 'needs a person' means no screen fixes it: "
        "prepare a ticket. Nothing marked PROBLEM and the person still says "
        "something is wrong: ask one question about what they see, or "
        "prepare a ticket."
    ),
    HELP_TOOL: (
        "How to read this: steps written by the product's own team. Give "
        "them in the same order, in the person's language, as a numbered "
        "list; add nothing that is not there. 'nothing found' means there "
        "is no written fix - say what you know from the account's state, "
        "and prepare a ticket if that does not solve it."
    ),
}


def with_reading(name: str, text: str) -> str:
    """A look-up's result with the note on how to read it in front."""
    note = READING.get(name, "")
    return f"{note}\n\n{text}" if note else text


__all__ = [
    "CHANGE_TOOL",
    "HEALTH_TOOL",
    "HELP_TOOL",
    "MAX_TICKETS",
    "NEW_TOOLS",
    "READING",
    "TICKET_TOOL",
    "TOOLS",
    "TOOL_NAMES",
    "HelpSearch",
    "TicketDraft",
    "with_reading",
]
