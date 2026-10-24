"""Links in an answer: the model names them, the product writes them."""

import html
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

LINK: Final = re.compile(r"\[\[([a-z_]+)\]\]")


@dataclass(frozen=True, slots=True)
class Link:
    """One address the answer may point at, and what it is called."""

    label: str
    url: str


def link_html(rendered: str, links: Mapping[str, Link]) -> str:
    """Rendered HTML with every known name turned into an anchor."""

    def anchor(match: re.Match[str]) -> str:
        found = links.get(match.group(1))
        if found is None:
            return ""
        return (
            f'<a href="{html.escape(found.url)}" target="_blank" '
            f'rel="noopener" class="underline">{html.escape(found.label)}</a>'
        )

    return LINK.sub(anchor, rendered)


def link_text(text: str, links: Mapping[str, Link]) -> str:
    """The same answer as plain text: the label and the address after it."""

    def spelled(match: re.Match[str]) -> str:
        found = links.get(match.group(1))
        return f"{found.label} ({found.url})" if found is not None else ""

    return LINK.sub(spelled, text)


__all__ = ["LINK", "Link", "link_html", "link_text"]
