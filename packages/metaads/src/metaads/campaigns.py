"""Reading the shape of an ad account: its campaigns, ad sets and ads.

Read-only. Pausing, resuming and budget changes are writes and live apart,
because a module that can only read is a module that cannot spend somebody
else's money by accident.

Everything here is asked for at the *account* level rather than per parent.
An advertiser with forty campaigns has forty ad set calls to make the naive
way, and the call budget - not the latency - is what runs out first.
"""

import logging
from typing import Any, Final

from metaads.client import GraphClient
from metaads.dto import AdRow, AdSetRow, CampaignRow
from metaads.errors import MetaAPIError
from metaads.parsing import parsed, parsed_all
from metaads.writing import graph_client

logger = logging.getLogger(__name__)

# Asked for explicitly, because Meta's default field set is id and name and
# nothing that says whether the thing is running.
#
# `effective_status` is the one that matters: `status` is what the
# advertiser set, and an ACTIVE campaign whose ad account is out of money
# has an effective status saying so.
#
# ``issues_info`` and ``recommendations` ride along on the same request. A
# field added to a list that is already being fetched costs no extra call -
# the whole account still comes back in one paged read - so the only price
# is a little more of Meta's own processing time, which its usage header
# counts separately from the call count.
CAMPAIGN_FIELDS = (
    "id,name,objective,status,effective_status,daily_budget,spend_cap,"
    "special_ad_categories,created_time,issues_info,recommendations"
)

# `learning_stage_info` is what the guardrail reads. Without it there is no
# way to tell an ad set that is still learning from one that has settled,
# and touching the first throws away the delivery Meta has bought so far.
# The two states in which an ad set is gone from its campaign as far as
# anybody running it is concerned.
REMOVED_STATUSES: Final = frozenset({"DELETED", "ARCHIVED"})

ADSET_FIELDS = (
    "id,name,campaign_id,status,effective_status,optimization_goal,"
    "billing_event,destination_type,daily_budget,targeting,promoted_object,"
    "learning_stage_info,start_time,end_time,issues_info,recommendations"
)

# Not on the mirror, and needed only when an ad set is copied from this one.
ADSET_SETTINGS_FIELDS = "bid_strategy,bid_amount,attribution_spec,frequency_control_specs"

# The nested creative read is there for one field above all: the lead form
# id, the link between an ad and the leads it bought, which asking for
# later would cost one call per ad.
#
# Reading the whole creative is still that one call. A nested
# expansion rides on a request already being made - the same trade
# ``issues_info`` makes above - where ``/act_<id>/adcreatives`` would be a
# fourth paged read of this sync. It also answers a different question:
# that edge lists every creative the advertiser has ever made, and a
# creative no ad points at has no figures to compare.
#
# ``ad_review_feedback`` is asked for on every ad and comes back on the
# refused ones only. There is no separate "was it rejected" call to make -
# an empty answer is the ad being fine.
#
# ``recommendations`` is deliberately absent. Meta gives advice about
# audiences and budgets, which live one level up; an ad has neither.
# ``effective_object_story_id`` and ``actor_id`` are asked for so an advert
# can be placed on the page it ran as. A creative built from a spec carries
# ``object_story_spec.page_id``; one Meta produced itself - a boosted post,
# an advert built in Ads Manager from an existing post - may carry neither
# that nor ``object_story_id``, and then the only two fields naming its page
# are these. An advert nothing can place is money on no screen at all.
CREATIVE_SUBFIELDS = (
    "id,name,status,thumbnail_url,object_story_id,object_story_spec,"
    "effective_object_story_id,actor_id"
)
AD_FIELDS = (
    f"id,name,adset_id,status,effective_status,creative{{{CREATIVE_SUBFIELDS}}},"
    "issues_info,ad_review_feedback"
)

# An Advantage+ creative Meta cannot read back: the first value of its asset
# feed does not match the story spec. Raised on the creative's content, not
# on the ad, so the ad is still readable once the content is not asked for - one
# such advert anywhere in an account fails the whole ``/ads`` list.
UNREADABLE_CREATIVE_SUBCODE: Final = 2446211

# The ad without its creative's content: the creative's id survives, and the
# status - which is what a launch is waiting on - is untouched.
AD_FIELDS_WITHOUT_CONTENT: Final = (
    "id,name,adset_id,status,effective_status,creative{id},"
    "issues_info,ad_review_feedback"
)

# Meta's own maximum for these endpoints. Fewer, larger pages is fewer calls
# against the same budget.
PAGE_SIZE = 100

# How deep the three account lists may page - their own ceiling rather than
# the client's default of 25, which holds 2 500 rows.
#
# These are the one family of edges here that grows with how long somebody
# has advertised: nothing is ever removed from them but by hand, so an
# account with a thousand campaigns behind it carries two and a half
# thousand ad sets and as many ads. The mirror is all or nothing - a row
# missing from the list is a row it deletes - so a list one page too long
# is not a short sync, it is no sync at all, and the account goes dark.
#
# A hundred pages is ten thousand rows of each. Past that the ceiling is no
# longer what stops the sync: it writes row by row under a five-minute
# lock, and the time runs out first.
MIRROR_PAGES: Final = 100

# What `get_status` asks for, by level.
#
# **Meta refuses a field a node does not have.** Asking an ad for
# `daily_budget`, or a campaign for `learning_stage_info`, is error 100 -
# "Tried accessing nonexisting field" - and not an empty answer. So this is
# a table rather than one string: a level whose read asked for one field too
# many fails on every object at that level, every time, and the failure is
# the read taken immediately before a write.
#
# ``daily_budget`` rides along at the two levels that can hold one, because
# a budget change is decided against the current figure and this is the read
# that was going to happen anyway. It comes back absent - not zero - on an
# object whose budget lives one level down, which is the distinction that
# has to survive.
#
# An ad has neither. It holds no money and has no learning stage of its own:
# both belong to the ad set above it, which is where a caller that needs
# them has to go and ask.
BASE_STATUS_FIELDS = "status,effective_status"
BUDGET_STATUS_FIELDS = f"{BASE_STATUS_FIELDS},daily_budget"
ADSET_STATUS_FIELDS = f"{BUDGET_STATUS_FIELDS},learning_stage_info"

STATUS_FIELDS: dict[str, str] = {
    "campaign": BUDGET_STATUS_FIELDS,
    "adset": ADSET_STATUS_FIELDS,
    "ad": BASE_STATUS_FIELDS,
}


def list_campaigns(
    *, account_id: str, token: str, client: GraphClient | None = None
) -> list[CampaignRow]:
    """Every campaign in the account, as Meta currently describes it.

    Deleted campaigns simply stop appearing, which is how the mirror learns
    that one is gone: there is no tombstone to read.
    """
    rows = _read(
        path=f"{account_id}/campaigns",
        fields=CAMPAIGN_FIELDS,
        token=token,
        client=client,
    )
    return parsed_all(CampaignRow, rows)


def list_adsets(
    *, account_id: str, token: str, client: GraphClient | None = None
) -> list[AdSetRow]:
    """Every ad set in the account, across every campaign."""
    rows = _read(
        path=f"{account_id}/adsets", fields=ADSET_FIELDS, token=token, client=client
    )
    return parsed_all(AdSetRow, rows)


def read_adset_settings(
    *, adset_id: str, token: str, client: GraphClient | None = None
) -> dict[str, Any]:
    """The delivery settings of one ad set, raw, as a new one will be sent them."""
    with graph_client(client, token) as graph:
        return graph.get(adset_id, fields=ADSET_SETTINGS_FIELDS)


def count_campaign_adsets(
    *, campaign_id: str, token: str, client: GraphClient | None = None
) -> int:
    """How many ad sets under one campaign are neither deleted nor archived.

    Counted from the rows rather than asked of a filter: an
    ``effective_status`` value the edge does not accept fails the whole
    read, and a campaign holds a handful of ad sets at most.
    """
    rows = _read(
        path=f"{campaign_id}/adsets",
        fields="id,effective_status",
        token=token,
        client=client,
    )
    return sum(
        1
        for row in rows
        if str(row.get("effective_status") or "").upper() not in REMOVED_STATUSES
    )


def list_ads(
    *, account_id: str, token: str, client: GraphClient | None = None
) -> list[AdRow]:
    """Every ad in the account, across every ad set.

    Read again without the creatives' content when one creative's content
    is what Meta refuses. Without that, one Advantage+ advert - often one
    nobody here made - left the whole account's mirror unread on every
    sync. The ads come back with their creative's id alone; the caller
    keeps what it already holds about those creatives.
    """
    try:
        rows = _read(
            path=f"{account_id}/ads", fields=AD_FIELDS, token=token, client=client
        )
    except MetaAPIError as exc:
        if exc.subcode != UNREADABLE_CREATIVE_SUBCODE:
            raise
        logger.warning("ads of %s read without creative content: %s", account_id, exc)
        rows = _read(
            path=f"{account_id}/ads",
            fields=AD_FIELDS_WITHOUT_CONTENT,
            token=token,
            client=client,
        )
    return parsed_all(AdRow, rows)


def get_adset(
    *, adset_id: str, token: str, client: GraphClient | None = None
) -> AdSetRow:
    """One ad set, read fresh.

    Used before a write rather than trusting the mirror: the mirror is as
    old as the last sync, and "was it still learning a quarter of an hour
    ago" is not the question the guardrail is asking.
    """
    graph = client or GraphClient(token=token)
    try:
        row = graph.get(adset_id, fields=ADSET_STATUS_FIELDS)
    finally:
        if client is None:
            graph.close()

    return parsed(AdSetRow, row)


def get_object(
    *, object_id: str, fields: str, token: str, client: GraphClient | None = None
) -> dict[str, Any]:
    """One object's raw fields. The escape hatch for level-specific reads."""
    graph = client or GraphClient(token=token)
    try:
        return graph.get(object_id, fields=fields)
    finally:
        if client is None:
            graph.close()


def _read(
    *, path: str, fields: str, token: str, client: GraphClient | None
) -> list[dict[str, Any]]:
    """One paged list read, closing only a client this function opened."""
    graph = client or GraphClient(token=token)
    try:
        return graph.get_all(
            path, fields=fields, limit=PAGE_SIZE, max_pages=MIRROR_PAGES
        )
    finally:
        if client is None:
            graph.close()
