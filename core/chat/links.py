"""Links in an answer: the model names them, the product writes them.

The model never writes an address. It writes ``[[name]]`` from a closed
list it was shown, and the address behind each name is filled in for the
reader at the moment the answer is drawn. Three reasons, each sufficient:

* **A ready answer is shared.** It is written once and shown to every
  advertiser who meets the same refusal - an address in it would be the
  first advertiser's account opened by the second.
* **The figure gate reads digits.** An ad account id inside an address is
  a figure nobody supplied, and it would reach the screen as ``[?]``.
* **The renderer writes no links of its own** (see
  :mod:`core.chat.markdown`). A name this module does not know is removed,
  so the worst the model can do is drop a link - never add one.
"""

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
    """Rendered HTML with every known name turned into an anchor.

    Run on the renderer's output, after escaping: the names are letters and
    underscores, so they survive escaping unchanged, and the label and the
    address are escaped here.
    """

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
