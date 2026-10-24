"""An ad built out of a post that is already on Instagram."""

from typing import Any, Final

from pydantic import Field, field_validator, model_validator

from metaads.client import GraphClient
from metaads.dto_base import MetaDTO
from metaads.specs import CTA_NO_BUTTON, MAX_WELCOME_QUESTIONS, checked_questions
from metaads.stories import greeting
from metaads.writing import fake_id, graph_client, id_of, post_object

_CREATIVE: Final = "creative"

BOOST_FIELDS: Final = (
    "id,name,status,object_id,object_type,instagram_user_id,"
    "source_instagram_media_id,effective_instagram_media_id,"
    "effective_object_story_id,call_to_action,call_to_action_type,thumbnail_url"
)

BOOST_FIELDS_MINIMAL: Final = "id,name,status,object_id,call_to_action_type"

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
    call_to_action: str = ""
    lead_form_id: str = ""
    app_destination: str = ""
    link_url: str = ""
    url_tags: str = ""
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
        the one thing a rollback cannot remove."""
        wants_button = self.call_to_action and self.call_to_action != CTA_NO_BUTTON
        if wants_button and not self.link_url:
            raise ValueError(
                "a boosted post's button needs link_url: Meta refuses "
                "every call_to_action on this route without one"
            )
        return self


def boost_payload(spec: BoostSpec) -> dict[str, Any]:
    """The flat object Meta wants, from the flat one we hold."""
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
    """The button: a link, and whatever else it opens."""
    if not spec.call_to_action or spec.call_to_action == CTA_NO_BUTTON:
        return {}

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
    """The creative as Meta holds it, raw."""
    with graph_client(client, token) as graph:
        return graph.get(creative_id, fields=fields)


def story_of_ad(*, ad_id: str, token: str, client: GraphClient | None = None) -> str:
    """The page post an advert's creative shows, or empty."""
    with graph_client(client, token) as graph:
        row = graph.get(ad_id, fields="creative{effective_object_story_id}")
    creative = row.get("creative") or {}
    return str(creative.get("effective_object_story_id", ""))


def story_counts(
    *, story_id: str, token: str, client: GraphClient | None = None
) -> dict[str, int]:
    """Reactions, comments and shares on one page post, as Meta totals them."""
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
