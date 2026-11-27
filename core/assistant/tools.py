"""What the one chat's assistant may call while it answers.

The fifteen look-ups of the old chat are used as they are
(``core/chat/lookups.py``). Ten are new: a check of the account's own
state, a search of known problems and their steps, a ticket for a person
in Support - prepared, never sent, until the client presses its button -
a note to the team about a question that was left unanswered, the
product's own plans, prices and dollar rate, what the CRM did with each
campaign's leads, what the half-hourly guard warned about or stopped, the
invite link and wallet, and a note of what the person said about their own
business - kept only when they press its button - and the business's
kind, confirmed the same way.

How to read a result travels with the result (``READING``), not in the
prompt: the model is told about a look-up's output when it has one in hand,
and the prompt stays short for the questions that never call it.
"""

from typing import Final, Literal

from llmkit import Tool
from pydantic import Field

from core.chat.lookup_arguments import Arguments, Nothing, Window
from core.chat.lookups import CHANGE_TOOL
from core.chat.lookups import TOOLS as LOOKUPS

HEALTH_TOOL: Final = "account_health"
HELP_TOOL: Final = "help_search"
TICKET_TOOL: Final = "create_ticket"
GAP_TOOL: Final = "report_gap"
PLANS_TOOL: Final = "plans_and_prices"
CRM_TOOL: Final = "crm_outcomes"
GUARD_TOOL: Final = "guard_alerts"
WALLET_TOOL: Final = "referrals_and_wallet"
NOTE_TOOL: Final = "note_business"
KIND_TOOL: Final = "set_business_kind"

MAX_TICKETS: Final = 1
MAX_GAPS: Final = 1
MAX_NOTES: Final = 1
MAX_KINDS: Final = 1
# The facts kept about a business, as ``businesses.constants.FactKey``
# spells them: the list is closed, and a test holds the two together.
FactName = Literal[
    "customers",
    "area",
    "delivery",
    "guarantee",
    "payment",
    "prices",
    "hours",
    "address",
    "contacts",
    "advantages",
    "answers",
    "other",
]
# What is missing: words a person can write, or something that has to be built.
GAP_ANSWER: Final = "answer"
GAP_BUILD: Final = "tool"


class HelpSearch(Arguments):
    query: str = Field(
        min_length=2,
        max_length=160,
        description=(
            "The problem in a few plain words - what does not work, or what "
            "they are trying to do. Write it in Uzbek whatever language the "
            "person writes in: the fixes are written in Uzbek. When a "
            "look-up gave a code - 'page_terms', or Meta's number such as "
            "'1885316' - send that code alone: a code finds its own fix."
        ),
    )


class TicketDraft(Arguments):
    """A request for a person in Support, for the client to confirm."""

    summary: str = Field(
        min_length=10,
        max_length=600,
        description=(
            "The purpose of the request, in one or two sentences, in the "
            "person's language: what exactly the Support specialist has to "
            "do or find out for this client, and about which object (the "
            "campaign's, bill's or page's name). Written as a task, not as "
            "a story: never retell the conversation, never say what you "
            "answered or guessed earlier, never 'the client asked for an "
            "operator' when the conversation shows what they need."
        ),
    )
    checked: list[str] = Field(
        default_factory=list,
        max_length=8,
        description=(
            "The facts a look-up returned that bear on this request, one "
            "short line each, five at most - 'Tarif: faol, 12 kun qoldi', "
            "'Facebook ulanishi: uzilgan'. Leave out a check that has "
            "nothing to do with the request. Only what a look-up actually "
            "returned."
        ),
    )
    new_problem: bool = Field(
        default=False,
        description=(
            "True only when `account_health` showed a request Support "
            "already has in hand and this one is about a different "
            "problem. Leave it false otherwise."
        ),
    )


class GapReport(Arguments):
    """A question the assistant had to leave unanswered, for the team."""

    topic: str = Field(
        min_length=3,
        max_length=160,
        description=(
            "What the person asked for, as a short title in plain Uzbek - "
            "'Reklamani boshqa akkauntga ko'chirish'. The general question, "
            "so the same one asked by somebody else gets the same title: "
            "no names, phones, figures or dates."
        ),
    )
    kind: Literal["answer", "tool"] = Field(
        description=(
            "'answer': the product can do it or the problem is known, but "
            "no written answer or steps exist here - a person can write "
            "them. 'tool': answering needs something you cannot read or do "
            "here - a look-up that does not exist, data that is not kept, "
            "or a feature the product does not have."
        ),
    )
    missing: str = Field(
        min_length=5,
        max_length=300,
        description=(
            "In Uzbek, one or two short sentences: exactly what has to be "
            "added so the next person gets an answer. For 'answer' - which "
            "steps or explanation should be written. For 'tool' - which "
            "data a look-up would have to return or which action it would "
            "have to make. Precise and short; never retell the conversation."
        ),
    )


class SoldNote(Arguments):
    """One thing the business sells, as the person said it."""

    name: str = Field(
        min_length=2,
        max_length=80,
        description=(
            "The product, service or course by its own short name, as the "
            "person wrote it - 'Ingliz tili kursi', 'Changyutgich Hoover "
            "H-Free'. One thing per entry, never a list in one name. To "
            "change something already kept, use its name exactly as the "
            "Context has it."
        ),
    )
    kind: Literal["product", "service", "course", "other"] = Field(
        default="other", description="What kind of thing it is."
    )
    price: str = Field(
        default="",
        max_length=60,
        description=(
            "Its price exactly as the person wrote it, with the currency - "
            "'450 000 so'm', 'oyiga 600 000 so'm'. Empty when they gave "
            "none: never work one out."
        ),
    )
    note: str = Field(
        default="",
        max_length=300,
        description=(
            "One short line the person said about it - who it is for, how "
            "long it lasts, what is included. Empty when they said nothing."
        ),
    )
    gone: bool = Field(
        default=False,
        description=(
            "True when the person said they no longer sell this. It is "
            "then taken off the list, not deleted."
        ),
    )


class FactNote(Arguments):
    """One lasting fact about how the business works."""

    key: FactName = Field(
        description=(
            "Which fact: customers (who buys), area (where it works), "
            "delivery, guarantee, payment (instalments, cards), prices (the "
            "general level or a price list), hours, address, contacts, "
            "advantages (why people choose it), answers (who answers "
            "customers and how fast), other."
        ),
    )
    value: str = Field(
        min_length=2,
        max_length=400,
        description=(
            "The fact in the person's own words and language, short. "
            "Numbers exactly as written."
        ),
    )


class BusinessNote(Arguments):
    """What the person just said about their own business, to be kept."""

    about: str = Field(
        default="",
        max_length=600,
        description=(
            "What the business does, in one or two sentences in the "
            "person's language - only when they described it and the "
            "Context has no description or theirs changes it. Empty "
            "otherwise."
        ),
    )
    items: list[SoldNote] = Field(default_factory=list, max_length=8)
    facts: list[FactNote] = Field(default_factory=list, max_length=6)


class BusinessKind(Arguments):
    """What kind of business this is, for the person to confirm."""

    direction: str = Field(
        min_length=2,
        max_length=64,
        description=(
            "The kind's key, exactly as the Context's 'Kinds to choose "
            "from' line writes it - 'education', 'ecommerce'. Only a key "
            "from that line."
        ),
    )
    subtype: str = Field(
        default="",
        max_length=80,
        description=(
            "The narrower kind inside it, two or three plain words in "
            "Uzbek (latin script) - 'ingliz tili kurslari', 'oshxona "
            "mebeli', 'stomatologiya'. Never a brand, the business's own "
            "name or a city. Empty when what they said does not show it."
        ),
    )
    name: str = Field(
        default="",
        max_length=255,
        description=(
            "The business's name as the person said it should be called. "
            "Empty unless they gave one or corrected the one in the Context."
        ),
    )


def _tool(name: str, arguments: type, *lines: str) -> Tool:
    return Tool(name=name, description=" ".join(lines), arguments=arguments)


NEW_TOOLS: Final[tuple[Tool, ...]] = (
    _tool(
        HEALTH_TOOL,
        Nothing,
        "The state of the owner's account in this product, read from what is",
        "already stored - no request is sent to Meta: an unfinished setup",
        "(«Tayyorgarlik») and its next step, the plan and its days left, the",
        "last payments and bills, the bound card, autopay and the last",
        "automatic charge, whether the account is blocked and why, the",
        "Facebook connection and its permissions, each ad account's standing,",
        "where leads are delivered (Google Sheets, Telegram) and whether",
        "delivery is broken, what is waiting on the cabinet's list, and the",
        "client's request to Support: whether one is open, what it is about",
        "and where it stands. Call it first for any 'something does not",
        "work' question: payment, autopay, plan, sign-in, setup, connection,",
        "leads not arriving, adverts not starting.",
    ),
    _tool(
        HELP_TOOL,
        HelpSearch,
        "Search the product's known problems and their step-by-step fixes,",
        "its video lessons, and the ready fixes for Meta's errors: an advert",
        "that was not created, an advert Meta refused or will not run, a",
        "change Meta did not take. Call it when the person asks how to do",
        "something in the product or how to fix something, before answering",
        "from memory. Not needed when a look-up's result already carries a",
        "'Ready fix' for the problem.",
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
        "When Support already has a request in hand, it is refused unless",
        "this one is about a different problem (`new_problem`).",
    ),
    _tool(
        PLANS_TOOL,
        Nothing,
        "This product's own plans the person may buy now - price in so'm,",
        "days, pages included, extra page and CRM seat prices, Start being",
        "a first purchase only - their current plan, a personal discount if",
        "they have one, and today's dollar rate in so'm. Use it for any",
        "question about what the product costs, a free option, renewing,",
        "or turning a dollar amount into so'm.",
    ),
    _tool(
        CRM_TOOL,
        Window,
        "What the owner's CRM did with each campaign's leads: how many were",
        "sold, refused or marked poor quality (Sifatsiz), still new or in",
        "progress, the share sold, the amount sold for, the most common",
        "reasons for refused and poor leads - and who works them: each",
        "manager's leads, outcomes, overdue ones and last move in the CRM,",
        "and leads given to nobody. Counts only. Use it for 'sales are low',",
        "'the leads are poor', 'which campaign brings buyers', 'does my",
        "manager call the leads'. Lead-form campaigns only: chat and call",
        "campaigns have no CRM cards.",
    ),
    _tool(
        GUARD_TOOL,
        Window,
        "What the product's guard - it checks every running ad group every",
        "half hour - warned the owner about or stopped by itself: price far",
        "above the group's usual, money spent with nothing back, a site that",
        "does not open, a weak advert; with the exact words the owner got in",
        "the cabinet and on Telegram, when, and which button they pressed.",
        "Use it for 'why did my advert stop', 'what was that warning'.",
    ),
    _tool(
        WALLET_TOOL,
        Nothing,
        "The owner's invite link, how many friends signed up through it and",
        "paid, the wallet's balance (earned, spent on plans, taken out), the",
        "requests to take money out, and whether taking it out to a card is",
        "open. Use it for referral, bonus, balance or 'pul yechish' questions.",
    ),
    _tool(
        NOTE_TOOL,
        BusinessNote,
        "Keep what the person just told you about their own business, so the",
        "next advert and the next answer start from it: what the business",
        "does, a product, service or course with its price, something they no",
        "longer sell, a lasting fact (delivery, guarantee, payment terms,",
        "hours, address, who their customers are). Nothing is saved: the",
        "person sees a button under your answer and it is kept only when they",
        "press it. Call it when their message states such a thing as a fact",
        "about their business and the Context's Business section does not",
        "already hold it. Only what they said themselves, in their words -",
        "never a guess, never something you read in an advert or a look-up,",
        "never a figure about the account, never a one-off (today's discount,",
        "this week's plan). At most once per answer, with everything new in",
        "one call. It costs no look-up; answer their question as usual.",
    ),
    _tool(
        KIND_TOOL,
        BusinessKind,
        "Prepare the business's kind - its direction from the closed list,",
        "the narrower kind inside it, and its name - for the person to",
        "confirm with a button. Nothing is saved until they press. Call it",
        "when the Context says the kind is a guess or not known and the",
        "person has just said what their business does or agreed with the",
        "guess, or when they say the kind or the name in the Context is",
        "wrong and give the right one. Never from your own guess alone: only",
        "from what they said in this conversation. At most once per answer;",
        "it costs no look-up.",
    ),
    _tool(
        GAP_TOOL,
        GapReport,
        "Tell the product's team about a question you could not answer, so",
        "they write the missing answer or build the missing look-up. Call it",
        "once, before you write, when `help_search` found nothing and the",
        "account's state does not explain the problem, when no look-up reads",
        "what the person asked about, or when the product cannot do what",
        "they want. Not for a question you answered, and not for one that is",
        "not about advertising or this product. The person is not told.",
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
        "this product's totals. Said to the person it is a campaign "
        "«Ads Manager'da yaratilgan» - never 'not this product'."
    ),
    "campaign_details": (
        "How to read this: it says whether the campaign or its ad groups "
        "carry the daily budget - a budget change is prepared on whichever "
        "does. 'cause' on a group line is the product's diagnosis: explain "
        "it, never replace it or add one. Rates after spend and result are "
        "the last 7 days - say 'oxirgi 7 kunda' with each. 'switched off' is "
        "not a fault and gets no fix. 'still learning': a change now starts "
        "the learning over. 'Meta code N' on a line means Meta will not "
        "run it for a reason the product has a written answer for: the "
        "'Ready fix' for that code is under the lists - say its cause in "
        "one sentence and give its steps as they are, in order. Never say "
        "the code itself to the person. An advert marked 'refused' has its "
        "ready fix in `ad_details`."
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
        "advert's text breaks. A 'Ready fix' block is the product's own "
        "written answer for this advert: say its cause in one sentence and "
        "give its steps as they are, in order, as a numbered list."
    ),
    "daily_figures": (
        "How to read this: one line a day. The latest day is still being "
        "spent, so a small fall there means nothing. Quote days as they are "
        "written; never work out a percentage yourself. There is no hour by "
        "hour reading anywhere: never offer to look at hours of the day. "
        "'Checked against Ads Manager' says which closed days the product "
        "compared with Ads Manager's own total: a day apart is told as it "
        "is, with Ads Manager's figure as the right one."
    ),
    "lead_counts": (
        "How to read this: counts only. Names, phones and answers are never "
        "available here - for those the person opens [[lidlar]]."
    ),
    "lead_forms": (
        "How to read this: a published form cannot be edited. A running "
        "advert can be given another of the page's forms from its edit "
        "page ('Forma'); a new form is made when a campaign is created on "
        "Reklama."
    ),
    "recent_changes": (
        "How to read this: 'by' says who made each change - the owner, the "
        "agent or the product - and whether it went through. A change made "
        "in Ads Manager is not here: it was made outside this product, most "
        "often by the owner - never call it «somebody». A refused "
        "change changed nothing. 'why it failed' is the screen's own "
        "sentence for it, with what Meta wrote; a 'Ready fix' after it is "
        "the steps to give, as they are."
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
        "happens if it waits, and which screen fixes it. Something switched "
        "off «in Ads Manager» was done there, outside this product - most "
        "often by the owner themselves: say where it was done, never that "
        "«somebody» did it or that access should be checked, unless they "
        "say it was not them."
    ),
    "crm_outcomes": (
        "How to read this: each line is one campaign's leads as the CRM "
        "left them. «Sifatsiz lid» is a lead the owner's team judged poor, "
        "«Rad etildi» one that did not buy; their reasons are the team's "
        "own words - say them as theirs. Leads still in «Yangi lid» have no "
        "outcome: never count them as unsold. Under 'Who works these leads' "
        "a manager's name is the owner's own staff: say it. Leads given to "
        "nobody and leads past their «muddat» are what to point at first."
    ),
    GUARD_TOOL: (
        "How to read this: each finding is the guard's own message, with "
        "when it was written - 'Bugun' in its words is that day, not today. "
        "Say what it found and what it did in plain words; a STOPPED one was "
        "stopped by the product to save money, and switching it back on is "
        "the owner's choice («Qayta yoqish» under the message, or on "
        "Reklama). Never say it was Meta, the owner or «somebody»."
    ),
    WALLET_TOOL: (
        "How to read this: the sums are the wallet's own; never add two "
        "currencies. Friends are counts, never names. Taking money out is "
        "answered exactly as the last lines say."
    ),
    "preparations": (
        "How to read this: a campaign prepared here may never have reached "
        "Meta. For one that stopped, the reason is given in words - say "
        "that reason, not a guess. Each stopped line names its 'ready "
        "fix', and the fix itself is under the list: the product's own "
        "written answer. Say its cause in one sentence and give its steps "
        "as they are, in order, as a numbered list - add none, drop none. "
        "The buttons its steps name are on the «Reklamani yaratib "
        "bo'lmadi» sheet, which opens from that campaign on Reklama: say "
        "so first. Do not call `help_search` for a problem that has one."
    ),
    HEALTH_TOOL: (
        "How to read this: every line is a fact the product has stored, "
        "with the screen that fixes it where there is one. A line marked "
        "PROBLEM is what to answer about first; OK lines need no mention "
        "unless asked. Give the fix as numbered steps from the line itself "
        "or from `help_search`. A setup step named «next» is the one to do "
        "now, on «Tayyorgarlik». A card line is the bound card and autopay as "
        "they stand; never promise a charge's sum. 'needs a person' means no "
        "screen fixes it: "
        "prepare a ticket. Nothing marked PROBLEM and the person still says "
        "something is wrong: ask one question about what they see, or "
        "prepare a ticket."
    ),
    HELP_TOOL: (
        "How to read this: steps written by the product's own team. Give "
        "them in the same order, in the person's language, as a numbered "
        "list; add nothing that is not there. 'nothing found' means there "
        "is no written fix - say what you know from the account's state, "
        "prepare a ticket if that does not solve it, and call `report_gap` "
        "if the person is left without the answer they asked for. A result "
        "marked "
        "'a video lesson' is a video the person can watch: name it by its "
        "exact title, as it is written here, in «» - the page then shows "
        "it under your answer as a card that opens the video. So do not "
        "write steps for finding it in Darsliklar, and do not correct or "
        "shorten its title."
    ),
}


def with_reading(name: str, text: str) -> str:
    """A look-up's result with the note on how to read it in front."""
    note = READING.get(name, "")
    return f"{note}\n\n{text}" if note else text


__all__ = [
    "CHANGE_TOOL",
    "GAP_ANSWER",
    "GAP_BUILD",
    "GAP_TOOL",
    "GUARD_TOOL",
    "HEALTH_TOOL",
    "HELP_TOOL",
    "KIND_TOOL",
    "MAX_GAPS",
    "MAX_KINDS",
    "MAX_NOTES",
    "MAX_TICKETS",
    "NEW_TOOLS",
    "NOTE_TOOL",
    "READING",
    "TICKET_TOOL",
    "TOOLS",
    "TOOL_NAMES",
    "WALLET_TOOL",
    "BusinessKind",
    "BusinessNote",
    "FactNote",
    "GapReport",
    "HelpSearch",
    "SoldNote",
    "TicketDraft",
    "with_reading",
]
