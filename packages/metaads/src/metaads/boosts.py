"""An ad built out of a post that is already on Instagram.

Meta has two ways of describing a creative and they are alternatives, not
layers. An ``object_story_spec`` - :mod:`metaads.stories` - describes a post
that does not exist yet: Meta publishes it while it creates the ad, and the
picture, the words and the button all travel inside the nested block. This
module is the other one: three flat fields naming a post that was published
weeks ago, which keeps the likes, the comments and the place it already has
in somebody's profile.

=========================  ===========================================
new post (``stories``)     existing post (here)
=========================  ===========================================
``object_story_spec``      ``object_id`` + ``source_instagram_media_id``
``page_id``, nested        ``object_id``, flat
``call_to_action``, nested ``call_to_action``, flat
=========================  ===========================================

Sending both is the failure worth naming here, because it is silent: Meta
accepts a creative carrying a story spec **and** a source media id, and
what it then advertises is the story spec - a new, empty post beside the
one somebody chose.

The account is named twice on this route and neither name is optional.
``object_id`` is the **page**, which is what the ad is bought by, and
``instagram_user_id`` is the profile the post belongs to, which is what it
runs as. Meta's own guide sends both.

**The button.** Meta's guide for this route lists three destinations and
all three are conversations; a lead form is not among them. It works
anyway - a live account accepts the shape below, and reading the creative
back shows the form id still on it - but only with a ``link`` sitting
beside the form id in the button's own value.

That link is **not** about lead forms. A messaging button with no link is
refused with the same error, so the rule belongs to this route: every
button here carries a link, whatever else it carries.
Meta documents none of that, which is why the two facts are pinned by
``BoostSpec``'s validator rather than left to a caller to remember.

    100/2061015  The link field is required        (blamed: link)

**``object_url`` is not the place for it**, and the mistake is worth
naming because it is the obvious first guess: that field is where a flat
creative usually puts its destination, and sending it beside
``source_instagram_media_id`` makes Meta refuse the creative outright.

    100/1487929  Ambiguous Promoted Object Fields:
                 object_url, source_instagram_media_id

So there is exactly one slot for the address on this route, and it is
inside the button. See ``probe_boost_creative``, which is what asked.
"""

from typing import Any, Final

from pydantic import Field, field_validator, model_validator

from metaads.client import GraphClient
from metaads.dto_base import MetaDTO
from metaads.specs import CTA_NO_BUTTON, MAX_WELCOME_QUESTIONS, checked_questions
from metaads.stories import greeting
from metaads.writing import fake_id, graph_client, id_of, post_object

_CREATIVE: Final = "creative"

# What is worth reading back off a creative built this way, and it is a
# different list from ``discovery.CREATIVE_FIELDS`` on purpose: that one
# reads a story spec, and a creative built here has none.
#
# The ``effective_`` pair is the evidence. Meta answers them with what the
# ad will actually show, which is how a creative that silently fell back to
# something else - a new post, the page instead of the profile - is told
# apart from one that kept the post it was given.
BOOST_FIELDS: Final = (
    "id,name,status,object_id,object_type,instagram_user_id,"
    "source_instagram_media_id,effective_instagram_media_id,"
    "effective_object_story_id,call_to_action,call_to_action_type,thumbnail_url"
)

# The same read, minus the fields this package is not certain Meta answers
# on this node - ``call_to_action`` above all, which is the one that carries
# the form id back and the one the whole probe turns on. Meta refuses a
# whole request over one name it does not recognise - ``#100 nonexistent
# field`` - so a caller that wants an answer more than it wants the extra
# columns has somewhere to fall back to.
BOOST_FIELDS_MINIMAL: Final = "id,name,status,object_id,call_to_action_type"

# The two fields that say which post a creative advertises - the one it was
# given and the one it will show. Everything the after-launch check needs.
PROMOTED_MEDIA_FIELDS: Final = "source_instagram_media_id,effective_instagram_media_id"


class BoostSpec(MetaDTO):
    """One published post, and what the button on it should do.

    No words and no picture: both are already in the post, and that is the
    whole point of this route. What is left is the identity the ad runs
    under and the one decision the post itself cannot carry.
    """

    page_id: str
    instagram_user_id: str
    media_id: str
    name: str = ""
    # Empty means no button at all, which on this route is an ordinary ad
    # rather than a broken one: the post stands as it was published.
    call_to_action: str = ""
    lead_form_id: str = ""
    # The messaging surface, for the destinations Meta does document here.
    #
    # The refusal that proved the link is required was a messaging button,
    # and Meta's own click-to-Instagram example carries a link in the
    # button's value. The pair - link and surface together - is what
    # ``probe_post_boost --chat`` puts to a live account.
    app_destination: str = ""
    # Required as soon as there is a button - see the module docstring and
    # the validator below. Meta never follows it on a lead ad; the tap
    # opens the form. It is still refused when absent.
    link_url: str = ""
    # Appended to the address the button opens - see ``CreativeSpec``. The
    # post's own text is untouched: a link somebody typed into the caption
    # is theirs and Meta never rewrites it.
    url_tags: str = ""
    # The first lines of the conversation a messaging button opens - the
    # same pair ``CreativeSpec`` carries. Here they travel as a field of the
    # creative itself rather than inside ``link_data``, which this route
    # does not have; a live account kept them on both Messenger and
    # Instagram Direct.
    welcome_text: str = ""
    autofill_text: str = ""
    welcome_questions: tuple[str, ...] = Field(
        default=(), max_length=MAX_WELCOME_QUESTIONS
    )

    @field_validator("welcome_questions")
    @classmethod
    def _questions_fit(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return checked_questions(value)

    @model_validator(mode="after")
    def _a_button_needs_a_link(self) -> "BoostSpec":
        """Refuse here rather than at Meta, for the reason every validator
        in this package refuses early: this object is built after the
        campaign, the ad set and the form already exist, and the form is
        the one thing a rollback cannot remove.

        The rule is Meta's and is undocumented: ``100/2061015``, blaming
        ``link``, for a lead button and for a messaging button alike."""
        wants_button = self.call_to_action and self.call_to_action != CTA_NO_BUTTON
        if wants_button and not self.link_url:
            raise ValueError(
                "a boosted post's button needs link_url: Meta refuses "
                "every call_to_action on this route without one"
            )
        return self


def boost_payload(spec: BoostSpec) -> dict[str, Any]:
    """The flat object Meta wants, from the flat one we hold.

    Exported for the same reason :func:`metaads.stories.story_spec` is: the
    two shapes are alike enough to be confused and a test is the only thing
    that keeps them apart.
    """
    payload: dict[str, Any] = {
        "object_id": spec.page_id,
        "instagram_user_id": spec.instagram_user_id,
        "source_instagram_media_id": spec.media_id,
    }
    if spec.name:
        payload["name"] = spec.name

    if spec.url_tags:
        payload["url_tags"] = spec.url_tags

    welcome = greeting(
        text=spec.welcome_text,
        autofill=spec.autofill_text,
        questions=spec.welcome_questions,
    )
    if welcome:
        payload["page_welcome_message"] = welcome

    action = call_to_action(spec)
    if action:
        payload["call_to_action"] = action
    return payload


def call_to_action(spec: BoostSpec) -> dict[str, Any]:
    """The button: a link, and whatever else it opens.

    **Two things in the slot, not one**, and that is the difference between
    this and :mod:`metaads.stories`. There, sending a link beside a form id
    is how an ad silently opens a website instead of the form it was built
    for. Here the link is compulsory and the form rides beside it - proved
    against a live account, because the documentation says neither.

    A conversation and a form are still exclusive. A spec naming both is
    one nobody should have built, and the form is the half that cost a call
    which cannot be taken back.
    """
    if not spec.call_to_action or spec.call_to_action == CTA_NO_BUTTON:
        return {}

    # The link first and always, because on this route it is not the
    # fallback it is inside a story spec - it is the field Meta refuses the
    # creative for omitting, whatever else the button carries.
    value: dict[str, Any] = {"link": spec.link_url}
    if spec.lead_form_id:
        value["lead_gen_form_id"] = spec.lead_form_id
    elif spec.app_destination:
        value["app_destination"] = spec.app_destination
    return {"type": spec.call_to_action, "value": value}


def create_boost_creative(
    *,
    account_id: str,
    spec: BoostSpec,
    token: str,
    client: GraphClient | None = None,
    dry_run: bool = True,
) -> str:
    """One creative pointed at a post that already exists."""
    if dry_run:
        return fake_id(_CREATIVE)

    payload = post_object(
        path=f"{account_id}/adcreatives",
        data=boost_payload(spec),
        token=token,
        client=client,
    )
    return id_of(payload)


def read_creative(
    *,
    creative_id: str,
    token: str,
    fields: str = BOOST_FIELDS,
    client: GraphClient | None = None,
) -> dict[str, Any]:
    """The creative as Meta holds it, raw.

    Raw for :mod:`metaads.discovery`'s reason: what this is for is finding
    out which of the fields sent actually survived, and a parser written
    against a guess would drop exactly the one that did not.
    """
    with graph_client(client, token) as graph:
        return graph.get(creative_id, fields=fields)


def story_of_ad(*, ad_id: str, token: str, client: GraphClient | None = None) -> str:
    """The page post an advert's creative shows, or empty.

    A promoted Instagram post comes back with an ``effective_object_story_id``
    too - the page post Meta publishes for it - and whether engagement on
    Facebook placements lands there or on the Instagram post is not
    documented. This is the id to measure it on.
    """
    with graph_client(client, token) as graph:
        row = graph.get(ad_id, fields="creative{effective_object_story_id}")
    creative = row.get("creative") or {}
    return str(creative.get("effective_object_story_id", ""))


def story_counts(
    *, story_id: str, token: str, client: GraphClient | None = None
) -> dict[str, int]:
    """Reactions, comments and shares on one page post, as Meta totals them.

    Needs the **page** token: it is the page's own post.
    """
    with graph_client(client, token) as graph:
        row = graph.get(
            story_id,
            fields=(
                "reactions.summary(total_count).limit(0),"
                "comments.summary(total_count).limit(0),shares"
            ),
        )
    return {
        "reactions": int(
            (row.get("reactions") or {}).get("summary", {}).get("total_count", 0)
        ),
        "comments": int(
            (row.get("comments") or {}).get("summary", {}).get("total_count", 0)
        ),
        "shares": int((row.get("shares") or {}).get("count", 0)),
    }


__all__ = [
    "BOOST_FIELDS",
    "BOOST_FIELDS_MINIMAL",
    "PROMOTED_MEDIA_FIELDS",
    "BoostSpec",
    "boost_payload",
    "call_to_action",
    "create_boost_creative",
    "read_creative",
    "story_counts",
    "story_of_ad",
]
