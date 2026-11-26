"""Deleting a campaign through the port, without a network.

Three things are pinned: a rehearsal never reaches Meta, a real delete is one
call to the object's own id, and Meta's refusal arrives as the domain's
error. And one thing about the contract: every stand-in answers the new
method, so a provider still being built refuses it by name rather than with
an ``AttributeError`` at the call site.
"""

from unittest.mock import patch

import httpx
import pytest
from adskit import CampaignControlPort, ExternalRef
from adskit.errors import PortNotAvailable, ProviderError
from adskit.unavailable import Unavailable
from metaads.adapter import MetaCampaigns
from metaads.client import GraphClient
from metaads.errors import MetaAPIError
from metaads.writes import delete_object

CAMPAIGN = ExternalRef(provider="meta", level="campaign", id="120000000000238")


def recording(
    seen: list[tuple[str, str]], *, status: int = 200, body: dict | None = None
) -> GraphClient:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        return httpx.Response(
            status, json=body if body is not None else {"success": True}
        )

    return GraphClient(
        token="t", client=httpx.Client(transport=httpx.MockTransport(handler))
    )


def test_a_rehearsed_delete_never_reaches_meta() -> None:
    """``dry_run`` defaults to True on every write in this package, and a
    delete is the one write nothing can put back."""
    seen: list[tuple[str, str]] = []

    with patch("metaads.adapter.GraphClient", return_value=recording(seen)):
        result = MetaCampaigns().delete(ref=CAMPAIGN, token="t")

    assert seen == []
    assert result.ok is True
    assert result.dry_run is True


def test_a_delete_is_one_call_to_the_objects_own_id() -> None:
    seen: list[tuple[str, str]] = []

    with patch("metaads.adapter.GraphClient", return_value=recording(seen)):
        result = MetaCampaigns().delete(ref=CAMPAIGN, token="t", dry_run=False)

    assert len(seen) == 1
    method, path = seen[0]
    assert method == "DELETE"
    assert path.endswith(f"/{CAMPAIGN.id}")
    # The domain's word for what was asked, never Meta's.
    assert result.applied == {"status": "deleted"}
    assert result.ref == CAMPAIGN


def test_metas_refusal_arrives_as_the_domains_error() -> None:
    body = {"error": {"code": 100, "message": "Invalid parameter"}}

    with (
        patch(
            "metaads.adapter.GraphClient",
            return_value=recording([], status=400, body=body),
        ),
        pytest.raises(ProviderError) as refused,
    ):
        MetaCampaigns().delete(ref=CAMPAIGN, token="t", dry_run=False)

    assert type(refused.value).__module__.startswith("adskit")


def test_the_meta_port_still_satisfies_the_contract() -> None:
    assert isinstance(MetaCampaigns(), CampaignControlPort)


@pytest.mark.parametrize("method", ["delete", "set_end_time", "set_spend_cap"])
def test_a_provider_still_being_built_refuses_by_name(method: str) -> None:
    stand_in = Unavailable(provider="google", port="campaigns")
    arguments = {
        "delete": {},
        "set_end_time": {"end_time": "2026-10-01T23:59:59+05:00"},
        "set_spend_cap": {"spend_cap_minor": 100},
    }[method]

    with pytest.raises(PortNotAvailable):
        getattr(stand_in, method)(ref=CAMPAIGN, token="t", **arguments)


# --- Deleting what is already gone -----------------------------------------
def answering(*, on_delete: tuple[int, dict], on_get: tuple[int, dict]) -> GraphClient:
    def handler(request: httpx.Request) -> httpx.Response:
        status, body = on_delete if request.method == "DELETE" else on_get
        return httpx.Response(status, json=body)

    return GraphClient(
        token="t", client=httpx.Client(transport=httpx.MockTransport(handler))
    )


MISSING = {"error": {"code": 100, "error_subcode": 33, "message": "Unsupported"}}
REFUSED = {"error": {"code": 100, "message": "Invalid parameter"}}


def test_an_id_meta_no_longer_knows_counts_as_deleted() -> None:
    """A rollback would otherwise keep the id, and the launch, forever."""
    graph = answering(on_delete=(400, MISSING), on_get=(400, MISSING))

    assert delete_object(object_id="120", token="t", client=graph, dry_run=False)


def test_a_refused_delete_of_a_deleted_object_counts_as_deleted() -> None:
    graph = answering(
        on_delete=(400, REFUSED), on_get=(200, {"effective_status": "DELETED"})
    )

    assert delete_object(object_id="120", token="t", client=graph, dry_run=False)


def test_a_refused_delete_of_a_live_object_stays_refused() -> None:
    graph = answering(
        on_delete=(400, REFUSED), on_get=(200, {"effective_status": "PAUSED"})
    )

    with pytest.raises(MetaAPIError):
        delete_object(object_id="120", token="t", client=graph, dry_run=False)
