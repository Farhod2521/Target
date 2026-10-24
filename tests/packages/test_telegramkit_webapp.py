"""``initData``: the proof that a page opened inside Telegram is somebody's.

No Django, no database and no clock - the whole point of the module under
test is that the token and the current time arrive as arguments.

**These tests are written not to trust the code they test.** A file that
signs every payload with ``build_init_data`` - which lives in the module
under test - agrees with that module's own mistake: leave ``signature``
out of the digest and the helper leaves it out too, the tests agree with
themselves, and production refuses every real payload. The reasons this
file passes are:

1. :data:`VECTOR` is a **frozen known answer**. The string and the hex
   digest are literals; nothing computes them at run time.
2. :func:`reference_hash` is a second implementation, transcribed from
   ``aiogram.utils.web_app.check_webapp_signature`` - a library that
   receives real payloads from real clients every day. It shares no code
   with ``telegramkit``, so a mistake has to be made twice to hide.
3. The vector is checked against the reference as well as against the
   parser, so neither can drift alone.
4. :data:`WRONG_DIGEST` is the digest that reading leaves behind, kept as
   a literal and checked against the reference too - so the regression
   stays named rather than becoming a test nobody can read.
"""

import hashlib
import hmac
import json
from operator import itemgetter
from typing import Any
from urllib.parse import parse_qsl

import pytest
from telegramkit import (
    InitDataError,
    InitDataExpired,
    build_init_data,
    parse_init_data,
)
from telegramkit.webapp import SECRET_SALT

TOKEN = "123456:AA-secret-token-nobody-should-see"
NOW = 1_772_000_000

# --- The frozen vector ----------------------------------------------------

# A modern payload in the shape a real client sends: percent-encoded with
# encodeURIComponent, ``user`` as JSON, and ``signature`` present - the
# field Telegram added for third-party validation and the one easiest to
# leave out of the digest.
#
# Everything below is a literal. Nothing here is produced by the code
# under test, which is the only reason this file can fail.
VECTOR = (
    "query_id=AAHdF6IQAAAAAN0XohDhrOrc"
    "&user=%7B%22id%22%3A987654%2C%22first_name%22%3A%22Aziz%22%2C"
    "%22last_name%22%3A%22%22%2C%22username%22%3A%22aziz%22%2C"
    "%22language_code%22%3A%22ru%22%2C%22allows_write_to_pm%22%3Atrue%7D"
    "&auth_date=1772000000"
    "&chat_instance=-3788475317572404878"
    "&chat_type=private"
    "&signature=nq7hwzsFqDLmXsY2xJ7wZbFq8bB0R8oQ2Vd3xQnUuBvLPz6cGkFmYw"
    "&hash=00286f7e42a6579e3ae48d356a3555c4a8a38f4aa7faa1f2b53f3f573c10a355"
)

# What an implementation that leaves ``signature`` out of the digest
# computes for the same payload. Kept as a literal so the regression has a
# name: refusing VECTOR in favour of this digest is the production bug.
WRONG_DIGEST = "8c4229f520b3ac5acade9395741fcbe5d09e4712c53bcccdec73e6409cfb1fe3"


def reference_hash(init_data: str, token: str, *, keep_blank: bool = False) -> str:
    """``aiogram.utils.web_app.check_webapp_signature``, transcribed.

    Shares nothing with ``telegramkit``: ``parse_qsl`` rather than the
    package's own splitting, ``hash`` popped and nothing else removed,
    the two-stage HMAC written out. A format mistake would have to be
    made here too before it could hide.

    ``keep_blank`` is the one place two references disagree. aiogram
    leaves it at ``parse_qsl``'s default, which **drops** a field sent as
    ``start_param=``; ``URLSearchParams`` - what Telegram's own
    documentation snippet uses, and what the client that built the
    payload used - keeps it as an empty string. ``telegramkit`` follows
    the JavaScript, so the test for that case asks for it here rather
    than pretending the two agree.
    """
    parsed = dict(
        parse_qsl(init_data, keep_blank_values=keep_blank, strict_parsing=True)
    )
    parsed.pop("hash", None)
    check = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items(), key=itemgetter(0)))
    secret = hmac.new(key=b"WebAppData", msg=token.encode(), digestmod=hashlib.sha256)
    return hmac.new(
        key=secret.digest(), msg=check.encode(), digestmod=hashlib.sha256
    ).hexdigest()


def fields(**overrides: Any) -> dict[str, str]:
    """A payload shaped like the real thing, with fields swapped or added."""
    payload = {
        "auth_date": str(NOW - 60),
        "query_id": "AAHdF6IQAAAAAN0XohDhrOrc",
        "user": json.dumps(
            {"id": 987_654, "first_name": "Aziz", "username": "aziz", "is_bot": False}
        ),
    }
    payload.update({key: str(value) for key, value in overrides.items()})
    return payload


def signed(**overrides: Any) -> str:
    return build_init_data(fields(**overrides), bot_token=TOKEN)


# --- The vector, and the three things it holds together -------------------


def test_the_frozen_vector_is_what_the_reference_implementation_computes() -> None:
    """The vector's own guard.

    Without this the literal could be anything - including whatever this
    package happened to produce on the day it was pasted in, which is the
    trap the whole file exists to avoid.
    """
    body, _, digest = VECTOR.rpartition("&hash=")

    assert reference_hash(body, TOKEN) == digest


def test_a_real_shaped_payload_is_accepted() -> None:
    """The regression, and the payload a modern client actually sends.

    Every field a modern client sends, ``signature`` included, signed the
    way the documentation's HMAC section and every working library agree
    on: all received fields except ``hash``.
    """
    verified = parse_init_data(VECTOR, bot_token=TOKEN, now=NOW + 60)

    assert verified.user.id == "987654"
    assert verified.user.username == "aziz"


def test_the_digest_covers_the_signature_field() -> None:
    """The property the whole digest rests on.

    "except hash and signature" belongs to Telegram's Ed25519 procedure,
    which is a different check string with a ``bot_id`` prefix. The HMAC
    covers everything but the hash.
    """
    verified = parse_init_data(VECTOR, bot_token=TOKEN, now=NOW + 60)

    assert "signature" in verified.signed_keys
    assert "hash" not in verified.signed_keys


def test_the_frozen_wrong_digest_really_is_the_old_reading() -> None:
    """The literal's own guard, computed the way the old reading computed
    it.

    Dropping ``signature`` from the payload before hashing produces the
    same check string that reading builds from a payload that had it, so
    the reference implementation can state the refused digest without the
    old code being here to ask.
    """
    body = VECTOR.rpartition("&hash=")[0]
    without = "&".join(
        pair for pair in body.split("&") if not pair.startswith("signature=")
    )

    assert reference_hash(without, TOKEN) == WRONG_DIGEST
    assert VECTOR.rpartition("&hash=")[2] != WRONG_DIGEST


def test_a_payload_signed_the_old_way_is_refused() -> None:
    """The ambiguity is closed, and closed in one direction.

    ``signature`` is inside the digest, so this one is not a second
    reading of Telegram's format. It is a digest Telegram would not have
    written.
    """
    body = VECTOR.rpartition("&hash=")[0]

    with pytest.raises(InitDataError) as caught:
        parse_init_data(f"{body}&hash={WRONG_DIGEST}", bot_token=TOKEN, now=NOW)

    assert caught.value.reason == "bad-signature"


def test_a_payload_carrying_no_signature_still_verifies() -> None:
    """An older client sends fewer fields, and fewer fields is not a
    different format: the digest covers what arrived."""
    verified = parse_init_data(signed(), bot_token=TOKEN, now=NOW)

    assert verified.user.id == "987654"
    assert "signature" not in verified.signed_keys


# --- The signature --------------------------------------------------------


def test_the_id_is_a_string_because_everything_stores_it_as_one() -> None:
    """``TelegramChat.chat_id`` is a CharField, and the comparison is ``==``.

    An int here would make that comparison silently false for every real
    account, which is a login screen that refuses everybody.
    """
    assert isinstance(parse_init_data(VECTOR, bot_token=TOKEN, now=NOW).user.id, str)


def test_a_payload_signed_with_another_token_is_refused() -> None:
    with pytest.raises(InitDataError) as caught:
        parse_init_data(VECTOR, bot_token="999:someone-elses-bot", now=NOW)

    assert caught.value.reason == "bad-signature"


def test_a_tampered_field_invalidates_the_signature() -> None:
    """The attack this whole module exists to stop: another account's id."""
    with pytest.raises(InitDataError) as caught:
        parse_init_data(VECTOR.replace("987654", "111111"), bot_token=TOKEN, now=NOW)

    assert caught.value.reason == "bad-signature"


def test_an_unconfigured_deployment_verifies_nothing() -> None:
    """An empty key still produces a valid HMAC, so this is checked here too.

    Without it a deployment with no ``TELEGRAM_BOT_TOKEN`` would accept
    anything signed with the empty string - which is to say, anything.
    """
    with pytest.raises(InitDataError) as caught:
        parse_init_data(VECTOR, bot_token="", now=NOW)

    assert caught.value.reason == "no-token"


def test_the_secret_is_derived_the_way_telegram_derives_it() -> None:
    """Salt as the key, token as the message - and not the other way round.

    Swapping the two produces a perfectly valid HMAC that never matches
    anything Telegram sends, and the failure looks identical to a forgery.
    """
    swapped = hmac.new(TOKEN.encode(), SECRET_SALT, hashlib.sha256).digest()
    body = VECTOR.rpartition("&hash=")[0]
    check = "\n".join(
        f"{k}={v}" for k, v in sorted(dict(parse_qsl(body)).items(), key=itemgetter(0))
    )
    wrong = hmac.new(swapped, check.encode(), hashlib.sha256).hexdigest()

    with pytest.raises(InitDataError):
        parse_init_data(f"{body}&hash={wrong}", bot_token=TOKEN, now=NOW)


# --- Decoding -------------------------------------------------------------


def test_a_plus_is_decoded_the_way_every_client_decodes_it() -> None:
    """As a space, which is what ``parse_qsl`` and ``URLSearchParams`` do.

    A parser that kept ``+`` as a plus would compute a different check
    string from Telegram for any payload containing one, and be right only
    about its own tests.
    """
    body = "auth_date=1772000000&note=a+b&user=%7B%22id%22%3A5%7D"
    raw = f"{body}&hash={reference_hash(body, TOKEN)}"

    assert parse_init_data(raw, bot_token=TOKEN, now=NOW).user.id == "5"


def test_a_percent_encoded_plus_survives_as_a_plus() -> None:
    """The other half. ``%2B`` is a plus, and the digest has to agree."""
    body = "auth_date=1772000000&note=a%2Bb&user=%7B%22id%22%3A5%7D"
    raw = f"{body}&hash={reference_hash(body, TOKEN)}"

    assert parse_init_data(raw, bot_token=TOKEN, now=NOW).user.id == "5"


def test_a_blank_value_is_a_field_rather_than_a_missing_one() -> None:
    """``start_param=`` is signed as an empty string, not dropped.

    The one case where the two reference implementations differ, and the
    JavaScript one wins: ``URLSearchParams`` keeps a blank value and the
    client that built the payload is a browser. A parser that dropped it
    would build a shorter check string than Telegram signed and refuse a
    payload nobody could explain.
    """
    body = "auth_date=1772000000&start_param=&user=%7B%22id%22%3A5%7D"
    raw = f"{body}&hash={reference_hash(body, TOKEN, keep_blank=True)}"

    assert parse_init_data(raw, bot_token=TOKEN, now=NOW).user.id == "5"


# --- Refusals, each with its own name -------------------------------------


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        ("", "empty"),
        ("notaquerystring", "malformed"),
        ("auth_date=1&user=%7B%7D", "no-hash"),
        ("user=%7B%22id%22%3A1%7D&user=%7B%22id%22%3A2%7D&hash=abc", "repeated-field"),
    ],
    ids=["empty", "no pairs", "no hash", "repeated key"],
)
def test_a_malformed_payload_names_its_own_failure_in_the_log(
    raw: str, reason: str
) -> None:
    """One class out, a different slug on each.

    The class is what the caller shows a reader - one sentence, because a
    page that named the failing check would tell a forger how far they
    got. The slug is what the caller logs, which is the other half of
    that bargain.
    """
    with pytest.raises(InitDataError) as caught:
        parse_init_data(raw, bot_token=TOKEN, now=NOW)

    assert caught.value.reason == reason


def test_a_refusal_carries_the_field_names_and_never_a_value() -> None:
    """The log needs to know what arrived. It must not know who.

    ``user`` is a person's name and Telegram id; a log line carrying it
    would be the one place in this product that stores what the digest
    exists to protect.
    """
    with pytest.raises(InitDataError) as caught:
        parse_init_data(VECTOR, bot_token="999:wrong", now=NOW)

    assert "signature" in caught.value.keys
    assert "user" in caught.value.keys
    assert not any("Aziz" in key or "987654" in key for key in caught.value.keys)


@pytest.mark.parametrize(
    ("user", "reason"),
    [
        ("", "no-user"),
        ("not json", "user-not-json"),
        ("[1, 2]", "user-not-object"),
        ('{"first_name": "Aziz"}', "user-has-no-id"),
        ('{"id": true}', "user-has-no-id"),
    ],
    ids=["absent", "not json", "not an object", "no id", "a bool is not an id"],
)
def test_a_payload_naming_no_account_is_refused(user: str, reason: str) -> None:
    """Even signed. A proof of authenticity that names nobody buys nothing.

    ``{"id": true}`` is the interesting one: ``bool`` is an ``int`` in
    Python, so without an explicit check it would log somebody in as the
    account whose id is 1.
    """
    with pytest.raises(InitDataError) as caught:
        parse_init_data(
            build_init_data(fields(user=user), bot_token=TOKEN),
            bot_token=TOKEN,
            now=NOW,
        )

    assert caught.value.reason == reason


def test_an_account_with_no_handle_is_still_an_account() -> None:
    """A Telegram account need not have a username, and most screens cope."""
    raw = build_init_data(
        fields(user=json.dumps({"id": 42, "first_name": "Aziz"})), bot_token=TOKEN
    )

    user = parse_init_data(raw, bot_token=TOKEN, now=NOW).user
    assert (user.id, user.username) == ("42", "")


# --- The clock ------------------------------------------------------------


def test_an_old_but_genuine_payload_is_named_as_old() -> None:
    """The one failure with an action behind it, and the only one named.

    Safe to name because it is only reachable once the HMAC checked out:
    whoever sees this already holds something Telegram signed.
    """
    with pytest.raises(InitDataExpired) as caught:
        parse_init_data(signed(), bot_token=TOKEN, now=NOW, max_age_seconds=30)

    assert caught.value.reason == "expired"
    assert caught.value.age_seconds == 60


def test_a_payload_inside_the_window_is_accepted() -> None:
    raw = signed(auth_date=NOW - 29)

    assert parse_init_data(raw, bot_token=TOKEN, now=NOW, max_age_seconds=30)


def test_a_payload_dated_in_the_future_carries_the_skew() -> None:
    """A drifted server clock and a page left open look identical on the
    screen and need completely different fixes, so the number is what the
    log gets to tell them apart by."""
    raw = signed(auth_date=NOW + 3_600)

    with pytest.raises(InitDataExpired) as caught:
        parse_init_data(raw, bot_token=TOKEN, now=NOW)

    assert caught.value.reason == "future-date"
    assert caught.value.age_seconds == -3_600


def test_an_unreadable_auth_date_is_refused() -> None:
    with pytest.raises(InitDataError) as caught:
        parse_init_data(signed(auth_date="yesterday"), bot_token=TOKEN, now=NOW)

    assert caught.value.reason == "no-auth-date"
