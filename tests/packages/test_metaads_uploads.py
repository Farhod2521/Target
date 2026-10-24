"""Getting a file and a form to Meta, and the shapes both answer with.

Two subjects in one file because they are the two steps that happen before
anything is created: the owner's picture has to exist at Meta, and so does
the form the whole campaign is built to fill in.

The lead form half is the one worth reading. Meta prefills a standard
question from the person's own profile and labels it in their own
language, so sending our Uzbek wording alongside is an error rather than an
override - and the error arrives after the campaign exists.
"""

import base64
import json
from io import BytesIO
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest
from metaads.client import GraphClient
from metaads.leadforms import create_lead_form, questions_for
from metaads.specs import LeadFormSpec, LeadQuestionSpec
from metaads.uploads import (
    upload_image,
    upload_video,
    upload_video_from_url,
    video_status,
    video_thumbnail,
)
from pydantic import ValidationError

FORM = LeadFormSpec(
    name="Osh markazi - lidlar",
    privacy_policy_url="https://targetolog.ai/privacy/",
    questions=(
        LeadQuestionSpec(kind="FULL_NAME", label="Ismingiz"),
        LeadQuestionSpec(kind="PHONE", label="Telefon"),
        LeadQuestionSpec(
            kind="CUSTOM", label="Qaysi tuman?", options=("Chilonzor", "Yunusobod")
        ),
    ),
)


def recording(
    payload: dict[str, Any],
) -> tuple[GraphClient, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=payload)

    client = GraphClient(
        token="t", client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    return client, seen


def exploding() -> GraphClient:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"a dry run reached the network: {request.url}")

    return GraphClient(
        token="t", client=httpx.Client(transport=httpx.MockTransport(handler))
    )


# --- Images --------------------------------------------------------------
def test_an_image_comes_back_identified_by_its_hash() -> None:
    """Not an id. Meta's own odd one out, and a creative that names an
    image by id builds cleanly and shows nothing."""
    graph, _ = recording({"images": {"bytes": {"hash": "9f8e", "url": "https://x"}}})

    assert (
        upload_image(
            account_id="act_1", data=b"jpeg", token="t", client=graph, dry_run=False
        )
        == "9f8e"
    )


def test_the_hash_is_found_whatever_meta_keyed_it_under() -> None:
    """The key is the name of the field the bytes were sent in, so reading
    a fixed one is a guess about our own request."""
    graph, _ = recording({"images": {"menu.jpg": {"hash": "aaaa"}}})

    assert (
        upload_image(
            account_id="act_1", data=b"jpeg", token="t", client=graph, dry_run=False
        )
        == "aaaa"
    )


def test_the_image_goes_out_base64_encoded() -> None:
    graph, seen = recording({"images": {"bytes": {"hash": "9f8e"}}})

    upload_image(
        account_id="act_1", data=b"jpeg", token="t", client=graph, dry_run=False
    )

    body = parse_qs(seen[0].content.decode())
    assert body["bytes"][0] == base64.b64encode(b"jpeg").decode()


def test_a_named_image_goes_out_as_multipart_under_its_name() -> None:
    """Meta names the library row after the file. Sent as base64 the row
    is called "bytes", and that is what the owner's library shows."""
    graph, seen = recording({"images": {"kurs.jpg": {"hash": "9f8e"}}})

    created = upload_image(
        account_id="act_1",
        data=b"jpeg",
        filename="kurs.jpg",
        token="t",
        client=graph,
        dry_run=False,
    )

    assert created == "9f8e"
    assert seen[0].url.path.endswith("/act_1/adimages")
    assert b"multipart/form-data" in seen[0].headers["content-type"].encode()
    assert b'name="filename"; filename="kurs.jpg"' in seen[0].content
    assert b'name="bytes"' not in seen[0].content


def test_a_dry_run_upload_sends_nothing() -> None:
    graph = exploding()

    upload_image(account_id="act_1", data=b"jpeg", token="t", client=graph)
    upload_video(
        account_id="act_1",
        file=BytesIO(b"mp4"),
        filename="a.mp4",
        token="t",
        client=graph,
    )


# --- Videos --------------------------------------------------------------
def test_a_video_goes_out_as_multipart() -> None:
    """The one call Meta will not take as a form field."""
    graph, seen = recording({"id": "777"})

    created = upload_video(
        account_id="act_1",
        file=BytesIO(b"mp4-bytes"),
        filename="reklama.mp4",
        token="t",
        client=graph,
        dry_run=False,
    )

    assert created == "777"
    assert b"multipart/form-data" in seen[0].headers["content-type"].encode()
    assert b"reklama.mp4" in seen[0].content
    assert b"mp4-bytes" in seen[0].content


def test_a_video_sent_in_one_request_is_named_in_the_library() -> None:
    """Untitled, every later read of the library empties the tile's name."""
    graph, seen = recording({"id": "777"})

    upload_video(
        account_id="act_1",
        file=BytesIO(b"mp4-bytes"),
        filename="reklama.mp4",
        token="t",
        client=graph,
        dry_run=False,
    )

    assert b'name="title"\r\n\r\nreklama.mp4' in seen[0].content


def test_a_video_can_be_fetched_by_meta_instead_of_carried() -> None:
    """The asymmetry the Instagram route is shaped around: ``advideos``
    takes a URL and ``adimages`` takes none, so a reel never occupies a
    worker and a photograph always does."""
    graph, seen = recording({"id": "888"})

    created = upload_video_from_url(
        account_id="act_1",
        file_url="https://scontent.cdninstagram.com/reel.mp4",
        token="t",
        client=graph,
        dry_run=False,
    )

    assert created == "888"
    body = parse_qs(seen[0].content.decode())
    assert body["file_url"][0] == "https://scontent.cdninstagram.com/reel.mp4"
    assert "multipart" not in seen[0].headers.get("content-type", "")


def test_a_dry_run_fetches_nothing_either() -> None:
    graph = exploding()

    assert upload_video_from_url(
        account_id="act_1", file_url="https://cdn/reel.mp4", token="t", client=graph
    )


def test_a_video_still_transcoding_is_not_ready() -> None:
    graph, _ = recording({"status": {"video_status": "processing"}})

    assert video_status(video_id="777", token="t", client=graph) == "processing"


def test_the_older_shape_of_the_status_field_still_reads() -> None:
    """It used to be a plain string. Accounts do not all move at once."""
    graph, _ = recording({"status": "ready"})

    assert video_status(video_id="777", token="t", client=graph) == "ready"


def test_a_status_meta_did_not_send_reads_as_empty() -> None:
    """Which the caller treats as "keep waiting" rather than as ready."""
    graph, _ = recording({})

    assert video_status(video_id="777", token="t", client=graph) == ""


def test_the_thumbnail_meta_prefers_is_the_one_taken() -> None:
    graph, _ = recording(
        {
            "data": [
                {"uri": "https://x/1.jpg"},
                {"uri": "https://x/2.jpg", "is_preferred": True},
            ]
        }
    )

    assert video_thumbnail(video_id="777", token="t", client=graph) == "https://x/2.jpg"


def test_with_no_preference_the_first_thumbnail_will_do() -> None:
    graph, _ = recording({"data": [{"uri": "https://x/1.jpg"}]})

    assert video_thumbnail(video_id="777", token="t", client=graph) == "https://x/1.jpg"


def test_no_thumbnails_at_all_is_an_empty_string() -> None:
    graph, _ = recording({"data": []})

    assert video_thumbnail(video_id="777", token="t", client=graph) == ""


# --- Lead forms ----------------------------------------------------------
def test_a_form_cannot_be_described_without_a_privacy_policy() -> None:
    """Meta refuses the form without one, and refuses it after the campaign
    and ad set already exist. Refused here instead, for free."""
    with pytest.raises(ValidationError):
        LeadFormSpec(name="x")  # type: ignore[call-arg]


def test_a_standard_question_is_sent_without_our_wording() -> None:
    """Meta prefills and labels it itself; a label alongside is an error."""
    built = questions_for(FORM.questions)

    assert built[0] == {"type": "FULL_NAME"}
    assert built[1] == {"type": "PHONE"}


def test_a_custom_question_carries_a_key_the_answers_come_back_under() -> None:
    built = questions_for(FORM.questions)[2]

    assert built["type"] == "CUSTOM"
    assert built["key"] == "q3"
    assert built["label"] == "Qaysi tuman?"


def test_the_choices_of_a_custom_question_get_their_own_keys() -> None:
    """Positional, so that fixing a typo in an option does not change the
    identity of every answer already collected under it."""
    options = questions_for(FORM.questions)[2]["options"]

    assert options == [
        {"key": "q3_o1", "value": "Chilonzor"},
        {"key": "q3_o2", "value": "Yunusobod"},
    ]


def test_the_form_is_created_on_the_page_with_the_page_token() -> None:
    """A user token gets an error naming a permission, which reads like a
    missing scope and is not one."""
    graph, seen = recording({"id": "555"})

    created = create_lead_form(
        page_id="99", spec=FORM, page_token="page-tok", client=graph, dry_run=False
    )

    assert created == "555"
    assert "99/leadgen_forms" in str(seen[0].url)
    assert parse_qs(seen[0].content.decode())["access_token"] == ["page-tok"]


def test_a_form_with_no_thank_you_text_sends_no_thank_you_page() -> None:
    """An empty one renders as a blank screen; an absent one lets Meta use
    its own wording."""
    graph, seen = recording({"id": "555"})

    create_lead_form(
        page_id="99", spec=FORM, page_token="p", client=graph, dry_run=False
    )

    assert "thank_you_page" not in parse_qs(seen[0].content.decode())


def test_a_thank_you_screen_without_a_website_has_no_button() -> None:
    """The normal case here: half these businesses have no website at all."""
    spec = FORM.model_copy(update={"thank_you_title": "Rahmat!"})
    graph, seen = recording({"id": "555"})

    create_lead_form(
        page_id="99", spec=spec, page_token="p", client=graph, dry_run=False
    )

    page = parse_qs(seen[0].content.decode())["thank_you_page"][0]
    assert '"button_type": "NONE"' in page


def test_a_thank_you_screen_with_a_website_gets_one() -> None:
    spec = FORM.model_copy(
        update={"thank_you_title": "Rahmat!", "thank_you_url": "https://osh.uz"}
    )
    graph, seen = recording({"id": "555"})

    create_lead_form(
        page_id="99", spec=spec, page_token="p", client=graph, dry_run=False
    )

    page = parse_qs(seen[0].content.decode())["thank_you_page"][0]
    assert '"button_type": "VIEW_WEBSITE"' in page
    assert '"website_url": "https://osh.uz"' in page


def _thank_you_sent(spec: LeadFormSpec) -> dict:
    graph, seen = recording({"id": "555"})
    create_lead_form(
        page_id="99", spec=spec, page_token="p", client=graph, dry_run=False
    )
    return json.loads(parse_qs(seen[0].content.decode())["thank_you_page"][0])


def test_a_call_button_sends_the_number_and_its_country() -> None:
    spec = FORM.model_copy(
        update={
            "thank_you_title": "Rahmat!",
            "thank_you_button": "CALL_BUSINESS",
            "thank_you_button_text": "Qo'ng'iroq qilish",
            "thank_you_phone": "+998901234567",
            "thank_you_country": "UZ",
        }
    )

    page = _thank_you_sent(spec)

    assert page["button_type"] == "CALL_BUSINESS"
    assert page["business_phone_number"] == "+998901234567"
    assert page["country_code"] == "UZ"
    assert page["button_text"] == "Qo'ng'iroq qilish"
    assert "website_url" not in page


def test_an_explicit_no_button_ignores_a_stray_address() -> None:
    """Each button carries only its own field."""
    spec = FORM.model_copy(
        update={
            "thank_you_title": "Rahmat!",
            "thank_you_button": "NONE",
            "thank_you_url": "https://osh.uz",
            "thank_you_button_text": "Sayt",
        }
    )

    page = _thank_you_sent(spec)

    assert page["button_type"] == "NONE"
    assert "website_url" not in page
    assert "button_text" not in page


def _spec(**update: str) -> LeadFormSpec:
    return LeadFormSpec.model_validate(
        {**FORM.model_dump(), "thank_you_title": "Rahmat!", **update}
    )


def test_a_link_button_without_an_address_is_refused_before_sending() -> None:
    with pytest.raises(ValidationError):
        _spec(thank_you_button="VIEW_WEBSITE")


def test_a_link_button_into_meta_is_refused_before_sending() -> None:
    with pytest.raises(ValidationError):
        _spec(thank_you_button="VIEW_WEBSITE", thank_you_url="https://facebook.com/x")


def test_a_call_button_without_a_dialable_number_is_refused() -> None:
    with pytest.raises(ValidationError):
        _spec(thank_you_button="CALL_BUSINESS", thank_you_phone="90 123 45 67")


def test_a_button_meta_does_not_know_is_refused() -> None:
    with pytest.raises(ValidationError):
        _spec(thank_you_button="TELEGRAM")


def test_a_button_needs_a_title_to_sit_under() -> None:
    with pytest.raises(ValidationError):
        LeadFormSpec.model_validate(
            {
                **FORM.model_dump(),
                "thank_you_button": "VIEW_WEBSITE",
                "thank_you_url": "https://osh.uz",
            }
        )


def test_a_dry_run_form_sends_nothing() -> None:
    create_lead_form(page_id="99", spec=FORM, page_token="p", client=exploding())
