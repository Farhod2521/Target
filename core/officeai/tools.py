"""What the office's assistant may look up. Every look-up only reads.

Each one is a figure the office already shows somewhere - the dashboard,
the customers list, the plans - so the answer and the screen never
disagree. Money (takings, who paid) is offered only to the roles that see
it on the dashboard: for the others it is left out of the list, and the
runner refuses it too.
"""

from datetime import date
from typing import Final, Literal

from llmkit import Tool
from pydantic import Field

from core.chat.lookup_arguments import Arguments, Nothing

Period = Literal["today", "7", "30", "month", "year", "range"]
CustomerState = Literal[
    "", "trial", "active", "expiring", "lapsed", "never", "blocked", "trouble"
]

CUSTOMERS: Final = "customers_summary"
MONEY: Final = "money_summary"
PLATFORM: Final = "platform_activity"
QUEUES: Final = "waiting_now"
SALES: Final = "sales_by_manager"
PAYMENTS: Final = "recent_payments"
CUSTOMER_LIST: Final = "customer_list"
PLANS: Final = "plans_summary"

# Seen only by the roles the dashboard shows money to.
MONEY_TOOLS: Final = frozenset({MONEY, PAYMENTS})


class Span(Arguments):
    """Which days to read. Every day is the office's day (Tashkent)."""

    period: Period = Field(
        default="30",
        description=(
            "`today`; `7` or `30` - that many days back, today included; "
            "`month` - this calendar month so far; `year` - this year so far; "
            "`range` - the days in `since`..`until`."
        ),
    )
    since: date | None = Field(
        default=None, description="With `range`: the first day, YYYY-MM-DD."
    )
    until: date | None = Field(
        default=None, description="With `range`: the last day, YYYY-MM-DD."
    )
    per_bar: bool = Field(
        default=False,
        description=(
            "Also give a row per day, week or month. Only when the person asks "
            "how it went over time; the totals come either way."
        ),
    )


CustomerField = Literal["business", "joined", "paid", "ads", "manager", "problem"]
LIST_LIMIT: Final = 30
LIST_DEFAULT: Final = 10


class Queues(Arguments):
    problems: bool = Field(
        default=False,
        description=(
            "Also list the problems one by one - who and what. Without it: "
            "only how many there are and how many are urgent."
        ),
    )


class CustomerQuery(Arguments):
    term: str = Field(
        default="",
        max_length=100,
        description=(
            "Part of a name, an email, a phone number, an invoice number, or "
            "an ad account or page id. Empty: everyone the other filters keep."
        ),
    )
    state: CustomerState = Field(
        default="",
        description=(
            "`trial` - on a trial now; `active` - on a paid plan now; "
            "`expiring` - the plan ends within a few days; `lapsed` - had a "
            "plan, has none now; `never` - never had a plan; `blocked`; "
            "`trouble` - something on the office's problem list. Empty: all."
        ),
    )
    plan: str = Field(
        default="",
        max_length=32,
        description="A plan's `code`, as `plans_summary` names it.",
    )
    joined_from: date | None = Field(
        default=None, description="Signed up on or after this day, YYYY-MM-DD."
    )
    joined_to: date | None = Field(
        default=None, description="Signed up on or before this day, YYYY-MM-DD."
    )
    fields: list[CustomerField] = Field(
        default_factory=list,
        description=(
            "What to add to each row beyond name, email and plan - only what "
            "the answer needs: `business` its name; `joined` sign-up day; "
            "`paid` paid in all; `ads` campaigns running and leads; `manager` "
            "sales manager; `problem` the worst problem."
        ),
    )
    limit: int = Field(
        default=LIST_DEFAULT,
        ge=1,
        le=LIST_LIMIT,
        description="How many rows to list. The total that matched comes anyway.",
    )


def _tool(name: str, arguments: type, *lines: str) -> Tool:
    return Tool(name=name, description=" ".join(lines), arguments=arguments)


TOOLS: Final[tuple[Tool, ...]] = (
    _tool(
        CUSTOMERS,
        Span,
        "Customers over a window of days: how many there are in all, how many",
        "signed up (and the window before, for comparison), how many of those",
        "paid for a plan and the conversion, how many are on a trial or a paid",
        "plan now, whose plan ends soon, who stopped, who has not finished the",
        "setup or connected Facebook. Staff accounts are never counted.",
    ),
    _tool(
        MONEY,
        Span,
        "Takings over a window of days: money in, number of payments, the",
        "average, online versus entered by hand, each plan's share, the window",
        "before for comparison, unpaid bills now, plans given free. In the",
        "currency most bills were paid in.",
    ),
    _tool(
        PLATFORM,
        Span,
        "What the product did for its customers over a window of days:",
        "campaigns running now, launched and failed, ad spend, leads (and the",
        "window before), and what the AI cost.",
    ),
    _tool(
        QUEUES,
        Queues,
        "What waits on a person in the office right now - support chats with",
        "no answer, promo and plan requests, feedback, sales requests, stuck",
        "payments, block suggestions - and how long the problem list is:",
        "broken connections, failed launches, plans about to end, leads not",
        "arriving.",
    ),
    _tool(
        SALES,
        Span,
        "Each sales manager: sales closed in the window and cards open now.",
    ),
    _tool(
        PAYMENTS,
        Nothing,
        "The last payments, newest first: when, who, which plan, how much.",
    ),
    _tool(
        CUSTOMER_LIST,
        CustomerQuery,
        "Find customers, or list the ones a filter keeps: the total that",
        "matched and the first rows, each with name, email, plan and its",
        "state, days left or when it ended. Use it for 'who' and for one",
        "customer's situation. For 'how many', `limit` 1 is enough.",
    ),
    _tool(
        PLANS,
        Nothing,
        "Every plan with its code, price and length, whether it is on sale,",
        "and how many customers are on it now - on a trial and paying.",
    ),
)
TOOL_NAMES: Final = frozenset(tool.name for tool in TOOLS)


def tools_for(*, sees_money: bool) -> tuple[Tool, ...]:
    """The look-ups this person may have read for them."""
    if sees_money:
        return TOOLS
    return tuple(tool for tool in TOOLS if tool.name not in MONEY_TOOLS)


LOOKING: Final[dict[str, str]] = {
    CUSTOMERS: "Mijozlar sonini o'qiyapman…",
    MONEY: "Tushumni hisoblayapman…",
    PLATFORM: "Platforma faolligini o'qiyapman…",
    QUEUES: "Kutayotgan ishlarni ko'ryapman…",
    SALES: "Sotuvlarni o'qiyapman…",
    PAYMENTS: "Oxirgi to'lovlarni ko'ryapman…",
    CUSTOMER_LIST: "Mijozlarni qidiryapman…",
    PLANS: "Tariflarni o'qiyapman…",
}


__all__ = [
    "CUSTOMERS",
    "CUSTOMER_LIST",
    "LOOKING",
    "MONEY",
    "MONEY_TOOLS",
    "PAYMENTS",
    "PLANS",
    "PLATFORM",
    "QUEUES",
    "SALES",
    "TOOLS",
    "TOOL_NAMES",
    "CustomerQuery",
    "Queues",
    "Span",
    "tools_for",
]
