"""Taking in what a person said, one checked value at a time.

``Heard`` is what one message carried - read off a button, or worked out of
free text by a model. Nothing in it is trusted: :func:`merge` checks every
value against the frame and puts into the brief only what stands, and says
in ``Note`` codes what did not, so the reply can name the reason instead of
silently asking again.
"""

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Final

from core.launch_agent.brief import (
    FORM_AUTO,
    FORM_NEW,
    FORM_OWN,
    START_DAYS,
    Brief,
    Frame,
)

USD: Final = "USD"
UZS: Final = "UZS"
OFFER_CHARS: Final = 500
KIND_CHARS: Final = 300
MIN_PHONE_DIGITS: Final = 9
MAX_PHONE_DIGITS: Final = 15
_TELEGRAM_HOSTS: Final = ("t.me/", "telegram.me/", "telegram.dog/")
_USERNAME: Final = re.compile(r"^@?([A-Za-z][A-Za-z0-9_]{3,31})$")
_HOST: Final = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9-]+)+$")


@dataclass(frozen=True, slots=True)
class Heard:
    """What one message said. Every field empty: nothing of that was said."""

    kind: str = ""
    offer: str = ""
    goal: str = ""
    link: str = ""
    phone: str = ""
    channel: str = ""
    form: str = ""
    budget: str = ""
    budget_currency: str = ""
    start_day: str = ""

    @property
    def nothing(self) -> bool:
        return not any(
            (
                self.kind,
                self.offer,
                self.goal,
                self.link,
                self.phone,
                self.channel,
                self.form,
                self.budget,
                self.start_day,
            )
        )


@dataclass(frozen=True, slots=True)
class Note:
    """One thing that was said and could not be taken, and why."""

    slot: str
    code: str
    detail: str = ""


@dataclass(frozen=True, slots=True)
class Merged:
    brief: Brief
    notes: tuple[Note, ...] = ()
    # The slots this message filled or changed.
    took: tuple[str, ...] = field(default_factory=tuple)


def _plain(words: str, limit: int) -> str:
    return " ".join(str(words or "").split())[:limit]


def site_link(raw: str) -> str:
    """A website address as it is saved, or ``""`` when it is not one."""
    text = str(raw or "").strip()
    if not text or " " in text:
        return ""
    bare = re.sub(r"^https?://", "", text, flags=re.IGNORECASE)
    host = bare.split("/", 1)[0].split("?", 1)[0].lower()
    if not _HOST.match(host):
        return ""
    return f"https://{bare}"


def telegram_link(raw: str) -> str:
    """A Telegram address as ``https://t.me/name``, or ``""``."""
    text = str(raw or "").strip()
    bare = re.sub(r"^https?://", "", text, flags=re.IGNORECASE)
    for host in _TELEGRAM_HOSTS:
        if bare.lower().startswith(host):
            rest = bare[len(host) :].strip("/")
            return f"https://t.me/{rest}" if rest and " " not in rest else ""
    found = _USERNAME.match(text)
    return f"https://t.me/{found.group(1)}" if found else ""


def phone_number(raw: str) -> str:
    """A phone number as ``+digits``, or ``""``."""
    digits = re.sub(r"\D", "", str(raw or ""))
    if not MIN_PHONE_DIGITS <= len(digits) <= MAX_PHONE_DIGITS:
        return ""
    if len(digits) == MIN_PHONE_DIGITS:
        # A local Uzbek number said without its country code.
        digits = f"998{digits}"
    return f"+{digits}"


def amount(raw: str) -> Decimal | None:
    """A sum as it was written - '5', '5.5', '50 000', '50 ming' - or nothing."""
    text = str(raw or "").lower().replace(" ", " ").strip()
    scale = Decimal(1)
    for word, times in (("mln", 1_000_000), ("million", 1_000_000), ("ming", 1_000)):
        if word in text:
            scale = Decimal(times)
            text = text.replace(word, " ")
            break
    text = re.sub(r"[^\d.,\s]", " ", text).strip()
    compact = re.sub(r"\s+", "", text)
    if not compact:
        return None
    if re.fullmatch(r"\d{1,3}([.,]\d{3})+", compact):
        compact = re.sub(r"[.,]", "", compact)
    else:
        compact = compact.replace(",", ".")
    try:
        value = Decimal(compact) * scale
    except InvalidOperation:
        return None
    return value if value > 0 else None


def budget_minor(raw: str, currency: str, frame: Frame) -> tuple[int, str]:
    """``(minor units in the account's currency, problem code)``."""
    value = amount(raw)
    if value is None:
        return 0, "not_a_sum"
    said = (currency or frame.currency).upper()
    if said != frame.currency.upper():
        if {said, frame.currency.upper()} != {USD, UZS} or frame.uzs_per_usd <= 0:
            return 0, "other_currency"
        rate = Decimal(frame.uzs_per_usd)
        value = value / rate if said == UZS else value * rate
    return int((value * frame.minor_per_unit).to_integral_value()), ""


def merge(brief: Brief, heard: Heard, frame: Frame) -> Merged:
    """The brief with what was heard and stands; what did not stand, noted."""
    notes: list[Note] = []
    took: list[str] = []
    new = brief

    def take(slot: str, **changes: object) -> None:
        nonlocal new
        new = new.with_(**changes, said=new.said | {slot})
        took.append(slot)

    if heard.kind and not frame.kind_known:
        take("kind", kind_said=_plain(heard.kind, KIND_CHARS))
    if heard.offer:
        take("offer", offer=_plain(heard.offer, OFFER_CHARS))
    if heard.goal:
        if frame.goal(heard.goal) is None:
            notes.append(Note("goal", "unknown_goal", heard.goal))
        elif heard.goal != new.goal:
            # Another goal asks other questions: what the old one was told
            # about where the tap goes does not carry over.
            take("goal", goal=heard.goal, link="", phone="", channel="", form="")
            new = new.with_(said=new.said - {"link", "phone", "channel", "form"})
    goal = frame.goal(new.goal)
    if heard.link:
        wants_telegram = goal is not None and goal.telegram
        link = telegram_link(heard.link) if wants_telegram else site_link(heard.link)
        if goal is not None and not goal.needs_link:
            notes.append(Note("link", "not_asked"))
        elif not link:
            notes.append(
                Note("link", "not_telegram" if wants_telegram else "not_a_link")
            )
        else:
            take("link", link=link)
    if heard.phone:
        phone = phone_number(heard.phone)
        if not phone:
            notes.append(Note("phone", "not_a_phone"))
        else:
            take("phone", phone=phone)
    if heard.channel:
        offered = {key for key, _label in goal.channels} if goal is not None else set()
        if heard.channel in offered:
            take("channel", channel=heard.channel)
        else:
            notes.append(Note("channel", "unknown_channel", heard.channel))
    if heard.form:
        allowed = {FORM_AUTO, FORM_NEW, FORM_OWN, *(one.id for one in frame.forms)}
        if heard.form in allowed:
            take("form", form=heard.form)
        else:
            notes.append(Note("form", "unknown_form"))
    if heard.budget:
        minor, problem = budget_minor(heard.budget, heard.budget_currency, frame)
        floor = goal.min_daily_minor if goal is not None else 0
        if problem:
            notes.append(Note("budget", problem))
        elif minor < floor:
            notes.append(Note("budget", "below_floor", str(floor)))
        else:
            take("budget", budget_minor=minor)
    if heard.start_day in START_DAYS:
        new = new.with_(start_day=heard.start_day)
    # A goal chosen after the budget may ask for more than was said.
    goal = frame.goal(new.goal)
    if goal is not None and 0 < new.budget_minor < goal.min_daily_minor:
        notes.append(Note("budget", "below_floor", str(goal.min_daily_minor)))
        new = new.with_(budget_minor=0, said=new.said - {"budget"})
        took = [slot for slot in took if slot != "budget"]
    return Merged(brief=new, notes=tuple(notes), took=tuple(dict.fromkeys(took)))


__all__ = [
    "Heard",
    "Merged",
    "Note",
    "amount",
    "budget_minor",
    "merge",
    "phone_number",
    "site_link",
    "telegram_link",
]
