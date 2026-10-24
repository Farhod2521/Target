"""telegramkit: the transport, the error split, and reading an update.

No Django and no database, like every test in this directory. The client
gets an ``httpx.MockTransport``, which is the level at which a fake is
distinguishable from a socket - and is exactly what the suite-wide guard
in ``tests/conftest.py`` lets through on purpose.
"""

import json
from typing import Any

import httpx
import pytest
from telegramkit import (
    MESSAGE_MAX_CHARS,
    BotBlocked,
    BotClient,
    Button,
    ButtonPress,
    ChatUnreachable,
    Command,
    OtherMessage,
    TelegramAPIError,
    TelegramError,
    TelegramRateLimited,
    TelegramTemporaryError,
    TextMessage,
    read_update,
    scrubbed,
    secret_matches,
)

TOKEN = "123456:AA-secret-token-nobody-should-see"


def client_answering(
    payload: dict[str, Any],
    *,
    status: int = 200,
    seen: list[httpx.Request] | None = None,
) -> BotClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return httpx.Response(status, json=payload)

    return BotClient(
        token=TOKEN, client=httpx.Client(transport=httpx.MockTransport(handler))
    )


def client_raising(error: Exception) -> BotClient:
    def handler(request: httpx.Request) -> httpx.Response:
        raise error

    return BotClient(
        token=TOKEN, client=httpx.Client(transport=httpx.MockTransport(handler))
    )


# --- The credential -------------------------------------------------------


def test_the_token_never_appears_in_an_error_message() -> None:
    """The one string that reliably reaches a log must not carry the key.

    Telegram puts the token in the URL path, so any message built from a
    URL - a timeout, a transport failure, a non-JSON body - carries the
    whole credential unless something takes it out.
    """
    failure = httpx.ConnectError("failed to connect to /bot" + TOKEN)
    with (
        client_raising(failure) as bot,
        pytest.raises(TelegramTemporaryError) as caught,
    ):
        bot.send_message(chat_id="1", text="salom")

    assert TOKEN not in str(caught.value)
    assert "/bot***" in str(caught.value)


def test_scrubbing_leaves_the_rest_of_the_sentence_alone() -> None:
    assert scrubbed(f"POST https://api.telegram.org/bot{TOKEN}/sendMessage failed") == (
        "POST https://api.telegram.org/bot***/sendMessage failed"
    )


def test_a_client_without_a_token_is_refused_at_construction() -> None:
    """Not at the first call. An empty token is a deployment that has not
    been configured, and the failure belongs where somebody can read it."""
    with pytest.raises(ValueError, match="token"):
        BotClient(token="")


# --- Sending --------------------------------------------------------------


def test_sending_returns_the_id_an_edit_would_need() -> None:
    seen: list[httpx.Request] = []
    with client_answering(
        {"ok": True, "result": {"message_id": 42, "chat": {"id": 7}}}, seen=seen
    ) as bot:
        sent = bot.send_message(chat_id="7", text="salom")

    assert sent.message_id == 42
    assert sent.chat_id == "7"
    assert seen[0].url.path.endswith("/sendMessage")


def test_a_picture_goes_up_as_a_multipart_photo_quoting_its_message() -> None:
    seen: list[httpx.Request] = []
    with client_answering(
        {"ok": True, "result": {"message_id": 43, "chat": {"id": 7}}}, seen=seen
    ) as bot:
        sent = bot.send_photo(
            chat_id="7", filename="shot.jpg", content=b"\xff\xd8jpeg", reply_to=42
        )

    assert sent.message_id == 43
    request = seen[0]
    assert request.url.path.endswith("/sendPhoto")
    assert request.headers["content-type"].startswith("multipart/form-data")
    body = request.read()
    assert b'name="photo"; filename="shot.jpg"' in body
    assert b"\xff\xd8jpeg" in body
    assert b'"message_id": 42' in body


def test_any_other_file_goes_up_as_a_document() -> None:
    seen: list[httpx.Request] = []
    with client_answering({"ok": True, "result": {"message_id": 5}}, seen=seen) as bot:
        bot.send_document(chat_id="7", filename="hisob.pdf", content=b"%PDF")

    assert seen[0].url.path.endswith("/sendDocument")
    body = seen[0].read()
    assert b'name="document"; filename="hisob.pdf"' in body
    assert b"reply_parameters" not in body


def test_a_message_asks_for_html_and_no_link_preview() -> None:
    """Both are decisions, not defaults. HTML because Telegram's Markdown
    refuses a whole message over an unescaped underscore in a campaign
    name; no preview because a card of somebody's landing page pushes the
    sentence that mattered off the screen."""
    import json

    seen: list[httpx.Request] = []
    with client_answering({"ok": True, "result": {"message_id": 1}}, seen=seen) as bot:
        bot.send_message(chat_id="7", text="salom")

    body = json.loads(seen[0].content)
    assert body["parse_mode"] == "HTML"
    assert body["link_preview_options"] == {"is_disabled": True}


def test_a_message_longer_than_telegram_accepts_is_cut_rather_than_refused() -> None:
    """A truncated notification still says which screen to open. A refused
    one says nothing at all."""
    import json

    seen: list[httpx.Request] = []
    with client_answering({"ok": True, "result": {"message_id": 1}}, seen=seen) as bot:
        bot.send_message(chat_id="7", text="x" * (MESSAGE_MAX_CHARS + 500))

    body = json.loads(seen[0].content)
    assert len(body["text"]) == MESSAGE_MAX_CHARS
    assert body["text"].endswith("…")


def test_a_cut_never_lands_inside_a_tag() -> None:
    """A slice is not a cut when the message is HTML.

    Every message goes with ``parse_mode="HTML"``, so a cut that ends
    halfway through ``<a href="...">`` is not a shorter message - it is
    "can't parse entities", and the whole thing is refused. Which is the
    outcome the truncation exists to avoid, arrived at by the truncation.
    """
    import json

    tail = '<a href="https://example.test/app/some/long/path">Kabinetda ochish</a>'
    seen: list[httpx.Request] = []
    with client_answering({"ok": True, "result": {"message_id": 1}}, seen=seen) as bot:
        bot.send_message(chat_id="7", text="x" * (MESSAGE_MAX_CHARS - 12) + tail)

    text = json.loads(seen[0].content)["text"]
    assert "<a" not in text
    assert "href" not in text


def test_a_cut_closes_what_it_left_open() -> None:
    """The other half of the same rule. A ``<b>`` opened before the cut and
    closed after it is markup Telegram refuses to parse, so the closer is
    put back - and only the ones that were actually open."""
    import json

    seen: list[httpx.Request] = []
    with client_answering({"ok": True, "result": {"message_id": 1}}, seen=seen) as bot:
        bot.send_message(chat_id="7", text="<b>" + "x" * (MESSAGE_MAX_CHARS + 500))

    text = json.loads(seen[0].content)["text"]
    assert text.startswith("<b>")
    assert text.endswith("</b>")
    assert text.count("<b>") == text.count("</b>") == 1


def test_the_ceiling_is_measured_the_way_telegram_measures_it() -> None:
    """Code units, not characters.

    An emoji in a campaign name is one character to Python and two to the
    API, so three thousand of them are inside a ``len`` of 4096 and outside
    Telegram's - which is a refusal in the one place this guard exists to
    prevent one.
    """
    import json

    seen: list[httpx.Request] = []
    with client_answering({"ok": True, "result": {"message_id": 1}}, seen=seen) as bot:
        bot.send_message(chat_id="7", text="\U0001f3af" * 3_000)

    text = json.loads(seen[0].content)["text"]
    assert len(text.encode("utf-16-le")) // 2 <= MESSAGE_MAX_CHARS


def test_an_edit_with_no_buttons_sends_an_empty_keyboard() -> None:
    """Which is how Telegram is told to take the old one away - and taking
    it away is the point: a card still offering a decision that has been
    made invites a second press."""
    import json

    seen: list[httpx.Request] = []
    with client_answering({"ok": True, "result": True}, seen=seen) as bot:
        bot.edit_message_text(chat_id="7", message_id=3, text="tayyor")

    body = json.loads(seen[0].content)
    assert body["reply_markup"] == {"inline_keyboard": []}


def test_buttons_can_be_taken_off_without_touching_the_text() -> None:
    """For a message whose text is the thing that was asked for.

    An answer the assistant wrote has a question above it and a reader
    holding it. Rewriting the message - what a card does to report its own
    outcome - would take that answer off the screen; this call says which
    method Telegram is asked for, and that no text goes with it.
    """
    import json

    seen: list[httpx.Request] = []
    with client_answering({"ok": True, "result": True}, seen=seen) as bot:
        bot.edit_message_buttons(chat_id="7", message_id=3)

    assert seen[0].url.path.endswith("/editMessageReplyMarkup")
    body = json.loads(seen[0].content)
    assert body["reply_markup"] == {"inline_keyboard": []}
    assert "text" not in body


def test_a_bare_true_result_is_normalised_to_a_dict() -> None:
    """Most write methods answer with ``true``. No caller should have to
    check the type of what it got."""
    with client_answering({"ok": True, "result": True}) as bot:
        bot.answer_callback_query(query_id="q1", text="bajarildi")


def test_callback_data_over_the_limit_is_refused_where_it_is_written() -> None:
    """Telegram refuses the whole request and names none of the buttons, so
    by the time the error arrives the value that was too long is three
    frames away."""
    with pytest.raises(ValueError, match="64 bytes"):
        Button(text="ha", data="a:" + "x" * 100).as_payload()


def test_a_button_either_answers_or_opens_a_page_and_never_both() -> None:
    """Telegram refuses such a keyboard; this refuses it where it is written."""
    with pytest.raises(ValueError, match="not both and not neither"):
        Button(text="ha", data="a:1", web_app="https://example.test/").as_payload()

    with pytest.raises(ValueError, match="not both and not neither"):
        Button(text="ha").as_payload()


def test_a_web_app_button_carries_the_url_telegram_expects() -> None:
    assert Button(text="Batafsil", web_app="https://example.test/m/").as_payload() == {
        "text": "Batafsil",
        "web_app": {"url": "https://example.test/m/"},
    }


def test_a_styled_button_carries_its_colour_and_a_plain_one_does_not() -> None:
    """Older clients ignore the field; a plain button must not send it."""
    assert Button(text="Ha", data="a:1", style="success").as_payload() == {
        "text": "Ha",
        "callback_data": "a:1",
        "style": "success",
    }
    assert "style" not in Button(text="Ha", data="a:1").as_payload()


def test_answers_share_a_row_and_a_page_gets_one_of_its_own() -> None:
    """Two side-by-side buttons read as a choice; a link is not a choice."""
    import json

    seen: list[httpx.Request] = []
    with client_answering({"ok": True, "result": {"message_id": 1}}, seen=seen) as bot:
        bot.send_message(
            chat_id="55",
            text="taklif",
            buttons=(
                Button(text="Tasdiqlash", data="a:1"),
                Button(text="Rad etish", data="r:1"),
                Button(text="Batafsil", web_app="https://example.test/m/"),
            ),
        )

    rows = json.loads(seen[0].content)["reply_markup"]["inline_keyboard"]
    assert [len(row) for row in rows] == [2, 1]
    assert rows[1][0]["web_app"] == {"url": "https://example.test/m/"}


def test_a_button_asking_for_its_own_row_gets_one_under_the_answers() -> None:
    """A list of replies side by side would be cut into each other on a
    phone, so each takes a line - under the shared row, above any page."""
    import json

    seen: list[httpx.Request] = []
    with client_answering({"ok": True, "result": {"message_id": 1}}, seen=seen) as bot:
        bot.send_message(
            chat_id="55",
            text="savol",
            buttons=(
                Button(text="Batafsil", web_app="https://example.test/m/"),
                Button(text="Navbat kutish", data="q:1:0", row="own"),
                Button(text="To'xtatish", data="c:1"),
                Button(text="Narx qimmat", data="q:1:1", row="own"),
            ),
        )

    rows = json.loads(seen[0].content)["reply_markup"]["inline_keyboard"]
    assert [[button["text"] for button in row] for row in rows] == [
        ["To'xtatish"],
        ["Navbat kutish"],
        ["Narx qimmat"],
        ["Batafsil"],
    ]


def test_set_webhook_narrows_what_telegram_may_deliver() -> None:
    import json

    seen: list[httpx.Request] = []
    with client_answering({"ok": True, "result": True}, seen=seen) as bot:
        bot.set_webhook(url="https://example.test/hook/", secret_token="s3cret")

    body = json.loads(seen[0].content)
    assert body["allowed_updates"] == ["message", "callback_query"]
    assert body["secret_token"] == "s3cret"


def test_webhook_info_carries_telegram_s_own_account_of_the_failure() -> None:
    """The five fields the "nothing arrives" question is answered from.

    An update that was never delivered leaves nothing on our side to look
    at - no log line, no row - so this response is the only evidence there
    is that a webhook exists at all and what happened to the last delivery.
    """
    with client_answering(
        {
            "ok": True,
            "result": {
                "url": "https://example.test/webhooks/telegram/",
                "has_custom_certificate": False,
                "pending_update_count": 3,
                "last_error_date": 1_757_000_000,
                "last_error_message": "Wrong response from the webhook: 403 Forbidden",
                "max_connections": 40,
                "allowed_updates": ["message", "callback_query"],
            },
        }
    ) as bot:
        info = bot.get_webhook_info()

    assert info.url == "https://example.test/webhooks/telegram/"
    assert info.pending_update_count == 3
    assert info.last_error_date == 1_757_000_000
    assert "403" in info.last_error_message
    assert info.allowed_updates == ("message", "callback_query")


def test_a_bot_with_no_webhook_reads_as_an_empty_url_rather_than_an_error() -> None:
    """Telegram answers a bot nobody set up with ``{"url": ""}`` and ok:true.

    Not an error, and it must not be read as one: it is also what a bot
    that polls looks like. The empty string is the whole finding.
    """
    with client_answering(
        {"ok": True, "result": {"url": "", "pending_update_count": 0}}
    ) as bot:
        info = bot.get_webhook_info()

    assert info.url == ""
    assert info.last_error_message == ""
    assert info.allowed_updates == ()


# --- The error split ------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "description", "expected"),
    [
        (403, "Forbidden: bot was blocked by the user", BotBlocked),
        (400, "Bad Request: chat not found", ChatUnreachable),
        (400, "Bad Request: user is deactivated", ChatUnreachable),
        (400, "Bad Request: message is not modified", TelegramAPIError),
        (400, "Bad Request: message text is empty", TelegramAPIError),
        (429, "Too Many Requests: retry after 30", TelegramRateLimited),
        (500, "Internal Server Error", TelegramTemporaryError),
        (502, "Bad Gateway", TelegramTemporaryError),
    ],
)
def test_a_refusal_becomes_the_class_the_caller_branches_on(
    status: int, description: str, expected: type[Exception]
) -> None:
    """The class is the decision. Only two of these switch a link off, and
    telling them apart from the status code alone is impossible: a
    malformed edit and a deleted account are both 400."""
    with (
        client_answering(
            {"ok": False, "description": description}, status=status
        ) as bot,
        pytest.raises(expected),
    ):
        bot.send_message(chat_id="7", text="salom")


def test_an_unmodified_message_is_not_treated_as_a_dead_chat() -> None:
    """The 400 a second press produces. Read as ``ChatUnreachable`` it
    would switch somebody's notifications off for pressing twice."""
    with (
        client_answering(
            {"ok": False, "description": "Bad Request: message is not modified"},
            status=400,
        ) as bot,
        pytest.raises(TelegramAPIError) as caught,
    ):
        bot.edit_message_text(chat_id="7", message_id=1, text="bir xil")

    assert not isinstance(caught.value, ChatUnreachable)
    assert not isinstance(caught.value, BotBlocked)


def test_a_rate_limit_carries_telegram_s_own_wait() -> None:
    with (
        client_answering(
            {
                "ok": False,
                "description": "Too Many Requests",
                "parameters": {"retry_after": 27},
            },
            status=429,
        ) as bot,
        pytest.raises(TelegramRateLimited) as caught,
    ):
        bot.send_message(chat_id="7", text="salom")

    assert caught.value.retry_after == 27


def test_a_two_hundred_with_ok_false_is_still_a_refusal() -> None:
    """Telegram answers some refusals with the ordinary success status.
    Reading only the status code lets one travel on as a message that was
    sent and has no id."""
    with (
        client_answering(
            {"ok": False, "description": "Bad Request: chat not found"}
        ) as bot,
        pytest.raises(ChatUnreachable),
    ):
        bot.send_message(chat_id="7", text="salom")


def test_a_timeout_is_temporary_rather_than_permanent() -> None:
    with (
        client_raising(httpx.ReadTimeout("too slow")) as bot,
        pytest.raises(TelegramTemporaryError),
    ):
        bot.send_message(chat_id="7", text="salom")


def test_a_non_json_body_is_temporary_and_carries_no_token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>gateway</html>")

    with (
        BotClient(
            token=TOKEN, client=httpx.Client(transport=httpx.MockTransport(handler))
        ) as bot,
        pytest.raises(TelegramTemporaryError) as caught,
    ):
        bot.send_message(chat_id="7", text="salom")

    assert TOKEN not in str(caught.value)


def test_every_failure_class_is_catchable_as_one() -> None:
    """A caller that only wants "did it go" catches the base and stops."""
    assert issubclass(BotBlocked, TelegramError)
    assert issubclass(TelegramRateLimited, TelegramTemporaryError)


def test_a_borrowed_client_is_not_closed() -> None:
    """The pool belongs to whoever made it. Closing it would break the
    next message in the same sweep."""
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"ok": True}))
    shared = httpx.Client(transport=transport)
    with BotClient(token=TOKEN, client=shared):
        pass
    assert not shared.is_closed


# --- Reading an update ----------------------------------------------------


def test_a_start_command_carries_its_deep_link_payload() -> None:
    """``t.me/bot?start=XYZ`` arrives as the text ``/start XYZ``, which is
    the whole two-tap linking mechanism."""
    update = read_update(
        {
            "message": {
                "chat": {"id": 555},
                "from": {"id": 555, "username": "aslon"},
                "text": "/start abc123",
            }
        }
    )
    assert isinstance(update, Command)
    assert (update.name, update.argument, update.chat_id) == ("start", "abc123", "555")
    assert update.sender.username == "aslon"


def test_a_command_addressed_to_the_bot_by_name_is_the_same_command() -> None:
    """Telegram appends the username in group chats. A bot that only
    matched the bare form would be silent there."""
    update = read_update(
        {"message": {"chat": {"id": 1}, "from": {"id": 1}, "text": "/stop@thebot"}}
    )
    assert isinstance(update, Command)
    assert update.name == "stop"


def test_something_somebody_typed_is_read_as_a_message_rather_than_dropped() -> None:
    """The bot answers questions now, so a sentence is an update it acts on."""
    update = read_update(
        {
            "message": {
                "message_id": 42,
                "chat": {"id": 555, "type": "private"},
                "from": {"id": 555, "username": "aslon"},
                "text": "  Nega lidlar qimmatlashdi?  ",
            }
        }
    )
    assert isinstance(update, TextMessage)
    assert update.text == "Nega lidlar qimmatlashdi?"
    assert (update.chat_id, update.message_id) == ("555", 42)
    assert update.chat_type == "private"


def test_where_it_was_said_is_carried_and_not_acted_on() -> None:
    """A bot that answers every sentence is right in a private
    conversation and is a bot being removed from a group. Which of those a
    deployment wants is not a question a parser should answer."""
    update = read_update(
        {
            "message": {
                "message_id": 5,
                "chat": {"id": -100500, "type": "supergroup"},
                "from": {"id": 555},
                "text": "salom",
            }
        }
    )
    assert isinstance(update, TextMessage)
    assert update.chat_type == "supergroup"


def test_a_body_with_no_chat_type_says_so_rather_than_guessing() -> None:
    """Telegram documents the field as always present, so an absent one is
    a body that is not Telegram's - and the caller refuses it."""
    update = read_update(
        {
            "message": {
                "message_id": 5,
                "chat": {"id": 555},
                "from": {"id": 555},
                "text": "salom",
            }
        }
    )
    assert isinstance(update, TextMessage)
    assert update.chat_type == ""


def test_a_command_is_never_read_as_a_question() -> None:
    """A command is also a message with text in it. The order the two
    readers are tried in is the whole distinction between them."""
    update = read_update(
        {
            "message": {
                "message_id": 7,
                "chat": {"id": 1},
                "from": {"id": 1},
                "text": "/stop",
            }
        }
    )
    assert isinstance(update, Command)


def test_a_message_with_no_text_is_read_as_wordless() -> None:
    """A photograph, a voice note, a location, a sticker.

    Each is a person expecting an answer, so it is read - who sent it and
    where - and what it contained is not: nothing here can read it.
    """
    update = read_update(
        {
            "message": {
                "message_id": 7,
                "chat": {"id": 1, "type": "private"},
                "from": {"id": 1, "username": "aslon"},
                "photo": [{"file_id": "x"}],
            }
        }
    )

    assert isinstance(update, OtherMessage)
    assert (update.chat_id, update.chat_type, update.message_id) == ("1", "private", 7)
    assert update.sender.username == "aslon"


def test_a_caption_is_not_read_as_a_question() -> None:
    """The words under a photograph are about the photograph, and an
    answer that cannot see it would be a guess."""
    update = read_update(
        {
            "message": {
                "message_id": 7,
                "chat": {"id": 1, "type": "private"},
                "from": {"id": 1},
                "photo": [{"file_id": "x"}],
                "caption": "Bu reklama nega rad etildi?",
            }
        }
    )

    assert isinstance(update, OtherMessage)


def test_a_wordless_message_with_no_sender_is_nothing() -> None:
    """Only something a person sent is somebody waiting for an answer."""
    assert (
        read_update({"message": {"message_id": 7, "chat": {"id": 1}, "photo": []}})
        is None
    )


def test_a_message_with_no_id_is_not_something_an_answer_can_quote() -> None:
    assert (
        read_update({"message": {"chat": {"id": 1}, "from": {"id": 1}, "text": "hi"}})
        is None
    )


def test_the_typing_hint_is_sent_and_never_raised() -> None:
    """A hint about a message that is coming. Losing it must never lose
    the message, so a refusal here is swallowed where every other call in
    this client raises."""
    seen: list[httpx.Request] = []
    client_answering({"ok": True, "result": True}, seen=seen).send_chat_action(
        chat_id="555"
    )

    assert seen[0].url.path.endswith("/sendChatAction")
    assert json.loads(seen[0].content) == {"chat_id": "555", "action": "typing"}

    client_raising(httpx.ConnectTimeout("down")).send_chat_action(chat_id="555")


def test_an_answer_can_quote_the_question_it_belongs_to() -> None:
    """Twenty seconds and three messages may sit between the two."""
    seen: list[httpx.Request] = []
    client_answering(
        {"ok": True, "result": {"message_id": 9, "chat": {"id": 555}}}, seen=seen
    ).send_message(chat_id="555", text="javob", reply_to=42)

    body = json.loads(seen[0].content)
    assert body["reply_parameters"] == {
        "message_id": 42,
        "allow_sending_without_reply": True,
    }


def test_a_notification_quotes_nothing() -> None:
    """It answers no message - it arrives because a sweep ran."""
    seen: list[httpx.Request] = []
    client_answering(
        {"ok": True, "result": {"message_id": 9, "chat": {"id": 555}}}, seen=seen
    ).send_message(chat_id="555", text="xabar")

    assert "reply_parameters" not in json.loads(seen[0].content)


def test_a_button_press_carries_what_answering_and_editing_both_need() -> None:
    update = read_update(
        {
            "callback_query": {
                "id": "q-1",
                "from": {"id": 555},
                "data": "a:abc",
                "message": {"message_id": 9, "chat": {"id": 555}},
            }
        }
    )
    assert isinstance(update, ButtonPress)
    assert (update.query_id, update.message_id, update.data) == ("q-1", 9, "a:abc")


def test_a_press_from_a_forwarded_card_keeps_the_two_ids_apart() -> None:
    """The whole authorisation check downstream. ``from`` is who pressed
    and ``chat`` is where the message sits, and a forwarded card is where
    they differ."""
    update = read_update(
        {
            "callback_query": {
                "id": "q-1",
                "from": {"id": 999},
                "data": "a:abc",
                "message": {"message_id": 9, "chat": {"id": 555}},
            }
        }
    )
    assert isinstance(update, ButtonPress)
    assert update.sender.id == "999"
    assert update.chat_id == "555"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"edited_message": {"chat": {"id": 1}, "text": "/start"}},
        {"channel_post": {"chat": {"id": 1}, "text": "salom"}},
        {"message": {"chat": {"id": 1}, "from": {"id": 1}, "text": "salom"}},
        {"message": {"chat": {"id": 1}, "from": {"id": 1}, "text": "/"}},
        {"message": {"from": {"id": 1}, "text": "/start"}},
        {"callback_query": {"id": "q", "from": {"id": 1}, "data": "a:1"}},
        {"callback_query": {"id": "q", "from": {"id": 1}, "message": {"chat": {}}}},
    ],
)
def test_anything_this_bot_has_no_behaviour_for_reads_as_nothing(
    payload: dict[str, Any],
) -> None:
    """The ordinary case rather than an error: Telegram delivers what the
    subscription allows, and a message that is not a command is not a
    fault. A press with no message behind it is here too - nothing can be
    edited and nothing identifies what was pressed on."""
    assert read_update(payload) is None


# --- The secret -----------------------------------------------------------


def test_the_secret_must_match_exactly() -> None:
    assert secret_matches(header="s3cret", expected="s3cret")
    assert not secret_matches(header="s3cre", expected="s3cret")
    assert not secret_matches(header="S3CRET", expected="s3cret")


def test_an_unconfigured_deployment_matches_nothing() -> None:
    """Empty means refuse, not "accept anybody". The same rule
    ``META_WEBHOOK_VERIFY_TOKEN`` follows with the same problem."""
    assert not secret_matches(header="", expected="")
    assert not secret_matches(header="anything", expected="")
    assert not secret_matches(header="", expected="s3cret")


def test_a_shared_row_longer_than_telegram_draws_is_wrapped() -> None:
    """Eleven numbers are one question; Telegram draws eight to a line."""
    import json

    seen: list[httpx.Request] = []
    with client_answering({"ok": True, "result": {"message_id": 1}}, seen=seen) as bot:
        bot.send_message(
            chat_id="55",
            text="baho",
            buttons=tuple(Button(text=str(n), data=f"n:{n}") for n in range(11)),
        )

    rows = json.loads(seen[0].content)["reply_markup"]["inline_keyboard"]
    assert [len(row) for row in rows] == [8, 3]
