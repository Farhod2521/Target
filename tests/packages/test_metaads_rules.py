"""The rule document Meta reads, and the four places a guess was wrong.

Everything here was checked against the v26.0 guides before it was written,
and each of these tests pins one thing that the obvious implementation would
have got wrong:

* ``subtype`` is not sent, and has not been supported for rule-built
  audiences since 2018
* a lead form's source type is ``lead``, not the ``lead_gen_form`` this
  product's own vocabulary would suggest
* an event is compared with ``eq`` on every source - the ``i_contains``
  examples in the website guide are matching *custom* event names, and on a
  standard one partial matching only catches more than was asked for
* the window lives inside the rule as seconds, and the top-level
  ``retention_days`` parameter is not sent at all

No network: every payload goes through a mock transport.
"""

import json
from urllib.parse import parse_qs

import httpx
from adskit import AudienceRuleDTO, ExternalRef
from metaads.audience_rules import (
    EVENTS,
    EXCLUDED_EVENTS,
    MAX_RETENTION_DAYS,
    SECONDS_PER_DAY,
    event_of,
    excluded_event_of,
    rule_document,
    supported_rules,
)
from metaads.audiences import create_rule_audience
from metaads.client import GraphClient


def rule(
    kind: str = "lead_form", action: str = "submitted", days: int = 30
) -> AudienceRuleDTO:
    levels = {"pixel": "pixel", "page": "page", "lead_form": "form"}
    return AudienceRuleDTO(
        kind=kind,  # type: ignore[arg-type]
        action=action,  # type: ignore[arg-type]
        source=ExternalRef(provider="meta", level=levels[kind], id="777"),  # type: ignore[arg-type]
        retention_days=days,
    )


def answering(payload: dict, *, seen: list[httpx.Request] | None = None) -> GraphClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return httpx.Response(200, json=payload)

    return GraphClient(
        token="t", client=httpx.Client(transport=httpx.MockTransport(handler))
    )


def only_rule(document: dict) -> dict:
    return document["inclusions"]["rules"][0]


def excluded_rule(document: dict) -> dict:
    return document["exclusions"]["rules"][0]


def matched(block: dict) -> dict:
    return block["filter"]["filters"][0]


# --- The shape -----------------------------------------------------------
def test_the_envelope_is_the_documented_one() -> None:
    body = rule_document(rule())

    assert set(body) == {"inclusions"}
    assert body["inclusions"]["operator"] == "or"
    assert len(body["inclusions"]["rules"]) == 1


def test_a_lead_form_is_filed_under_lead_and_not_its_own_name() -> None:
    """``lead_gen_form`` is what this product calls it everywhere else and
    is a name Meta does not know."""
    source = only_rule(rule_document(rule()))["event_sources"][0]

    assert source == {"id": "777", "type": "lead"}


def test_the_window_is_seconds_inside_the_rule() -> None:
    """The top-level ``retention_days`` parameter stops at 180, and two of
    the three sources look back further. Meta's own guide says the value is
    taken from here when the parameter is absent."""
    body = only_rule(rule_document(rule(days=90)))

    assert body["retention_seconds"] == 90 * SECONDS_PER_DAY
    assert "retention_days" not in body


def test_an_event_is_compared_with_eq_on_every_source() -> None:
    """The reference is explicit - *"if ``field`` set to ``event``, must use
    ``=``"* - and the website guide's ``i_contains`` examples match custom
    event names, where partial matching is the point.

    It matters most where it was wrong: ``i_contains "Purchase"`` also
    catches a custom ``SubscriptionPurchase``, and on the subtracting side
    that silently removes people who never bought anything.
    """
    operators = {
        matched(only_rule(rule_document(rule(kind=kind, action=action))))["operator"]
        for kind, action in EVENTS
    }

    assert operators == {"eq"}


def test_the_event_word_is_metas_own() -> None:
    body = only_rule(rule_document(rule(kind="page", action="engaged")))
    matched = body["filter"]["filters"][0]

    assert matched["field"] == "event"
    assert matched["value"] == "page_engaged"


def test_a_pair_meta_does_not_build_is_refused_by_name() -> None:
    """Unreachable through the domain, which checks first. Both halves
    travel because neither alone identifies the problem."""
    try:
        rule_document(rule(kind="lead_form", action="purchased"))
    except ValueError as exc:
        assert "lead_form" in str(exc)
        assert "purchased" in str(exc)
    else:
        raise AssertionError("a lead form does not report a purchase")


# --- What is on offer ----------------------------------------------------
def test_the_offer_is_derived_from_the_table_it_is_built_from() -> None:
    """A hand-written second list is the shape of bug that offers somebody
    a choice the create call then refuses."""
    offered = {
        (support.kind, action)
        for support in supported_rules()
        for action in support.actions
    }

    assert offered == set(EVENTS)


def test_each_source_carries_its_own_maximum() -> None:
    """Three different numbers, and the differences are large enough that a
    single figure would be wrong for two of them."""
    limits = {support.kind: support.max_retention_days for support in supported_rules()}

    assert limits == MAX_RETENTION_DAYS
    assert limits["lead_form"] < limits["pixel"] < limits["page"]


def test_video_is_not_offered() -> None:
    """Pinned so it cannot be added by accident.

    Meta builds video audiences and the current guides do not say how: the
    engagement source list has nine types and video is not among them, and
    the only JSON example is on pages archived at v2.6. Writing it from
    those would be the bet ``approximate_count`` lost.
    """
    assert "video" not in {support.kind for support in supported_rules()}


# --- On the wire ---------------------------------------------------------
def test_creating_sends_a_rule_and_no_subtype() -> None:
    """``subtype`` stopped being supported for these in September 2018.
    ``customer_file_source`` describes where personal data came from, and
    none is involved."""
    seen: list[httpx.Request] = []
    create_rule_audience(
        account_id="act_1",
        name="Formani tashlab ketganlar",
        rule=rule(action="abandoned"),
        token="t",
        client=answering({"id": "23849"}, seen=seen),
        dry_run=False,
    )

    form = parse_qs(seen[0].content.decode())
    assert "subtype" not in form
    assert "customer_file_source" not in form
    assert "retention_days" not in form
    assert "prefill" not in form
    sent = json.loads(form["rule"][0])
    assert only_rule(sent)["filter"]["filters"][0]["value"] == "lead_generation_dropoff"


def test_a_rehearsal_creates_nothing_and_names_itself_apart() -> None:
    """A second synthetic id, because the mirror keys rows on it: one id for
    both creates would have a rehearsed retargeting audience overwrite the
    rehearsed customer list."""
    seen: list[httpx.Request] = []
    created = create_rule_audience(
        account_id="act_1",
        name="Sinov",
        rule=rule(),
        token="t",
        client=answering({}, seen=seen),
        dry_run=True,
    )

    assert seen == []
    assert created.startswith("dryrun-")
    assert created != "dryrun-audience"


def test_the_event_word_travels_back_for_the_mirror() -> None:
    assert event_of(rule(kind="pixel", action="visited")) == "PageView"
    assert event_of(rule(kind="lead_form", action="opened")) == "lead_generation_opened"


# --- Subtraction ---------------------------------------------------------
#
# Three actions take a second group back out again, and the whole of that is
# an ``exclusions`` block beside the inclusions one. The tests below pin the
# two things that would be wrong silently rather than loudly: a block
# written when nobody asked for one, and two halves that do not agree about
# the source or the window they are talking about.
def test_an_action_that_only_gathers_writes_no_exclusions_block() -> None:
    """Absent rather than empty. Meta reads a block with no rules in it as a
    malformed document, not as "exclude nobody"."""
    assert set(rule_document(rule(kind="pixel", action="visited"))) == {"inclusions"}


def test_an_action_that_subtracts_writes_both_blocks() -> None:
    body = rule_document(rule(kind="pixel", action="visited_not_purchased"))

    assert set(body) == {"inclusions", "exclusions"}
    assert matched(only_rule(body))["value"] == "PageView"
    assert matched(excluded_rule(body))["value"] == "Purchase"


def test_both_halves_name_the_same_source_and_the_same_window() -> None:
    """The single window is what makes the label honest. "Visited in the
    last month and did not buy in the last year" is not a sentence a picker
    can put on a screen."""
    body = rule_document(rule(kind="page", action="engaged_not_messaged", days=90))

    included, excluded = only_rule(body), excluded_rule(body)
    assert included["event_sources"] == excluded["event_sources"]
    assert included["retention_seconds"] == excluded["retention_seconds"]
    assert excluded["retention_seconds"] == 90 * SECONDS_PER_DAY


def test_the_exclusions_block_has_the_same_shape_as_the_inclusions_one() -> None:
    body = rule_document(rule(kind="pixel", action="added_to_cart_not_purchased"))

    assert body["exclusions"]["operator"] == "or"
    assert len(body["exclusions"]["rules"]) == 1
    assert set(excluded_rule(body)) == set(only_rule(body))


def test_every_subtraction_has_something_to_subtract_from() -> None:
    """A pair that says who comes out and not who goes in is an audience of
    nobody, built without a single error anywhere."""
    assert set(EXCLUDED_EVENTS) <= set(EVENTS)


def test_a_lead_form_subtracts_nothing_because_meta_already_ships_it() -> None:
    """ "Opened it and did not send it" is not built out of two blocks here.
    Meta gives it as one event, and the long road would be the same
    audience."""
    assert not [kind for kind, _action in EXCLUDED_EVENTS if kind == "lead_form"]
    assert EVENTS[("lead_form", "abandoned")] == "lead_generation_dropoff"


def test_the_excluded_word_travels_back_and_empty_is_an_answer() -> None:
    """Empty means nobody is taken out, never that nothing is known - the
    mirror stores this beside ``event_raw`` and no screen may read the two
    cases as the same."""
    assert excluded_event_of(rule(kind="pixel", action="visited_not_purchased")) == (
        "Purchase"
    )
    assert excluded_event_of(rule(kind="pixel", action="visited")) == ""
    assert excluded_event_of(rule(kind="lead_form", action="submitted")) == ""


def test_creating_a_subtracting_audience_sends_both_blocks() -> None:
    seen: list[httpx.Request] = []
    create_rule_audience(
        account_id="act_1",
        name="Kirgan, xarid qilmagan",
        rule=rule(kind="pixel", action="visited_not_purchased"),
        token="t",
        client=answering({"id": "23850"}, seen=seen),
        dry_run=False,
    )

    sent = json.loads(parse_qs(seen[0].content.decode())["rule"][0])
    assert matched(only_rule(sent))["value"] == "PageView"
    assert matched(excluded_rule(sent))["value"] == "Purchase"
