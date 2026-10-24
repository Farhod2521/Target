"""A refused launch as the model is told about it, and its answer's key."""

import json
import re
from dataclasses import dataclass, field
from typing import Any, Final

from core.chat.numbers import figures_in
from core.chat.preparations import TROUBLE_WORDS, UNKNOWN_TROUBLE
from core.chat.verify import FigureGate

_NUMBERS: Final = re.compile(r"code (\d+)/(\d+)\s*$")

UNSPECIFIC: Final = frozenset({"", "refused", "unknown", "not_launchable"})

SECTION_CHARS: Final = 3_000


def refusal_key(*, provider: str, error_code: str, error_message: str) -> str:
    """The name one written answer is kept under, or empty for none."""
    found = _NUMBERS.search(error_message or "")
    if found:
        return f"{provider}:{found.group(1)}/{found.group(2)}"
    if error_code and error_code not in UNSPECIFIC and error_code in TROUBLE_WORDS:
        return f"{provider}:{error_code}"
    return ""


@dataclass(frozen=True, slots=True)
class RefusalFacts:
    """One refused launch, everything the model may know about it."""

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
    links: tuple[tuple[str, str], ...] = ()
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
    """Whether an answer carries no figure of this owner's own."""
    gate = FigureGate(allowed=frozenset())
    gate.feed(text)
    gate.flush()
    return gate.masked == 0


__all__ = ["UNSPECIFIC", "RefusalFacts", "refusal_key", "shareable"]
