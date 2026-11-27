"""The changes the assistant may prepare beyond a budget and a switch.

Each kind here is a thin reading of what the owner asked into the ask the
campaigns screen itself would make (``app.modules.ads.actions``), with the
words the confirm button shows: what it is now, what it becomes. Nothing is
checked here that the screen's own service does not check again - the point
is one set of rules, so an advert cannot be changed through the conversation
in a way the screen would refuse.

What is kept on the answer's row is the owner's wish (``params``), not the
finished change. The button is pressed minutes later; an audience built then
from the wish is built from the audience as it stands then.
"""

from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any, Final
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.common.money import format_minor, provider_money
from app.modules.accounts.models import User
from app.modules.ads.constants import (
    BUTTON_LABELS,
    PLACEMENT_MODE_LABELS,
    ManagedLevel,
)
from core.chat.lookup_arguments import ChangeProposal

DEFAULT_ZONE: Final = "Asia/Tashkent"
SHOWN_CHARS: Final = 80

RENAME: Final = "rename"
END_DATE: Final = "end_date"
NO_END_DATE: Final = "no_end_date"
COST_CAP: Final = "cost_cap"
AUDIENCE: Final = "audience"
PLACEMENT: Final = "placement"
ADVERT_TEXT: Final = "advert_text"

# The level each kind lives on; a rename lives on all three.
LEVEL_OF: Final[dict[str, str]] = {
    END_DATE: ManagedLevel.ADSET,
    NO_END_DATE: ManagedLevel.ADSET,
    COST_CAP: ManagedLevel.ADSET,
    AUDIENCE: ManagedLevel.ADSET,
    PLACEMENT: ManagedLevel.ADSET,
    ADVERT_TEXT: ManagedLevel.AD,
}
KINDS: Final = frozenset({RENAME, *LEVEL_OF})

WHAT: Final[dict[str, str]] = {
    RENAME: "Nomini o'zgartirish",
    END_DATE: "Tugash sanasini belgilash",
    NO_END_DATE: "Tugash sanasini olib tashlash",
    COST_CAP: "Bitta natija narxi chegarasi",
    AUDIENCE: "Auditoriyani o'zgartirish",
    PLACEMENT: "Ko'rsatiladigan joyni o'zgartirish",
    ADVERT_TEXT: "Reklama matnini o'zgartirish",
}
NO_END: Final = "Tugash sanasi yo'q"
NO_CAP: Final = "Chegara yo'q"
FROM_ADS_MANAGER: Final = "Ads Manager'da sozlangan"
GENDER_WORDS: Final = {"": "hamma", "male": "erkaklar", "female": "ayollar"}
GENDERS: Final[dict[str, tuple[int, ...]]] = {"all": (), "men": (1,), "women": (2,)}
ADVANTAGE_WORDS: Final = {True: "Advantage+ yoqilgan", False: "Advantage+ o'chirilgan"}
WORD_LABELS: Final = {
    "message": "Matn",
    "headline": "Sarlavha",
    "description": "Tavsif",
    "button": "Tugma",
    "link": "Havola",
}
LEVEL_NAMES: Final = {
    ManagedLevel.ADSET: "an ad group (adset)",
    ManagedLevel.AD: "an advert (ad)",
}


class NotPossible(Exception):
    """Why this change cannot be prepared, in words for the model to pass on."""


@dataclass(frozen=True, slots=True)
class Built:
    """One prepared change: the screen's own ask, and the button's two words."""

    ask: Any
    before: str
    after: str


def params_of(arguments: ChangeProposal) -> dict[str, Any]:
    """The owner's wish as it is kept on the row: only this kind's own fields."""
    kind = arguments.action
    if kind == RENAME:
        return {"name": arguments.name}
    if kind == END_DATE:
        return {"end_date": arguments.end_date}
    if kind == COST_CAP:
        return {"cost_cap": arguments.cost_cap}
    if kind == AUDIENCE:
        return {
            "age_min": arguments.age_min,
            "age_max": arguments.age_max,
            "gender": arguments.gender,
            "advantage": arguments.advantage,
        }
    if kind == PLACEMENT:
        return {"apps": arguments.apps}
    if kind == ADVERT_TEXT:
        return {
            "message": arguments.message,
            "headline": arguments.headline,
            "description": arguments.description,
            "button": arguments.button,
            "link": arguments.link,
        }
    return {}


def build(
    db: Session,
    *,
    owner: User,
    kind: str,
    level: str,
    target: Any,
    params: dict[str, Any],
) -> Built:
    """The ask this wish makes of the campaigns screen, read against ``target`` as it is now."""
    wanted = LEVEL_OF.get(kind)
    if wanted is not None and level != wanted:
        raise NotPossible(
            f"This change is made on {LEVEL_NAMES[wanted]}, not on a {level}. "
            "Look the object up and use that id."
        )
    return _BUILDERS[kind](db, owner, target, level, params)


def _rename(
    db: Session, owner: User, target: Any, level: str, params: dict[str, Any]
) -> Built:
    from app.modules.ads import actions

    name = " ".join(str(params.get("name") or "").split())
    if not name:
        raise NotPossible("A rename needs the new name. Ask the owner for it.")
    return Built(
        ask=actions.Rename(external_id=str(target.external_id), name=name, level=level),
        before=str(target.name or ""),
        after=name,
    )


def _zone(db: Session, owner: User) -> ZoneInfo:
    from app.modules.businesses.selectors import business_timezone

    return ZoneInfo(business_timezone(db, owner=owner) or DEFAULT_ZONE)


def _day(stamp: datetime | None, zone: ZoneInfo) -> str:
    return stamp.astimezone(zone).strftime("%d.%m.%Y") if stamp else NO_END


def _end_date(
    db: Session, owner: User, target: Any, level: str, params: dict[str, Any]
) -> Built:
    from app.modules.ads import actions

    zone = _zone(db, owner)
    try:
        day = date.fromisoformat(str(params.get("end_date") or ""))
    except ValueError:
        raise NotPossible(
            "An end date needs the day as YYYY-MM-DD. Ask the owner which day."
        ) from None
    if day <= utcnow().astimezone(zone).date():
        raise NotPossible(
            "The last day must be tomorrow or later. To stop it now, prepare a pause."
        )
    ends = datetime.combine(day, time(23, 59, 59), tzinfo=zone)
    return Built(
        ask=actions.EndTime(external_id=str(target.external_id), end_time=ends),
        before=_day(target.end_time, zone),
        after=_day(ends, zone),
    )


def _no_end_date(
    db: Session, owner: User, target: Any, level: str, params: dict[str, Any]
) -> Built:
    from app.modules.ads import actions

    if target.end_time is None:
        raise NotPossible("It has no end date already. Nothing to change.")
    if target.daily_budget_minor is None and target.campaign.daily_budget_minor is None:
        raise NotPossible(
            "Its budget is set for the whole run, and Meta does not let such an "
            "advert run without an end date. Offer to move the date instead."
        )
    return Built(
        ask=actions.EndTime(external_id=str(target.external_id), end_time=None),
        before=_day(target.end_time, _zone(db, owner)),
        after=NO_END,
    )


def _cost_cap(
    db: Session, owner: User, target: Any, level: str, params: dict[str, Any]
) -> Built:
    from app.modules.ads import actions
    from app.modules.ads.services import delivery

    typed = str(params.get("cost_cap") or "").replace(",", ".")
    if not typed:
        raise NotPossible(
            "A price ceiling needs the amount, or 0 to remove it. Ask the owner."
        )
    now = delivery.held(target)
    if not now.readable:
        raise NotPossible(
            "Meta did not answer what this ad group's ceiling is now. Say so and "
            "ask the owner to try again a little later."
        )
    currency = str(target.currency or target.campaign.currency or "")
    wanted = int(
        provider_money(provider=target.provider).to_minor(
            amount=typed, currency=currency
        )
    )
    held = now.now.cap_minor or 0
    if wanted == held:
        raise NotPossible("That is already its price ceiling. Nothing to change.")
    return Built(
        ask=actions.Delivery(
            external_id=str(target.external_id), asked={delivery.CAP: wanted}
        ),
        before=_money(held, currency),
        after=_money(wanted, currency),
    )


def _money(amount_minor: int, currency: str) -> str:
    if not amount_minor:
        return NO_CAP
    return format_minor(amount_minor=amount_minor, currency=currency, keep_cents=True)


def _audience_target(db: Session, target: Any) -> Any:
    """The group's audience as the edit dialog reads it, or why it has none to change."""
    from app.modules.ads import selectors

    edit = selectors.editable(
        db, campaign=target.campaign, group=str(target.external_id)
    )
    if edit is None or edit.audience is None:
        raise NotPossible(
            "This ad group's audience is not readable here. Say it is changed on "
            "the Reklama screen."
        )
    return edit.audience


def _revised(aud: Any, edit: Any) -> dict[str, Any]:
    from core.targeting.exceptions import TargetingError
    from core.targeting.revise import revised

    try:
        spec, _notes = revised(aud.spec, edit=edit, special=aud.special)
    except TargetingError as exc:
        raise NotPossible(f"The audience rules refuse it: {exc}.") from None
    if spec == aud.spec:
        raise NotPossible("The audience is already like that. Nothing to change.")
    return dict(spec)


def _audience_words(spec: dict[str, Any]) -> str:
    from core.targeting import describe
    from core.targeting.modes import is_automatic
    from core.targeting.validators import MAX_AGE, MIN_AGE

    sketch = describe(spec)
    low, high = sketch.age_min or MIN_AGE, sketch.age_max or MAX_AGE
    ages = f"{low}-{high}{'+' if high >= MAX_AGE else ''}"
    return (
        f"{ages} yosh, {GENDER_WORDS[sketch.genders]}, "
        f"{ADVANTAGE_WORDS[is_automatic(spec)]}"
    )


def _audience(
    db: Session, owner: User, target: Any, level: str, params: dict[str, Any]
) -> Built:
    from app.modules.ads import actions
    from core.targeting import MAX_AGE, MIN_AGE, AudienceEdit, describe

    aud = _audience_target(db, target)
    low, high = params.get("age_min"), params.get("age_max")
    gender = str(params.get("gender") or "")
    switch = str(params.get("advantage") or "")
    if low is None and high is None and not gender and not switch:
        raise NotPossible(
            "An audience change needs what to change: the ages, the gender or the "
            "Advantage+ switch. Places, interests and languages are changed on the "
            "Reklama screen - say so."
        )
    sketch = describe(aud.spec)
    ages = low is not None or high is not None
    if switch == "on" and aud.special:
        raise NotPossible(
            "This campaign is in a special ad category, where Meta may not widen "
            "the audience on its own."
        )
    if gender and gender != "all" and not aud.allows_gender:
        raise NotPossible(
            "This campaign is in a special ad category, where the audience cannot "
            "be narrowed by gender."
        )
    edit = AudienceEdit(
        age_min=(low if low is not None else sketch.age_min or MIN_AGE)
        if ages
        else None,
        age_max=(high if high is not None else sketch.age_max or MAX_AGE)
        if ages
        else None,
        genders=GENDERS[gender] if gender else None,
        automatic={"on": True, "off": False}.get(switch),
    )
    spec = _revised(aud, edit)
    return Built(
        ask=actions.Audience(external_id=str(target.external_id), targeting=spec),
        before=_audience_words(aud.spec),
        after=_audience_words(spec),
    )


def _placement_words(spec: dict[str, Any]) -> str:
    from core.targeting.placements import held_mode

    mode = held_mode(spec)
    return str(PLACEMENT_MODE_LABELS[mode]) if mode else FROM_ADS_MANAGER


def _placement(
    db: Session, owner: User, target: Any, level: str, params: dict[str, Any]
) -> Built:
    from app.modules.ads import actions
    from app.modules.ads.contract.words import APPS_OUT
    from core.targeting import AudienceEdit

    aud = _audience_target(db, target)
    mode = APPS_OUT.get(str(params.get("apps") or ""))
    if mode is None:
        raise NotPossible(
            "A placement change needs where: auto, fbig, instagram or facebook."
        )
    if not aud.placement_modes:
        raise NotPossible(
            "This advert leads to the Instagram profile, so it is shown on "
            "Instagram only and that cannot be changed."
        )
    if mode not in aud.placement_modes:
        raise NotPossible(
            "This advert opens a chat in the other app, so it cannot be shown "
            "only there. Offer Facebook and Instagram together instead."
        )
    spec = _revised(aud, AudienceEdit(placement=mode))
    return Built(
        ask=actions.Audience(external_id=str(target.external_id), targeting=spec),
        before=_placement_words(aud.spec),
        after=_placement_words(spec),
    )


def _clip(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= SHOWN_CHARS else f"{text[: SHOWN_CHARS - 1]}…"


def _advert_text(
    db: Session, owner: User, target: Any, level: str, params: dict[str, Any]
) -> Built:
    from metaads.restage import button_of, link_of

    from app.modules.ads import actions, selectors
    from app.modules.ads.inputs import Problems
    from app.modules.ads.inputs.destination import own_site

    content = selectors.creative_of(db, owner=owner, ad=target)
    story = getattr(content, "story_raw", None)
    if content is None or not isinstance(story, dict) or not story:
        raise NotPossible(
            "This advert shows a post, and its words live on the post itself. "
            "They cannot be changed here."
        )
    link = str(params.get("link") or "").strip()
    if link:
        problems = Problems()
        link = own_site(link, problems=problems, field="link")
        if problems.found:
            raise NotPossible(
                f"The address cannot be used: {problems.found['link']} Ask the "
                "owner for their own site's address."
            )
    button = str(params.get("button") or "").strip().upper()
    held = {
        "message": str(content.message or ""),
        "headline": str(content.headline or ""),
        "description": str(content.description or ""),
        "button": str(button_of(story).get("type") or ""),
        "link": link_of(story),
    }
    asked = {
        "message": params.get("message"),
        "headline": params.get("headline"),
        "description": params.get("description"),
        "button": button or None,
        "link": link or None,
    }
    moved = {
        key: str(value)
        for key, value in asked.items()
        if value is not None and str(value) != held[key]
    }
    if not moved:
        raise NotPossible(
            "An advert change needs what to change and its new wording, and it "
            "must differ from what the advert says now."
        )

    def shown(key: str, value: str) -> str:
        if key == "button":
            value = str(BUTTON_LABELS.get(value, value))
        return f"{WORD_LABELS[key]}: {_clip(value) or '—'}"

    return Built(
        ask=actions.NewAdvert(
            external_id=str(target.external_id),
            message=asked["message"],
            headline=asked["headline"],
            description=asked["description"],
            button=button,
            link=link,
        ),
        before="\n".join(shown(key, held[key]) for key in moved),
        after="\n".join(shown(key, value) for key, value in moved.items()),
    )


_BUILDERS: Final = {
    RENAME: _rename,
    END_DATE: _end_date,
    NO_END_DATE: _no_end_date,
    COST_CAP: _cost_cap,
    AUDIENCE: _audience,
    PLACEMENT: _placement,
    ADVERT_TEXT: _advert_text,
}

__all__ = ["KINDS", "LEVEL_OF", "WHAT", "Built", "NotPossible", "build", "params_of"]
