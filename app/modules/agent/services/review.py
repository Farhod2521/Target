"""Asking Claude to check the shortlist and write the sentence.

The one Claude call the agent makes, and the smaller half of its job. The
decisions were made by arithmetic before this runs - see
``core.agent.rules`` - and what the model adds is two things a rule cannot
produce: a second opinion on whether the numbers really support each
change, and an explanation a shop owner can read.

**It may drop an entry; it may never add one.** The shortlist arrives with
the ad set, the kind and the figure already fixed, and the schema gives the
model no field to invent another. That constraint is not politeness: a
language model asked what to do with an advertising budget will eventually
produce a fluent recommendation about an ad set that does not exist, and
no prompt removes the possibility.

**Nor does it choose the cause.** Each group's diagnosis is found by
arithmetic too - see ``core.agent.diagnosis`` - and travels on its entry as
the sentence the card prints above the model's. The model writes *why this
change*, resting on that cause, and is told never to name another.

One call for the whole list rather than one per change. The entries compete
for the same budget and the same attention, and three calls cost three
times as much to produce an answer that agrees with itself less often. A
list longer than one answer may hold is sent in parts - see
:data:`core.agent.schemas.MAX_NOTES` - because the faults the provider
reports are proposed however many there are.

**Three parts, in the order they change.** The rules are the same for every
account the night reaches; the business and its totals are one account's;
the shortlist is tonight's. They are sent as the stable half of the system
prompt, the half after it, and the question - which is the seam a cache
breakpoint needs. Whether one is placed there is one deployment setting in
``shared.llm``.
"""

from collections.abc import Callable, Mapping
from typing import Any

from llmkit import LLMError, LLMResult, render

from app.common.llm import UNATTENDED, both, claude, prompts
from app.modules.ads.troubles import first_known
from app.modules.agent.aims import expectation, goal_of, result_line
from app.modules.agent.causes import cause_label, cause_line
from app.modules.agent.constants import RULE_LABELS, SuggestionKind
from app.modules.agent.diagnosed import diagnosis_of, diagnosis_record
from app.modules.agent.figures import readable
from app.modules.agent.services.check_review import (
    PROMPT,
    Reviewed,
    merged,
    numbered,
    record_failure,
    spent_with,
)
from app.modules.agent.services.describe_account import account_block
from app.modules.agent.steps import steps_block
from app.modules.businesses.models import Business
from core.agent import AccountFacts, AgentReview, Finding
from core.agent.diagnosis import Diagnosis
from core.agent.rules.faults import REFUSED_AD
from core.agent.schemas import MAX_NOTES
from core.chat.numbers import figures_in


def review(
    *,
    account: AccountFacts,
    business: Business,
    findings: list[Finding],
    language: str,
    causes: Mapping[str, Diagnosis] | None = None,
    history: Callable[[list[Finding]], str] | None = None,
) -> tuple[list[Reviewed], LLMResult[AgentReview]]:
    """The shortlist, judged. Raises whatever ``llmkit`` raises.

    Failures are not swallowed here. A proposal with no explanation is not
    a smaller feature, it is a button on a screen that says "trust me" -
    so the caller treats a failed call as a night with nothing to show and
    records why, with what it cost.

    ``causes`` is each group's diagnosis by group id, the same mapping the
    rows are written with afterwards. ``language`` is the owner's, which is
    the one the sentence is written in: the card and the message around it
    are drawn in it too.

    ``history`` writes what was proposed before about one part's entries -
    see :mod:`apps.agent.past`. Read by the caller, which holds the owner.

    The result is every part's answer added into one, so the caller writes
    one ledger row for what the account's review cost.
    """
    if not findings:
        raise ValueError("a review needs something to review")
    template, version = prompts().get(PROMPT)
    system = render(template, {"account": ""}).rstrip()
    tail = account_block(account=account, business=business, language=language)
    reviewed: list[Reviewed] = []
    total: LLMResult[AgentReview] | None = None
    with claude(tier=UNATTENDED) as client:
        for start in range(0, len(findings), MAX_NOTES):
            part = findings[start : start + MAX_NOTES]
            listed = shortlist(account=account, findings=part, causes=causes)
            behind = [
                steps_block(
                    findings=part, causes=causes or {}, currency=account.currency
                ),
                history(part) if history is not None else "",
            ]
            ask: dict[str, Any] = {
                "prompt": "\n\n".join([listed, *(each for each in behind if each)]),
                "schema": AgentReview,
                "prompt_name": PROMPT,
                "prompt_version": version,
                "system": system,
                "system_tail": tail,
            }
            try:
                result = numbered(client, ask=ask, size=len(part))
            except LLMError as exc:
                if total is not None:
                    exc.spent = spent_with(exc.spent, total)
                raise
            reviewed += merged(
                findings=part,
                notes=result.value.notes,
                allowed=figures_in(f"{listed}\n{tail}"),
            )
            total = result if total is None else both(total, result)
    assert total is not None
    return (reviewed, total)


def shortlist(
    *,
    account: AccountFacts,
    findings: list[Finding],
    causes: Mapping[str, Diagnosis] | None = None,
) -> str:
    """The findings as the model reads them: numbered, named, with figures.

    Named by object rather than by id. The model writes a sentence somebody
    reads next to a button, and "reklama guruhi 120330..." is not a phrase
    anybody recognises as their own campaign. Which *kind* of object is
    named too, because a proposal can be about one advert inside a group,
    and "your group is spending money for nothing" said about a
    single advert is a sentence that would frighten somebody for no reason.

    **The expectation and the cause go in as context, never as a task.**
    Both are the product's own sentences, shown on the same card as the
    model's - so the model is given them to rest its sentence on, and told
    in the prompt not to restate or replace them.
    """
    names = _names(account=account, findings=findings)
    blocks = []
    for index, finding in enumerate(findings):
        name = names.get(finding.ref.id) or finding.ref.id
        heading = _HEADINGS.get(finding.level, _HEADINGS["adset"])
        lines = "\n".join(
            (
                f"- {label}: {value}"
                for label, value in readable(
                    finding.evidence, currency=account.currency
                )
            )
        )
        goal = goal_of(
            evidence=finding.evidence,
            diagnosis=diagnosis_record(diagnosis_of(finding, causes or {})),
        )
        result = result_line(goal, currency=account.currency)
        label = "Guruh natijasi" if finding.level == "ad" else "Natija"
        said = f"{label}: {result}\n" if result else ""
        blocks.append(
            f'### {index}. {heading}: "{name}"\nTaklif: {SuggestionKind(finding.kind).label} ({RULE_LABELS.get(finding.rule, finding.rule)})\nBiz kutamiz: {expectation(rule=finding.rule, evidence=goal)}\n{said}{_cause(finding, causes or {}, currency=account.currency)}{_fault(finding)}{lines}'
        )
    return "## The shortlist\n\n" + "\n\n".join(blocks)


def _cause(finding: Finding, causes: Mapping[str, Diagnosis], *, currency: str) -> str:
    """The group's diagnosis, as the card prints it above the model's sentence.

    Empty for an entry with none - a campaign, or a group the diagnosis
    found nothing wrong with. The model is then left with the figures,
    which is what it had before there was a diagnosis at all.
    """
    record = diagnosis_record(diagnosis_of(finding, causes))
    label = cause_label(str(record.get("cause", "")))
    if not label:
        return ""
    line = cause_line(record, currency=currency)
    return f"Sabab: {label}" + (f" - {line}" if line else "") + "\n"


def _fault(finding: Finding) -> str:
    """What the provider said is wrong, where it said anything.

    Empty for the rules that read figures, which is most of the shortlist.
    It is here at all because the provider's fault is the one entry on the
    list whose *reason* is not in the numbers beside it: the figures say a
    group stopped spending and only this says why.

    **This product's sentence, never the provider's own text.** The table
    in ``apps.ads.troubles`` is written for somebody who has never opened
    an Ads Manager, and a fault it does not recognise gets the shorter
    line below rather than a paragraph of the platform's English - the
    model would translate that English into a confident Uzbek instruction
    to press something four screens away.
    """
    if finding.rule == REFUSED_AD:
        return "Meta nima dedi: Meta bu reklamani o'z qoidalariga zid deb rad etgan, u hech kimga ko'rsatilmayapti. Guruhning raqamlari bu reklamaniki emas.\n"
    codes = finding.evidence.get("issue_codes")
    if not codes:
        return ""
    known = first_known(tuple(str(code) for code in codes))
    said = (
        str(known.detail)
        if known is not None
        else "Meta bu guruhni o'z sababi bilan to'xtatgan."
    )
    return f"Meta nima dedi: {said}\n"


_HEADINGS: dict[str, str] = {
    "adset": "Reklama guruhi",
    "ad": "Reklama",
    "campaign": "Kampaniya",
}


def _names(*, account: AccountFacts, findings: list[Finding]) -> dict[str, str]:
    """``{id: name}`` for everything on the shortlist, from the facts.

    The adverts come off the ad sets they belong to rather than from a
    query: the facts already carry them, and a second read here would be
    the same rows fetched twice inside one pass.
    """
    found = {item.external_id: item.name for item in account.adsets}
    wanted = {finding.ref.id for finding in findings}
    for item in account.adsets:
        for ad in item.ads:
            if ad.external_id in wanted:
                found[ad.external_id] = ad.name
    return found


__all__ = [
    "PROMPT",
    "Reviewed",
    "account_block",
    "record_failure",
    "review",
    "shortlist",
]
