"""Creating a campaign, an ad set and an ad - and undoing them."""

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Final

from metaads.client import GraphClient
from metaads.errors import MetaError
from metaads.specs import STATUS_ACTIVE, STATUS_PAUSED, AdSetSpec, CampaignSpec
from metaads.writing import fake_id, graph_client, id_of, is_dry_run_id, post_object

logger = logging.getLogger(__name__)

TARGETING_FIELDS: Final = "targeting"

_SUCCESS: Final = "success"

_CAMPAIGN: Final = "campaign"
_ADSET: Final = "adset"
_AD: Final = "ad"


@dataclass(frozen=True, slots=True)
class AdSetCreated:
    """An ad set, and what Meta quietly declined to keep."""

    id: str
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
    """The container. Created paused, always."""
    if dry_run:
        return fake_id(_CAMPAIGN)

    payload = post_object(
        path=f"{account_id}/campaigns",
        data={
            "name": spec.name,
            "objective": spec.objective,
            "status": spec.status,
            "special_ad_categories": list(spec.special_ad_categories),
            "special_ad_category_country": (
                list(spec.special_ad_category_country) or None
            ),
            "is_adset_budget_sharing_enabled": spec.budget_sharing,
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
    """The audience and the budget, then a read-back of what survived."""
    if dry_run:
        return AdSetCreated(id=fake_id(_ADSET))

    with graph_client(client, token) as graph:
        payload = post_object(
            path=f"{account_id}/adsets",
            data={
                "name": spec.name,
                "campaign_id": spec.campaign_id,
                "daily_budget": spec.daily_budget_minor,
                "optimization_goal": spec.optimization_goal,
                "billing_event": spec.billing_event,
                "bid_strategy": spec.bid_strategy,
                "bid_amount": spec.bid_amount_minor or None,
                "destination_type": spec.destination_type,
                "targeting": spec.targeting,
                "promoted_object": spec.promoted_object,
                "start_time": spec.start_time,
                "end_time": spec.end_time,
                "daily_min_spend_target": spec.daily_min_spend_minor or None,
                "daily_spend_cap": spec.daily_max_spend_minor or None,
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
    """Start or stop one object, at any level."""
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
    """Replace the daily budget on a campaign or an ad set."""
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
    """Say when this ad set should stop."""
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
    """The most this campaign may spend before Meta stops it."""
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
) -> dict[str, Any]:
    """Replace an ad set's audience, then read back what survived."""
    if dry_run or is_dry_run_id(object_id):
        return {}

    with graph_client(client, token) as graph:
        post_object(
            path=object_id,
            data={"targeting": dict(targeting)},
            token=token,
            client=graph,
        )
        held = _targeting_held(graph, object_id=object_id)

    if held is None:
        return {}
    return dropped_from(sent=targeting, returned=held)


def _targeting_held(graph: GraphClient, *, object_id: str) -> dict[str, Any] | None:
    """The targeting an ad set holds now, or ``None`` when the read failed."""
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
    """Remove one object. The rollback's only tool."""
    if dry_run or is_dry_run_id(object_id):
        return True

    with graph_client(client, token) as graph:
        payload = graph.delete(object_id)
    return bool(payload.get(_SUCCESS, True))


def dropped_from(
    *, sent: Mapping[str, Any], returned: Mapping[str, Any]
) -> dict[str, Any]:
    """What was asked for and is not there afterwards."""
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
    """What Meta put into the spec, or set to another value, on its own."""
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
    """Every interest id inside a spec, however deeply Meta nests them."""
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
    "changed_from",
    "create_ad",
    "create_adset",
    "create_campaign",
    "delete_object",
    "dropped_from",
    "set_budget",
    "set_status",
    "write_targeting",
]
