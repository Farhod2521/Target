"""Custom audiences on Meta: the object, and the list posted into it.

Two modules under test and one reason they are apart - ``audiences`` makes
and removes a container, ``customer_lists`` fills it, and only the second
ever handles anything about a person.

Three of Meta's answers are pinned here because a guess would have been
wrong about each: the count is a *range* and the single figure was retired,
the timestamps are unix integers where the rest of this package gets ISO
strings, and the two statuses are codes with no published vocabulary.

No network: every payload is served through a mock transport.
"""

import json

import httpx
import pytest
from adskit import AudienceMemberDTO, ExternalRef
from metaads.adapter import MetaAudienceSources
from metaads.audience_rows import RAW_KEY
from metaads.audiences import (
    AUDIENCE_FIELDS,
    CUSTOMER_FILE_SOURCE,
    SUBTYPE_CUSTOM,
    create_audience,
    delete_audience,
    list_audiences,
    terms_url,
)
from metaads.client import GraphClient
from metaads.customer_lists import MAX_MEMBERS_PER_CALL, add_members, remove_members
from metaads.dto import CustomAudienceRow
from metaads.parsing import parsed

AUDIENCE = {
    "id": "23848",
    "name": "Do'kon mijozlari",
    "description": "2026 yil mijozlari",
    "subtype": "CUSTOM",
    "customer_file_source": "USER_PROVIDED_ONLY",
    "approximate_count_lower_bound": 1000,
    "approximate_count_upper_bound": 1400,
    "operation_status": {"code": 200, "description": "Normal"},
    "delivery_status": {"code": 200, "description": "This audience is ready for use"},
    "data_source": {"type": "USER_PROVIDED_ONLY", "sub_type": "ANYTHING"},
    "time_created": 1_767_225_600,
    "time_updated": 1_767_312_000,
}

DIGEST = "a" * 64
OTHER = "b" * 64


def answering(payload: dict, *, seen: list[httpx.Request] | None = None) -> GraphClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return httpx.Response(200, json=payload)

    return GraphClient(
        token="t", client=httpx.Client(transport=httpx.MockTransport(handler))
    )


# --- What is asked for ---------------------------------------------------
def test_the_retired_count_field_is_not_asked_for() -> None:
    """``approximate_count`` was replaced by a pair of bounds, exactly as
    the interest catalogue's ``audience_size`` was. Asking for the old name
    gets a confident nothing back."""
    assert "approximate_count_lower_bound" in AUDIENCE_FIELDS
    assert "approximate_count_upper_bound" in AUDIENCE_FIELDS
    assert "approximate_count," not in AUDIENCE_FIELDS


def test_the_fields_that_say_whether_it_is_usable_are_asked_for() -> None:
    for field in ("operation_status", "delivery_status", "subtype"):
        assert field in AUDIENCE_FIELDS


# --- What comes back -----------------------------------------------------
def test_a_unix_timestamp_is_read_as_a_date() -> None:
    """Everywhere else in this package Meta answers ISO strings under
    ``created_time``; here it answers seconds under ``time_created``."""
    row = parsed(CustomAudienceRow, AUDIENCE)

    assert row.time_created is not None
    assert row.time_created.year == 2026


def test_the_count_is_a_range_and_still_counting_is_not_zero() -> None:
    """Meta answers ``-1`` for both bounds while it works. Passed straight
    on, that reads as a negative number of people; read as zero it would
    read as an empty audience, which is the opposite advice."""
    counting = parsed(
        CustomAudienceRow,
        {
            **AUDIENCE,
            "approximate_count_lower_bound": -1,
            "approximate_count_upper_bound": -1,
        },
    )

    assert counting.count_lower == 0
    assert counting.count_upper == 0


def test_only_a_customer_file_accepts_members() -> None:
    """Every other subtype is one Meta fills in itself, and an unfamiliar
    one answers no - the safe direction, because the cost is a missing
    button rather than personal data posted somewhere it did not belong."""
    assert parsed(CustomAudienceRow, AUDIENCE).accepts_members

    for subtype in ("WEBSITE", "ENGAGEMENT", "LOOKALIKE", "SOMETHING_NEW", ""):
        row = parsed(CustomAudienceRow, {**AUDIENCE, "subtype": subtype})
        assert not row.accepts_members


def test_an_unfamiliar_delivery_code_reads_as_not_ready() -> None:
    """The full vocabulary is unpublished. Anything but the documented
    ready code means "not yet", and the code and Meta's own sentence travel
    whole for whoever has to find out what an unfamiliar one meant."""
    assert parsed(CustomAudienceRow, AUDIENCE).is_ready

    stalled = parsed(
        CustomAudienceRow,
        {**AUDIENCE, "delivery_status": {"code": 414, "description": "Not ready"}},
    )
    assert not stalled.is_ready
    assert stalled.delivery_status.description == "Not ready"


def test_the_list_reaches_the_account_edge() -> None:
    seen: list[httpx.Request] = []
    rows = list_audiences(
        account_id="act_1", token="t", client=answering({"data": [AUDIENCE]}, seen=seen)
    )

    assert [row.id for row in rows] == ["23848"]
    assert "act_1/customaudiences" in str(seen[0].url)


# --- The two documents, in whichever shape they arrive -------------------
#
# Meta's own reference declares ``rule`` a **string** - a JSON document
# serialised into one - and ``lookalike_spec`` an object, side by side in
# the same payload. Both shapes have been seen in the wild for the first,
# so neither is something this package may assume.
#
# What made the assumption expensive rather than merely wrong is
# ``parsed_all``: it is all-or-nothing, so one unreadable row takes the
# whole account's list with it, and the sync above swallows that into a log
# line. The tests below are about that blast radius, not about the field.
A_RULE = {
    "inclusions": {
        "operator": "or",
        "rules": [
            {
                "event_sources": [{"id": "px-1", "type": "pixel"}],
                "retention_seconds": 2_592_000,
                "filter": {
                    "operator": "and",
                    "filters": [
                        {"field": "event", "operator": "eq", "value": "PageView"}
                    ],
                },
            }
        ],
    }
}


def test_a_rule_sent_as_text_is_read_as_the_document() -> None:
    row = parsed(CustomAudienceRow, {**AUDIENCE, "rule": json.dumps(A_RULE)})

    assert row.rule == A_RULE


def test_a_rule_sent_as_an_object_is_kept_as_it_is() -> None:
    """The other shape, and it must go on working untouched."""
    row = parsed(CustomAudienceRow, {**AUDIENCE, "rule": A_RULE})

    assert row.rule == A_RULE


def test_a_lookalike_spec_sent_as_text_is_read_the_same_way() -> None:
    """Declared an object and parsed like the one beside it anyway. Meta
    says of this field only that it is "generated", so what comes back is
    the one document here nobody has a schema for."""
    spec = {"ratio": 0.01, "country": "UZ"}

    row = parsed(CustomAudienceRow, {**AUDIENCE, "lookalike_spec": json.dumps(spec)})

    assert row.lookalike_spec == spec


def test_a_document_nothing_can_read_is_kept_rather_than_dropped() -> None:
    """Dropped, it would say "this is a customer list" about an audience
    that plainly is not - the one question anything asks of this field is
    whether there is a document at all. Kept, the text is still there for
    whoever has to find out what arrived."""
    row = parsed(CustomAudienceRow, {**AUDIENCE, "rule": "not json at all"})

    assert row.rule == {RAW_KEY: "not json at all"}


def test_an_empty_document_is_an_empty_one() -> None:
    """A customer list has no rule, and Meta spells that absence both ways."""
    assert parsed(CustomAudienceRow, {**AUDIENCE, "rule": ""}).rule == {}


def test_one_unreadable_rule_does_not_take_the_account_with_it() -> None:
    """The failure this whole section exists for.

    ``parsed_all`` is all-or-nothing by design, so without the coercion a
    single audience somebody built in Ads Manager - which is exactly the
    row that carries a rule - stops the account's entire list from being
    read. The sync catches that as a provider refusal and logs it, so the
    list simply stops moving and no screen says why.
    """
    built_by_hand = {
        **AUDIENCE,
        "id": "23849",
        "subtype": "WEBSITE",
        "rule": json.dumps(A_RULE),
    }

    rows = list_audiences(
        account_id="act_1",
        token="t",
        client=answering({"data": [AUDIENCE, built_by_hand]}),
    )

    assert [row.id for row in rows] == ["23848", "23849"]
    assert rows[1].rule == A_RULE


# --- Creating and deleting ----------------------------------------------
def test_creating_sends_the_subtype_and_the_data_source() -> None:
    """``customer_file_source`` looks optional and is not: Meta accepts the
    create without it and then refuses the upload, one spreadsheet later."""
    seen: list[httpx.Request] = []
    created = create_audience(
        account_id="act_1",
        name="Mijozlar",
        description="izoh",
        token="t",
        client=answering({"id": "999"}, seen=seen),
        dry_run=False,
    )

    assert created == "999"
    body = seen[0].content.decode()
    assert f"subtype={SUBTYPE_CUSTOM}" in body
    assert CUSTOMER_FILE_SOURCE in body


def test_a_rehearsal_creates_nothing_and_reaches_nobody() -> None:
    seen: list[httpx.Request] = []
    created = create_audience(
        account_id="act_1",
        name="Mijozlar",
        token="t",
        client=answering({"id": "999"}, seen=seen),
    )

    assert created.startswith("dryrun-")
    assert seen == []


def test_deleting_a_rehearsed_id_never_reaches_the_provider() -> None:
    """A cleanup walking a list of refs must not be where a synthetic id
    first reaches Meta - and refusing loudly instead would abort the
    cleanup partway through."""
    seen: list[httpx.Request] = []
    assert delete_audience(
        audience_id="dryrun-audience",
        token="t",
        client=answering({"success": True}, seen=seen),
        dry_run=False,
    )
    assert seen == []


def test_the_terms_link_names_the_account() -> None:
    """Acceptance is per person and per account. An advertiser with two who
    opens the bare page agrees on whichever one Meta picks, then meets the
    same refusal with nothing to say they agreed to the wrong thing."""
    assert "act=1234" in terms_url("act_1234")
    assert "act=" not in terms_url()


# --- The upload ----------------------------------------------------------
def members(count: int) -> list[AudienceMemberDTO]:
    return [AudienceMemberDTO(email=DIGEST) for _ in range(count)]


def posted(request: httpx.Request) -> dict:
    """The ``payload`` field of a form-encoded upload, decoded."""
    from urllib.parse import parse_qs

    form = parse_qs(request.content.decode())
    return json.loads(form["payload"][0])


def test_the_schema_holds_only_the_keys_the_list_actually_has() -> None:
    """A column nobody filled would be an empty string on every row - bytes
    a person reading the request has to rule out, for nothing."""
    seen: list[httpx.Request] = []
    add_members(
        audience_id="23848",
        members=[AudienceMemberDTO(email=DIGEST, phone=OTHER)],
        token="t",
        client=answering({"audience_id": "23848", "num_received": 1}, seen=seen),
        dry_run=False,
    )

    assert posted(seen[0])["schema"] == ["EMAIL", "PHONE"]


def test_a_row_missing_a_chosen_key_sends_an_empty_string_for_it() -> None:
    seen: list[httpx.Request] = []
    add_members(
        audience_id="23848",
        members=[
            AudienceMemberDTO(email=DIGEST, phone=OTHER),
            AudienceMemberDTO(email=DIGEST),
        ],
        token="t",
        client=answering({"audience_id": "23848", "num_received": 2}, seen=seen),
        dry_run=False,
    )

    assert posted(seen[0])["data"] == [[DIGEST, OTHER], [DIGEST, ""]]


def test_nothing_but_digests_is_ever_on_the_wire() -> None:
    """**The guarantee, checked at the transport.**

    Not "the code hashes first" - that is what the type enforces. This is
    the other end: whatever ends up in the request body, none of it looks
    like a person.
    """
    seen: list[httpx.Request] = []
    add_members(
        audience_id="23848",
        members=[AudienceMemberDTO(email=DIGEST, phone=OTHER, first_name="c" * 64)],
        token="t",
        client=answering({"audience_id": "23848", "num_received": 1}, seen=seen),
        dry_run=False,
    )

    for row in posted(seen[0])["data"]:
        for value in row:
            assert value == "" or (len(value) == 64 and value.isalnum())


def test_a_long_list_is_split_and_the_counts_are_summed() -> None:
    """Splitting is this package's job, not the caller's: a caller doing it
    would be a caller that had learned Meta's batching rules."""
    seen: list[httpx.Request] = []
    answer = add_members(
        audience_id="23848",
        members=members(MAX_MEMBERS_PER_CALL + 5),
        token="t",
        client=answering(
            {"audience_id": "23848", "num_received": 10, "session_id": 7}, seen=seen
        ),
        dry_run=False,
    )

    assert len(seen) == 2
    # Ten per batch in this fake, two batches - the point being that the
    # figure describes the whole list rather than the last request.
    assert answer.num_received == 20


def test_a_split_upload_ties_its_parts_together_with_one_session() -> None:
    from urllib.parse import parse_qs

    seen: list[httpx.Request] = []
    add_members(
        audience_id="23848",
        members=members(MAX_MEMBERS_PER_CALL + 1),
        token="t",
        client=answering({"audience_id": "23848", "num_received": 1}, seen=seen),
        dry_run=False,
    )

    sessions = [
        json.loads(parse_qs(request.content.decode())["session"][0]) for request in seen
    ]
    assert {session["session_id"] for session in sessions} == {
        sessions[0]["session_id"]
    }
    assert [session["batch_seq"] for session in sessions] == [1, 2]
    assert sessions[-1]["last_batch_flag"] is True


def test_a_single_upload_invents_no_session() -> None:
    """An identifier that names one request names nothing, and it would end
    up in an audit trail as though it did."""
    from urllib.parse import parse_qs

    seen: list[httpx.Request] = []
    add_members(
        audience_id="23848",
        members=members(3),
        token="t",
        client=answering({"audience_id": "23848", "num_received": 3}, seen=seen),
        dry_run=False,
    )

    assert "session" not in parse_qs(seen[0].content.decode())


def test_the_refused_rows_are_carried_back() -> None:
    """The number nobody looks at and the only warning a normalisation rule
    applied wrongly ever produces."""
    answer = add_members(
        audience_id="23848",
        members=members(5),
        token="t",
        client=answering(
            {
                "audience_id": "23848",
                "num_received": 3,
                "num_invalid_entries": 2,
                "invalid_entry_samples": {"0": "invalid hash"},
            }
        ),
        dry_run=False,
    )

    assert answer.num_invalid_entries == 2
    assert answer.invalid_entry_samples == {"0": "invalid hash"}


def test_a_rehearsed_upload_reports_the_rows_it_would_have_sent() -> None:
    """Zero from a rehearsal of nine hundred rows reads as a problem with
    the nine hundred rows."""
    seen: list[httpx.Request] = []
    answer = add_members(
        audience_id="23848",
        members=members(900),
        token="t",
        client=answering({}, seen=seen),
    )

    assert answer.num_received == 900
    assert seen == []


def test_an_empty_list_asks_nothing() -> None:
    """A POST with an empty schema is refused by Meta with an error about a
    parameter rather than with the truth, which is that there was nobody to
    upload."""
    seen: list[httpx.Request] = []
    answer = add_members(
        audience_id="23848",
        members=[],
        token="t",
        client=answering({}, seen=seen),
        dry_run=False,
    )

    assert answer.num_received == 0
    assert seen == []


# --- Taking people back out ----------------------------------------------
def test_a_withdrawal_is_a_real_delete() -> None:
    """**The verb is the evidence.**

    Meta also accepts a POST carrying ``?method=delete``, and this package
    refuses it here for the same reason it refuses it for objects: the
    access log where somebody's personal data was withdrawn is what answers
    an erasure audit, and a removal recorded as a write answers nothing.
    """
    seen: list[httpx.Request] = []
    remove_members(
        audience_id="23848",
        members=[AudienceMemberDTO(email=DIGEST)],
        token="t",
        client=answering({"audience_id": "23848", "num_received": 1}, seen=seen),
        dry_run=False,
    )

    assert seen[0].method == "DELETE"
    assert seen[0].url.path.endswith("/23848/users")
    assert "method" not in seen[0].url.params


def test_a_withdrawal_carries_its_rows_in_the_body() -> None:
    """Ten thousand digests of sixty-four characters is most of a megabyte.
    In a query string that is truncated by something in the middle long
    before Meta reads it; the token stays in the query, as it does on every
    other call here."""
    seen: list[httpx.Request] = []
    remove_members(
        audience_id="23848",
        members=[AudienceMemberDTO(email=DIGEST, phone=OTHER)],
        token="t",
        client=answering({"audience_id": "23848", "num_received": 1}, seen=seen),
        dry_run=False,
    )

    assert "payload" not in seen[0].url.params
    assert seen[0].url.params["access_token"] == "t"
    assert posted(seen[0])["schema"] == ["EMAIL", "PHONE"]


def test_a_withdrawal_sends_nothing_but_digests() -> None:
    seen: list[httpx.Request] = []
    remove_members(
        audience_id="23848",
        members=[AudienceMemberDTO(email=DIGEST, first_name="c" * 64)],
        token="t",
        client=answering({"audience_id": "23848", "num_received": 1}, seen=seen),
        dry_run=False,
    )

    for row in posted(seen[0])["data"]:
        for value in row:
            assert value == "" or (len(value) == 64 and value.isalnum())


def test_a_split_withdrawal_invents_no_session() -> None:
    """A session exists so Meta can report several requests as one upload.
    There is no such aggregate on the way out, and an identifier that names
    nothing would end up in an audit row."""
    seen: list[httpx.Request] = []
    remove_members(
        audience_id="23848",
        members=members(MAX_MEMBERS_PER_CALL + 1),
        token="t",
        client=answering({"audience_id": "23848", "num_received": 1}, seen=seen),
        dry_run=False,
    )

    from urllib.parse import parse_qs

    assert len(seen) == 2
    for request in seen:
        assert "session" not in parse_qs(request.content.decode())


def test_a_long_withdrawal_is_split_and_the_counts_are_summed() -> None:
    seen: list[httpx.Request] = []
    answer = remove_members(
        audience_id="23848",
        members=members(MAX_MEMBERS_PER_CALL + 5),
        token="t",
        client=answering({"audience_id": "23848", "num_received": 7}, seen=seen),
        dry_run=False,
    )

    assert len(seen) == 2
    assert answer.num_received == 14


def test_a_rehearsed_withdrawal_reaches_nobody() -> None:
    seen: list[httpx.Request] = []
    answer = remove_members(
        audience_id="23848",
        members=[AudienceMemberDTO(email=DIGEST)],
        token="t",
        client=answering({}, seen=seen),
        dry_run=True,
    )

    assert seen == []
    assert answer.num_received == 1


def test_withdrawing_from_a_rehearsed_id_never_reaches_the_provider() -> None:
    """A cleanup walking a list of refs must not be where a synthetic id
    first meets Meta - the same guard the object delete has."""
    seen: list[httpx.Request] = []
    remove_members(
        audience_id="dryrun-audience",
        members=[AudienceMemberDTO(email=DIGEST)],
        token="t",
        client=answering({}, seen=seen),
        dry_run=False,
    )

    assert seen == []


def test_the_two_directions_build_the_same_schema() -> None:
    """One piece of code on purpose. Written twice they would drift, and
    the drift would take somebody out of a column they were never put
    into - with nobody reporting an error."""
    people = [AudienceMemberDTO(email=DIGEST, city="d" * 64)]
    added: list[httpx.Request] = []
    removed: list[httpx.Request] = []
    reply = {"audience_id": "23848", "num_received": 1}

    add_members(
        audience_id="23848",
        members=people,
        token="t",
        client=answering(reply, seen=added),
        dry_run=False,
    )
    remove_members(
        audience_id="23848",
        members=people,
        token="t",
        client=answering(reply, seen=removed),
        dry_run=False,
    )

    assert posted(added[0]) == posted(removed[0])


# --- Through the port ----------------------------------------------------
def test_the_adapter_answers_the_domains_own_shape() -> None:
    ref = ExternalRef(provider="meta", level="account", id="act_1")
    port = MetaAudienceSources()

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(
            "metaads.adapter.read_audiences",
            lambda **_kw: [parsed(CustomAudienceRow, AUDIENCE)],
        )
        found = port.list_audiences(account=ref, token="t")

    assert len(found) == 1
    dto = found[0]
    assert dto.ref.level == "audience"
    assert dto.ref.id == "23848"
    assert dto.is_ready
    assert dto.accepts_members
    assert (dto.approximate_count_lower, dto.approximate_count_upper) == (1000, 1400)
    # The provider's own codes survive as text, unenumerated.
    assert dto.readiness.code == "200"
    assert dto.readiness.description == "This audience is ready for use"
