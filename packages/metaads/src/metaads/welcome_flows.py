"""A chat advert's greeting kept on the page, where Ads Manager offers it.

Meta calls these welcome message flows: made through
``/{page_id}/welcome_message_flows`` with the page's token, they show in Ads
Manager under the creative's «Message template» → «Partner App» for the
Engagement and Sales objectives, so an owner can open a hand-made advert
with the greeting they saved here.

**Not the advert's own greeting.** A flow is a Send API message - text and
quick replies - not the ``page_welcome_message`` ice breakers this product
puts on its own adverts, which carry an answer Meta sends by itself. A
quick reply's title is cut at 20 characters and has no answer behind it, so
the questions go into the text as a numbered list, and only the ones short
enough to stand as a button whole are buttons as well. Nothing is cut.

**Permissions.** ``pages_messaging`` on the page (and
``instagram_manage_messages`` for Instagram), with a page token from
somebody who may message as the page. Neither is needed to launch, so a
refusal here is answered by the caller, never by a refused launch.

**A flow an advert uses is fixed.** Meta refuses to change or delete it;
:func:`update_flow` raises and the caller makes a new one instead.

https://developers.facebook.com/documentation/business-messaging/messenger-platform/ads/ads-welcome-message-flows
"""

from typing import Any, Final

from metaads.client import GraphClient
from metaads.writing import delete_payload, fake_id, post_object

_FLOW: Final = "welcome_flow"
EDGE: Final = "welcome_message_flows"
MESSENGER: Final = "messenger"
INSTAGRAM: Final = "instagram"
# The Send API's ceilings: a quick reply's title, a text message.
MAX_REPLY_TITLE: Final = 20
MAX_TEXT_CHARS: Final = 2000


def flow_text(text: str, questions: tuple[str, ...]) -> str:
    """The greeting with the questions under it, numbered."""
    body = text.strip()
    if questions:
        listed = "\n".join(
            f"{place}. {question}" for place, question in enumerate(questions, 1)
        )
        body = f"{body}\n\n{listed}" if body else listed
    return body[:MAX_TEXT_CHARS]


def flow_message(text: str, questions: tuple[str, ...]) -> list[dict[str, Any]]:
    """The flow Meta keeps: one message, the questions short enough as buttons."""
    message: dict[str, Any] = {"text": flow_text(text, questions)}
    replies = [
        {"content_type": "text", "title": question, "payload": question}
        for question in questions
        if 0 < len(question) <= MAX_REPLY_TITLE
    ]
    if replies:
        message["quick_replies"] = replies
    return [{"message": message}]


def create_flow(
    *,
    page_id: str,
    name: str,
    text: str,
    questions: tuple[str, ...],
    platforms: tuple[str, ...],
    page_token: str,
    client: GraphClient | None = None,
    dry_run: bool = True,
) -> str:
    """Keep the greeting on the page; answer the flow's id."""
    if dry_run:
        return fake_id(_FLOW)
    payload = post_object(
        path=f"{page_id}/{EDGE}",
        data={
            "name": name,
            "welcome_message_flow": flow_message(text, questions),
            "eligible_platforms": list(platforms),
        },
        token=page_token,
        client=client,
    )
    found = payload.get("flow_id") or payload.get("id")
    if not found:
        raise ValueError(f"no flow id in Meta's answer: {sorted(payload)}")
    return str(found)


def update_flow(
    *,
    page_id: str,
    flow_id: str,
    name: str,
    text: str,
    questions: tuple[str, ...],
    platforms: tuple[str, ...],
    page_token: str,
    client: GraphClient | None = None,
    dry_run: bool = True,
) -> None:
    """Write over a kept flow. Raises when an advert uses it."""
    if dry_run:
        return
    post_object(
        path=f"{page_id}/{EDGE}",
        data={
            "flow_id": flow_id,
            "name": name,
            "welcome_message_flow": flow_message(text, questions),
            "eligible_platforms": list(platforms),
        },
        token=page_token,
        client=client,
    )


def delete_flow(
    *,
    page_id: str,
    flow_id: str,
    page_token: str,
    client: GraphClient | None = None,
    dry_run: bool = True,
) -> None:
    """Take a kept flow off the page. Raises when an advert uses it."""
    if dry_run:
        return
    delete_payload(
        path=f"{page_id}/{EDGE}",
        data={"flow_id": flow_id},
        token=page_token,
        client=client,
    )


__all__ = [
    "EDGE",
    "INSTAGRAM",
    "MAX_REPLY_TITLE",
    "MESSENGER",
    "create_flow",
    "delete_flow",
    "flow_message",
    "flow_text",
    "update_flow",
]
