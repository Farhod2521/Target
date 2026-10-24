"""Daily performance, as Meta reports it.

One call answers a whole date range: ``time_increment=1`` makes Meta split
its own aggregate into one row per day, which is the difference between a
ninety-day backfill costing one request and costing ninety.

Two things about this endpoint are worth knowing before reading anything
here, because both are silent and both cost money.

**Spend is in whole currency.** ``"12.34"`` means twelve dollars and
thirty-four cents. Budgets on the very same object are the opposite -
``"1234"``, minor units, also as a string - so the two are indistinguishable
in a payload and differ by a factor of a hundred. Every amount that leaves
this module has been through :func:`adskit.money.to_minor` with the
account's own currency.

**Leads live inside ``actions``.** There is no ``leads`` field. The count is
one entry in a list of every action type the ad produced, and which entry
depends on where the form lives - an instant form reports ``lead``, a form
on the advertiser's own site reports a pixel action under a different name.
Reading the wrong one reports zero leads on a campaign that is working.

Returns raw rows. The adapter parses; this module asks.
"""

import json
import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from typing import Any, Final

from metaads.client import GraphClient
from metaads.errors import MetaAPIError

# What one row has to carry. ``account_currency`` is the reason spend can be
# converted at all: the amount is in whole currency and only the account
# says which one, so asking for the figure without it is asking for a number
# with no unit.
INSIGHT_FIELDS: Final = (
    "date_start,date_stop,account_currency,"
    "campaign_id,campaign_name,adset_id,adset_name,ad_id,ad_name,"
    "spend,impressions,reach,clicks,frequency,ctr,cpm,cpc,actions,"
    # What the click actually was. ``clicks`` counts every click on the
    # unit, including the ones that expand the caption or open the page's
    # profile; ``inline_link_clicks`` counts the ones that went where the
    # advertiser was paying for them to go. The gap between the two is a
    # creative that is being poked at rather than acted on, and it is
    # invisible from ``ctr`` alone.
    #
    # The ``unique_`` pair counts people instead of events. One person
    # clicking six times is six clicks and one unique click, which is the
    # difference between an ad that interests a crowd and one that a
    # handful of people keep tapping.
    "unique_clicks,inline_link_clicks,unique_inline_link_clicks,"
    "outbound_clicks,"
    # What each kind of result cost and what it was worth. Both are arrays
    # keyed by action type - the same shape as ``actions`` - and both are
    # read the same way it is.
    "cost_per_action_type,action_values,"
    # How far into the video people got. The one measure of a creative that
    # does not depend on anybody clicking, and the earliest warning that an
    # ad has stopped holding attention: the fall shows here before it shows
    # in the cost per lead.
    #
    # Every one of these is absent on an image ad, which is the normal case
    # and not a gap.
    "video_play_actions,video_thruplay_watched_actions,"
    "video_p25_watched_actions,video_p50_watched_actions,"
    "video_p75_watched_actions,video_p100_watched_actions,"
    # How many people the provider estimates would remember the advert.
    #
    # The result of an awareness campaign, and the figure the screen
    # promises in words: it tells the owner of such a campaign that its
    # result is "the number of people who remember you", and this is what
    # goes there.
    #
    # Absent on every campaign bought for anything else, which is the
    # ordinary case and not a gap.
    "estimated_ad_recallers,"
    # Which attribution window the **account** is set to.
    #
    # Not a figure. It is what makes every figure above checkable: this
    # product sends its own window on every request, and an account set to
    # a different one in Ads Manager will disagree with our lead counts for
    # ever with nothing on either screen to explain it. Asked for on the
    # request that was going to be made anyway.
    "attribution_setting,"
    # What the ad set is bought for, which is what says where its leads
    # are counted - see ``WEBSITE_LEAD_ACTIONS``.
    "optimization_goal"
)

# Which conversions count towards this account, and over how long.
#
# **Sent explicitly, and that is the whole point of it.** Meta has a
# default - seven days after a click, one day after a view - and accepting
# it without saying so anywhere leaves a figure whose basis is implicit,
# which is a figure nobody can check: two people comparing our cost per
# lead with Ads Manager's could disagree for a fortnight before either of
# them thought to ask what window each was using.
#
# The value chosen is Meta's own default, deliberately. The point of this
# constant is to stop the assumption being silent, not to change what the
# numbers mean - a different window would restate every figure this product
# has ever stored, and the rows already in the table were gathered under
# this one.
#
# It affects **actions only**: leads, their costs and their values. Spend,
# impressions and clicks are counted when they happen and no window applies.
#
# Changing it is therefore a decision with a migration attached. See the
# note in ``apps.metrics.services.sync_insights``.
ATTRIBUTION_WINDOWS: Final[tuple[str, ...]] = ("7d_click", "1d_view")

# The same pair in the spelling Meta answers with.
#
# ``attribution_setting`` comes back as one underscore-joined string -
# ``"7d_click_1d_view"`` - where the request takes a JSON array. They are
# the same fact in two shapes, and the join is written once here rather
# than at the call site so the two cannot drift into disagreeing about a
# window they both describe.
#
# **Not what the comparison uses.** Meta answers with the same pair in its
# own order, so this string and the account's are equal only by luck - see
# :func:`differing_attribution`.
ATTRIBUTION_ASKED: Final = "_".join(ATTRIBUTION_WINDOWS)

# Where one window ends and the next begins inside that joined string.
#
# It cannot be split on the underscore: the windows contain one each, so
# ``"1d_view_7d_click"`` would come apart into four atoms that no longer
# say which view goes with which day. Every window Meta names starts with
# a number of days, and that is the only boundary the string offers.
_NEXT_WINDOW: Final = re.compile(r"_(?=\d)")


def _windows(setting: str) -> frozenset[str]:
    """The windows in one of Meta's joined settings, order thrown away.

    A set because the order carries nothing: an account reporting
    ``"1d_view_7d_click"`` is set to exactly what ``"7d_click_1d_view"``
    asks for, and no figure differs between them.
    """
    return frozenset(_NEXT_WINDOW.split(setting))


def differing_attribution(setting: object) -> str:
    """The account's own attribution window, but only if it is not ours.

    Empty when the two agree and empty when the provider said nothing,
    which are both "no discrepancy to report" and neither is worth a
    sentence on a screen.

    The comparison lives here because this is the only place that knows
    which window was asked for. A caller handed the raw setting would have
    to know the request's own constant to make anything of it, and that is
    Meta's vocabulary crossing a boundary to answer a question the boundary
    can answer itself.

    ``default`` is Meta's word for "whatever the account is set to", and it
    is treated as agreement: it is what an account that has never been
    changed answers, and this pair is Meta's own default.

    **Compared as a set, never as a string.** Meta answers with its own
    ordering, and for this pair that ordering is the reverse of the one the
    request sends: an account set to precisely what we ask for reports
    ``"1d_view_7d_click"`` against our ``"7d_click_1d_view"``. Matched on
    the string, every such account - which is most of them, this being
    Meta's default - would be told its figures were gathered under a window
    it had not chosen, and sent to look for a discrepancy that does not
    exist. The reverse mistake is the one to avoid: ``1d_click``
    and ``7d_view`` share every atom with our pair and are a different
    window, so the split has to keep each window whole.
    """
    found = str(setting or "").strip()
    if not found or found == "default":
        return ""
    if _windows(found) == frozenset(ATTRIBUTION_WINDOWS):
        return ""
    return found


# How Meta rates one ad against the ads it competes with: the creative, the
# engagement it earns, and the conversions it produces.
#
# **Only at ad level.** They are a judgement about a creative and a
# campaign is not one; asking for them on a campaign or ad set breakdown
# returns an error rather than an empty column. So they are appended to the
# field list for one level and left off the other two, which is also why
# they are a separate constant.
#
# Asked for on the request that was going to be made anyway. No extra call,
# and the answer arrives per day because ``time_increment=1`` splits the
# range - which is what gives the figure a history instead of a current
# value that is overwritten nightly.
AD_RANKING_FIELDS: Final = (
    "quality_ranking,engagement_rate_ranking,conversion_rate_ranking"
)

# The level whose rows carry a ranking. Meta's word, not the domain's - the
# adapter is what maps a domain level onto it.
RANKED_LEVEL: Final = "ad"

# Meta pages insights, and a ninety-day range at ad set level on a busy
# account is a lot of rows. Larger pages mean fewer round trips against a
# rate limit shared with everything else this product does.
PAGE_SIZE: Final = 500

# How deep an insights read may page before it gives up and says so.
#
# The client's own default is twenty-five, which is right for the small
# edges it was written for - an account list, a page list - and wrong here
# by an order of magnitude. A single day of one ad set is up to twenty-one
# rows on the age-and-gender cut, so a thirty-day first read on an account
# with thirty ad sets is around sixteen thousand rows: thirty-three pages,
# eight past that default.
#
# Two hundred is not a data limit and is not meant to be one. At five
# hundred rows a page it is a hundred thousand rows, far past anything a
# real window produces - which makes it what a ceiling should be: a guard
# against a cursor pointing at itself, and nothing else. What actually
# bounds a large read is the usage guard in ``GraphClient``, which stops at
# eighty percent of the account's call budget and says why.
MAX_INSIGHT_PAGES: Final = 200

# Which ``actions`` entry is a lead.
#
# Four spellings, because Meta files a lead under several names and not
# every name is in every answer. ``leadgen_grouped`` and
# ``onsite_conversion.lead_grouped`` are two generations of the instant
# form on its own; accounts answer with one or the other. ``lead`` is every
# lead the ad produced - the instant form *and* a form on the advertiser's
# own website, added together. The pixel one is the website form on its own.
#
# **The instant form first.** It is what Ads Manager's results column counts
# for a form campaign, and what reaches this product by webhook. ``lead``
# read first put the website's leads into the same count: one form
# campaign's day read 36 where 26 people filled the form and 10 more were a
# pixel firing on the site afterwards - every price a quarter too cheap, and
# a quarter of the leads "missing" that had never been form leads at all.
#
# The region cut answers the instant form alone, so it reads the same name
# as every other row now.
#
# Read in order and the first match wins: they overlap, and adding them
# together counts one submission twice.
LEAD_ACTIONS: Final[tuple[str, ...]] = (
    "onsite_conversion.lead_grouped",
    "leadgen_grouped",
    "lead",
    "offsite_conversion.fb_pixel_lead",
)

# The same question for an ad set bought for leads on the advertiser's own
# website, and **the ad set's goal decides which list a row reads, never the
# names one day happens to carry.**
#
# A website ad set's rows usually hold no form name and the list above falls
# through to ``lead`` on its own. But Meta files a stray instant-form lead
# against one now and then, and on that day the form name wins: one such
# campaign's day read 1 where 1,175 people had filled the site's form, and
# its month added up to a figure that matched neither of Ads Manager's
# columns. ``lead`` first is what Ads Manager's "Leads" column counts.
WEBSITE_LEAD_ACTIONS: Final[tuple[str, ...]] = (
    "lead",
    "offsite_conversion.fb_pixel_lead",
)

# The ``optimization_goal`` a row carries when its ad set is bought for
# conversions on a website. Meta answers it on ad set and ad rows; a
# campaign's row says "Unknown Optimization Goal", and reads the list above
# like any other - see ``apps.metrics.services.store_metrics`` for how the
# campaign's count is kept in step with its ad sets.
WEBSITE_GOALS: Final = frozenset({"OFFSITE_CONVERSIONS"})

# Which ``actions`` entry is a result that is **not** a lead.
#
# Read into its own figure and never added to the lead count. A messaging
# conversation and a form submission are both "a result" and they are not
# the same object: one has a name and a telephone number in this product's
# own table and can be marked qualified, the other lives in an inbox
# nothing here reads. Folding them together would put a number into the
# cost per lead that no lead is behind.
#
# **The fallback, not the read.** A row's result is Meta's own ``results``
# field - see :func:`meta_result_count` - and this list answers only for a
# row that came without it. First match wins, which is exactly why it is
# not the read: an ad set bought for calls whose viewers also wrote a
# message reports both, and the first name here is the conversation.
#
# The call name is the one Ads Manager's own results column reads for an
# ad set bought for calls, ``click_to_call_native_call_placed``, before the
# confirmation Meta also files.
RESULT_ACTIONS: Final[tuple[str, ...]] = (
    "onsite_conversion.messaging_conversation_started_7d",
    "onsite_conversion.total_messaging_connection",
    "click_to_call_native_call_placed",
    "click_to_call_call_confirm",
)

# Meta's own count of what an ad set is judged on, in its own field - the
# number in Ads Manager's "Results" column, under an indicator that names
# it: ``actions:<action type>`` for an action, ``profile_visit_view`` or
# ``total_profile_visits`` for a profile visit, ``reach`` or
# ``estimated_ad_recallers`` for a count of people.
#
# **The one result that is not in ``actions``.** A visit to the Instagram
# profile appears under no action type - read off live ad sets, every one
# of them reported it only here, as ``{"indicator": ..., "values":
# [{"value": "1479"}]}``. Two indicators, by where the advert sends people:
# the profile alone, or the profile and the Facebook page together. The
# second counts more than the link clicks on the same row, so link clicks
# are not a stand-in for either.
#
# Asked for beside every other field rather than in a request of its own,
# which would spend the account's rate limit twice for one number - see
# :func:`fetch_insights` for what happens where Meta refuses it.
RESULTS_FIELD: Final = "results"
PROFILE_VISIT_INDICATORS: Final = frozenset(
    {"profile_visit_view", "total_profile_visits"}
)
# How an action-based result names itself in that field.
ACTION_INDICATOR: Final = "actions:"
# How a ``results`` value names the ad set's own attribution setting - the
# figure Ads Manager prints - beside the one value per window asked for.
DEFAULT_WINDOW: Final = "default"
# Meta's code for a parameter it does not accept.
_INVALID_PARAMETER: Final = 100

# What ``outbound_clicks`` files its count under. One entry, one name -
# but read through the same reader as everything else here, because a
# hard-coded index is what breaks the day a second entry appears.
OUTBOUND_ACTION: Final = "outbound_click"

# What people did with the post itself, in the same ``actions`` array every
# other count here comes out of.
#
# **Not one extra request.** These arrive in every insights response
# already. Reading them costs nothing at the provider and moves the rate
# limit not at all - which is what makes them worth four columns.
#
# Why an advertiser cares: this is the one "did people like it" signal the
# owner of a shop understands without being taught, and the only one that
# arrives without money being spent on a click. A comment is also a job -
# somebody asked a question in public and nobody answered it.
#
# Meta's spellings, each read first-match-wins like every other array here:
#
# * ``post_reaction`` is every reaction, not only the thumb;
# * ``comment`` is a comment on the ad's post;
# * ``post`` is a share. Meta's name for it is the bare word, which is
#   exactly the sort of thing a hard-coded index gets wrong;
# * ``onsite_conversion.post_save`` is somebody saving it to come back to.
REACTION_ACTIONS: Final[tuple[str, ...]] = ("post_reaction",)
COMMENT_ACTIONS: Final[tuple[str, ...]] = ("comment",)
SHARE_ACTIONS: Final[tuple[str, ...]] = ("post",)
SAVE_ACTIONS: Final[tuple[str, ...]] = ("onsite_conversion.post_save",)

# How far people got past the click and past the first frame, out of the
# same ``actions`` array.
#
# ``landing_page_view`` is somebody whose browser actually loaded the page
# the advert sent them to. A link click that left before the page arrived
# is not one, so the gap between the two is the site itself - slow, broken,
# or not the page the advert promised. Meta can only count it where its
# pixel is on that page: a site without one reports nought, and that is a
# fact about the site's tagging rather than about its visitors.
#
# ``video_view`` is Meta's three-second view, and it is **not**
# ``video_play_actions``: a play starts the moment the video is on screen,
# a view is somebody who stayed for three seconds. Views over impressions
# is how often the opening stops the scroll.
LANDING_PAGE_ACTIONS: Final[tuple[str, ...]] = ("landing_page_view",)
VIDEO_VIEW_ACTIONS: Final[tuple[str, ...]] = ("video_view",)


def fetch_insights(
    *,
    account_id: str,
    since: date,
    until: date,
    level: str,
    token: str,
    client: GraphClient | None = None,
) -> list[dict[str, Any]]:
    """Every day in the range, one row per object per day.

    The range is **inclusive at both ends** and expressed in the ad
    account's own timezone, which is the boundary Meta aggregated on. This
    module does not know that timezone and does not need to: the caller
    passes dates, Meta answers with ``date_start``, and converting either
    one into somebody else's day is how a dashboard stops matching the
    provider's own.

    ``level`` travels as the provider's word. It is one of ``account``,
    ``campaign``, ``adset`` or ``ad``, and the adapter is what maps a domain
    level onto it - a service naming ``"adset"`` here would have written
    Meta's vocabulary into the domain.
    """
    with _session(client, token) as graph:
        try:
            return _read_days(
                graph,
                account_id=account_id,
                fields=f"{fields_for(level)},{RESULTS_FIELD}",
                level=level,
                since=since,
                until=until,
            )
        except MetaAPIError as exc:
            # The profile visit count is one field, and a version or an
            # account that refuses it must not take every other figure of
            # the day down with it. Asked again without it, once; anything
            # else that is wrong fails the second request the same way.
            if type(exc) is not MetaAPIError or exc.code != _INVALID_PARAMETER:
                raise
            return _read_days(
                graph,
                account_id=account_id,
                fields=fields_for(level),
                level=level,
                since=since,
                until=until,
            )


def _read_days(
    graph: GraphClient,
    *,
    account_id: str,
    fields: str,
    level: str,
    since: date,
    until: date,
) -> list[dict[str, Any]]:
    """One insights read, a row per object per day."""
    return list(
        graph.get_all(
            f"{account_id}/insights",
            fields=fields,
            level=level,
            time_increment=1,
            time_range=as_time_range(since=since, until=until),
            action_attribution_windows=json.dumps(list(ATTRIBUTION_WINDOWS)),
            limit=PAGE_SIZE,
            max_pages=MAX_INSIGHT_PAGES,
        )
    )


# What a range's people count needs: the object, the range it is about, and
# the two figures that count people rather than events.
PEOPLE_FIELDS: Final = (
    "date_start,date_stop,campaign_id,adset_id,ad_id,reach,estimated_ad_recallers"
)


def fetch_people_counts(
    *,
    account_id: str,
    ranges: list[tuple[date, date]],
    level: str,
    token: str,
    client: GraphClient | None = None,
) -> list[dict[str, Any]]:
    """Reach and the ad recall estimate over whole ranges, one row per range.

    No ``time_increment``: that is the whole point. With it Meta splits the
    range into days and counts each day's people separately, so the same
    person on five days comes back five times; without it Meta counts the
    range once, which is the number Ads Manager prints for it.

    ``time_ranges`` asks for every range in the one request, and each row
    names the range it answers in ``date_start`` and ``date_stop``.
    """
    with _session(client, token) as graph:
        return list(
            graph.get_all(
                f"{account_id}/insights",
                fields=PEOPLE_FIELDS,
                level=level,
                time_ranges=json.dumps(
                    [
                        {"since": since.isoformat(), "until": until.isoformat()}
                        for since, until in ranges
                    ]
                ),
                limit=PAGE_SIZE,
                max_pages=MAX_INSIGHT_PAGES,
            )
        )


def fetch_action_totals(
    *,
    account_id: str,
    since: date,
    until: date,
    token: str,
    client: GraphClient | None = None,
) -> list[dict[str, Any]]:
    """Every action type the account reported over a range, as Meta sent it.

    One row for the whole account and the whole range - no
    ``time_increment`` - so the answer is the list of names and nothing
    else. It exists for a question no document settles: which names Meta
    actually files this account's events under. The action-type reference
    lists what may appear; only an account says what does, and a parser
    written against the reference reads nought off a name that never comes.

    Unparsed on purpose, attribution columns included. The caller is a
    person looking for a name they do not know yet.
    """
    with _session(client, token) as graph:
        rows = list(
            graph.get_all(
                f"{account_id}/insights",
                fields="actions",
                level="account",
                time_range=as_time_range(since=since, until=until),
                action_attribution_windows=json.dumps(list(ATTRIBUTION_WINDOWS)),
                limit=PAGE_SIZE,
            )
        )
    return [
        entry
        for row in rows
        for entry in (row.get("actions") or [])
        if isinstance(entry, dict)
    ]


def fields_for(level: str) -> str:
    """What to ask for at one level.

    The base list everywhere, plus the three ranking verdicts on ads. The
    split is not a preference: Meta refuses the ranking fields at any other
    level, and a request that asked for them everywhere would return an
    error for two levels out of three.
    """
    if level == RANKED_LEVEL:
        return f"{INSIGHT_FIELDS},{AD_RANKING_FIELDS}"
    return INSIGHT_FIELDS


def action_value(entries: object, names: tuple[str, ...]) -> str:
    """The first of ``names`` this array reports, as Meta sent it.

    The one reader for every array Meta keys by action type - ``actions``,
    ``cost_per_action_type``, ``action_values`` - because they have the
    same shape and the same trap. **First match wins and nothing is added
    together**: the names overlap, and a lead counted under two of them is
    one submission counted twice.

    A string comes back rather than a number because the three arrays are
    not the same kind of thing. One counts, two are money in whole
    currency, and converting money without knowing the currency is how a
    figure ends up a hundredfold wrong. The caller knows which it asked
    for.

    Empty when the array is absent or names nothing asked for, which is the
    ordinary answer for a day nobody filled a form in.
    """
    if not isinstance(entries, list):
        return ""

    by_type = {
        str(row.get("action_type", "")): row.get("value")
        for row in entries
        if isinstance(row, dict)
    }
    for name in names:
        if name in by_type:
            value = by_type[name]
            return "" if value is None else str(value)
    return ""


def lead_actions_for(goal: object) -> tuple[str, ...]:
    """Which ``actions`` names count as a lead for a row with this goal.

    ``goal`` is the row's ``optimization_goal`` as Meta sent it, absent
    included - a row without one reads the instant form first.
    """
    return WEBSITE_LEAD_ACTIONS if goal in WEBSITE_GOALS else LEAD_ACTIONS


def lead_count(actions: object, *, goal: object) -> int:
    """How many leads one row reports, whatever Meta called them.

    Zero when the list is absent, which is the normal answer for a day an ad
    ran and nobody filled anything in - not a failure and not a gap.
    """
    return _as_int(action_value(actions, lead_actions_for(goal)))


def result_count(actions: object) -> int:
    """How many results of a kind this product holds no table for.

    A conversation on the provider's own surface, a confirmed telephone
    call. Zero for a form campaign, which reports its result as a lead and
    is counted there.
    """
    return _as_int(action_value(actions, RESULT_ACTIONS))


def meta_result_count(results: object) -> int | None:
    """Ads Manager's "Results" for one row, where it can be added up.

    An action or a profile visit is an event and a day's count adds to the
    next day's. A count of people - ``reach``, ``estimated_ad_recallers``
    - does not: the same person on two days is one person, so a row
    carrying one of those answers ``None`` here, as does a row Meta sent
    without the field or without a figure in it.
    """
    if not isinstance(results, list):
        return None
    for entry in results:
        if not isinstance(entry, dict):
            continue
        indicator = str(entry.get("indicator", ""))
        values = entry.get("values")
        if values and (
            indicator.startswith(ACTION_INDICATOR)
            or indicator in PROFILE_VISIT_INDICATORS
        ):
            return result_value(values)
    return None


def profile_visit_count(results: object) -> int:
    """How many Instagram profile visits one row reports, from ``results``.

    Zero for every ad set judged on anything else - its indicator names
    that other thing - and for a row Meta sent without the field.
    """
    if not isinstance(results, list):
        return 0
    for entry in results:
        if (
            isinstance(entry, dict)
            and entry.get("indicator") in PROFILE_VISIT_INDICATORS
        ):
            return result_value(entry.get("values")) or 0
    return 0


def result_value(values: object) -> int | None:
    """The count Ads Manager prints, out of one ``results`` entry's values.

    **Not the first value.** Because every request names its attribution
    windows, Meta answers ``results`` with one value per window and one
    for the ad set's own setting, each labelled::

        [{"value": "5", "attribution_windows": ["7d_click"]},
         {"value": "7", "attribution_windows": ["1d_view"]},
         {"value": "12", "attribution_windows": ["default"]}]

    The first is the click window alone. Read as the count, an ad set with
    twelve conversations in Ads Manager showed five here - every view-through
    result missing, on every row. ``default`` is the one Ads Manager shows.

    Never a sum: the windows overlap, and adding them counts one result
    twice the day Meta files it under both. A row with no labels - Meta's
    shape when no window was named - is a single value and read as one.

    ``None`` when every value is labelled and none is ``default``: then no
    value here is the figure, and the caller falls back to ``actions``,
    whose plain ``value`` is the ad set's own setting.
    """
    if not isinstance(values, list):
        return None
    entries = [row for row in values if isinstance(row, dict)]
    for row in entries:
        if DEFAULT_WINDOW in (row.get("attribution_windows") or ()):
            return _as_int(row.get("value"))
    for row in entries:
        if not row.get("attribution_windows"):
            return _as_int(row.get("value"))
    return None


def action_count(entries: object, names: tuple[str, ...]) -> int:
    """The first of ``names`` this array reports, as a whole number.

    :func:`action_value` with the conversion the counting callers all need.
    Six copies of ``_as_int(action_value(...))`` would be five chances to
    write one of them without the conversion and store a string in an
    integer column.

    Zero when the array is absent or names nothing asked for, which is the
    ordinary answer for a day nobody reacted to anything.
    """
    return _as_int(action_value(entries, names))


def single_value(entries: object) -> int:
    """The count out of one of Meta's single-entry arrays.

    The video fields and ``outbound_clicks`` are arrays of the same shape
    as ``actions``, but with one entry in them - Meta files a plain count
    under an action type rather than sending a number. Read as "the first
    entry", not as a sum: a sum would be right today and would silently
    double-count the day Meta adds a second row.

    Zero when the field is absent, which is every image ad for every video
    field and is not a gap.
    """
    if not isinstance(entries, list):
        return 0
    for row in entries:
        if isinstance(row, dict):
            return _as_int(row.get("value"))
    return 0


def as_time_range(*, since: date, until: date) -> str:
    """``time_range`` as Meta takes it: a JSON object in a query string.

    Public because the breakdown request beside this one has to encode the
    range the same way. Two spellings of the same window is how a summary
    and its own segments end up covering different days.

    Encoded here rather than passed as two parameters because ``since`` and
    ``until`` on their own mean something different to this endpoint - they
    are a *relative* window, and mixing the two spellings returns a range
    nobody asked for.
    """
    return json.dumps({"since": since.isoformat(), "until": until.isoformat()})


def _as_int(value: object) -> int:
    """Meta sends counts as strings, and sometimes as decimal ones."""
    if value is None:
        return 0
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return 0


@contextmanager
def _session(client: GraphClient | None, token: str) -> Iterator[GraphClient]:
    """One connection, closed only if this module opened it."""
    graph = client or GraphClient(token=token)
    try:
        yield graph
    finally:
        if client is None:
            graph.close()
