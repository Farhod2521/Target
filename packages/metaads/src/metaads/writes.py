"""Creating a campaign, an ad set and an ad - and undoing them.

Apart from :mod:`metaads.campaigns` on purpose, and the reason is written
in that module's own docstring: a module that can only read is a module
that cannot spend somebody else's money by accident. This is the other
half, and everything in it defaults to ``dry_run=True``.

The order matters and is not an implementation detail. A campaign holds an
ad set holds an ad, each one naming its parent at creation, so the sequence
cannot be reordered or parallelised. Read backwards it is also the rollback
order, which is why a half-finished sequence has to record what it made
after every single step rather than at the end.

One thing here is not obvious. Meta accepts a targeting spec, silently
removes parts of it, and answers 200. :func:`create_adset` therefore reads
its own work back and reports the difference, because an interest that
disappeared between the review screen and the ad set is an audience the
owner approved and did not get.
"""

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Final

from metaads.client import GraphClient
from metaads.errors import MetaError
from metaads.specs import STATUS_ACTIVE, STATUS_PAUSED, AdSetSpec, CampaignSpec
from metaads.writing import fake_id, graph_client, id_of, is_dry_run_id, post_object

# What the ad set is asked for after it is created. Only targeting: the
# rest of what came back is what was sent, and re-reading it would cost a
# call to learn nothing.
logger = logging.getLogger(__name__)

TARGETING_FIELDS: Final = "targeting"

# Meta's answer to a delete and to a status change. Both are a bare
# ``{"success": true}`` rather than an object.
_SUCCESS: Final = "success"

# Levels, as they appear in a dry-run id. Short words rather than the
# ``Level`` literal from adskit, because this module builds strings and the
# domain vocabulary belongs one layer up.
_CAMPAIGN: Final = "campaign"
_ADSET: Final = "adset"
_AD: Final = "ad"


@dataclass(frozen=True, slots=True)
class AdSetCreated:
    """An ad set, and what Meta quietly declined to keep.

    A dataclass rather than a pydantic model because nobody parses this:
    it is assembled from a call we just made, which is the same reason
    ``adskit.ActionResult`` is one.
    """

    id: str
    dropped: dict[str, Any] = field(default_factory=dict)
    # The targeting the ad set holds after the write, as Meta reads it back.
    # Kept whole because what Meta *adds* - an age ceiling, a location type -
    # is not a loss and never reaches ``dropped``.
    returned: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TargetingWritten:
    """A replaced audience: what Meta declined to keep, and what it holds.

    ``returned`` is empty when nothing was read back - a dry run, or a
    read that failed after Meta had already accepted the write.
    """

    dropped: dict[str, Any] = field(default_factory=dict)
    returned: dict[str, Any] = field(default_factory=dict)


def create_campaign(
    *,
    account_id: str,
    spec: CampaignSpec,
    token: str,
    client: GraphClient | None = None,
    dry_run: bool = True,
) -> str:
    """The container. Created paused, always.

    Two fields are sent even though they look optional, and for the same
    reason: Meta reads a missing one as an error rather than as a default.
    ``special_ad_categories`` has to be there even when empty, and a
    campaign without its own budget has to say whether its ad sets may
    share theirs - "Invalid parameter" is the whole of what comes back
    otherwise. A campaign with its own budget must not say anything:
    Meta documents no answer for it, and ``true`` is refused.
    """
    if dry_run:
        return fake_id(_CAMPAIGN)

    payload = post_object(
        path=f"{account_id}/campaigns",
        data={
            "name": spec.name,
            "objective": spec.objective,
            "status": spec.status,
            "special_ad_categories": list(spec.special_ad_categories),
            # ``None`` with no category, so the key is left out.
            "special_ad_category_country": (
                list(spec.special_ad_category_country) or None
            ),
            "daily_budget": spec.daily_budget_minor or None,
            "bid_strategy": spec.bid_strategy,
            "is_adset_budget_sharing_enabled": (
                None if spec.daily_budget_minor else spec.budget_sharing
            ),
            # ``None`` for a campaign with no ceiling, so the key is left
            # out of the body: Meta reads a zero here as a cap of nothing
            # and refuses it, the same trap the bid amount carries on the
            # ad set below.
            "spend_cap": spec.spend_cap_minor or None,
        },
        token=token,
        client=client,
    )
    return id_of(payload)


def create_adset(
    *,
    account_id: str,
    spec: AdSetSpec,
    token: str,
    client: GraphClient | None = None,
    dry_run: bool = True,
) -> AdSetCreated:
    """The audience and the budget, then a read-back of what survived.

    The second call is not caution for its own sake. Meta drops retired
    placements and interests it no longer recognises without saying so, and
    the only evidence is the difference between what went out and what the
    ad set now holds.
    """
    if dry_run:
        return AdSetCreated(id=fake_id(_ADSET))

    with graph_client(client, token) as graph:
        payload = post_object(
            path=f"{account_id}/adsets",
            data={
                "name": spec.name,
                "campaign_id": spec.campaign_id,
                # Both left out under a campaign that holds the budget:
                # Meta takes one or the other, never both levels.
                "daily_budget": spec.daily_budget_minor or None,
                "optimization_goal": spec.optimization_goal,
                "billing_event": spec.billing_event,
                "bid_strategy": spec.bid_strategy if spec.daily_budget_minor else None,
                # ``None`` for an uncapped ad set, so the key is left out of
                # the body entirely - an uncapped ad set must not carry it,
                # and Meta reads a zero as a cap of nothing rather than as
                # no cap.
                #
                # Turned into ``None`` here rather than relying on
                # ``post_object`` to drop it. That function drops ``None``,
                # ``""`` and ``{}`` and deliberately keeps everything else:
                # ``special_ad_categories: []`` is how a campaign says none
                # apply, and ``is_adset_budget_sharing_enabled: false`` is an
                # answer Meta requires. A zero is only meaningless for *this*
                # field, so this is the only field that says so.
                "bid_amount": spec.bid_amount_minor or None,
                "destination_type": spec.destination_type,
                "targeting": spec.targeting,
                "promoted_object": spec.promoted_object,
                "start_time": spec.start_time,
                # Dropped when empty, like the start beside it, which is
                # what an ad set with no end is: Meta reads an absent field
                # as "runs until stopped" and an empty string as an error.
                "end_time": spec.end_time,
                # Both dropped when zero, like the bid amount above: a
                # provider reading a zero as "spend nothing today" would be
                # told to stop the ad set on every one of them.
                "daily_min_spend_target": spec.daily_min_spend_minor or None,
                "daily_spend_cap": spec.daily_max_spend_minor or None,
                # Both dropped when empty - an empty list here is not "the
                # default", it is a list Meta reads as an answer and
                # refuses.
                "attribution_spec": list(spec.attribution) or None,
                "frequency_control_specs": list(spec.frequency_control) or None,
                "status": spec.status,
            },
            token=token,
            client=graph,
        )
        created = id_of(payload)
        held = _targeting_held(graph, object_id=created)

    if held is None:
        return AdSetCreated(id=created)
    return AdSetCreated(
        id=created,
        dropped=dropped_from(sent=spec.targeting, returned=held),
        returned=held,
    )


def create_ad(
    *,
    account_id: str,
    adset_id: str,
    creative_id: str,
    name: str,
    token: str,
    client: GraphClient | None = None,
    dry_run: bool = True,
    status: str = STATUS_PAUSED,
) -> str:
    """The last object: a creative pointed at an audience."""
    if dry_run:
        return fake_id(_AD)

    payload = post_object(
        path=f"{account_id}/ads",
        data={
            "name": name,
            "adset_id": adset_id,
            "creative": {"creative_id": creative_id},
            "status": status,
        },
        token=token,
        client=client,
    )
    return id_of(payload)


def set_status(
    *,
    object_id: str,
    status: str,
    token: str,
    client: GraphClient | None = None,
    dry_run: bool = True,
) -> bool:
    """Start or stop one object, at any level.

    The only call in this module that touches something which may already
    be delivering, which is why the guardrails that decide *whether* to
    call it live above the package and not here.
    """
    if dry_run or is_dry_run_id(object_id):
        return True

    payload = post_object(
        path=object_id, data={"status": status}, token=token, client=client
    )
    return bool(payload.get(_SUCCESS, True))


def set_budget(
    *,
    object_id: str,
    daily_budget_minor: int,
    token: str,
    client: GraphClient | None = None,
    dry_run: bool = True,
) -> bool:
    """Replace the daily budget on a campaign or an ad set.

    One field on one object, and the same field name at both levels -
    which is the whole reason this does not need to know which level it was
    handed. What it cannot do is decide *that*: an ad set's budget is
    ignored when the campaign above it holds one, so writing to the wrong
    level succeeds, changes nothing, and reports success.

    The amount goes out in the account currency's minor units, exactly as
    it is stored. Meta reads the field that way and there is no second
    representation to convert to - which is the point of never letting a
    budget become a float on this side either.
    """
    if dry_run or is_dry_run_id(object_id):
        return True

    payload = post_object(
        path=object_id,
        data={"daily_budget": daily_budget_minor},
        token=token,
        client=client,
    )
    return bool(payload.get(_SUCCESS, True))


def set_end_time(
    *,
    object_id: str,
    end_time: str,
    token: str,
    client: GraphClient | None = None,
    dry_run: bool = True,
) -> bool:
    """Say when this ad set should stop.

    ``end_time`` is ISO-8601 with an offset, a string for the reason
    ``AdSetSpec.start_time`` is one: this package has no clock and no
    timezone, and the caller knows the business's.

    **Setting only.** Meta reads an absent field as "no change" and an
    empty one as an error, and ``post_object`` drops empties for exactly
    that reason - so there is no value this function could send to mean
    "remove the end date". Removing one is a different call, it is not
    written here, and the screens above do not offer it: an end date can be
    moved forward but not taken off. See ``apps.ads.services.request_limits``
    for what that costs an advertiser and why it is the honest trade.
    """
    if dry_run or is_dry_run_id(object_id):
        return True

    payload = post_object(
        path=object_id,
        data={"end_time": end_time},
        token=token,
        client=client,
    )
    return bool(payload.get(_SUCCESS, True))


def set_spend_cap(
    *,
    object_id: str,
    spend_cap_minor: int,
    token: str,
    client: GraphClient | None = None,
    dry_run: bool = True,
) -> bool:
    """The most this campaign may spend before Meta stops it.

    A ceiling rather than a rate, which is why it is not
    :func:`set_budget` with a different field name: the daily budget says
    how fast, this says how far, and an advertiser can want either without
    the other.

    Meta enforces two rules this does not check. It has a minimum, which
    differs per currency, and it refuses a cap below what the campaign has
    already spent - both come back as ordinary Graph errors and are
    translated where every other refusal is. Copying that arithmetic here
    would be a second copy to keep in step with a figure Meta publishes and
    changes.

    **Setting only**, like :func:`set_end_time` above and for the same
    reason: there is no value here that means "no cap".
    """
    if dry_run or is_dry_run_id(object_id):
        return True

    payload = post_object(
        path=object_id,
        data={"spend_cap": spend_cap_minor},
        token=token,
        client=client,
    )
    return bool(payload.get(_SUCCESS, True))


def write_targeting(
    *,
    object_id: str,
    targeting: Mapping[str, Any],
    token: str,
    client: GraphClient | None = None,
    dry_run: bool = True,
) -> TargetingWritten:
    """Replace an ad set's audience, then read back what survived.

    Two calls, and the second one is the reason this is not a one-liner
    beside :func:`set_budget`. A budget is a number Meta either takes or
    refuses; a targeting spec is a document Meta takes *partly* - it strips
    a retired placement or an interest it has merged away, answers 200, and
    the ad set then runs against an audience nobody approved. The read-back
    is the only way to learn that, and it has to happen here rather than at
    the next sync, because by then the difference is indistinguishable from
    something the owner changed in Ads Manager.

    Returns what was dropped and what is held, not whether it worked: a
    write Meta rejects raises, so reaching the return means it was accepted,
    and the only open question is how much of it.
    """
    if dry_run or is_dry_run_id(object_id):
        return TargetingWritten()

    with graph_client(client, token) as graph:
        post_object(
            path=object_id,
            data={"targeting": dict(targeting)},
            token=token,
            client=graph,
        )
        held = _targeting_held(graph, object_id=object_id)

    if held is None:
        return TargetingWritten()
    return TargetingWritten(
        dropped=dropped_from(sent=targeting, returned=held), returned=held
    )


def read_targeting(
    *, object_id: str, token: str, client: GraphClient | None = None
) -> dict[str, Any]:
    """The audience an ad set holds right now.

    Unlike the read-back after a write, a failure here raises: it is asked
    *before* a write, and an edit that cannot see the current audience must
    not replace it.
    """
    with graph_client(client, token) as graph:
        stored = graph.get(object_id, fields=TARGETING_FIELDS)
    returned = stored.get("targeting")
    return dict(returned) if isinstance(returned, dict) else {}


def _targeting_held(graph: GraphClient, *, object_id: str) -> dict[str, Any] | None:
    """The targeting an ad set holds now, or ``None`` when the read failed.

    The read-back follows a write Meta has already accepted, so its failure
    must not become the write's. Raised, it lost the new ad set's id - the
    only copy is in the reply just read - and left an ad set with a budget
    that nothing here knows to delete. The likeliest cause is the client's
    own brake, set by the write's answer when the call budget passed 80%.

    ``None`` rather than ``{}``: an empty dict compared with what was sent
    would report every key as dropped.
    """
    try:
        stored = graph.get(object_id, fields=TARGETING_FIELDS)
    except MetaError as exc:
        logger.warning("could not read back the targeting of %s: %s", object_id, exc)
        return None
    returned = stored.get("targeting")
    return returned if isinstance(returned, dict) else {}


def delete_object(
    *,
    object_id: str,
    token: str,
    client: GraphClient | None = None,
    dry_run: bool = True,
) -> bool:
    """Remove one object. The rollback's only tool.

    A dry-run id answers true without a call. That is the whole point of
    :func:`is_dry_run_id`: a rollback iterating over refs must not be the
    place where a synthetic id first reaches Meta, and refusing loudly
    instead would abort a rollback partway through - leaving behind exactly
    the half-deleted campaign it was called to prevent.
    """
    if dry_run or is_dry_run_id(object_id):
        return True

    with graph_client(client, token) as graph:
        payload = graph.delete(object_id)
    return bool(payload.get(_SUCCESS, True))


def dropped_from(
    *, sent: Mapping[str, Any], returned: Mapping[str, Any]
) -> dict[str, Any]:
    """What was asked for and is not there afterwards.

    Only absence counts. Meta normalises almost everything it keeps - it
    expands a city key into a full location object, adds fields nobody
    sent - so a value-by-value comparison would report a dozen differences
    per ad set and be ignored within a week.
    """
    dropped: dict[str, Any] = {
        key: value
        for key, value in sent.items()
        if value not in (None, [], {}, "") and not returned.get(key)
    }

    lost = _interest_ids(sent) - _interest_ids(returned)
    if lost:
        dropped["interests"] = sorted(lost)

    return dropped


def changed_from(
    *, sent: Mapping[str, Any], returned: Mapping[str, Any]
) -> dict[str, dict[str, Any]]:
    """What Meta put into the spec, or set to another value, on its own.

    The other half of :func:`dropped_from`, and narrow for the same reason.
    A key that was never sent is reported with what Meta wrote - an ad set
    sent without ``age_max`` comes back with 65. A value that was sent is
    compared only when it is a plain one: Meta rewrites every location and
    interest list it keeps, and a report of those is a report nobody reads.
    """
    changed: dict[str, dict[str, Any]] = {}
    for key, value in returned.items():
        if key not in sent:
            changed[key] = {"sent": None, "returned": value}
        elif _plain(value) and _plain(sent[key]) and sent[key] != value:
            changed[key] = {"sent": sent[key], "returned": value}
    return changed


def _plain(value: Any) -> bool:
    return isinstance(value, str | int | float | bool)


def _interest_ids(targeting: Mapping[str, Any]) -> set[str]:
    """Every interest id inside a spec, however deeply Meta nests them.

    Interests live under ``flexible_spec`` as a list of blocks, each with
    its own list. One missing id out of eight is invisible at the top level
    and is the difference between the audience that was approved and the
    one that was bought.
    """
    found: set[str] = set()
    blocks = targeting.get("flexible_spec")
    if not isinstance(blocks, list):
        return found

    for block in blocks:
        rows = block.get("interests") if isinstance(block, dict) else None
        if not isinstance(rows, list):
            continue
        for row in rows:
            if isinstance(row, dict) and row.get("id"):
                found.add(str(row["id"]))

    return found


__all__ = [
    "STATUS_ACTIVE",
    "STATUS_PAUSED",
    "AdSetCreated",
    "TargetingWritten",
    "changed_from",
    "create_ad",
    "create_adset",
    "create_campaign",
    "delete_object",
    "dropped_from",
    "read_targeting",
    "set_budget",
    "set_status",
    "write_targeting",
]
