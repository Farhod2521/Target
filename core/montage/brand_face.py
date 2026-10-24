"""A brand's face: when it is complete, its short brief, the colours it suggests."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, Literal

from core.montage.colors import (
    DARK,
    TEXT_CONTRAST,
    contrast_ratio,
    is_hex,
    is_plain,
    readable_on,
)
from core.montage.logo import LogoAnalysis

BRIEF_MAX_WORDS: Final = 100

ContrastProblem = Literal["text_on_primary", "accent_on_video"]


@dataclass(frozen=True, slots=True)
class Contacts:
    """Where a viewer is sent. Usernames without ``@``, phone in E.164."""

    telegram: str = ""
    instagram: str = ""
    phone: str = ""

    def any(self) -> bool:
        return bool(self.telegram or self.instagram or self.phone)


@dataclass(frozen=True, slots=True)
class Palette:
    primary: str
    accent: str
    text: str


def is_complete(*, brand_name: str, description: str, contacts: Contacts) -> bool:
    """Whether a montage may be made with this brand."""
    return bool(brand_name.strip() and description.strip() and contacts.any())


def brief(
    *,
    brand_name: str,
    description: str,
    tagline: str,
    cta_text: str,
    contacts: Contacts,
    logo: LogoAnalysis | None,
) -> str:
    """The brand in at most :data:`BRIEF_MAX_WORDS` words, for Claude to read."""
    parts = [f"Brand: {brand_name.strip()}."]
    if description.strip():
        parts.append(f"What it does: {_sentence(description)}")
    if tagline.strip():
        parts.append(f"Tagline: {_sentence(tagline)}")
    if logo is not None:
        parts.append(_logo_line(logo))
    reach = _reach(contacts)
    if reach:
        parts.append(f"Contact: {reach}.")
    if cta_text.strip():
        parts.append(f"Call to action: {_sentence(cta_text)}")
    return _cap(" ".join(parts), BRIEF_MAX_WORDS)


def speech_terms(
    *, name: str, keyterms: Sequence[str], text_in_logo: str
) -> tuple[str, ...]:
    """Words the transcriber should expect: the brand's name, the owner's
    key terms and what the logo says - each once, as first spelled."""
    seen: set[str] = set()
    terms = []
    for raw in (name, *keyterms, text_in_logo):
        term = " ".join(raw.split())
        if term and term.casefold() not in seen:
            seen.add(term.casefold())
            terms.append(term)
    return tuple(terms)


def suggested_palette(
    *, colors: tuple[str, ...] | list[str], logo: LogoAnalysis | None, neutral: Palette
) -> Palette:
    """The colours the form proposes for a logo; ``neutral`` where it has none."""
    strong = [c for c in colors if is_hex(c) and not is_plain(c)]
    primary = strong[0] if strong else neutral.primary
    offered = [logo.suggested_accent] if logo is not None else []
    accent = next(
        (
            c
            for c in (*offered, *strong[1:])
            if c.lower() != primary.lower() and _lit(c)
        ),
        neutral.accent,
    )
    return Palette(primary=primary, accent=accent, text=readable_on(primary))


def contrast_problems(
    *, primary: str, accent: str, text: str
) -> tuple[ContrastProblem, ...]:
    """The pairs that fall under WCAG's 4.5 for text; colours not yet valid
    are not judged."""
    found: list[ContrastProblem] = []
    if (
        is_hex(primary)
        and is_hex(text)
        and contrast_ratio(text, primary) < TEXT_CONTRAST
    ):
        found.append("text_on_primary")
    if is_hex(accent) and contrast_ratio(accent, DARK) < TEXT_CONTRAST:
        found.append("accent_on_video")
    return tuple(found)


def _lit(color: str) -> bool:
    """Bright enough to light a word over dark footage."""
    return bool(contrast_ratio(color, DARK) >= TEXT_CONTRAST)


def _logo_line(logo: LogoAnalysis) -> str:
    kind = {
        "wordmark": "lettering only",
        "icon": "a symbol only",
        "combination": "a symbol with lettering",
    }[logo.logo_type]
    line = f"Logo: {kind}"
    if logo.text_in_logo.strip():
        line += f' reading "{logo.text_in_logo.strip()}"'
    if logo.style_keywords:
        line += f"; style {', '.join(logo.style_keywords[:4])}"
    return line + "."


def _reach(contacts: Contacts) -> str:
    found = []
    if contacts.telegram:
        found.append(f"Telegram @{contacts.telegram}")
    if contacts.instagram:
        found.append(f"Instagram @{contacts.instagram}")
    if contacts.phone:
        found.append(f"phone {contacts.phone}")
    return ", ".join(found)


def _sentence(text: str) -> str:
    text = " ".join(text.split())
    return text if text.endswith((".", "!", "?", "…")) else f"{text}."


def _cap(text: str, words: int) -> str:
    split = text.split()
    if len(split) <= words:
        return text
    return " ".join(split[:words]).rstrip(",;:") + "…"
