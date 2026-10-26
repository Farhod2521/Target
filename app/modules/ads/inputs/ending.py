"""The screen after a new lead form: its words and its one button."""

from pydantic import BaseModel, Field

from app.modules.ads.constants import (
    ENDING_BODY_MAX,
    ENDING_BUTTON_MAX,
    ENDING_TITLE_MAX,
)
from app.modules.ads.inputs import Problems
from app.modules.ads.inputs.destination import URL_MAX, own_site, phone_in
from core.leads.ending import (
    DEFAULT_BUTTON_TEXT,
    ENDING_CALL,
    ENDING_KINDS,
    ENDING_NONE,
    ENDING_TELEGRAM,
    ENDING_WEBSITE,
    FormEnding,
    telegram_username,
)


class EndingIn(BaseModel):
    kind: str = ""
    website: str = Field("", max_length=URL_MAX)
    telegram: str = Field("", max_length=URL_MAX)
    phone: str = Field("", max_length=32)
    button: str = Field("", max_length=ENDING_BUTTON_MAX)
    title: str = Field("", max_length=ENDING_TITLE_MAX)
    body: str = Field("", max_length=ENDING_BODY_MAX)


def check_ending(
    ending: EndingIn | None,
    *,
    region: str,
    default_title: str,
    problems: Problems,
) -> FormEnding | None:
    """The ending of a form about to be built, or ``None`` after a problem."""
    if ending is None or ending.kind not in ENDING_KINDS:
        problems.add("ending.kind", "Forma oxirida nima bo'lishini tanlang.")
        return None
    kind = ending.kind
    target: str | None = ""
    if kind == ENDING_WEBSITE:
        target = own_site(ending.website, problems=problems, field="ending.website")
    elif kind == ENDING_TELEGRAM:
        target = telegram_username(ending.telegram)
        if not target:
            problems.add(
                "ending.telegram", "Telegram username'ini yozing, masalan: @osh_markazi"
            )
    elif kind == ENDING_CALL:
        target = phone_in(
            ending.phone, region=region, problems=problems, field="ending.phone"
        )
    if kind != ENDING_NONE and not target:
        return None
    title = ending.title.strip()
    button = ending.button.strip()
    return FormEnding(
        kind=kind,
        target=target or "",
        button_text=""
        if kind == ENDING_NONE or button == DEFAULT_BUTTON_TEXT.get(kind)
        else button,
        title="" if title == default_title else title,
        body=ending.body.strip(),
    )


__all__ = ["EndingIn", "check_ending"]
