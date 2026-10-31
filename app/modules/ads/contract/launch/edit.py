"""The proposal editor: the review read as its tabs, and its save read back as a patch.

As the browser did in ``live/review-map.ts``. Only what the owner changed
goes back: ``ProposalIn`` is a patch, so a section the editor could not read
whole is never sent back empty over the AI's answer.
"""

from typing import Any, Final

from app.modules.ads.contract.launch.review import ad, number, text
from app.modules.ads.inputs.proposal_body import ProposalIn

WHO_IN: Final = {"automatic": "auto", "interests": "interests", "broad": "broad"}
WHO_OUT: Final = {value: key for key, value in WHO_IN.items()}
APPS_IN: Final = {"automatic": "auto", "standard": "fbig"}
APPS_OUT: Final = {value: key for key, value in APPS_IN.items()}
# The editor's fields, as the backend's question kinds name them.
KIND_OF: Final[dict[str, str]] = {
    "full_name": "full_name",
    "first_name": "first_name",
    "phone": "phone",
    "last_name": "last_name",
    "email": "email",
    "city": "city",
    "region": "state",
    "country": "country",
    "zip": "zip",
    "address": "street_address",
}
FIELD_OF: Final[dict[str, str]] = {kind: field for field, kind in KIND_OF.items()}
END_IN: Final = {
    "none": "none",
    "": "none",
    "website": "site",
    "telegram": "telegram",
    "call": "call",
}
END_OUT: Final = {
    "none": "none",
    "site": "website",
    "telegram": "telegram",
    "call": "call",
}
AREA: Final = "area:"
SECTIONS: Final = ("aud", "geo", "int", "hab", "reach", "ads", "form", "adv")

# What the word check found in an advert, in the owner's words.
FINDINGS: Final[dict[str, dict[str, str]]] = {
    "empty": {
        "level": "danger",
        "title": "Matn bo'sh",
        "text": "Reklamaga matn yozing.",
        "fix": "rewrite",
    },
    "too_short": {
        "level": "info",
        "title": "Matn juda qisqa",
        "text": "Nima taklif qilinayotgani aniq emas — bir-ikki gap qo'shing.",
        "fix": "rewrite",
    },
    "same_in_all_fields": {
        "level": "info",
        "title": "Hamma qatorda bir xil matn",
        "text": "Sarlavha va matn bir-birini takrorlamasin.",
        "fix": "rewrite",
    },
    "number_not_in_offer": {
        "level": "danger",
        "title": "Taklifda yo'q raqam",
        "text": "Matndagi narx yoki raqam siz yozgan taklifda yo'q.",
        "fix": "rewrite",
    },
    "promise_not_in_offer": {
        "level": "danger",
        "title": "Taklifda yo'q va'da",
        "text": "Matn siz aytmagan narsani va'da qilyapti.",
        "fix": "rewrite",
    },
    "personal_attribute": {
        "level": "danger",
        "title": "Shaxsiy xususiyat",
        "text": "Meta odamning shaxsiy xususiyatini nazarda tutgan matnni rad etadi.",
        "fix": "rewrite",
    },
    "action_mismatch": {
        "level": "info",
        "title": "Chaqiriq tugmaga mos emas",
        "text": "Matndagi chaqiriq reklama tugmasi bilan bir xil bo'lsin.",
        "fix": "rewrite",
    },
    "phone_in_form_ad": {
        "level": "danger",
        "title": "Matnda telefon raqami",
        "text": "Forma reklamasida raqam yozilsa, Meta rad etadi.",
        "fix": "remove_phone",
    },
    "phone_dropped": {
        "level": "info",
        "title": "Raqam olib tashlandi",
        "text": "Matndagi telefon raqami olib tashlandi.",
        "fix": "rewrite",
    },
}


def _same(left: Any, right: Any) -> bool:
    """Equal by value: the screen's 12 and the model's 12.0 are one radius."""
    return bool(left == right)


def edit_ad(variant: dict[str, Any]) -> dict[str, Any]:
    checks = []
    for index, note in enumerate(variant.get("copy_notes") or []):
        code = text(note.get("code"))
        found = FINDINGS.get(code) or {
            "level": "info",
            "title": code,
            "text": text(note.get("detail")),
            "fix": "rewrite",
        }
        checks.append({"id": f"{code}-{index}", **found})
    return {
        **ad(variant),
        "name": text(variant.get("ad_name")) if variant.get("ad_named") else "",
        "desc": text(variant.get("description")),
        "by": "me" if variant.get("words_touched") else "ai",
        "instagram": bool(variant.get("is_post")),
        "checks": checks,
    }


def _form(found: dict[str, Any] | None) -> dict[str, Any]:
    found = found or {}
    kinds = set(found.get("chosen_kinds") or [])
    ending = found.get("ending") or {}
    end = END_IN.get(text(ending.get("kind")), "none")
    target = {
        "site": text(ending.get("website")),
        "telegram": text(ending.get("telegram")),
        "call": text(ending.get("phone")),
    }.get(end, "")
    depth = (found.get("depth") or {}).get("chosen")
    out = {
        "existing": [
            {
                "id": row["external_id"],
                "name": row["name"],
                "leads": row.get("leads_count") or 0,
                "questions": len(row.get("questions") or []),
                "date": row.get("created_time") or "",
                "archived": False,
            }
            for row in found.get("lead_forms") or []
        ],
        "choice": found.get("chosen_form") or "new",
        "name": text((found.get("card") or {}).get("name")),
        "fields": {field: KIND_OF[field] in kinds for field in KIND_OF},
        "questions": [
            {
                "id": text(row.get("kind")),
                "text": text(row.get("label")),
                "options": [text(option) for option in row.get("options") or []]
                if isinstance(row.get("options"), list)
                else [],
            }
            for row in found.get("questions") or []
            if text(row.get("kind")) in kinds and text(row.get("kind")) not in FIELD_OF
        ],
        "end": end,
        "end_target": target.removeprefix("@"),
        "end_button": text(ending.get("button")),
        "end_title": text(ending.get("title")),
        "end_text": text(ending.get("body")),
        "privacy": found.get("privacy_url") or "",
    }
    if depth in ("short", "deep"):
        out["depth"] = depth
    return out


def _advanced(found: dict[str, Any]) -> list[dict[str, Any]]:
    """The advanced tab: what each setting is, read-only where the backend locks it."""
    advanced = found["advanced"]
    rows: list[dict[str, Any]] = []

    def pick(
        key: str,
        en: str,
        options: list[dict[str, Any]],
        chosen: str,
        locked: bool,
        mine: bool,
    ) -> None:
        if not options:
            return
        label = next(
            (text(row.get("label")) for row in options if row.get("key") == chosen),
            chosen,
        )
        rows.append(
            {
                "key": key,
                "en": en,
                "value": label,
                "mode": "ro" if locked else "me" if mine else "",
                "options": [text(row.get("label")) for row in options],
            }
        )

    types = advanced.get("campaign_types")
    if types:
        pick(
            "buying_type",
            "Campaign type",
            types["options"],
            types["chosen"],
            types["locked"],
            types.get("source") == "owner",
        )
    events = advanced.get("conversion_events")
    if events:
        pick(
            "conversion_event",
            "Conversion event",
            [*events["arriving_options"], *events["other_options"]],
            events["chosen"],
            events["locked"],
            events.get("source") == "owner",
        )
    pixels = advanced.get("pixels") or []
    if pixels:
        chosen = next((row for row in pixels if row.get("is_chosen")), None)
        rows.append(
            {
                "key": "pixel",
                "en": "Pixel",
                "value": (chosen or {}).get("name") or "",
                "mode": "",
                "options": [row["name"] for row in pixels],
            }
        )
    buttons = advanced.get("buttons")
    if buttons:
        pick(
            "cta",
            "Call to action",
            buttons["options"],
            buttons["chosen"],
            buttons["locked"],
            bool(buttons.get("by_owner")),
        )
    delivery = advanced.get("delivery") or {}
    if delivery.get("offers_window"):
        pick(
            "attribution",
            "Attribution",
            delivery.get("windows") or [],
            delivery.get("chosen_window") or "",
            bool(delivery.get("locked")),
            False,
        )
    if delivery.get("offers_cap") and delivery.get("cap_times"):
        rows.append(
            {
                "key": "frequency",
                "en": "Frequency cap",
                "value": f"{delivery['cap_times']} / {delivery.get('cap_days') or 7}",
                "mode": "ro",
                "options": [],
            }
        )
    cap = advanced.get("cost_cap") or {}
    if cap.get("amount") is not None and text(cap.get("amount")):
        rows.append(
            {
                "key": "cost_cap",
                "en": "Cost per result goal",
                "value": f"{text(cap['amount'])} {cap.get('currency') or ''}",
                "mode": "ro",
                "options": [],
            }
        )
    tags = (advanced.get("tracking") or {}).get("tags")
    if tags:
        rows.append(
            {
                "key": "url_tags",
                "en": "URL parameters",
                "value": tags,
                "mode": "ro",
                "options": [],
            }
        )
    depth = (found.get("lead_form") or {}).get("depth")
    if depth:
        rows.append(
            {
                "key": "review_screen",
                "en": "Instant form · Review screen",
                "value": "",
                "mode": "ro" if depth.get("locked") else "sw",
                "options": [],
                "on": depth.get("intent"),
            }
        )
    return rows


def edit_from(answer: dict[str, Any]) -> dict[str, Any]:
    """The editor's tabs, from the review."""
    found = answer.get("proposal")
    if not found:
        raise LookupError("no proposal drawn")
    audience = found["audience"]
    chosen = audience["chosen"]
    age = [number(chosen.get("age_min")) or 18, number(chosen.get("age_max")) or 65]
    geo = audience.get("geo") or {}
    radius = number(chosen.get("radius_km")) or number(geo.get("radius_km")) or 0
    areas = {
        text(row.get("key")): text(row.get("name"))
        for row in audience.get("geo_areas") or []
    }
    places = [
        {
            "id": text(row.get("key")),
            "name": text(row.get("name")),
            "type": "region" if row.get("kind") == "region" else "city",
        }
        for row in audience.get("geo_places") or []
    ] + [
        {"id": f"{AREA}{key}", "name": areas.get(key) or key, "type": "region"}
        for key in audience.get("geo_chosen_areas") or []
    ]
    advice = found.get("advice") or {}
    say = {section: "" for section in SECTIONS} | {
        "aud": text((advice.get("audience") or {}).get("note")),
        "form": text(((found.get("lead_form") or {}).get("advice") or {}).get("note")),
        "adv": text((advice.get("placement") or {}).get("note")),
    }
    genders = (
        [int(item) for item in chosen.get("genders") or []]
        if isinstance(chosen.get("genders"), list)
        else []
    )
    return {
        "say": say,
        "aud": {
            "who": WHO_IN.get(text(audience.get("mode")), "auto"),
            "apps": APPS_IN.get(text(audience.get("placement_mode")), "auto"),
            "optimize": "quality"
            if audience.get("lead_buying") == "quality"
            else "all",
            "age": age,
            "ai_age": age,
            "genders": ["m" if item == 1 else "f" for item in genders],
            "lists": [
                {
                    "id": row["key"],
                    "name": row["label"],
                    "sub": row["reason"],
                    "mode": row["role"]
                    if row.get("role") in ("include", "exclude")
                    else "off",
                }
                for row in audience.get("targets") or []
            ],
        },
        "geo": {
            "mode": "map" if text(geo.get("mode")) == "around" else "list",
            "places": places,
            "km": radius,
            "address": text(geo.get("address")),
        },
        "interests": (found.get("interests") or {}).get("chosen_queries") or [],
        "habits": (found.get("traits") or {}).get("chosen_queries") or [],
        "ads": [edit_ad(variant) for variant in found.get("variants") or []],
        "form": _form(found.get("lead_form")),
        "adv": _advanced(found),
    }


def _form_patch(
    now: dict[str, Any], was: dict[str, Any], source: dict[str, Any]
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if now["choice"] != was["choice"]:
        out["lead_form"] = "" if now["choice"] == "new" else now["choice"]
    if now.get("depth") and now.get("depth") != was.get("depth"):
        out["form_depth"] = now["depth"]
    if not _same(now["fields"], was["fields"]) or not _same(
        now["questions"], was["questions"]
    ):
        offered = {text(row.get("kind")) for row in source.get("questions") or []}
        out["rows"] = [
            {"key": KIND_OF[field], "label": "", "options": [], "text_only": False}
            for field in KIND_OF
            if now["fields"].get(field)
        ] + [
            {
                "key": row["id"] if row["id"] in offered else f"new:{row['id']}",
                "label": row["text"],
                "options": row["options"],
                "text_only": not row["options"],
            }
            for row in now["questions"]
        ]
    ending = ("end", "end_target", "end_button", "end_title", "end_text")
    if any(now[key] != was[key] for key in ending):
        target = now["end_target"].strip()
        out["ending"] = {
            "kind": END_OUT[now["end"]],
            "website": target if now["end"] == "site" else "",
            "telegram": target if now["end"] == "telegram" else "",
            "phone": target if now["end"] == "call" else "",
            "button": now["end_button"],
            "title": now["end_title"],
            "body": now["end_text"],
        }
    return out


def _advanced_patch(
    rows: list[dict[str, Any]], was: list[dict[str, Any]], advanced: dict[str, Any]
) -> dict[str, Any]:
    """A row the owner changed: the label picked, read back to the key it was offered under."""
    out: dict[str, Any] = {}

    def key_of(options: list[dict[str, Any]], value: str) -> str:
        return next(
            (row["key"] for row in options if text(row.get("label")) == value), ""
        )

    for row in rows:
        then = next((item for item in was if item["key"] == row["key"]), None)
        if then is None or row["value"] == then["value"] or row["mode"] == "ro":
            continue
        if row["key"] == "buying_type" and advanced.get("campaign_types"):
            out["campaign_type"] = key_of(
                advanced["campaign_types"]["options"], row["value"]
            )
        if row["key"] == "conversion_event" and advanced.get("conversion_events"):
            events = advanced["conversion_events"]
            out["conversion_event"] = key_of(
                [*events["arriving_options"], *events["other_options"]], row["value"]
            )
        if row["key"] == "pixel":
            out["pixel_id"] = next(
                (
                    pixel["external_id"]
                    for pixel in advanced.get("pixels") or []
                    if pixel["name"] == row["value"]
                ),
                "",
            )
        if row["key"] == "cta" and advanced.get("buttons"):
            out["call_to_action"] = key_of(advanced["buttons"]["options"], row["value"])
        if row["key"] == "attribution":
            out["attribution"] = key_of(
                (advanced.get("delivery") or {}).get("windows") or [], row["value"]
            )
    return out


def proposal_patch(edit: dict[str, Any], answer: dict[str, Any]) -> ProposalIn:
    """Only what the owner changed, compared with the proposal as it stands now."""
    was = edit_from(answer)
    found = answer["proposal"]
    out: dict[str, Any] = {}

    audience: dict[str, Any] = {}
    now_aud, was_aud = edit["aud"], was["aud"]
    if now_aud["who"] != was_aud["who"]:
        audience["targeting_mode"] = WHO_OUT[now_aud["who"]]
    if now_aud["apps"] != was_aud["apps"]:
        audience["placement_mode"] = APPS_OUT[now_aud["apps"]]
    if now_aud["optimize"] != was_aud["optimize"]:
        audience["lead_buying"] = (
            "quality" if now_aud["optimize"] == "quality" else "volume"
        )
    if not _same(now_aud["age"], was_aud["age"]):
        audience["age_min"] = max(18, now_aud["age"][0])
        audience["age_max"] = min(65, now_aud["age"][1])
    if sorted(now_aud["genders"]) != sorted(was_aud["genders"]):
        audience["genders"] = (
            [1 if now_aud["genders"][0] == "m" else 2]
            if len(now_aud["genders"]) == 1
            else []
        )
    if not _same(now_aud["lists"], was_aud["lists"]):
        audience["audiences"] = {
            row["id"]: row["mode"] for row in now_aud["lists"] if row["mode"] != "off"
        }
    if not _same(edit["geo"], was["geo"]):
        geo = edit["geo"]
        known = {row.get("key") for row in found["audience"].get("geo_places") or []}
        kept = [row for row in geo["places"] if not row["id"].startswith(AREA)]
        audience |= {
            "geo_mode": "around"
            if geo["mode"] == "map"
            else "places"
            if geo["places"]
            else "country",
            "places": [row["id"] for row in kept if row["id"] in known],
            "added": [row["name"] for row in kept if row["id"] not in known],
            "areas": [
                row["id"].removeprefix(AREA)
                for row in geo["places"]
                if row["id"].startswith(AREA)
            ],
        }
        if geo["mode"] == "map" and geo["km"]:
            audience["radius_km"] = max(1, min(80, round(geo["km"])))
    if audience:
        out["audience"] = audience

    if not _same(edit["interests"], was["interests"]):
        offered = {
            text(row.get("query"))
            for row in (found.get("interests") or {}).get("offered") or []
        }
        offered |= set(was["interests"])
        out["interests"] = {
            "queries": [query for query in edit["interests"] if query in offered],
            "added": [query for query in edit["interests"] if query not in offered],
        }
    if not _same(edit["habits"], was["habits"]):
        out["traits"] = edit["habits"]

    creatives = []
    for variant in found.get("variants") or []:
        key = str(variant["position"])
        now = next((row for row in edit["ads"] if row["id"] == key), None)
        then = next((row for row in was["ads"] if row["id"] == key), None)
        if now is None or then is None or variant.get("is_post"):
            continue
        if all(
            now[field] == then[field] for field in ("text", "headline", "desc", "name")
        ):
            continue
        creatives.append(
            {
                "position": variant["position"],
                "primary_text": now["text"],
                "headline": now["headline"],
                "description": now["desc"],
                "ad_name": now["name"] or None,
            }
        )
    if creatives:
        out["creatives"] = creatives

    lead_form = found.get("lead_form")
    if lead_form and not _same(edit["form"], was["form"]):
        out["form"] = _form_patch(edit["form"], was["form"], lead_form)
    switch = next((row for row in edit["adv"] if row["key"] == "review_screen"), None)
    switch_was = next(
        (row for row in was["adv"] if row["key"] == "review_screen"), None
    )
    if lead_form and switch and switch_was and switch.get("on") != switch_was.get("on"):
        out["form"] = {**out.get("form", {}), "higher_intent": bool(switch.get("on"))}

    advanced = _advanced_patch(edit["adv"], was["adv"], found["advanced"])
    if advanced:
        out["advanced"] = advanced
    return ProposalIn.model_validate(out)


__all__ = ["FIELD_OF", "KIND_OF", "edit_from", "proposal_patch"]
