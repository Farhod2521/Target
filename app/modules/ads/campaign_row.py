"""Short lines a campaign row prints: its name, whether it has begun, and its audience."""

from datetime import datetime

from app.common import timezone
from app.modules.ads import naming
from core.targeting import AudienceSketch

SEPARATOR = " · "


def short_name(value: str) -> str:
    return naming.short_name(str(value or ""))


def has_begun(moment: datetime | None) -> bool:
    return moment is not None and moment <= timezone.now()


def audience_line(sketch: AudienceSketch | None) -> str:
    if sketch is None or sketch.is_empty:
        return ""
    parts = [
        _where(sketch),
        _ages(sketch),
        _genders(sketch),
        _interests(sketch),
        _lists(sketch),
        _automatic(sketch),
    ]
    return SEPARATOR.join(part for part in parts if part)


def _where(sketch: AudienceSketch) -> str:
    if sketch.geo == "around":
        if not sketch.radius:
            return ""
        return "%(km)s km atrofida" % {"km": sketch.radius}
    if sketch.geo == "places":
        return "%(count)s ta joy" % {"count": sketch.places}
    if sketch.geo == "country":
        if sketch.places == 1:
            return "Butun mamlakat"
        return "%(count)s ta mamlakat" % {"count": sketch.places}
    return ""


def _ages(sketch: AudienceSketch) -> str:
    low, high = (sketch.age_min, sketch.age_max)
    if low and high:
        return "%(low)s-%(high)s yosh" % {"low": low, "high": high}
    if low:
        return "%(low)s yoshdan katta" % {"low": low}
    if high:
        return "%(high)s yoshgacha" % {"high": high}
    return ""


def _genders(sketch: AudienceSketch) -> str:
    if sketch.genders == "male":
        return "erkaklar"
    if sketch.genders == "female":
        return "ayollar"
    return ""


def _interests(sketch: AudienceSketch) -> str:
    if not sketch.interests:
        return ""
    return "%(count)s qiziqish" % {"count": sketch.interests}


def _lists(sketch: AudienceSketch) -> str:
    if not sketch.uses_own_lists:
        return ""
    return "o'z ro'yxatingiz"


def _automatic(sketch: AudienceSketch) -> str:
    if not sketch.is_automatic:
        return ""
    return "Meta kengaytiradi"


__all__ = ["audience_line", "short_name"]
