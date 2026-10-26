"""The rates behind each shortlisted entry, for the model to check against.

The diagnosis compares every step of a group's funnel with the account's -
what a thousand impressions cost, how many of them clicked, how many clicks
became a lead, how long a video held, how often one person saw it - and
until now the model saw only the one sentence the first failing step
produced. A second opinion on whether the numbers support a change cannot
be given from a conclusion; it needs the numbers.

**For checking, never for quoting.** None of these is printed on the card,
and a reason citing a figure the owner cannot see beside it is the failure
``apps.agent.figures`` exists to prevent. So the block is sent after the
shortlist and left out of the figures the reason is allowed to name - see
:func:`apps.agent.services.review.review`. A sentence quoting one is
dropped by the gate, and the prompt says so.

Read from the same evidence the row keeps, through the same formatters as
the cause sentence, so a rate here and the rate in "Sabab:" are one string.
The chat and the reports read the same lines in English - see
:mod:`apps.agent.step_words` - so every model is shown one set of figures.
"""

from collections.abc import Callable, Mapping
from typing import Any

from app.common.dates import number_format
from app.common.money import format_minor
from app.modules.agent.diagnosed import diagnosis_of
from app.modules.agent.figures import bp_percent, decimal_of, hundredths, whole
from app.modules.agent.step_words import UZ, StepWords
from app.modules.metrics.constants import BreakdownKind
from core.agent import Finding
from core.agent.diagnosis import Diagnosis
from core.agent.sufficiency import MIN_IMPRESSIONS, MIN_LINK_CLICKS, SPEND_MULTIPLE

Shown = Callable[[int], str]


def steps_block(
    *, findings: list[Finding], causes: Mapping[str, Diagnosis], currency: str
) -> str:
    """``## The figures behind each entry`` with one part per entry, or ``""``.

    Indexed like the shortlist. An entry with no diagnosis - a campaign, a
    group too new for the night - is left out rather than listed empty.
    """
    parts = []
    for index, finding in enumerate(findings):
        diagnosis = diagnosis_of(finding, causes)
        if diagnosis is None:
            continue
        lines = step_lines(diagnosis.evidence, currency=currency)
        if lines:
            parts.append(f"### {index}\n" + "\n".join(f"- {line}" for line in lines))
    if not parts:
        return ""
    return "## The figures behind each entry\n\n" + "\n\n".join(parts)


def step_lines(
    evidence: Mapping[str, Any],
    *,
    currency: str,
    words: StepWords = UZ,
    skip: frozenset[str] = frozenset(),
) -> list[str]:
    """Each step the group's figures reach, beside the account's own.

    ``skip`` leaves out steps a caller already prints on the same line -
    ``"cpm"``, ``"ctr"``, ``"frequency"``, ``"slice"`` - so no figure is
    said twice in two shapes.
    """

    def money(value: int) -> str:
        return format_minor(amount_minor=value, currency=currency)

    lines = {
        "cpm": _beside(
            words.cpm, evidence, "cpm_minor", "account_cpm_minor", money, words
        ),
        "ctr": _beside(
            words.ctr,
            evidence,
            "link_ctr_bp",
            "account_link_ctr_bp",
            lambda value: decimal_of(value, 10),
            words,
        ),
        "arrival": _arrival(evidence, words),
        "click_to_lead": _beside(
            words.click_to_lead,
            evidence,
            "click_to_lead_bp",
            "account_click_to_lead_bp",
            lambda value: decimal_of(value, 100),
            words,
        )
        if evidence.get("outcome") == "lead"
        else "",
        "hook": _beside(
            words.hook, evidence, "hook_bp", "account_hook_bp", bp_percent, words
        ),
        "hold": _beside(
            words.hold, evidence, "hold_bp", "account_hold_bp", bp_percent, words
        ),
        "spend_share": _share(words.spend_share, evidence, "spend_share"),
        "junk": _junk(evidence, words),
        "learning": _learning(evidence, words),
        "enough": _enough(evidence, money=money, words=words),
        "trend": _trend(evidence, money=money, words=words),
        "launch": _launch(evidence, words),
        "frequency": _weeks(evidence, words),
        "halves": _halves(evidence, words),
        "slice": _slice(evidence.get("costly_slice"), money=money, words=words),
    }
    return [line for key, line in lines.items() if line and key not in skip]


def _beside(
    label: str,
    evidence: Mapping[str, Any],
    own_key: str,
    usual_key: str,
    shown: Shown,
    words: StepWords,
) -> str:
    """``label: own (usual)``, or the group's own figure alone."""
    own = whole(evidence.get(own_key))
    if own is None:
        return ""
    usual = whole(evidence.get(usual_key))
    if usual is None:
        return f"{label}: {shown(own)}"
    return f"{label}: {shown(own)} ({words.usual} {shown(usual)})"


def _halves(evidence: Mapping[str, Any], words: StepWords) -> str:
    """The window's first half against its second, which is the only trend
    the facts hold - see ``core.agent.facts``."""
    early, late = (
        whole(evidence.get("early_ctr_bp")),
        whole(evidence.get("late_ctr_bp")),
    )
    if early is None or late is None:
        return ""
    return f"{words.halves}: {words.halves_early} {bp_percent(early)}, {words.halves_late} {bp_percent(late)}"


def _weeks(evidence: Mapping[str, Any], words: StepWords) -> str:
    """A frequency over the newest seven days, and over the seven before."""
    now = whole(evidence.get("frequency"))
    before = whole(evidence.get("prior_frequency"))
    if now is None:
        return ""
    line = f"{words.frequency}: {words.frequency_now} {hundredths(now)}"
    if before is not None:
        line += f", {words.frequency_before} {hundredths(before)}"
    return line


def _share(label: str, evidence: Mapping[str, Any], key: str) -> str:
    share = whole(evidence.get(key))
    return f"{label}: {share}%" if share is not None else ""


def _junk(evidence: Mapping[str, Any], words: StepWords) -> str:
    junk, leads = (whole(evidence.get("junk_leads")), whole(evidence.get("leads")))
    if not junk or not leads:
        return ""
    return f"{words.junk}: {junk} / {leads}"


def _learning(evidence: Mapping[str, Any], words: StepWords) -> str:
    """The week's results against the fifty the provider wants to learn."""
    results = whole(evidence.get("results"))
    if results is None:
        return ""
    return words.learning.format(results=results)


def _enough(evidence: Mapping[str, Any], *, money: Shown, words: StepWords) -> str:
    """Whether the week's money is the brief's three results' worth.

    The figure every verdict asks first - see :mod:`core.agent.sufficiency`.
    With no usual price yet, the showings and clicks the brief asks for
    instead. Nothing for showings, whose price is a thousand's.
    """
    spent, usual = (
        whole(evidence.get("spend_minor")),
        whole(evidence.get("account_cost_minor")),
    )
    if spent is None or evidence.get("outcome") == "view":
        return ""
    if not usual:
        return _enough_shown(evidence, words=words)
    needed = usual * SPEND_MULTIPLE
    said = words.enough_yes if spent >= needed else words.enough_no
    return f"{words.enough}: " + said.format(spent=money(spent), needed=money(needed))


def _enough_shown(evidence: Mapping[str, Any], *, words: StepWords) -> str:
    """The brief's bar where no usual price exists: showings and clicks."""
    shown, clicks = (
        whole(evidence.get("impressions")),
        whole(evidence.get("link_clicks")),
    )
    if shown is None or clicks is None:
        return ""
    said = (
        words.enough_shown_yes
        if shown >= MIN_IMPRESSIONS and clicks >= MIN_LINK_CLICKS
        else words.enough_shown_no
    )
    return f"{words.enough}: " + said.format(
        shown=_grouped(shown),
        clicks=_grouped(clicks),
        min_shown=_grouped(MIN_IMPRESSIONS),
        min_clicks=_grouped(MIN_LINK_CLICKS),
    )


def _grouped(count: int) -> str:
    return str(number_format(count))


def _trend(evidence: Mapping[str, Any], *, money: Shown, words: StepWords) -> str:
    """The last three days' price against the usual one, and what the night
    called it - the brief's warning or its reason to act."""
    recent = whole(evidence.get("recent_cost_minor"))
    usual = whole(evidence.get("usual_cost_minor"))
    if usual is None:
        return ""
    now = money(recent) if recent is not None else words.trend_none
    trend = whole(evidence.get("cost_trend_pct"))
    tail = f", {words.trend_share.format(pct=trend)}" if trend is not None else ""
    line = f"{words.trend}: {now} ({words.trend_usual} {money(usual)}{tail})"
    level = evidence.get("price_level")
    if level == "act":
        line += f" - {words.act}"
    elif level == "warn":
        line += f" - {words.warn}"
    return line


def _launch(evidence: Mapping[str, Any], words: StepWords) -> str:
    """The click rate while the advert was new against its last three days."""
    then, now = (
        whole(evidence.get("launch_ctr_bp")),
        whole(evidence.get("recent_ctr_bp")),
    )
    if then is None or now is None:
        return ""
    return f"{words.launch}: {words.launch_new} {bp_percent(then)}, {words.launch_now} {bp_percent(now)}"


def _arrival(evidence: Mapping[str, Any], words: StepWords) -> str:
    """How many clicks reached the page. Nothing for a group that sends
    nobody to a site - a form or a chat has no page view to count."""
    clicks = whole(evidence.get("link_clicks")) or 0
    arrived = whole(evidence.get("landing_page_views")) or 0
    if clicks <= 0 or arrived <= 0:
        return ""
    share = bp_percent(round(arrived * 10000 / clicks))
    return f"{words.arrival}: {share}"


def _slice(found: object, *, money: Shown, words: StepWords) -> str:
    """The dear slice: which part of the audience, what share, what price."""
    if not isinstance(found, dict):
        return ""
    share, cpm = (whole(found.get("spend_share_pct")), whole(found.get("cpm_minor")))
    if share is None or cpm is None:
        return ""
    kind = str(found.get("kind", ""))
    try:
        cut = str(BreakdownKind(kind).label)
    except ValueError:
        cut = kind
    return f"{words.slice} ({cut}: {found.get('segment', '')}): {words.slice_share.format(share=share)}, {words.slice_cpm} {money(cpm)}"


__all__ = ["step_lines", "steps_block"]
