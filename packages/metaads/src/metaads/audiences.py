"""Custom audiences: the lists an advertiser owns, held on Meta.

Apart from :mod:`metaads.discovery` and :mod:`metaads.writes` on purpose.
Discovery answers "what is available" and writes builds the campaign
hierarchy; this is a third thing - an object that belongs to the account,
is pointed at from many ad sets, and outlives all of them.

**Nothing here carries personal data.** Filling an audience is a separate
module, :mod:`metaads.customer_lists`, so that the one piece of code in
this package that handles people is a file somebody can read end to end.

Meta's rule worth knowing before reading the code: **the advertiser has to
have agreed, personally.** Meta refuses to create a customer-list audience
until the person making the call has accepted the Custom Audience Terms,
once per account. It is the same shape of problem a lead form's terms are,
and it is reported the same way - see :data:`TERMS_URL`.
"""

from typing import Final

from adskit.dto import AudienceRuleDTO, LookalikeSpecDTO

from metaads.audience_rules import rule_document
from metaads.client import GraphClient
from metaads.dto import CustomAudienceRow
from metaads.lookalikes import SUBTYPE_LOOKALIKE, lookalike_spec
from metaads.parsing import parsed, parsed_all
from metaads.writing import fake_id, graph_client, id_of, is_dry_run_id, post_object

_AUDIENCE: Final = "audience"
# A second rehearsal id, and it earns its line. A dry run answers the same
# synthetic id every time, and the mirror keys rows on it - so one id for
# both create calls would mean a rehearsed retargeting audience overwriting
# the rehearsed customer list, in the one environment where somebody is
# looking at both.
_RULE_AUDIENCE: Final = "rule_audience"
# And a third, for the same reason there is a second. Three creates land in
# one mirror keyed on the id, so three rehearsals need three ids or the last
# one silently replaces the others.
_LOOKALIKE: Final = "lookalike"

# What an audience says about itself. Asked for explicitly, because Meta's
# default answer to this edge is an id and a name - and neither says
# whether the audience is usable, how many people are in it, or whether the
# last upload has finished being processed.
#
# ``approximate_count`` is **not** here, and its absence is the finding.
# That field was retired; the bounds below replaced it, exactly as they
# replaced ``audience_size`` on the interest catalogue. Asking for the old
# name gets a confident nothing.
# ``rule`` and ``retention_days`` are here for the audiences Meta fills in
# itself. They are empty on a customer list and are the whole of what a
# retargeting audience is - without them a screen could show that one
# exists and nothing about what it collects.
#
# ``lookalike_spec`` is the same bargain one step further out: it is the
# only thing Meta will say about an audience built to resemble another.
# Note what is *not* askable beside it - ``origin_audience_id`` is a
# creation parameter and not a field, so the seed a lookalike came from is
# never in this answer.
AUDIENCE_FIELDS: Final = (
    "id,name,description,subtype,customer_file_source,"
    "approximate_count_lower_bound,approximate_count_upper_bound,"
    "operation_status,delivery_status,data_source,rule,retention_days,"
    "lookalike_spec,time_created,time_updated"
)

# An account with two hundred audiences has been running ads for years and
# still comes back in a couple of requests.
PAGE_SIZE: Final = 100

# The subtype this product creates: a list the advertiser supplies. Every
# other subtype is one Meta fills in itself and would refuse an upload to.
SUBTYPE_CUSTOM: Final = "CUSTOM"

# How the advertiser says they came by the data. This product only ever
# uploads what the business collected itself - leads from its own forms,
# its own customer file - so the value is fixed rather than asked for.
# Claiming a partner supplied it would be a representation nobody made.
CUSTOMER_FILE_SOURCE: Final = "USER_PROVIDED_ONLY"

# Where a person agrees to Meta's rules about uploaded personal data. Not
# an API call - it is a URL handed to a browser, like the OAuth dialog and
# like the lead-ad terms beside it.
#
# Acceptance is per person *and* per ad account, which is why the account
# id belongs in the link: an advertiser with two accounts who opens the
# bare URL agrees on whichever one Meta picks, then meets the same refusal
# again with no way to tell that they agreed to the wrong thing.
TERMS_URL: Final = "https://business.facebook.com/ads/manage/customaudiences/tos/"


def terms_url(account_id: str = "") -> str:
    """The terms page, for one account when we know which."""
    if not account_id:
        return TERMS_URL
    return f"{TERMS_URL}?act={account_id.removeprefix('act_')}"


def list_audiences(
    *, account_id: str, token: str, client: GraphClient | None = None
) -> list[CustomAudienceRow]:
    """Every custom audience on the account, whatever state each is in.

    The ones this product did not create come back too, and are wanted: an
    advertiser who built one by hand has something ads can be aimed at, and
    a list that hid it would be a picker missing the row they were looking
    for.
    """
    with graph_client(client, token) as graph:
        rows = graph.get_all(
            f"{account_id}/customaudiences", fields=AUDIENCE_FIELDS, limit=PAGE_SIZE
        )
    return parsed_all(CustomAudienceRow, rows)


def get_audience(
    *, audience_id: str, token: str, client: GraphClient | None = None
) -> CustomAudienceRow:
    """One audience, read on its own.

    Worth a call of its own because of what happens after an upload: Meta
    counts for hours, and the screen asking whether it has finished is
    asking about one audience. Re-reading the whole account to learn one
    field would spend a paged call on it.
    """
    with graph_client(client, token) as graph:
        payload = graph.get(audience_id, fields=AUDIENCE_FIELDS)
    return parsed(CustomAudienceRow, payload)


def create_audience(
    *,
    account_id: str,
    name: str,
    description: str = "",
    token: str,
    client: GraphClient | None = None,
    dry_run: bool = True,
) -> str:
    """Create an empty audience a customer list can be uploaded into.

    Empty, always: Meta takes the container and the people in two calls and
    there is no shape of this function that could hide that honestly.

    ``customer_file_source`` is sent even though it looks optional. Meta
    accepts the create without it and then refuses the upload, several
    minutes and one spreadsheet later.
    """
    if dry_run:
        return fake_id(_AUDIENCE)

    payload = post_object(
        path=f"{account_id}/customaudiences",
        data={
            "name": name,
            "description": description,
            "subtype": SUBTYPE_CUSTOM,
            "customer_file_source": CUSTOMER_FILE_SOURCE,
        },
        token=token,
        client=client,
    )
    return id_of(payload)


def create_rule_audience(
    *,
    account_id: str,
    name: str,
    description: str = "",
    rule: AudienceRuleDTO,
    token: str,
    client: GraphClient | None = None,
    dry_run: bool = True,
) -> str:
    """Create an audience Meta populates itself, from a rule.

    Apart from :func:`create_audience` because the two produce opposite
    objects: that one is an empty container waiting for a customer list,
    this one is already filling and will refuse an upload for ever.

    **Three parameters that one sends are deliberately absent here.**
    ``subtype`` is not supported for rule-built audiences and has not been
    since 2018; ``customer_file_source`` describes where personal data came
    from and no personal data is involved; ``retention_days`` is capped at
    180 at the top level and is taken from the rule when omitted. Each of
    the three is explained in :mod:`metaads.audience_rules`.
    """
    if dry_run:
        return fake_id(_RULE_AUDIENCE)

    payload = post_object(
        path=f"{account_id}/customaudiences",
        data={
            "name": name,
            "description": description,
            "rule": rule_document(rule),
        },
        token=token,
        client=client,
    )
    return id_of(payload)


def create_lookalike_audience(
    *,
    account_id: str,
    name: str,
    description: str = "",
    spec: LookalikeSpecDTO,
    token: str,
    client: GraphClient | None = None,
    dry_run: bool = True,
) -> str:
    """Create an audience of people who resemble an audience that exists.

    The third create on this edge, and the only one whose input is another
    row of the same table. Nothing about anybody is sent: Meta holds the
    seed already, and what crosses is its id.

    **``subtype`` is sent here and not by the create above it.** That is not
    an inconsistency: Meta stopped supporting ``subtype`` for rule-built
    audiences in 2018 and requires it for this one. Its own example carries
    it, and the create is refused without it.

    ``origin_audience_id`` is a top-level field. It looks as though it
    belongs inside ``lookalike_spec`` and it does not - the spec says how
    wide and where, never what from. See :mod:`metaads.lookalikes`.

    ``customer_file_source`` and ``retention_days`` are both absent, for
    two different reasons. The first describes where personal data came
    from and none is involved. The second is documented as applying to
    customer files only, so there is nothing here for it to mean.
    """
    if dry_run:
        return fake_id(_LOOKALIKE)

    payload = post_object(
        path=f"{account_id}/customaudiences",
        data={
            "name": name,
            "description": description,
            "subtype": SUBTYPE_LOOKALIKE,
            "origin_audience_id": spec.origin.id,
            "lookalike_spec": lookalike_spec(spec),
        },
        token=token,
        client=client,
    )
    return id_of(payload)


def delete_audience(
    *,
    audience_id: str,
    token: str,
    client: GraphClient | None = None,
    dry_run: bool = True,
) -> bool:
    """Remove the audience and everything uploaded into it.

    The only way this product can withdraw personal data it has sent, which
    is why it exists before anything needs it for tidiness: an account
    being erased has to be able to take its customers' customers off
    somebody else's platform.

    A dry-run id answers true without a call, for the same reason
    :func:`metaads.writes.delete_object` does - a cleanup walking a list of
    refs must not be where a synthetic id first reaches Meta.
    """
    if dry_run or is_dry_run_id(audience_id):
        return True

    with graph_client(client, token) as graph:
        payload = graph.delete(audience_id)
    return bool(payload.get("success", True))


__all__ = [
    "AUDIENCE_FIELDS",
    "CUSTOMER_FILE_SOURCE",
    "SUBTYPE_CUSTOM",
    "TERMS_URL",
    "create_audience",
    "create_lookalike_audience",
    "create_rule_audience",
    "delete_audience",
    "get_audience",
    "list_audiences",
    "terms_url",
]
