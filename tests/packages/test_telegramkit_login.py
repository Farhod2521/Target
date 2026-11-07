"""telegramkit.login: the Login Widget's redirect, checked as Telegram signs it."""

import pytest
from telegramkit import LoginWidgetError, login_digest, verify_login

TOKEN = "123:bot-token"
NOW = 1_800_000_000
FIELDS = {
    "id": "42",
    "first_name": "Vali",
    "last_name": "Aliyev",
    "username": "vali",
    "auth_date": str(NOW - 5),
}


def signed(fields: dict[str, str]) -> dict[str, str]:
    return fields | {"hash": login_digest(fields, bot_token=TOKEN)}


def check(query: dict[str, str], *, max_age: int = 600) -> object:
    return verify_login(query, bot_token=TOKEN, now=NOW, max_age_seconds=max_age)


def test_a_signed_redirect_names_the_account() -> None:
    login = check(signed(FIELDS) | {"next": "ours, not signed"})
    assert login == verify_login(
        signed(FIELDS), bot_token=TOKEN, now=NOW, max_age_seconds=600
    )
    assert (login.id, login.name, login.username) == (42, "Vali Aliyev", "vali")  # type: ignore[attr-defined]
    assert "Vali" not in repr(login)


def test_the_known_digest_for_a_fixed_payload() -> None:
    # Telegram's recipe: HMAC-SHA256 keyed with SHA256(token), "k=v" lines sorted.
    import hashlib
    import hmac

    lines = "\n".join(f"{k}={v}" for k, v in sorted(FIELDS.items()))
    expected = hmac.new(
        hashlib.sha256(TOKEN.encode()).digest(), lines.encode(), hashlib.sha256
    ).hexdigest()
    assert login_digest(FIELDS, bot_token=TOKEN) == expected


@pytest.mark.parametrize(
    ("query", "reason"),
    [
        (FIELDS, "no-hash"),
        (signed(FIELDS) | {"first_name": "Mallory"}, "bad-signature"),
        (signed(FIELDS | {"auth_date": str(NOW - 601)}), "expired"),
        (signed(FIELDS | {"auth_date": "soon"}), "malformed"),
    ],
    ids=["no-hash", "tampered", "too-old", "malformed"],
)
def test_a_redirect_that_does_not_hold_is_refused(
    query: dict[str, str], reason: str
) -> None:
    with pytest.raises(LoginWidgetError) as caught:
        check(query)
    assert caught.value.reason == reason


def test_another_bots_signature_is_refused() -> None:
    other = FIELDS | {"hash": login_digest(FIELDS, bot_token="999:other")}
    with pytest.raises(LoginWidgetError):
        check(other)
