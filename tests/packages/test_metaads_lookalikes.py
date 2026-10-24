"""The lookalike create, and the five places a guess would have been wrong.

Everything here was checked against the v26.0 guides, and each of these
pins one thing the obvious implementation would have got wrong - three of
them because the *neighbouring* create does the opposite:

* ``subtype`` **is** sent, and is required. The rule audiences do not send
  one and have not been able to since 2018; reading that as a rule about
  ``subtype`` rather than about those audiences would have produced a
  create Meta refuses.
* ``origin_audience_id`` is a **top-level** field, not a member of
  ``lookalike_spec``, although it reads as though it belongs there.
* ``origin_audience_id`` is **not readable** - it does not appear in the
  Custom Audience node's field list. Nothing here parses it back, and the
  test below proves the read carries no such field to parse.
* ``ratio`` runs 0.01 to 0.20, twice as far as Meta's own interface
  offers; the three rungs stop where the interface does.
* ``retention_days`` does not apply at all - Meta documents it as a
  customer-file field.

No network: every payload goes through a mock transport.
"""

import json
from typing import get_args
from urllib.parse import parse_qs

import httpx
import pytest
from adskit import ExternalRef, LookalikeSpecDTO
from adskit.refs import AudienceBreadth
from metaads.audiences import AUDIENCE_FIELDS, create_lookalike_audience
from metaads.client import GraphClient
from metaads.dto import CustomAudienceRow
from metaads.lookalikes import RATIOS, SUBTYPE_LOOKALIKE, lookalike_spec, ratio_of


def spec(breadth: str = "balanced", country: str = "UZ") -> LookalikeSpecDTO:
    return LookalikeSpecDTO(
        origin=ExternalRef(provider="meta", level="audience", id="seed-1"),
        breadth=breadth,  # type: ignore[arg-type]
        country=country,
    )


def answering(payload: dict, *, seen: list[httpx.Request] | None = None) -> GraphClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return httpx.Response(200, json=payload)

    return GraphClient(
        token="t", client=httpx.Client(transport=httpx.MockTransport(handler))
    )


def posted(request: httpx.Request) -> dict[str, str]:
    return {
        key: values[0] for key, values in parse_qs(request.content.decode()).items()
    }


# --- The spec ------------------------------------------------------------
def test_the_spec_holds_the_width_and_the_country_and_nothing_else() -> None:
    """The seed is not in here. It looks as though it belongs and it goes
    beside ``name`` instead - see the create below."""
    assert lookalike_spec(spec()) == {"ratio": 0.05, "country": "UZ"}


def test_the_country_is_upper_cased_rather_than_trusted() -> None:
    """Meta matches the code exactly and refuses a lower-case one with a
    message naming the parameter and not the case."""
    assert lookalike_spec(spec(country="uz"))["country"] == "UZ"


def test_the_three_widths_stop_where_metas_own_interface_does() -> None:
    """The API accepts 0.01 to 0.20. Ads Manager's slider stops at the
    tenth, and a value nobody can see the result of anywhere is a value
    nobody can check."""
    assert sorted(RATIOS.values()) == [0.01, 0.05, 0.10]
    assert max(RATIOS.values()) <= 0.20


def test_every_domain_width_has_a_number_and_no_number_has_two_widths() -> None:
    """The table is the whole of the mapping, so a width added to the
    literal and forgotten here would fail at the create rather than
    silently pick somebody else's ratio."""

    assert set(RATIOS) == set(get_args(AudienceBreadth))
    assert len(set(RATIOS.values())) == len(RATIOS)


def test_the_ratio_is_carried_back_as_text_with_two_places() -> None:
    """Text because nothing computes with it: it is Meta's spelling of a
    choice, kept beside the domain's word. Two places always, so ``0.1``
    and ``0.10`` cannot both appear for the same choice."""
    assert ratio_of(spec(breadth="broad")) == "0.10"
    assert ratio_of(spec(breadth="closest")) == "0.01"


# --- The create ----------------------------------------------------------
def test_the_subtype_is_sent_here_although_the_rule_create_sends_none() -> None:
    """The 2018 change was about website and engagement audiences. Reading
    it as a rule about ``subtype`` would produce a create Meta refuses."""
    seen: list[httpx.Request] = []
    create_lookalike_audience(
        account_id="act_1",
        name="Similar",
        spec=spec(),
        token="t",
        client=answering({"id": "9"}, seen=seen),
        dry_run=False,
    )

    assert posted(seen[0])["subtype"] == SUBTYPE_LOOKALIKE == "LOOKALIKE"


def test_the_seed_is_a_top_level_field_and_not_part_of_the_spec() -> None:
    seen: list[httpx.Request] = []
    create_lookalike_audience(
        account_id="act_1",
        name="Similar",
        spec=spec(),
        token="t",
        client=answering({"id": "9"}, seen=seen),
        dry_run=False,
    )
    body = posted(seen[0])

    assert body["origin_audience_id"] == "seed-1"
    assert "origin_audience_id" not in json.loads(body["lookalike_spec"])


def test_neither_the_file_source_nor_the_window_is_sent() -> None:
    """Two absences with two different reasons. ``customer_file_source``
    describes where personal data came from and none is involved;
    ``retention_days`` is documented as a customer-file field."""
    seen: list[httpx.Request] = []
    create_lookalike_audience(
        account_id="act_1",
        name="Similar",
        spec=spec(),
        token="t",
        client=answering({"id": "9"}, seen=seen),
        dry_run=False,
    )
    body = posted(seen[0])

    assert "customer_file_source" not in body
    assert "retention_days" not in body


def test_the_spec_travels_as_json_rather_than_as_a_python_repr() -> None:
    seen: list[httpx.Request] = []
    create_lookalike_audience(
        account_id="act_1",
        name="Similar",
        spec=spec(breadth="closest", country="UZ"),
        token="t",
        client=answering({"id": "9"}, seen=seen),
        dry_run=False,
    )

    assert json.loads(posted(seen[0])["lookalike_spec"]) == {
        "ratio": 0.01,
        "country": "UZ",
    }


def test_a_rehearsal_makes_no_call_and_answers_its_own_id() -> None:
    """A third rehearsal id, and it earns its line: three creates land in
    one mirror keyed on the id, so a shared one would have each rehearsal
    quietly replacing the last."""
    seen: list[httpx.Request] = []
    made = create_lookalike_audience(
        account_id="act_1",
        name="Similar",
        spec=spec(),
        token="t",
        client=answering({"id": "9"}, seen=seen),
    )

    assert seen == []
    assert made.startswith("dryrun-lookalike")


# --- The read ------------------------------------------------------------
def test_the_read_asks_for_the_spec_and_cannot_ask_for_the_seed() -> None:
    """``origin_audience_id`` is a creation parameter and not a field.
    Asking for it would get a confident nothing - the same shape of bug
    ``approximate_count`` was."""
    assert "lookalike_spec" in AUDIENCE_FIELDS
    assert "origin_audience_id" not in AUDIENCE_FIELDS


@pytest.mark.parametrize(
    ("subtype", "expected"),
    [
        ("CUSTOM", True),
        ("WEBSITE", True),
        ("ENGAGEMENT", True),
        ("lookalike", False),
        ("LOOKALIKE", False),
        ("SOMETHING_NEW", True),
    ],
)
def test_only_an_audience_that_is_already_one_refuses_to_be_a_seed(
    subtype: str, expected: bool
) -> None:
    """The opposite direction from ``accepts_members``, and deliberately:
    nothing personal moves either way here, so an unfamiliar subtype is let
    through rather than hidden with nothing to explain it."""
    assert CustomAudienceRow(id="1", subtype=subtype).can_seed is expected


def test_being_uploadable_and_being_a_seed_are_different_questions() -> None:
    """The easiest mistake to make here. ``accepts_members`` is false for
    a retargeting audience, which is a perfectly good seed."""
    row = CustomAudienceRow(id="1", subtype="WEBSITE")

    assert row.accepts_members is False
    assert row.can_seed is True
