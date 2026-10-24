"""Meta calling us: the handshake, the signature, and the batch.

A public, unauthenticated, CSRF-exempt endpoint. Everything here is what
stands between it and anybody who knows the URL, which is why these tests
are about refusals as much as about parsing.
"""

import hmac
import json
from datetime import UTC, datetime
from hashlib import sha256

import pytest
from metaads.webhooks import (
    LeadNotice,
    leadgen_notices,
    verification_challenge,
    verify_signature,
)

SECRET = "app-secret"


def signed(body: bytes, secret: str = SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, sha256).hexdigest()


def delivery(*changes: dict, page: str = "31415", obj: str = "page") -> dict:
    return {
        "object": obj,
        "entry": [{"id": page, "time": 1_770_000_000, "changes": list(changes)}],
    }


def leadgen(**value: object) -> dict:
    return {"field": "leadgen", "value": {"leadgen_id": "9001", **value}}


# --- The signature -------------------------------------------------------
def test_a_body_meta_signed_is_accepted() -> None:
    body = json.dumps(delivery(leadgen())).encode()

    assert verify_signature(body=body, header=signed(body), app_secret=SECRET)


def test_a_body_changed_after_signing_is_refused() -> None:
    """One byte. The whole point of signing the raw bytes rather than the
    re-serialised JSON is that this cannot be smuggled past."""
    body = json.dumps(delivery(leadgen())).encode()
    header = signed(body)

    assert not verify_signature(
        body=body.replace(b"9001", b"9002"), header=header, app_secret=SECRET
    )


def test_a_signature_from_a_different_secret_is_refused() -> None:
    """What a rotated app secret looks like, and what an attacker who
    guessed the payload but not the key looks like."""
    body = b"{}"

    assert not verify_signature(
        body=body, header=signed(body, "somebody-elses"), app_secret=SECRET
    )


@pytest.mark.parametrize(
    "header",
    [
        pytest.param("", id="absent"),
        pytest.param("deadbeef", id="no-algorithm"),
        # An attacker who chooses the algorithm chooses a weak one.
        pytest.param("sha1=deadbeef", id="weaker-algorithm"),
        pytest.param("sha256=", id="empty-digest"),
    ],
)
def test_a_header_that_is_not_a_sha256_signature_is_refused(header: str) -> None:
    assert not verify_signature(body=b"{}", header=header, app_secret=SECRET)


def test_a_deployment_with_no_app_secret_refuses_everything() -> None:
    """Rather than accepting everything, which is what an empty key does to
    a comparison written the obvious way."""
    assert not verify_signature(body=b"{}", header=signed(b"{}", ""), app_secret="")


# --- The handshake -------------------------------------------------------
def test_the_right_token_gets_the_challenge_back() -> None:
    answer = verification_challenge(
        mode="subscribe",
        token="shared",
        challenge="1158201444",
        expected_token="shared",
    )

    assert answer == "1158201444"


@pytest.mark.parametrize(
    ("mode", "token", "expected"),
    [
        pytest.param("subscribe", "wrong", "shared", id="wrong-token"),
        pytest.param("unsubscribe", "shared", "shared", id="not-a-subscription"),
        # Nothing configured. Echoing the challenge here would register the
        # webhook for whoever asked first.
        pytest.param("subscribe", "", "", id="nothing-configured"),
    ],
)
def test_anything_else_gets_silence(mode: str, token: str, expected: str) -> None:
    """Empty means "do not echo". A body explaining what was wrong would
    tell whoever guessed how close they got."""
    assert (
        verification_challenge(
            mode=mode, token=token, challenge="1158201444", expected_token=expected
        )
        == ""
    )


# --- The payload ---------------------------------------------------------
def test_one_lead_is_read_out_whole() -> None:
    payload = delivery(
        leadgen(
            page_id="31415",
            form_id="777",
            ad_id="222",
            adgroup_id="333",
            created_time=1_770_000_000,
        )
    )

    (notice,) = leadgen_notices(payload)

    assert notice == LeadNotice(
        page_external_id="31415",
        leadgen_external_id="9001",
        form_external_id="777",
        ad_external_id="222",
        adset_external_id="333",
        created_at=datetime(2026, 2, 2, 2, 40, tzinfo=UTC),
    )


def test_meta_batches_and_a_handler_written_for_one_lead_drops_the_rest() -> None:
    """Several pages per delivery and several leads per page. Nothing
    anywhere says a handler missed them."""
    payload = {
        "object": "page",
        "entry": [
            {"id": "1", "changes": [leadgen(leadgen_id="a"), leadgen(leadgen_id="b")]},
            {"id": "2", "changes": [leadgen(leadgen_id="c")]},
        ],
    }

    notices = leadgen_notices(payload)

    assert [n.leadgen_external_id for n in notices] == ["a", "b", "c"]
    assert [n.page_external_id for n in notices] == ["1", "1", "2"]


def test_the_page_id_falls_back_to_the_entry_meta_omits_it_from() -> None:
    (notice,) = leadgen_notices(delivery(leadgen(), page="31415"))

    assert notice.page_external_id == "31415"


def test_the_webhook_calls_it_adgroup_and_the_graph_read_calls_it_adset() -> None:
    """Meta's own inconsistency. Both are accepted, because the ad set is
    what the agent needs and losing it loses CPQL."""
    (adgroup,) = leadgen_notices(delivery(leadgen(adgroup_id="333")))
    (adset,) = leadgen_notices(delivery(leadgen(adset_id="333")))

    assert adgroup.adset_external_id == adset.adset_external_id == "333"


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param({"object": "instagram", "entry": []}, id="another-product"),
        pytest.param(delivery({"field": "feed", "value": {}}), id="another-field"),
        pytest.param({"object": "page"}, id="no-entries"),
        pytest.param({"object": "page", "entry": "nonsense"}, id="wrong-shape"),
        pytest.param({}, id="empty"),
    ],
)
def test_a_delivery_this_product_did_not_ask_for_is_skipped(payload: dict) -> None:
    """Meta sends everything the app is subscribed to down one URL. A
    webhook we did not ask for is somebody else's feature arriving early,
    not an error."""
    assert leadgen_notices(payload) == ()


def test_a_notice_naming_no_lead_is_dropped_rather_than_stored() -> None:
    """The leadgen id is the only field the second call needs. A row that
    can never be resolved would be a permanent failure in a table that is
    retried."""
    payload = delivery({"field": "leadgen", "value": {"page_id": "31415"}})

    assert leadgen_notices(payload) == ()


@pytest.mark.parametrize(
    "raw",
    [
        pytest.param("not-a-number", id="text"),
        pytest.param(None, id="absent"),
        pytest.param(True, id="boolean"),
        pytest.param(10**20, id="out-of-range"),
    ],
)
def test_an_unusable_timestamp_costs_the_time_and_not_the_lead(raw: object) -> None:
    (notice,) = leadgen_notices(delivery(leadgen(created_time=raw)))

    assert notice.created_at is None
    assert notice.leadgen_external_id == "9001"


def test_the_time_that_does_arrive_is_aware() -> None:
    """A naive datetime crossing into Django is stored as if it were local
    time, which moves a lead by hours."""
    (notice,) = leadgen_notices(delivery(leadgen(created_time=1_770_000_000)))

    assert notice.created_at is not None
    assert notice.created_at.tzinfo is not None
