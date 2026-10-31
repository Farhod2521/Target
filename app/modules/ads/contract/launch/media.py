"""The pictures step as the screen draws it: the Instagram grid and the library side by side.

``GET /media`` serves one source per call; the screen shows both, so both
are read and joined here, as the browser did in ``live/launch-map.ts``.
"""

from typing import Any, Final

from app.modules.ads.contract.launch.review import art, tone

# An upload's tile before the network takes it in: there is no asset id yet.
UPLOAD_TILE: Final = "upload-"
STATES: Final = frozenset({"uploading", "upload_failed", "deleting", "delete_failed"})
MEGABYTE: Final = 1_048_576
SMALL_SIDE: Final = 500


def _clock(seconds: float) -> str:
    # Half a second rounds up, as the screen always drew it.
    return f"{int(seconds // 60)}:{int(seconds % 60 + 0.5):02d}"


def asset(tile: dict[str, Any]) -> dict[str, Any]:
    """One tile as the grid draws it."""
    name = tile.get("name") or tile.get("caption") or ""
    caption = tile.get("caption") or name
    kind = tile.get("kind")
    video = kind in ("video", "ig_video")
    width, height = tile.get("width"), tile.get("height")
    out: dict[str, Any] = {
        "id": tile["id"],
        "tone": tone(tile["id"]),
        "art": art(caption),
        "caption": caption,
    }
    if video:
        out["video"] = _clock(tile["duration"]) if tile.get("duration") else ""
    if kind in ("ig_image", "ig_video"):
        out["post"] = True
    if tile.get("is_eligible") is False:
        out["blocked"] = True
    if width and height and min(width, height) < SMALL_SIDE:
        out["small"] = True
    if tile.get("permalink_url"):
        out["permalink"] = tile["permalink_url"]
    if tile.get("state") in STATES:
        out["state"] = tile["state"]
    if tile.get("progress") is not None:
        out["progress"] = tile["progress"]
    if tile.get("size"):
        out["size_mb"] = round(tile["size"] / MEGABYTE)
    if tile.get("caption") and tile.get("name") and tile["caption"] != tile["name"]:
        out["text"] = tile["caption"]
    if tile.get("created_at"):
        out["date"] = tile["created_at"]
    if tile.get("used_in"):
        out["used_in"] = tile["used_in"]
    if tile.get("thumbnail_url"):
        out["thumb"] = tile["thumbnail_url"]
    return out


def _square(square: dict[str, Any]) -> dict[str, Any] | None:
    """A square of the grid as a flat tile."""
    found = square.get("asset") or {}
    if not found.get("id"):
        return None
    tile = {**found, "used_in": square.get("used_in")}
    if square.get("deleting"):
        tile["state"] = "deleting"
    elif square.get("delete_failed"):
        tile["state"] = "delete_failed"
        tile["refusal"] = square.get("delete_refusal")
    return tile


def _squares(page: dict[str, Any] | None) -> list[dict[str, Any]]:
    return [tile for tile in map(_square, (page or {}).get("tiles") or []) if tile]


def _initials(name: str) -> str:
    words = [
        word
        for word in name.removeprefix("@").replace(".", " ").replace("_", " ").split()
        if word
    ]
    return "".join(word[0].upper() for word in words[:2]) or "IG"


def library(ig: dict[str, Any] | None, lib: dict[str, Any] | None) -> dict[str, Any]:
    """The Instagram grid and the library grid, and what the launch already holds."""
    shown = ig or lib or {}
    profile = (ig or {}).get("instagram_profile") or (ig or {}).get("instagram")
    variants = (lib or ig or {}).get("variants") or []
    held: dict[str, int] = {}
    uploads: list[dict[str, Any]] = []
    for variant in variants:
        found = variant.get("asset") or {}
        if found.get("id"):
            held[found["id"]] = variant["position"]
        elif variant.get("is_upload"):
            tile_id = f"{UPLOAD_TILE}{variant['position']}"
            held[tile_id] = variant["position"]
            tile = asset(
                {
                    "id": tile_id,
                    "name": variant.get("upload_name") or "",
                    "kind": "video" if variant.get("is_video") else "image",
                }
            )
            if variant.get("upload_failed"):
                tile["state"] = "upload_failed"
                tile["refusal"] = variant.get("upload_refusal")
            elif variant.get("is_uploading"):
                tile["state"] = "uploading"
            uploads.append(tile)
    synced = (
        (lib or {}).get("media_synced_at")
        or (ig or {}).get("media_synced_at")
        or shown.get("synced_at")
        or (profile or {}).get("synced_at")
    )
    posts = [*((ig or {}).get("posts") or [])]
    if ig and not ig.get("is_library"):
        posts += _squares(ig)
    grid = [*((lib or ig or {}).get("library") or []), *_squares(lib)]
    out: dict[str, Any] = {
        "say": shown.get("say") or "",
        "instagram": {
            "handle": f"@{profile['username'].removeprefix('@')}",
            "initials": _initials(profile.get("name") or profile["username"]),
            "sub": profile.get("name") or "",
            "posts": profile.get("posts") or 0,
            "followers": profile.get("followers") or 0,
            "following": profile.get("follows") or 0,
        }
        if profile and profile.get("username")
        else None,
        "page_name": shown.get("page_name") or "",
        "currency": shown.get("currency") or "",
        "posts": [asset(tile) for tile in posts],
        "library": [asset(tile) for tile in grid],
        "synced_at": synced,
        "held": held,
        "uploads": uploads,
    }
    for key, name in (
        ("max_image_mb", "max_image_mb"),
        ("max_video_mb", "max_video_mb"),
        ("accept", "accept_types"),
    ):
        if shown.get(name):
            out[key] = shown[name]
    return out


__all__ = ["UPLOAD_TILE", "asset", "library"]
