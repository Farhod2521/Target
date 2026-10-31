"""The review step as the screens draw it, from the review's own answer.

Read from ``GET /launch/{id}/review`` (``ReviewOut``) and its cheap half,
key for key as the browser did in ``live/review-map.ts``.
"""

from datetime import date
from typing import Any, Final

from app.common.contract import Money
from app.modules.ads.contract.launch.words import LaunchStatus

_BUTTON: Final = "button"


def number(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def text(value: Any) -> str:
    return "" if value is None else str(value)


def tone(key: str) -> int:
    """A placeholder tile's gradient (1-6), the same for the same key."""
    return sum(ord(char) for char in key) % 6 + 1


def art(name: str) -> str:
    stem, dot, tail = name.rpartition(".")
    plain = stem if dot and tail.isalnum() and tail.isascii() else name
    return plain[:6]


def review_status(state: dict[str, Any]) -> LaunchStatus:
    """A failed build is not a failed creation; a rolled-back launch shows
    its proposal again; a created one is sent once the network delivers."""
    status = state.get("status")
    if status == "building":
        return "building"
    if status in ("ready", "rolled_back"):
        return "ready"
    if status == "creating":
        return "creating"
    if status == "created":
        if state.get("delivery_pending"):
            return "creating"
        return "sent" if state.get("delivery_started") else "created"
    if status == "failed":
        if state.get("failed_creating"):
            return "failed"
        return "ready" if state.get("show_proposal") else "prep_failed"
    return "draft"


def building(state: dict[str, Any], adverts: int) -> dict[str, Any]:
    """While the AI writes: the audience and the texts ticked off as they pass."""
    stages = (state.get("preparing") or {}).get("stages") or []
    note = text((state.get("preparing") or {}).get("note"))

    def passed(index: int) -> bool:
        return len(stages) > index and stages[index].get("state") == "done"

    return {
        "findings": [{"label": "", "value": note, "tentative": True}] if note else [],
        "audience": passed(1),
        "texts_done": adverts if passed(2) else 0,
        "texts_total": adverts,
    }


def creation(state: dict[str, Any], adverts: int) -> dict[str, Any] | None:
    """While the network creates: checking, creating, switching on, live."""
    status = state.get("status")
    if status not in ("creating", "created"):
        return None
    stages = state.get("creating_stages") or []
    now = next(
        (index for index, stage in enumerate(stages) if stage.get("state") == "now"), -1
    )
    stage = (
        3 if status == "created" and not state.get("delivery_pending") else max(0, now)
    )
    made = stage >= 2
    return {
        "stage": stage,
        "campaign": made,
        "adset": made,
        "ads_done": adverts if made else 0,
        "ads_total": adverts,
        "sent_at": None,
    }


def _notice(
    icon: str, tone_: str, title: str, words: str, label: str, to: str
) -> dict[str, Any]:
    return {
        "icon": icon,
        "tone": tone_,
        "title": title,
        "text": words,
        "action": {"label": label, "to": to, "style": _BUTTON},
    }


# The one precondition «Ishga tushirish» waits on, as the screen says it.
BLOCKERS: Final[dict[str, dict[str, Any]]] = {
    "subscription": _notice(
        "wallet",
        "d",
        "Obuna tugagan",
        "Reklamani ishga tushirish uchun obunani yangilang.",
        "Obuna",
        "billing",
    ),
    "reconnect": _notice(
        "link",
        "d",
        "Meta qayta ulanishi kerak",
        "Ulanish eskirgan — qayta ulang.",
        "Ulanish",
        "connections",
    ),
    "permissions": _notice(
        "link",
        "d",
        "Ruxsat yetishmaydi",
        "Meta ulanishida kerakli ruxsatlar berilmagan.",
        "Ulanish",
        "connections",
    ),
    "no_page": _notice(
        "link",
        "d",
        "Sahifa tanlanmagan",
        "Reklama qaysi sahifa nomidan chiqishini tanlang.",
        "Ulanish",
        "connections",
    ),
    "page_gone": _notice(
        "link",
        "d",
        "Sahifa topilmadi",
        "Tanlangan sahifa endi mavjud emas yoki ruxsat olib qo'yilgan.",
        "Ulanish",
        "connections",
    ),
    "places_missing": _notice(
        "users",
        "d",
        "Hudud tanlanmagan",
        "Reklama qayerda ko'rsatilishini tanlang.",
        "Hudud",
        "geo",
    ),
    "media_missing": _notice(
        "film",
        "d",
        "Rasm yoki video yo'q",
        "Kamida bitta rasm yoki video tanlang.",
        "Rasm tanlash",
        "media",
    ),
    "media_gone": _notice(
        "film",
        "d",
        "Rasm kutubxonadan o'chirilgan",
        "Tanlangan fayllardan biri Meta kutubxonasida yo'q.",
        "Rasm tanlash",
        "media",
    ),
    "copy_missing": _notice(
        "film",
        "d",
        "Reklama matni yo'q",
        "Har bir reklamaga matn yozing.",
        "Reklamalar",
        "ads",
    ),
    "site_missing": _notice(
        "link",
        "d",
        "Sayt manzili yo'q",
        "Reklama ochadigan sayt manzilini kiriting.",
        "Rejaga qaytish",
        "plan",
    ),
    "phone_missing": _notice(
        "link",
        "d",
        "Telefon raqami yo'q",
        "Qo'ng'iroq uchun raqamni kiriting.",
        "Rejaga qaytish",
        "plan",
    ),
    "form_gone": _notice(
        "lead",
        "d",
        "Forma topilmadi",
        "Tanlangan lid formasi endi ariza yig'maydi.",
        "Forma",
        "form",
    ),
    "chat_channel": _notice(
        "link",
        "d",
        "Chat kanali mavjud emas",
        "Tanlangan kanal bu sahifaga ulanmagan.",
        "Rejaga qaytish",
        "plan",
    ),
    "instagram_profile": _notice(
        "link",
        "d",
        "Instagram ulanmagan",
        "Bu reklama Instagram profilingizga olib boradi — Instagram'ni sahifaga ulang.",
        "Ulanish",
        "connections",
    ),
    "budget_low": _notice(
        "wallet",
        "d",
        "Byudjet past",
        "Kunlik byudjet Meta talab qilgan eng kamidan past.",
        "Byudjetni moslash",
        "budget_fit",
    ),
    "group_budget_low": _notice(
        "wallet",
        "d",
        "Har reklamaga byudjet yetmaydi",
        "Reklamalar sonini kamaytiring yoki byudjetni oshiring.",
        "Reklamalarni kamaytirish",
        "ads_trim",
    ),
    "reach_empty": _notice(
        "users",
        "d",
        "Auditoriya bo'sh",
        "Tanlangan hudud va qiziqishlarda odam yo'q — kengaytiring.",
        "Auditoriya",
        "aud",
    ),
    "unchanged": _notice(
        "ai",
        "d",
        "O'zgarish yo'q",
        "Meta oldin rad etgan taklif o'zgarmagan. Matn yoki rasmni o'zgartiring.",
        "Reklamalar",
        "ads",
    ),
}


def blockers(state: dict[str, Any]) -> list[dict[str, Any]]:
    key = text(state.get("launch_blocker"))
    if not key:
        return []
    found = BLOCKERS.get(key)
    if found is None:
        return [
            {
                "id": key,
                "icon": "ai",
                "tone": "d",
                "title": "Ishga tushirib bo'lmaydi",
                "text": key,
            }
        ]
    words = found["text"]
    if key == "group_budget_low" and state.get("group_least"):
        words = f"{words} Har biriga kamida {state['group_least']}."
    return [{"id": key, **found, "text": words}]


def attention(state: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    posts = state.get("posts_not_promoted") or []
    if posts:
        out.append(
            {
                "id": "posts_not_promoted",
                "icon": "film",
                "tone": "w",
                "title": "Post o'zi reklama qilinmaydi",
                "text": f"{', '.join(map(str, posts))}-reklama postdan nusxa sifatida chiqadi.",
            }
        )
    if (state.get("reach") or {}).get("is_narrow"):
        out.append(
            {
                "id": "reach_narrow",
                "icon": "users",
                "tone": "w",
                "title": "Qamrov tor",
                "text": "Auditoriya kichik — reklama qimmatroq tushishi mumkin.",
                "action": {"label": "Auditoriya", "to": "aud", "style": "link"},
            }
        )
    return out


def reach(state: dict[str, Any]) -> dict[str, Any] | None:
    found = state.get("reach")
    if not found or found.get("lower") is None or found.get("upper") is None:
        return None
    if found.get("is_narrow"):
        level = "narrow"
    elif found["lower"] > 1_000_000:
        level = "wide"
    else:
        level = "good"
    return {
        "min": found["lower"],
        "max": found["upper"],
        "level": level,
        "from": {"narrow": 20, "good": 45, "wide": 70}[level],
        "width": 10,
    }


def _genders(value: Any) -> str:
    chosen = [int(item) for item in value] if isinstance(value, list) else []
    if len(chosen) == 1:
        return "m" if chosen[0] == 1 else "f"
    return "all"


def places(proposal: dict[str, Any]) -> list[str]:
    """The places shown: the matched ones, then the areas; none is the whole country."""
    audience = proposal["audience"]
    areas = {
        text(row.get("key")): text(row.get("name"))
        for row in audience.get("geo_areas") or []
    }
    named = [text(row.get("name")) for row in audience.get("geo_places") or []]
    named += [areas.get(key) or key for key in audience.get("geo_chosen_areas") or []]
    return [name for name in named if name]


def ad(variant: dict[str, Any]) -> dict[str, Any]:
    asset = variant.get("asset") or {}
    name = (
        asset.get("name") or variant.get("upload_name") or variant.get("ad_name") or ""
    )
    # Meta's thumbnail; else a picture's own file at a public address.
    own = text(variant.get("file_url"))
    file = own if not variant.get("is_video") and own.startswith("https://") else ""
    thumb = asset.get("thumbnail_url") or file
    return {
        "id": str(variant["position"]),
        "tone": tone(text(asset.get("id")) or str(variant["position"])),
        "art": art(name),
        "headline": text(variant.get("headline")),
        "text": text(variant.get("primary_text")),
        "thumb": thumb or None,
        "video": True if variant.get("is_video") else None,
    }


def proposal(
    answer: dict[str, Any],
    *,
    goal: dict[str, Any],
    to_money: Any,
    today: date,
) -> dict[str, Any]:
    """The proposal card. ``goal`` is the card's goal line read from the saved key."""
    found = answer["proposal"]
    state = answer["state"]
    launch = answer["launch"]
    chosen = found["audience"]["chosen"]
    destination = found.get("destination") or {}
    age_min, age_max = number(chosen.get("age_min")), number(chosen.get("age_max"))
    form = found.get("lead_form")
    line: dict[str, Any] = {**goal, "by": "me"}
    if form:
        line["form"] = {
            "name": form["card"]["name"],
            "questions": len(form["card"]["questions"]),
        }
    target = (
        destination.get("link")
        or destination.get("phone")
        or destination.get("profile")
    )
    if target:
        line["dest"] = target
    if destination.get("opens_chat"):
        channel = (
            "messenger"
            if "messenger" in text(destination.get("chat_channel_label")).lower()
            else "instagram"
        )
        line["chat"] = {
            "channel": channel,
            "questions": len(destination.get("chat_questions") or []),
        }
    if goal.get("method") == "website" and destination.get("link"):
        line["site"] = destination["link"]
    budget_minor = launch.get("daily_budget_minor")
    total: Money | None = to_money(budget_minor) if budget_minor is not None else None
    start = (
        (found.get("start_day") or {}).get("day")
        or launch.get("start_date")
        or today.isoformat()
    )
    return {
        "say": "",
        "name": found["campaign_title"],
        "goal": line,
        "audience": {
            "by": "me" if found["audience"].get("mode_source") == "owner" else "ai",
            "places": places(found),
            "age": [age_min, age_max]
            if age_min is not None and age_max is not None
            else None,
            "genders": _genders(chosen.get("genders")),
            "placements": text((found["audience"].get("card") or {}).get("placement")),
            "interests": (found.get("interests") or {}).get("chosen_queries") or [],
            "reach": reach(state),
        },
        "budget": {
            "by": "me",
            "level": found["advanced"]["budget"]["level"],
            "sharing": found["advanced"]["budget"]["sharing"],
            "ends_at": launch.get("end_date"),
            "total": total,
            "starts_at": start,
        },
        # The before/after lines are the backend's own sentences; the card's
        # typed changes are not offered back yet.
        "changes": [],
        "ads": [ad(variant) for variant in found.get("variants") or []],
        "attention": attention(state),
        "blockers": blockers(state),
    }


# Which sections were written again («Boshqacha qilib ko'r» is once per section).
REGENERATED: Final[dict[str, list[str]]] = {
    "audience": ["aud", "geo", "reach"],
    "interests": ["int"],
    "traits": ["hab"],
    "creative": ["ads"],
    "form": ["form"],
}
# The editor's section, as POST /regenerate/{section} names it; advanced has none.
REGENERATE: Final[dict[str, str]] = {
    "aud": "audience",
    "geo": "audience",
    "reach": "audience",
    "int": "interests",
    "hab": "traits",
    "ads": "creative",
    "form": "form",
}


def regenerated(found: dict[str, Any] | None) -> list[str]:
    done = (found or {}).get("regenerated") or {}
    return [
        section
        for name, was in done.items()
        if was
        for section in REGENERATED.get(name, [])
    ]


__all__ = [
    "REGENERATE",
    "ad",
    "art",
    "attention",
    "blockers",
    "building",
    "creation",
    "number",
    "places",
    "proposal",
    "reach",
    "regenerated",
    "review_status",
    "text",
    "tone",
]
