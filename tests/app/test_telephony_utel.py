"""UTeL's REST API as the telephony settings call it, with the network faked."""

from typing import Any

import httpx
import pytest

from app.modules.telephony import services, utel
from app.modules.telephony.constants import HOOK_EVENTS
from app.modules.telephony.exceptions import TenantShape


def _answers(
    monkeypatch: pytest.MonkeyPatch, status: int, body: Any
) -> list[dict[str, Any]]:
    asked: list[dict[str, Any]] = []

    def request(method: str, url: str, **options: Any) -> httpx.Response:
        asked.append({"method": method, "url": url} | options)
        if isinstance(body, Exception):
            raise body
        return httpx.Response(status, json=body)

    monkeypatch.setattr(httpx, "request", request)
    return asked


def test_a_login_gives_the_key(monkeypatch: pytest.MonkeyPatch) -> None:
    asked = _answers(
        monkeypatch,
        200,
        {"status": "success", "code": 200, "result": {"access_token": "1|abc"}},
    )

    assert utel.login("utc181", email="a@b.uz", password="sir") == "1|abc"

    (call,) = asked
    assert call["method"] == "POST"
    assert call["url"] == "https://api.utc181.utel.uz/api/v1/auth/login"
    assert call["json"] == {"email": "a@b.uz", "password": "sir"}
    assert "Authorization" not in call["headers"]
    assert call["follow_redirects"] is False


@pytest.mark.parametrize("status", [401, 403, 422])
def test_a_login_utel_will_not_take_is_a_refusal(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    _answers(monkeypatch, status, {"message": "yo'q"})
    with pytest.raises(utel.Refused):
        utel.login("utc181", email="a@b.uz", password="xato")


def test_silence_and_strange_answers_are_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _answers(monkeypatch, 200, httpx.ConnectTimeout("sekin"))
    with pytest.raises(utel.Unreachable):
        utel.extensions("utc181", token="k")
    _answers(monkeypatch, 500, {"message": "xato"})
    with pytest.raises(utel.Unreachable):
        utel.extensions("utc181", token="k")
    _answers(monkeypatch, 200, {"result": {"not": "a list"}})
    with pytest.raises(utel.Unreachable):
        utel.extensions("utc181", token="k")
    _answers(monkeypatch, 200, ["no envelope"])
    with pytest.raises(utel.Unreachable):
        utel.hooks("utc181", token="k")
    # A list UTeL would not take is not a lost key.
    _answers(monkeypatch, 422, {"message": "url"})
    with pytest.raises(utel.Unreachable) as caught:
        utel.put_hooks("utc181", token="k", rows=[])
    assert not isinstance(caught.value, utel.Refused)


def test_the_numbers_are_read_with_the_key(monkeypatch: pytest.MonkeyPatch) -> None:
    asked = _answers(
        monkeypatch,
        200,
        {
            "status": "success",
            "result": [
                {
                    "id": 101,
                    "title": " Operator 1 ",
                    "username": "101",
                    "password": "p",
                },
                {"id": 5, "title": "nomersiz", "username": ""},
                "axlat",
            ],
        },
    )

    found = utel.extensions("utc181", token="1|abc")

    assert found == [utel.Extension(number="101", title="Operator 1", password="p")]
    assert asked[0]["headers"]["Authorization"] == "Bearer 1|abc"
    assert asked[0]["url"].endswith("/ats/ps-user")


def test_a_hook_row_has_every_event_on() -> None:
    row = utel.hook_row("https://biz.uz/webhooks/utel/k")
    assert row == {"url": "https://biz.uz/webhooks/utel/k"} | dict.fromkeys(
        HOOK_EVENTS, True
    )


@pytest.mark.parametrize(
    "pasted",
    [
        "utc181",
        " UTC181 ",
        "utc181.utel.uz",
        "https://utc181.utel.uz/login",
        "api.utc181.utel.uz",
        "wss://utc181.utel.uz:8089/ws",
    ],
)
def test_the_tenant_is_read_out_of_what_was_pasted(pasted: str) -> None:
    assert services.tenant_of(pasted) == "utc181"


@pytest.mark.parametrize(
    "pasted",
    [
        "",
        "evil.com",
        "utc181.utel.uz.evil.com",
        "utc181@evil.com",
        "utc181.evil.com/x",
        "-utc",
        "utc_181",
        "127.0.0.1",
        "x" * 60,
    ],
)
def test_anything_else_is_not_a_tenant(pasted: str) -> None:
    with pytest.raises(TenantShape):
        services.tenant_of(pasted)
