"""A refused launch as the model is told about it, and its answer's key.

Two things, both pure. :func:`refusal_key` decides whether a refusal is
specific enough for one written answer to serve the next advertiser who
meets it, and under which name. :class:`RefusalFacts` is everything known
about the launch that was refused, rendered as the text the model reads.

**The key is the provider's numbers, never its sentences.** Meta writes
the same refusal in Russian, Uzbek and English depending on the ad
account, and quotes the refused value inside it - so a key built from the
text would split one refusal into dozens. The code and subcode read the
same everywhere; the developer string ends with them (see
``metaads.errors.describe``).

**A code alone is not a key.** ``100`` is "Invalid parameter" and covers
every value Meta can refuse; an answer written for one of them would be
wrong for the next. Only a pair - code and subcode - names one refusal.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any, Final

from core.chat.numbers import figures_in
from core.chat.preparations import TROUBLE_WORDS, UNKNOWN_TROUBLE
from core.chat.verify import FigureGate

# The tail ``describe`` writes: "... | code 100/1487851".
_NUMBERS: Final = re.compile(r"code (\d+)/(\d+)\s*$")

# Our own codes that say nothing about which refusal it was. Everything
# else in ``TROUBLE_WORDS`` names one failure and one fix, and may be kept.
UNSPECIFIC: Final = frozenset({"", "refused", "unknown", "not_launchable"})

# How much of each JSON section is shown. The answers and the draft carry
# the advert's own words, which matter; past this they are media lists.
SECTION_CHARS: Final = 3_000


def refusal_key(*, provider: str, error_code: str, error_message: str) -> str:
    """The name one written answer is kept under, or empty for none.

    The provider's code and subcode where the developer string carries
    both; otherwise our own code, where it names one failure. Empty when
    neither does - those refusals are answered afresh every time.
    """
    found = _NUMBERS.search(error_message or "")
    if found:
        return f"{provider}:{found.group(1)}/{found.group(2)}"
    if error_code and error_code not in UNSPECIFIC and error_code in TROUBLE_WORDS:
        return f"{provider}:{error_code}"
    return ""


@dataclass(frozen=True, slots=True)
class RefusalFacts:
    """One refused launch, everything the model may know about it.

    ``sections`` are the launch's own JSON columns - the answers, the
    draft, the audience - each already cut to a size. Kept as data rather
    than as text so a test can ask what was sent without parsing it back.
    """

    error_code: str
    provider_title: str = ""
    provider_message: str = ""
    developer_message: str = ""
    step: str = ""
    goal: str = ""
    budget: str = ""
    page: str = ""
    ad_account: str = ""
    sections: dict[str, Any] = field(default_factory=dict)
    # The link names the answer may use, each with what it opens - names
    # only, never the addresses (see :mod:`core.chat.links`).
    links: tuple[tuple[str, str], ...] = ()
    # A refusal of something this product sent wrongly. The owner can do
    # nothing about it, and steps would send them to try.
    our_fault: bool = False

    def render(self) -> str:
        """The facts as the model reads them. English, like every look-up."""
        meaning = TROUBLE_WORDS.get(self.error_code, UNKNOWN_TROUBLE)
        lines = [
            "## The refusal",
            f"- our code: {self.error_code or 'none'} ({meaning})",
            f"- Meta's title for the advertiser: {self.provider_title or 'none'}",
            f"- Meta's message for the advertiser: {self.provider_message or 'none'}",
            f"- Meta's developer message: {self.developer_message or 'none'}",
            f"- reached step: {self.step or 'unknown'}",
            "",
            "## The advert that was being created",
            f"- goal: {self.goal or 'unknown'}",
            f"- daily budget: {self.budget or 'unknown'}",
            f"- Facebook page: {self.page or 'unknown'}",
            f"- ad account: {self.ad_account or 'unknown'}",
        ]
        if self.our_fault:
            lines += [
                "",
                "## Whose fault",
                "This product's. It sent Meta something Meta does not accept; "
                "the owner did nothing wrong and can do nothing about it.",
            ]
        if self.links:
            lines += ["", "## Links you may use"]
            lines += [f"- [[{name}]] — {meaning}" for name, meaning in self.links]
        for name, value in self.sections.items():
            lines += ["", f"## {name}", _compact(value)]
        return "\n".join(lines)

    def figures(self) -> frozenset[str]:
        """Every figure the model was handed - the gate's allow-list."""
        return frozenset(figures_in(self.render()))


def _compact(value: Any) -> str:
    """One JSON column on as few characters as it will go."""
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
    return text if len(text) <= SECTION_CHARS else text[:SECTION_CHARS] + "…"


def shareable(text: str) -> bool:
    """Whether an answer carries no figure of this owner's own.

    The gate it streamed through allows every figure of the refused launch -
    the reader may be told their own budget - so a figure it let through
    is one of theirs. The answer kept is served to everybody who meets the
    refusal, so it may hold only the figures that are language: "2-3 kun",
    "24 soat".
    """
    gate = FigureGate(allowed=frozenset())
    gate.feed(text)
    gate.flush()
    return gate.masked == 0


__all__ = ["UNSPECIFIC", "RefusalFacts", "refusal_key", "shareable"]
