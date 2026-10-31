"""The reads that answer "what is available", before anything is built.

Interest names, the account's existing images and videos, the page's own
posts, the Instagram account's posts, and how many people a spec would
reach. Five questions the ad builder has to ask before it can offer a
choice.

Everything here returns **raw rows**, deliberately. Every other module in
this package parses into a DTO, because a DTO is the boundary that keeps
Meta's vocabulary out of the domain. These are different: their purpose is
to find out what Meta actually sends, and a parser written against a guess
would quietly drop the very field that turns out to matter. A DTO comes
once the shape is known, in the code that consumes it.

Nothing here writes. Every call is a GET, so running all of them against a
live account costs nothing and changes nothing.
"""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Final

from metaads.client import GraphClient

# What a searched interest carries. ``audience_size_lower_bound`` and its
# upper twin replaced the single ``audience_size`` field; both are asked
# for so that an account still answering the old way is visible rather than
# silently empty.
INTEREST_FIELDS: Final = (
    "id,name,audience_size_lower_bound,audience_size_upper_bound,path,topic"
)

# Enough to show a picture and to send it again later. ``hash`` is the
# identifier a creative refers to - not ``id``, which is the odd one out in
# Meta's own model. ``account_id`` says whose picture it is: the edge also
# lists pictures owned elsewhere, and a creative cannot use those - see
# ``metaads.creatives.belongs_to``.
IMAGE_FIELDS: Final = "hash,name,url,permalink_url,width,height,created_time,account_id"
# Where a library image is shown. ``creatives`` is Meta's list of the ad
# creatives carrying it - including ones made in Ads Manager, which no
# mirror of ours has ever seen - so it is the question a delete asks first.
IMAGE_USAGE_FIELDS: Final = "hash,creatives"
VIDEO_FIELDS: Final = "id,title,description,picture,source,created_time,length"
POST_FIELDS: Final = "id,message,created_time,full_picture,permalink_url"
CREATIVE_FIELDS: Final = "id,name,object_story_spec,thumbnail_url,status"

# What an Instagram post answers with. A different vocabulary from the two
# lists above and not a variation on them: this is the IG Media node, where
# the file is ``media_url`` and there is no hash anywhere.
#
# ``media_url`` is the field the whole Instagram route rests on. An image
# has to arrive at ``/act_<id>/adimages`` as base64 bytes, because that edge
# takes no URL of any kind - so the file has to be fetched from here first.
# It is a signed CDN link and it expires, which is why nothing stores it:
# it is read again at the moment it is used.
#
# ``media_product_type`` separates a feed post from a reel and from media
# that only ever existed as an ad - the last of which would be a confusing
# thing to offer somebody as "your Instagram posts".
#
# ``boost_eligibility_info`` has to be on the *list* rather than read per
# post, and the reason is arithmetic: a sweep over an account
# with a hundred posts would otherwise make a hundred extra calls to find
# out which of them can be advertised.
#
# What it answers is a real refusal and not a warning. A reel whose audio
# is licensed comes back with ``eligible_to_boost: false`` and a reason in
# Meta's own words - and the file is still downloadable, so a picker that
# read only ``media_url`` would offer a video that gets the finished ad
# rejected. The reason text is English and for the log; the screen says its
# own sentence.
IG_MEDIA_FIELDS: Final = (
    "id,caption,media_type,media_product_type,media_url,permalink,"
    "thumbnail_url,timestamp,boost_eligibility_info"
)

# What one post is asked on its own, and both are here for the same reason:
# neither is worth a hundred extra rows on a sweep.
#
# ``children`` is asked for even though a carousel does **not** need it.
# The documentation implies the parent carries no file; a live
# account says otherwise - Meta answers with one representative frame,
# tagged ``CAROUSEL_ITEM.best_image_urlgen`` in the URL, which is its own
# pick rather than ours. The edge stays here because it is the only way to
# see the other slides, and choosing between "Meta's favourite" and "all of
# them" is a product decision that needs both answers visible.
#
# ``fields`` stays a parameter on both calls regardless. Meta refuses a
# whole request over one name it does not recognise - ``#100 nonexistent
# field`` - and the next API version is where that is found out.
IG_MEDIA_DETAIL_FIELDS: Final = (
    f"{IG_MEDIA_FIELDS},username,is_shared_to_feed,"
    "children{id,media_type,media_url,thumbnail_url}"
)

# One page is plenty for a picker. Somebody with four hundred images needs a
# search box, not a longer list, and that is a decision for the screen.
PAGE_SIZE: Final = 50

# How deep the Instagram media list may page, and it is its own number
# because the client's default is sized for lists of accounts and forms.
# An active profile passes that default at about twelve hundred posts, and
# a read that reaches the ceiling stores nothing - so the grid of exactly
# the busiest accounts would stay empty or stop moving.
#
# Two hundred pages is ten thousand posts, which is as many as Meta
# returns on this edge at all.
IG_MEDIA_PAGES: Final = 200

# Everything a pixel row can answer. Wider than the product reads, because
# seeing what else is there is the whole reason this module returns raw
# rows.
PIXEL_FIELDS: Final = (
    "id,name,last_fired_time,is_unavailable,creation_time,data_use_setting,"
    "enable_automatic_matching,owner_business"
)

# Meta caps interest search results well below this; asking for more simply
# returns what there is.
SEARCH_LIMIT: Final = 25

# The catalogue is asked in English, and nothing here says so: the client
# pins ``API_LOCALE`` on every request it builds.
#
# Worth knowing anyway, because this module is why. Meta localises interest
# **names** to the account's own locale while keeping the ids the same, so a
# Russian account answers "Образование" where an English one answers
# "Education" - same interest, same id, different word. Every query this
# project sends is English by construction (see ``core.targeting.Interest``:
# the owner reads an Uzbek label and the provider is searched with an
# English term), so without the pin the two sides speak different languages
# and every name that happens to have a translation comes back unmatched.
#
# That is not hypothetical. On a Russian-locale account "Foreign language"
# and "Freelance marketplace" resolve, because Meta has no Russian entry
# for them, while "Education", "Fast food" and "English language" do not.


def search_interests(
    *, query: str, token: str, client: GraphClient | None = None
) -> list[dict[str, Any]]:
    """Interests whose name matches ``query``.

    The single call the whole interest flow depends on. A name typed by an
    owner or proposed by Claude means nothing to Meta until this returns an
    id for it, which is why the catalogue stores names and never ids.
    """
    with _session(client, token) as graph:
        payload = graph.get(
            "search",
            type="adinterest",
            q=query,
            limit=SEARCH_LIMIT,
            fields=INTEREST_FIELDS,
        )
    return list(payload.get("data", []))


# What a searched place carries. ``supports_city`` and ``supports_region``
# are Meta saying what it will accept this row *inside* - a row that
# supports neither is a key that can only be sent as its own type, and
# sending it as a city is a 100 with a subcode nobody reads.
LOCATION_FIELDS: Final = (
    "key,name,type,country_code,country_name,region,region_id,"
    "supports_region,supports_city"
)

# The three a campaign is ever aimed at. Meta also answers zip codes,
# neighborhoods, DMA regions and geo markets; asking for them would fill a
# picker with rows an owner has to rule out one by one, and none of the
# twelve presets targets at that grain.
LOCATION_TYPES: Final[tuple[str, ...]] = ("city", "region", "country")

# The reader's language in Meta's words. Uzbek is left out until a live call
# has shown Meta takes ``uz_UZ`` here: without a row the search stays on the
# client's English, which is known to answer.
LOCATION_LOCALES: Final[dict[str, str]] = {"ru": "ru_RU", "en": "en_US"}


def search_locations(
    *,
    query: str,
    token: str,
    location_types: tuple[str, ...] = LOCATION_TYPES,
    language: str = "",
    client: GraphClient | None = None,
) -> list[dict[str, Any]]:
    """Places whose name matches ``query``.

    The geography twin of :func:`search_interests`, and needed for the same
    reason: a targeting spec carries Meta's own key, never the word an owner
    typed. There is no ``adgeolocationvalid`` to check a whole list against,
    so this is one call per name - which is affordable because a campaign is
    aimed at one city or three, not at thirty.

    No ``country_code`` parameter. Meta accepts one on this endpoint and it
    is tempting, but it changes an unmatched name from a visible wrong
    answer into an empty result, and the caller has the country anyway -
    every row carries its own, so narrowing where the answer is *read* keeps
    the near-miss visible instead of swallowing it.

    ``language`` is the one exception to the pinned English: these names are
    read by a person and matched by key, so a Russian name costs nothing.
    """
    locale = LOCATION_LOCALES.get(language)
    with _session(client, token) as graph:
        payload = graph.get(
            "search",
            type="adgeolocation",
            q=query,
            location_types=_json_list(list(location_types)),
            limit=SEARCH_LIMIT,
            fields=LOCATION_FIELDS,
            **({"locale": locale} if locale else {}),
        )
    return list(payload.get("data", []))


# Meta's own name for each closed detailed-targeting class, against the
# domain's word for it.
#
# The vocabulary stops here, which is the whole point of the table. Meta
# spells the second one ``life_events`` and the first ``behaviors`` - with
# the American spelling, which is the kind of detail that produces an empty
# result rather than an error when a caller guesses it.
#
# Two, and the ones missing are missing for a reason. ``demographics``,
# ``industries``, ``income`` and the rest are real classes and are not
# offered: several of them are unavailable in most markets, and every one
# of them is removed outright under a Special Ad Category - which is the
# category a good part of this catalogue's businesses fall into.
TRAIT_CLASSES: Final[dict[str, str]] = {
    "behaviour": "behaviors",
    "life_event": "life_events",
}

# What a browsed category row carries. The same four an interest does, plus
# Meta's own class name - which is asked for so that a row filed somewhere
# unexpected is visible rather than silently taken as the class that was
# requested.
CATEGORY_FIELDS: Final = (
    "id,name,type,audience_size_lower_bound,audience_size_upper_bound,path"
)

# The whole class comes back, so the page has to hold it. Life events is
# about a dozen rows; behaviours is a few hundred and is the reason this is
# a paged read rather than one request.
CATEGORY_PAGE: Final = 100


def browse_traits(
    *, klass: str, token: str, client: GraphClient | None = None
) -> list[dict[str, Any]]:
    """Every row Meta publishes in one detailed-targeting class.

    A **browse**, not a search, and the difference is why this is a separate
    function from :func:`search_interests` above rather than a parameter on
    it. Meta answers ``adTargetingCategory`` with the entire class and
    ignores a query string; a caller that passed one and trusted the filter
    would get the whole list back and think it had matched.

    ``klass`` is Meta's own spelling, from :data:`TRAIT_CLASSES`. Nothing
    here validates it: an unknown class comes back empty, which is what an
    unknown class means, and the caller that chose the word is one layer up
    where the domain's own vocabulary lives.

    Raw rows, like everything else in this module. What comes back is small
    enough to hold - a dozen life events, a few hundred behaviours - and
    cheap enough to re-read that no cache lives in this package.
    """
    # ``class`` is a Python keyword and cannot be written as an argument
    # name, so it has to arrive through a mapping. Annotated rather than
    # inlined: unpacking a ``dict[str, str]`` into a signature that also
    # takes a typed keyword is a type error, and the alternative is naming
    # the parameter something Meta would not recognise.
    reserved: dict[str, Any] = {"class": klass}
    with _session(client, token) as graph:
        return graph.get_all(
            "search",
            type="adTargetingCategory",
            **reserved,
            limit=CATEGORY_PAGE,
            fields=CATEGORY_FIELDS,
        )


def suggest_interests(
    *, names: list[str], token: str, client: GraphClient | None = None
) -> list[dict[str, Any]]:
    """Interests Meta considers adjacent to the ones already chosen.

    A different endpoint from the search above and a different question:
    "what else would work" rather than "does this exist". Useful when a
    chosen list is too narrow to deliver.
    """
    with _session(client, token) as graph:
        payload = graph.get(
            "search",
            type="adinterestsuggestion",
            interest_list=_json_list(names),
            limit=SEARCH_LIMIT,
            fields=INTEREST_FIELDS,
        )
    return list(payload.get("data", []))


def validate_interests(
    *, names: list[str], token: str, client: GraphClient | None = None
) -> list[dict[str, Any]]:
    """Whether Meta still recognises these names, in one call.

    Cheaper than one search per name and the right shape for the weekly
    re-check: interests get merged and retired, and a stored id that stopped
    existing fails at creation time rather than here.

    ``fields`` is asked for explicitly, and that is not decoration. This
    endpoint answers "is this a real name", so its default answer is a name
    and a boolean - and a caller that needs the **id** in order to target
    anything gets a row it has to discard. Naming the fields is what turns
    a confident empty answer into a usable one.
    """
    with _session(client, token) as graph:
        payload = graph.get(
            "search",
            type="adinterestvalid",
            interest_list=_json_list(names),
            fields=INTEREST_FIELDS,
        )
    return list(payload.get("data", []))


def list_images(
    *, account_id: str, token: str, client: GraphClient | None = None
) -> list[dict[str, Any]]:
    """Images already uploaded to this ad account.

    The reason the wizard can offer a creative to somebody who has run ads
    before without asking them to upload anything again.
    """
    with _session(client, token) as graph:
        return graph.get_all(
            f"{account_id}/adimages", fields=IMAGE_FIELDS, limit=PAGE_SIZE
        )


def read_images(
    *,
    account_id: str,
    hashes: list[str],
    token: str,
    fields: str = IMAGE_FIELDS,
    client: GraphClient | None = None,
) -> list[dict[str, Any]]:
    """Named images on this ad account, rather than all of them.

    The edge :func:`list_images` reads, narrowed by ``hashes``. An image
    has no path of its own to read, for the reason it has none to delete:
    it is named by its contents, not given an id.
    """
    with _session(client, token) as graph:
        payload = graph.get(
            f"{account_id}/adimages", hashes=_json_list(hashes), fields=fields
        )
    return [row for row in payload.get("data", []) if isinstance(row, dict)]


def list_videos(
    *, account_id: str, token: str, client: GraphClient | None = None
) -> list[dict[str, Any]]:
    with _session(client, token) as graph:
        return graph.get_all(
            f"{account_id}/advideos", fields=VIDEO_FIELDS, limit=PAGE_SIZE
        )


def list_creatives(
    *, account_id: str, token: str, client: GraphClient | None = None
) -> list[dict[str, Any]]:
    """Whole creatives from previous campaigns, reusable as they are.

    **Not what the mirror reads.** That comes through ``/act_<id>/ads``,
    nested on the ad - one call instead of two, and a different population:
    this edge answers with every creative the advertiser has ever made,
    including the ones no ad has pointed at for years. Content with no
    figures beside it cannot be compared, which is what the mirror is for.

    This one stays because the two questions are different. "What could I
    reuse" wants the whole library.
    """
    with _session(client, token) as graph:
        return graph.get_all(
            f"{account_id}/adcreatives", fields=CREATIVE_FIELDS, limit=PAGE_SIZE
        )


def list_page_posts(
    *, page_id: str, token: str, client: GraphClient | None = None
) -> list[dict[str, Any]]:
    """The page's own posts, which can be promoted without a new creative.

    Needs the *page* token, not the user token: a user token can list the
    pages somebody administers, and reading a page's content is a different
    permission on a different object.
    """
    with _session(client, token) as graph:
        return graph.get_all(f"{page_id}/posts", fields=POST_FIELDS, limit=PAGE_SIZE)


def list_instagram_media(
    *,
    ig_user_id: str,
    token: str,
    fields: str = IG_MEDIA_FIELDS,
    client: GraphClient | None = None,
) -> list[dict[str, Any]]:
    """The Instagram account's own posts, newest first.

    ``graph.facebook.com`` and not ``graph.instagram.com``: this is the
    Facebook-Login half of the Instagram Platform, which is the half a page
    token already reaches. The account has to be a professional one linked
    to the page, which is exactly the set of accounts that gave us an
    ``instagram_business_account`` id in the first place.

    **Stories are not here.** They live on ``/stories``, last a day, and
    asking this edge for them returns nothing rather than an error - which
    is the sort of silence that reads as "this customer posts nothing".

    ``fields`` is a parameter so the console can bisect a refusal. Meta
    answers ``#100`` for the whole request over one unrecognised name, and
    finding out which name is the only way past it.
    """
    with _session(client, token) as graph:
        return graph.get_all(
            f"{ig_user_id}/media",
            fields=fields,
            limit=PAGE_SIZE,
            max_pages=IG_MEDIA_PAGES,
        )


def list_recent_instagram_media(
    *,
    ig_user_id: str,
    token: str,
    fields: str = IG_MEDIA_FIELDS,
    client: GraphClient | None = None,
) -> list[dict[str, Any]]:
    """The newest page of the same edge, and nothing past it.

    One request whatever the size of the account. The edge answers newest
    first, so a post published a minute ago is on this page - which is the
    only question asked of it. A short answer here is not a complete one,
    and the caller must not treat what is missing as deleted.
    """
    with _session(client, token) as graph:
        payload = graph.get(f"{ig_user_id}/media", fields=fields, limit=PAGE_SIZE)
    rows = payload.get("data", [])
    return list(rows) if isinstance(rows, list) else []


def read_instagram_media(
    *,
    media_id: str,
    token: str,
    fields: str = IG_MEDIA_DETAIL_FIELDS,
    client: GraphClient | None = None,
) -> dict[str, Any]:
    """One post, with everything worth asking it for.

    Two callers with one shape. The console reads it to find out what a
    carousel and a reel actually answer with; the launch reads it for a
    ``media_url`` that has not expired yet, which is the only reason the
    file can still be fetched minutes after somebody chose it.
    """
    with _session(client, token) as graph:
        return graph.get(media_id, fields=fields)


def read_media_insight(
    *,
    media_id: str,
    metric: str,
    token: str,
    client: GraphClient | None = None,
) -> int | None:
    """One insight figure for one Instagram post, or ``None`` if not given.

    One metric per request on purpose: Meta refuses the whole request over
    one metric it does not offer for that kind of post - a reel and a photo
    do not share a list, and the list moves between versions - so asking
    for several at once turns one unknown name into no figures at all.

    Both answer shapes are read: the older ``values[0].value`` and the
    ``total_value.value`` the newer metrics use.
    """
    with _session(client, token) as graph:
        payload = graph.get(f"{media_id}/insights", metric=metric)
    for row in payload.get("data", []):
        total = (row.get("total_value") or {}).get("value")
        if isinstance(total, int):
            return total
        values = row.get("values") or []
        if values and isinstance(values[0].get("value"), int):
            return int(values[0]["value"])
    return None


def list_pixels(
    *, account_id: str, token: str, client: GraphClient | None = None
) -> list[dict[str, Any]]:
    """The account's conversion pixels, raw.

    ``accounts.list_pixels`` parses the same rows into a DTO for the
    product. This one exists so the shape can be looked at first: the
    parsed version reads four fields and Meta sends more, and the console
    is where it is decided whether any of the rest matter.
    """
    with _session(client, token) as graph:
        return graph.get_all(
            f"{account_id}/adspixels", fields=PIXEL_FIELDS, limit=PAGE_SIZE
        )


def estimate_reach(
    *,
    account_id: str,
    targeting: dict[str, Any],
    optimization_goal: str,
    token: str,
    client: GraphClient | None = None,
) -> dict[str, Any]:
    """How many people this spec would reach, before anything is created.

    The number that turns "we narrowed your audience" into something the
    owner can judge. Meta answers with a range rather than a figure, and
    presenting it as a single number would be inventing precision.
    """
    with _session(client, token) as graph:
        payload = graph.get(
            f"{account_id}/delivery_estimate",
            optimization_goal=optimization_goal,
            targeting_spec=_json_value(targeting),
        )
    rows = payload.get("data", [])
    return dict(rows[0]) if rows else {}


def _json_list(values: list[str]) -> str:
    """Meta takes list parameters as a JSON array in a query string."""
    return _json_value(values)


def _json_value(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


@contextmanager
def _session(client: GraphClient | None, token: str) -> Iterator[GraphClient]:
    """One connection, closed only if this module opened it.

    The same pattern as every other module here: a caller making four of
    these calls in a row passes one client and pays for one handshake.
    """
    graph = client or GraphClient(token=token)
    try:
        yield graph
    finally:
        if client is None:
            graph.close()
