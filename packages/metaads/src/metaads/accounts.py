"""What a token can reach: which ad accounts, and which pages.

Read once when a connection is made and again whenever it is refreshed.
Both lists are asked for in full rather than filtered here - a closed ad
account and a page the person can only analyse are still worth showing,
greyed out with a reason, instead of vanishing and leaving them wondering
where their account went.
"""

import logging
from collections.abc import Iterable, Sequence
from typing import Any, Final
from urllib.parse import urlencode

from metaads.client import GraphClient
from metaads.dto import AdAccountDTO, PageDTO, PixelDTO, PixelEventRow
from metaads.errors import MetaAPIError, MetaError
from metaads.parsing import parsed_all

# The only logger in this package, and it earns its place: the sweep below
# reads several lists and one of them being refused is an ordinary event
# that must not stop the others. Raising would take a working advertiser's
# whole account list away over a business they merely happen to be in;
# staying silent would leave nobody able to tell that from an empty Meta.
logger = logging.getLogger(__name__)

# Asked for explicitly. Meta's default field set is a bare id and name, and
# the two that decide how every number is later read - currency and
# timezone - are not in it.
#
# ``min_daily_budget`` is the account's own floor, in its own currency's
# minor units. Meta publishes a different one per currency and per account
# and refuses an ad set below it, several calls into a creation sequence.
# Reading it here is what lets the wizard say so while the number is still
# being typed.
#
# ``disable_reason`` is only ever non-zero when ``account_status`` already
# says something is wrong, and it is not shown to anybody: Meta publishes it
# as a number whose meanings shift, and a wrong translation of "why your
# account is off" is worse than none. It is read so that a support
# conversation starts from what Meta actually said.
#
# ``tos_accepted`` and ``user_tos_accepted`` are what say whether a customer
# list may be uploaded to this account. Two fields for one question because
# Meta signs the agreement twice - once by the business, once by the person
# - and for an ordinary user token it is the second one that is enforced.
# They ride along on a list this connection already fetches, which is the
# difference between telling somebody before they upload a spreadsheet and
# telling them after.
AD_ACCOUNT_FIELDS = (
    "id,name,currency,timezone_name,account_status,spend_cap,amount_spent,"
    "min_daily_budget,disable_reason,tos_accepted,user_tos_accepted,business{id}"
)

# What a Business Manager is asked for. Only enough to walk its edges and
# to name it in a log line - nothing here is shown to anybody.
BUSINESS_FIELDS: Final = "id,name"

# Where the ad accounts a business holds actually live.
#
# ``/me/adaccounts`` answers with the accounts this *person* carries a role
# on, and that is not the set of accounts they can advertise from. An
# account created inside a Business Manager belongs to the business: an
# administrator of that business opens Ads Manager and sees it, spends from
# it, and is told here that they have no ad account - because nobody ever
# handed them a personal role on the thing they own through the business.
# That gap is the whole reason this sweep exists.
#
# Two edges rather than one because Meta files them apart. ``owned`` is what
# the business created for itself; ``client`` is what another business - an
# agency, a partner - shared with it, and for anybody working through an
# agency every account they have is in the second one.
BUSINESS_AD_ACCOUNT_EDGES: Final[tuple[str, ...]] = (
    "owned_ad_accounts",
    "client_ad_accounts",
)

# How many businesses one sweep will walk, and therefore how many rows the
# list above is asked for. Two calls each, and the sweep runs inside the
# connect callback with a person watching a blank browser tab - so this is
# a stopwatch, not a limit on what anybody may own.
#
# An advertiser has one business; somebody at an agency might be in a
# dozen. Twenty-five is far past both and still bounds the handshake at
# fifty requests, where an unbounded loop bounds it at whatever Meta and
# the gateway agree to time out at - and a timeout here is not a short
# list, it is no connection at all.
MAX_BUSINESSES: Final = 25

# Statuses from which no ad can be created, whatever the payload says.
# Deliberately not "everything that is not 1": 7 is pending risk review, 8
# pending settlement and 9 a grace period, and accounts in those do go on
# delivering. Refusing them here would stop launches Meta would have
# accepted, which is the more expensive of the two mistakes - the other one
# ends in a refusal that now arrives with Meta's own words attached.
#
# 2 disabled, 3 unsettled, 100 pending closure, 101 closed.
BLOCKED_ACCOUNT_STATUSES: Final[frozenset[int]] = frozenset({2, 3, 100, 101})

# Unsettled: a bill Meta could not charge. The one blocked status the owner
# clears themselves, on the billing page - every launch refused for a
# blocked account in production so far was this one.
UNSETTLED_STATUS: Final = 3

# `tasks` is what says whether this person may subscribe the page to lead
# webhooks. Without it a page that will fail at subscribe time looks
# identical to one that will work.
#
# `leadgen_tos_accepted` is a different thing despite the shared word: not
# the webhook subscription but Meta's one-off lead ad agreement, given per
# page by whoever administers it. Until it is given the ad set is refused
# with 100/1815089 - three calls in, after a lead form has been created
# and cannot be deleted. It is one field on a list we already ask for.
#
# `location` is read to offer, never to target. It is what a first-time
# advertiser's launch screen proposes instead of an empty geography field,
# and it costs nothing here: it rides along on a list this connection
# already fetches. Only pages filed under a physical-business category
# carry one, so most rows come back without it.
# `instagram_business_account` is the id an ad creative needs before it can
# open an Instagram conversation, and there is no substitute for it: a
# Facebook page cannot receive an Instagram message on somebody's behalf,
# so a missing one is a channel that cannot be offered rather than one that
# degrades. Nested, so the sub-fields are named - asking for the edge alone
# answers with an id and nothing to recognise it by.
#
# `connected_instagram_account` is asked beside it because it is not the
# same account on every page - see ``PageDTO.connected_instagram_account``.
BASE_PAGE_FIELDS = (
    "id,name,access_token,tasks,leadgen_tos_accepted,location,"
    "instagram_business_account{id,username}"
)
PAGE_FIELDS = BASE_PAGE_FIELDS + ",connected_instagram_account{id,username}"

# What Meta answers when one field of a list is not allowed for this token:
# the whole read is refused, not the field. ``#100`` names the field,
# ``#10`` and ``#200`` the permission behind it.
_FIELD_REFUSALS: Final[frozenset[int]] = frozenset({10, 100, 200})

# The roles that let somebody run ads from a page. Meta lists an admin's
# tasks in full, so ADVERTISE is normally there on its own; MANAGE is
# accepted as well because it is the role that implies every other.
#
# A constant with a function rather than a check written twice: the Django
# layer stores the raw list and asks the same question of it days later,
# and two copies of this rule would disagree the day Meta adds a task.
ADVERTISING_TASKS: Final[frozenset[str]] = frozenset({"ADVERTISE", "MANAGE"})

# `last_fired_time` is the one worth having. A pixel that exists and has
# seen nothing for weeks is the commonest reason a conversion campaign
# spends its budget and reports no sales, and it costs nothing to read here
# rather than to discover after the money is gone.
PIXEL_FIELDS = "id,name,last_fired_time,is_unavailable"


def owes_payment(account_status: int) -> bool:
    """Whether this account is stopped over a bill it has not paid."""
    return account_status == UNSETTLED_STATUS


def may_run_ads(account_status: int) -> bool:
    """Whether this ad account can carry a campaign at all.

    Zero is "Meta did not say" and answers ``True``. Every caller of this
    treats an unread field as permission to carry on, for the same reason
    they do with a page's role: the alternative locks out accounts that
    work over a question nobody asked.
    """
    return account_status not in BLOCKED_ACCOUNT_STATUSES


def may_advertise(tasks: Sequence[str]) -> bool:
    """Whether this role can create ads and lead forms on the page.

    A page somebody was given ANALYZE on lists beside every other and then
    refuses the form with a permission error naming the page, which reads
    as a missing scope and is not one.

    An empty list is *not* answered here. It means Meta was never asked,
    and what to do about that is the caller's decision - see the callers,
    both of which treat "never asked" as permission to carry on.
    """
    return any(task in ADVERTISING_TASKS for task in tasks)


def list_ad_accounts(
    *, token: str, client: GraphClient | None = None
) -> list[AdAccountDTO]:
    """Every ad account this token can act on, from all three places.

    ``/me/adaccounts`` on its own is not the answer, though it reads like
    it. It lists the accounts the *person* holds a role on, and the
    commonest ad account in this market is one that person never got a
    personal role on: it was made inside a Business Manager, it belongs to
    the business, and administering the business is what grants access to
    it. Asked only the personal edge, Meta answers honestly with nothing,
    and a customer looking at their own account in Ads Manager is told on
    our screen that they have none.

    So the businesses are walked too - see ``BUSINESS_AD_ACCOUNT_EDGES``.
    The three lists overlap heavily and are merged on ``id``, first answer
    winning, because the fields asked for are the same everywhere.

    The personal edge is the one that may fail loudly. A caller told "no
    accounts" when Meta refused to say is the failure this whole function
    is about.
    """
    graph = client or GraphClient(token=token)
    try:
        rows = graph.get_all("me/adaccounts", fields=AD_ACCOUNT_FIELDS, limit=100)
        rows.extend(_business_ad_account_rows(graph))
    finally:
        if client is None:
            graph.close()

    return parsed_all(AdAccountDTO, _unique_by_id(rows))


def _business_ad_account_rows(graph: GraphClient) -> list[dict[str, Any]]:
    """The ad account rows reachable through this person's businesses.

    **Nothing here raises.** Every read in this function is an addition to
    the list the personal edge already answered, and each one can be
    refused for a reason that says nothing about the others: a token
    issued without ``business_management`` cannot list businesses at all,
    and a business somebody was added to as an analyst refuses its client
    list while answering its owned one. Letting any of those through would
    take away the accounts the personal edge found, which is exactly the
    gap this sweep exists to close, in a new place.

    Every refusal is logged with the edge that produced it rather than
    swallowed. An operator reading "this business refused its client list"
    beside a customer's short picker knows what they are looking at, and
    that line is the whole difference between this and a bare ``except``.
    """
    try:
        payload = graph.get(
            "me/businesses", fields=BUSINESS_FIELDS, limit=MAX_BUSINESSES
        )
    except MetaError as exc:
        logger.warning("businesses could not be listed: %s", exc)
        return []

    businesses = payload.get("data", [])
    # One page, deliberately, so ``get_all`` is the wrong tool here: it
    # refuses to return a truncated list, and a truncated list is exactly
    # what is being asked for. What it would refuse with instead is an
    # empty sweep for the one person who has more businesses than the
    # ceiling - the reader this whole function exists for.
    if payload.get("paging", {}).get("next"):
        logger.warning(
            "more than %d businesses; the rest were not swept", MAX_BUSINESSES
        )

    rows: list[dict[str, Any]] = []
    for business in businesses:
        business_id = str(business.get("id") or "")
        if not business_id:
            continue
        for edge in BUSINESS_AD_ACCOUNT_EDGES:
            try:
                rows.extend(
                    # Stamped with the business it was walked from, where
                    # the row did not carry one. ``business{id}`` is asked
                    # for on every edge and comes back only for a token
                    # allowed to read it - but an account reached *through*
                    # a business is owned by that business whether or not
                    # Meta repeats it in the row, and this is the walk that
                    # knows. Nothing is overwritten: a row that answered for
                    # itself keeps its own answer.
                    _owned_by(
                        graph.get_all(
                            f"{business_id}/{edge}",
                            fields=AD_ACCOUNT_FIELDS,
                            limit=100,
                        ),
                        business_id=business_id,
                    )
                )
            except MetaError as exc:
                logger.warning("%s/%s could not be listed: %s", business_id, edge, exc)
    return rows


def _owned_by(rows: list[dict[str, Any]], *, business_id: str) -> list[dict[str, Any]]:
    """Name the business these rows were reached through, where they do not.

    Only where they do not. A row Meta answered with its own ``business``
    keeps it: the walk knows which business it *asked*, and an account
    shared into that business by an agency belongs to the other one.
    """
    for row in rows:
        if not row.get("business"):
            row["business"] = {"id": business_id}
    return rows


def _unique_by_id(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per account id, in the order they were first seen.

    The personal edge is read first and therefore wins, which is the order
    that matters: a business edge answering the same account with a field
    missing must not replace it.

    A row with no id is **kept**, not quietly dropped. It cannot be deduped
    against anything, and it is a shape change - which the DTO one line
    later is built to refuse by name. Dropping it here would turn "Meta
    sent something we do not understand" into a picker one row short, and
    the whole point of :mod:`metaads.parsing` is that those two are not
    allowed to look alike.
    """
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for row in rows:
        account_id = str(row.get("id") or "")
        if account_id and account_id in seen:
            continue
        if account_id:
            seen.add(account_id)
        unique.append(row)
    return unique


def list_pixels(
    *, account_id: str, token: str, client: GraphClient | None = None
) -> list[PixelDTO]:
    """Every conversion pixel on one ad account.

    Per account rather than per person, unlike the two lists above: a pixel
    belongs to an ad account, so this can only be asked once the customer
    has chosen which account they run through.

    Unavailable pixels are listed too, for the same reason closed ad
    accounts are: one the customer can see in Events Manager and cannot
    find here looks like our bug, not like a pixel Meta has disabled.
    """
    graph = client or GraphClient(token=token)
    try:
        rows = graph.get_all(f"{account_id}/adspixels", fields=PIXEL_FIELDS, limit=100)
    finally:
        if client is None:
            graph.close()

    return parsed_all(PixelDTO, rows)


# How far back Meta will answer for a pixel's own figures. Seven days, and
# it is the provider's window rather than a choice: asking for a month
# returns the same week, silently, so a caller that believed otherwise
# would report "this site has never sent a purchase" about a site that
# sends one every fortnight.
PIXEL_STATS_DAYS: Final = 7

# What the figures are grouped by. Meta can group a pixel's activity
# several ways - by URL, by device, by the event's own name - and only the
# last answers the question a campaign needs: which events does this site
# actually send.
EVENT_AGGREGATION: Final = "event"


def pixel_events(
    *, pixel_id: str, token: str, client: GraphClient | None = None
) -> list[PixelEventRow]:
    """Which events this pixel has reported in the provider's own window.

    The one honest source for what a website is wired up to send. A
    conversion campaign is bought against an event by name, and a name the
    site never fires buys nothing at all - the ad set delivers, spends, and
    reports no results, which reads on every screen like a campaign that
    has not started.

    Summed across whatever buckets Meta returns, because it answers in
    slices of time and the question is not "when" but "does this site send
    this at all". Newest first is not attempted for the same reason.

    Empty for a pixel that has fired nothing, and empty for one Meta has no
    figures for. The two are the same answer here and are told apart one
    layer up, by whether the sweep ever ran.
    """
    graph = client or GraphClient(token=token)
    try:
        rows = graph.get_all(
            f"{pixel_id}/stats",
            aggregation=EVENT_AGGREGATION,
        )
    finally:
        if client is None:
            graph.close()

    counted: dict[str, int] = {}
    for row in rows:
        for entry in row.get("data") or ():
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("value") or "").strip()
            if not name:
                continue
            counted[name] = counted.get(name, 0) + _times(entry.get("count"))

    return [
        PixelEventRow(event=name, count=times)
        for name, times in sorted(counted.items(), key=lambda pair: -pair[1])
    ]


def _times(value: object) -> int:
    """How many, as an integer. Meta answers in strings here and in numbers
    elsewhere on the same object, so neither is assumed.
    """
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return 0


def list_pages(*, token: str, client: GraphClient | None = None) -> list[PageDTO]:
    """Every page this token can see, each with its own token.

    The page tokens come back in this one response. Asking for them later,
    per page, is both slower and a second chance for the user token to have
    expired in between.
    """
    graph = client or GraphClient(token=token)
    try:
        try:
            rows = graph.get_all("me/accounts", fields=PAGE_FIELDS, limit=100)
        except MetaAPIError as exc:
            # The second Instagram field is the newest ask on the one read
            # every screen stands on. Refused, it costs that field and not
            # the page list.
            if exc.code not in _FIELD_REFUSALS:
                raise
            logger.warning("page list refused the full field set: %s", exc)
            rows = graph.get_all("me/accounts", fields=BASE_PAGE_FIELDS, limit=100)
    finally:
        if client is None:
            graph.close()

    return parsed_all(PageDTO, rows)


# Where an advertiser goes when Meta is holding their account. Not the
# Graph API host: this is a URL handed to a browser, like the OAuth dialog
# and the lead-terms page, and the account it opens on has to be named or
# somebody with three accounts confirms the wrong one.
ADS_MANAGER_URL: Final = "https://adsmanager.facebook.com/adsmanager/manage/campaigns"


def manager_url(account_id: str = "") -> str:
    """Ads Manager, opened on one account when we know which."""
    if not account_id:
        return ADS_MANAGER_URL
    return f"{ADS_MANAGER_URL}?{urlencode({'act': account_id.removeprefix('act_')})}"


# Where an advertiser adds a card or settles a bill. Meta's billing hub,
# opened on one ad account: checked by hand on 2026-10-06 - the address
# below lands on that account's payment settings, and Meta fills in the
# rest of the query itself. Undocumented, like the asset library below.
BILLING_URL: Final = (
    "https://business.facebook.com/latest/billing_hub/payment_settings/"
)


def billing_url(account_id: str = "") -> str:
    """The billing page, for one ad account when we know which.

    The id matters for the reason it does in :func:`manager_url`: somebody
    with two accounts who opens the bare page pays the other one's bill.
    """
    if not account_id:
        return BILLING_URL
    return f"{BILLING_URL}?{urlencode({'asset_id': account_id.removeprefix('act_')})}"


# Two addresses Meta's own error reference sends advertisers to: the
# account's standing (a restricted or disabled advertiser appeals there)
# and the identity check political and social-issue ads require.
ACCOUNT_QUALITY_URL: Final = "https://www.facebook.com/accountquality"
IDENTITY_URL: Final = "https://www.facebook.com/id"


# The ad account's own library inside Business Manager, which is where a
# file uploaded by hand becomes something an ad here can use.
#
# **Undocumented, and transcribed from a working address rather than
# guessed.** Meta publishes no URL for this - its help pages describe the
# menu path and nothing else - so what is written here is the address a
# browser sits on while uploading, copied rather than derived.
#
# ``global_scope_id`` repeats the business id, which is what that address
# carries. It is Business Manager's scope for the page being opened, and
# leaving it out is not known to work.
ASSET_LIBRARY_URL: Final = "https://business.facebook.com/asset_library/ad_accounts"


def media_library_url(account_id: str = "", business_id: str = "") -> str:
    """Where an advertiser puts a picture that an ad here can then use.

    Meta's own media library holds exactly what ``/act_<id>/adimages`` and
    ``/act_<id>/advideos`` answer with, which is why this is the one place
    worth sending somebody whose file is too big for the tile on our own
    screen: what they upload there is on the account, and the picker reads
    it back on the next refresh.

    **Both ids or neither.** The library is addressed inside a business
    portfolio, so without one there is no library address to give - and a
    link that lands on an error in front of somebody who was told to click
    it is worse than no link. That case falls back to Ads Manager, and the
    copy beside it names the menu step.

    The account still has to be right: an image hash is minted per ad
    account, so a picture uploaded to the wrong one cannot be used by an ad
    on this one - and somebody with two accounts who opens the bare URL is
    given whichever Meta remembers.
    """
    if not business_id or not account_id:
        return manager_url(account_id)

    return f"{ASSET_LIBRARY_URL}?" + urlencode(
        {
            "business_id": business_id,
            "global_scope_id": business_id,
            "ad_account": account_id.removeprefix("act_"),
        }
    )
