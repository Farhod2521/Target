"""A chat template kept on the page as a welcome message flow."""

import json
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest
from metaads.errors import MetaAPIError
from metaads.welcome_flows import (
    create_flow,
    delete_flow,
    flow_message,
    flow_text,
    update_flow,
)

QUESTIONS = ("Narxi qancha?", "Yetkazib berish Toshkent bo'ylab bormi?")


def answering(
    monkeypatch: pytest.MonkeyPatch, *, status: int = 200, body: dict[str, Any]
) -> list[httpx.Request]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, json=body)

    original = httpx.Client.__init__

    def patched(self: httpx.Client, **kwargs: Any) -> None:
        original(self, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(httpx.Client, "__init__", patched)
    monkeypatch.setattr("metaads.client._shared", None)
    return seen


def form(request: httpx.Request) -> dict[str, str]:
    return {
        key: values[0] for key, values in parse_qs(request.content.decode()).items()
    }


def test_the_questions_go_into_the_text_numbered_and_nothing_is_cut() -> None:
    assert flow_text("Salom!", QUESTIONS) == (
        "Salom!\n\n1. Narxi qancha?\n2. Yetkazib berish Toshkent bo'ylab bormi?"
    )
    assert flow_text(" Salom ", ()) == "Salom"


def test_only_a_question_short_enough_is_a_button_too() -> None:
    (message,) = flow_message("Salom!", QUESTIONS)
    assert message["message"]["quick_replies"] == [
        {"content_type": "text", "title": "Narxi qancha?", "payload": "Narxi qancha?"}
    ]
    (bare,) = flow_message("Salom!", ())
    assert "quick_replies" not in bare["message"]


def test_a_flow_is_made_on_the_page_with_its_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = answering(monkeypatch, body={"flow_id": "555"})

    made = create_flow(
        page_id="99",
        name="Yozgi",
        text="Salom!",
        questions=QUESTIONS,
        platforms=("messenger", "instagram"),
        page_token="page-token",
        dry_run=False,
    )

    assert made == "555"
    (request,) = seen
    assert request.method == "POST"
    assert request.url.path.endswith("/99/welcome_message_flows")
    sent = form(request)
    assert sent["name"] == "Yozgi"
    assert json.loads(sent["eligible_platforms"]) == ["messenger", "instagram"]
    assert json.loads(sent["welcome_message_flow"]) == flow_message("Salom!", QUESTIONS)
    assert sent["access_token"] == "page-token"


def test_a_rehearsal_sends_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = answering(monkeypatch, body={})

    made = create_flow(
        page_id="99",
        name="n",
        text="t",
        questions=(),
        platforms=("messenger",),
        page_token="t",
    )
    update_flow(
        page_id="99",
        flow_id="1",
        name="n",
        text="t",
        questions=(),
        platforms=("messenger",),
        page_token="t",
    )
    delete_flow(page_id="99", flow_id="1", page_token="t")

    assert made and seen == []


def test_a_flow_in_use_is_refused_on_rewrite_and_on_delete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = answering(
        monkeypatch,
        status=400,
        body={"error": {"code": 100, "message": "flow is used in an ad"}},
    )

    with pytest.raises(MetaAPIError):
        update_flow(
            page_id="99",
            flow_id="1",
            name="n",
            text="t",
            questions=(),
            platforms=("messenger",),
            page_token="t",
            dry_run=False,
        )
    with pytest.raises(MetaAPIError):
        delete_flow(page_id="99", flow_id="1", page_token="t", dry_run=False)

    assert form(seen[0])["flow_id"] == "1"
    assert seen[1].method == "DELETE"
