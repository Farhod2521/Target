"""An unlinked Telegram asking the bot for a new password is sent to the
sign-in page's email reset, never to the support desk."""

from typing import Any

from app.modules.notifications.services import answer_reset_request


class _Bot:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    def send_message(self, **fields: Any) -> None:
        self.sent.append(fields)


def test_an_unlinked_chat_is_pointed_at_the_email_reset() -> None:
    bot = _Bot()

    outcome = answer_reset_request(client=bot, chat_id="1", known=None)  # type: ignore[arg-type]

    assert outcome == "reset_unlinked"
    (sent,) = bot.sent
    assert "Parolni unutdingizmi?" in sent["text"]
    assert "Yordam xizmati" not in sent["text"]
    (button,) = sent["buttons"]
    assert button.url.endswith("/accounts/login/")
