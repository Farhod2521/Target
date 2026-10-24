"""Reading a creative back, and the table that decides whether it works.

Meta names three of the same fields differently depending on whether the
creative holds a still or a video, and :mod:`metaads.stories` writes that
table down. This file is the other half: the read side inverts it, and if
the two ever stop agreeing every video creative in an account comes back
with an empty headline. That failure is silent - nothing raises, the parse
just answers blank - which is why the check below is a round trip through
the real writer rather than a payload typed out from memory.

Nothing here reaches a network. A creative arrives nested inside an ad, so
these are the shapes ``/act_<id>/ads`` answers with.
"""

import pytest
from metaads.campaigns import AD_FIELDS
from metaads.dto import AdRow, CreativeRow
from metaads.specs import CTA_SIGN_UP, CreativeSpec
from metaads.stories import story_spec

# Somewhere outside Meta. A lead creative is refused when its link points
# back at a page, which is checked at construction - see ``CreativeSpec``.
SITE = "https://osh.uz"


def creative_of(spec: CreativeSpec, **extra: object) -> CreativeRow:
    """What Meta would answer for a creative this package just built.

    The assumption under every test here, stated once: Meta echoes the
    story spec it was given. That is what it does for the fields this
    product writes, and it is the only claim in this file that a live
    account could contradict - so it is made in one place rather than in
    twelve payloads, and the console (``/api/meta/``) is where it gets
    checked against a real answer.
    """
    return CreativeRow.model_validate(
        {"id": "555", "object_story_spec": story_spec(spec), **extra}
    )


# --- What is asked for ---------------------------------------------------
def test_the_whole_creative_rides_on_the_ads_read() -> None:
    """One call, not two. A nested expansion costs nothing extra, and
    ``/act_<id>/adcreatives`` would be a fourth paged read of a sync that
    makes three."""
    assert "creative{" in AD_FIELDS
    for field in ("object_story_spec", "thumbnail_url", "object_story_id", "status"):
        assert field in AD_FIELDS


# --- The two vocabularies, read back -------------------------------------
def test_an_image_creative_is_read_back_the_way_it_was_written() -> None:
    """``name`` is the headline on a ``link_data`` block. Meta's word."""
    row = creative_of(
        CreativeSpec(
            name="c",
            page_id="99",
            message="Salom",
            headline="Bugun",
            description="Qisqa",
            image_hash="abc",
            link_url=SITE,
        )
    )

    assert row.kind == "link"
    assert row.message == "Salom"
    assert row.headline == "Bugun"
    assert row.description == "Qisqa"
    assert row.image_hash == "abc"
    assert row.video_id == ""
    assert row.link_url == SITE


def test_a_video_creative_is_read_back_through_its_own_three_names() -> None:
    """``title`` and ``link_description``, not ``name`` and ``description``.

    The whole reason this file exists. Reading only the image spelling
    leaves every video creative looking like one nobody wrote words for.
    """
    row = creative_of(
        CreativeSpec(
            name="c",
            page_id="99",
            message="Salom",
            headline="Bugun",
            description="Qisqa",
            video_id="777",
            thumbnail_url="https://x/t.jpg",
            link_url=SITE,
        )
    )

    assert row.kind == "video"
    assert row.message == "Salom"
    assert row.headline == "Bugun"
    assert row.description == "Qisqa"
    assert row.video_id == "777"
    assert row.image_hash == ""
    assert row.image_url == "https://x/t.jpg"


@pytest.mark.parametrize(
    ("field", "expected"),
    [("headline", "Bugun"), ("description", "Qisqa"), ("message", "Salom")],
)
def test_both_shapes_answer_the_same_question_with_the_same_word(
    field: str, expected: str
) -> None:
    """The invariant the two tests above are each half of: whichever block a
    creative was built with, the domain asks for the same three things and
    gets the same three answers."""
    words = {
        "name": "c",
        "page_id": "99",
        "message": "Salom",
        "headline": "Bugun",
        "description": "Qisqa",
        "link_url": SITE,
    }
    image = creative_of(CreativeSpec(**words, image_hash="abc"))
    video = creative_of(
        CreativeSpec(**words, video_id="777", thumbnail_url="https://x/t.jpg")
    )

    assert getattr(image, field) == expected
    assert getattr(video, field) == expected


# --- The button ----------------------------------------------------------
def test_the_call_to_action_survives_the_round_trip_on_both_shapes() -> None:
    """Written into whichever block the creative uses, and read out of it.

    Kept as Meta's own word. There is no domain vocabulary for a button:
    the list belongs to the provider and the advertiser picked from it.
    """
    words = {"name": "c", "page_id": "99", "message": "Salom", "link_url": SITE}

    assert creative_of(CreativeSpec(**words, image_hash="a")).call_to_action == (
        CTA_SIGN_UP
    )
    assert (
        creative_of(
            CreativeSpec(**words, video_id="7", thumbnail_url="https://x/t.jpg")
        ).call_to_action
        == CTA_SIGN_UP
    )


def test_a_lead_creative_still_gives_up_its_form_id() -> None:
    """The oldest thing read out of a story spec, and now read out of the
    creative rather than out of the ad. Same answer, one place."""
    row = creative_of(
        CreativeSpec(
            name="c",
            page_id="99",
            message="Salom",
            image_hash="abc",
            link_url=SITE,
            lead_form_id="777",
        )
    )

    assert row.lead_form_id == "777"
    assert (
        AdRow.model_validate(
            {"id": "1", "creative": row.model_dump()}
        ).lead_form_external_id
        == "777"
    )


# --- Identity ------------------------------------------------------------
def test_the_page_and_the_instagram_account_come_back() -> None:
    """Who the ad ran as. The page is on every creative; the Instagram
    account is on the few advertisers who have one."""
    row = creative_of(
        CreativeSpec(
            name="c",
            page_id="99",
            message="Salom",
            image_hash="abc",
            link_url=SITE,
            instagram_user_id="1234",
        )
    )

    assert row.page_id == "99"
    assert row.instagram_user_id == "1234"


def test_the_old_spelling_of_the_account_is_not_read_back() -> None:
    """Deliberate, not an oversight. Meta retired ``instagram_actor_id``
    for every API version on 2025-09-09, so a creative still carrying it
    would have to predate that - and a column filled from a key the
    provider no longer sends is a column that quietly stops updating."""
    row = CreativeRow.model_validate(
        {
            "id": "9",
            "object_story_spec": {"page_id": "99", "instagram_actor_id": "1234"},
        }
    )

    assert row.instagram_user_id == ""


# --- Shapes this package does not write ----------------------------------
def test_a_creative_made_from_an_existing_post_has_no_words_of_its_own() -> None:
    """It names the post instead, and the words live there.

    An empty message on such a row is the truth rather than a parse that
    missed, which is why ``kind`` says which of the two it is looking at.
    """
    row = CreativeRow.model_validate(
        {"id": "9", "object_story_id": "99_123", "name": "Promoted post"}
    )

    assert row.kind == "post"
    assert row.message == ""
    assert row.headline == ""
    assert row.object_story_id == "99_123"


def test_a_shape_this_product_does_not_build_is_unknown_rather_than_guessed() -> None:
    """A carousel, an asset feed. Recorded as a creative with no kind, so a
    comparison can leave it out instead of counting it as a still."""
    row = CreativeRow.model_validate(
        {"id": "9", "object_story_spec": {"page_id": "99"}}
    )

    assert row.kind == ""
    assert row.headline == ""


def test_an_ad_with_no_creative_expansion_is_not_a_crash() -> None:
    """An empty row, not ``None``. Every accessor answers on it, which is
    what keeps a caller from checking twice."""
    row = AdRow.model_validate({"id": "1"})

    assert row.creative.id == ""
    assert row.creative_external_id == ""
    assert row.creative.kind == ""


def test_a_headline_that_arrives_as_a_number_is_read_as_text() -> None:
    """A creative named "2026" is a real creative. Refusing the row would
    lose the whole account's sync over one advertiser's taste in names."""
    row = CreativeRow.model_validate(
        {"id": "9", "object_story_spec": {"link_data": {"name": 2026}}}
    )

    assert row.headline == ""


def test_a_post_meta_made_itself_still_names_its_page() -> None:
    """A boosted page post, and an advert built in Ads Manager from one.

    Neither carries a story spec or ``object_story_id``, so the advert used
    to belong to no page at all - money on no screen in a cabinet with two
    pages. Both fields Meta does fill are read.
    """
    row = CreativeRow.model_validate(
        {"id": "9", "effective_object_story_id": "99_123", "actor_id": "99"}
    )

    assert row.page_id == "99"
    assert row.post_id == "99_123"
    assert row.kind == "post"


def test_what_this_product_wrote_outranks_what_meta_worked_out() -> None:
    """Both are true of an advert built from a spec; the spec is the one
    this product wrote, and the actor can name a different page."""
    row = CreativeRow.model_validate(
        {
            "id": "9",
            "object_story_spec": {"page_id": "77", "link_data": {"name": "Sarlavha"}},
            "object_story_id": "77_1",
            "effective_object_story_id": "99_123",
            "actor_id": "99",
        }
    )

    assert row.page_id == "77"
    assert row.post_id == "77_1"
