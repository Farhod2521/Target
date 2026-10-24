"""The decision layer.

Reads metrics, proposes changes, and refuses the ones that would hurt: a
suggestion is only ever applied after ``guardrails`` allows it *and* after
the owner has said yes. Nothing here reaches a provider on its own.

Two halves that are easy to confuse. ``rules`` decides - arithmetic over
figures, deterministic, replayable from the numbers stored beside each
suggestion. Claude reviews and explains: it may drop an entry the numbers
do not support and it writes the sentence the owner reads, but it cannot
add a change or invent an ad set. A fluent recommendation about an object
that does not exist is the one failure a prompt cannot be written out of.

Prompts live here too, as files under ``prompts/``, one directory per name
and one file per version. They are versioned because a prompt is the part of
this system most likely to be edited and least likely to be tested: when
answers get worse the only answerable question is "which prompt, and since
when", and a string in a Python file cannot answer it.
"""

from pathlib import Path

from core.agent.assess import (
    EXPECTATIONS,
    GONE,
    JUDGED_ON_PARENT,
    NOT_WORKED,
    UNCLEAR,
    WORKED,
    assess,
)
from core.agent.before_after import Change
from core.agent.broaden import Broadening, broaden
from core.agent.contracts import (
    Aftermath,
    Finding,
    GuardrailVerdict,
    Policy,
    ProviderAdvice,
    SuggestionKind,
    Verdict,
)
from core.agent.facts import (
    AccountFacts,
    AdFacts,
    AdSetFacts,
    Half,
    LibraryImage,
    ctr_bp,
    judgeable,
    troubled,
)
from core.agent.funnel import Funnel, Landing, per_ten_thousand
from core.agent.goal_reading import (
    ChoiceReading,
    ChoiceState,
    GoalReading,
    ReadingState,
    read_goal,
    read_goal_choice,
)
from core.agent.guardrails import (
    AdContext,
    ObjectState,
    check_ad_pause,
    check_budget_change,
    check_creative_swap,
    check_limit_change,
    check_status_change,
    check_targeting_change,
    resets_learning,
)
from core.agent.narrow import Narrowing, NarrowingStep, narrow
from core.agent.repair import Repair, named_audiences, repair
from core.agent.rules import CODES, UNCAPPED, cap, find, holds, scan
from core.agent.schemas import (
    AgentReview,
    AudienceProposal,
    ChatQuestions,
    CreativeProposal,
    CreativeSection,
    DecisionNote,
    DeepFormSection,
    FormQuestion,
    FormSection,
    GoalChoice,
    GoalIntent,
    GoogleSearchDraft,
    InterestProposal,
    InterestSection,
    LaunchDraft,
    LaunchDraftDeepForm,
    LaunchDraftWithoutForm,
    QuestionKind,
    QuestionOptions,
    TranslatedTerm,
    TranslatedTerms,
)
from core.agent.widen import Widening, WideningStep, widen

# Where ``llmkit.PromptLibrary`` is pointed. A path, not configuration:
# these files ship with the code and change with it.
PROMPT_DIR = Path(__file__).parent / "prompts"

__all__ = [
    "CODES",
    "EXPECTATIONS",
    "GONE",
    "JUDGED_ON_PARENT",
    "NOT_WORKED",
    "PROMPT_DIR",
    "UNCAPPED",
    "UNCLEAR",
    "WORKED",
    "AccountFacts",
    "AdContext",
    "AdFacts",
    "AdSetFacts",
    "Aftermath",
    "AgentReview",
    "AudienceProposal",
    "Broadening",
    "Change",
    "ChatQuestions",
    "ChoiceReading",
    "ChoiceState",
    "CreativeProposal",
    "CreativeSection",
    "DecisionNote",
    "DeepFormSection",
    "Finding",
    "FormQuestion",
    "FormSection",
    "Funnel",
    "GoalChoice",
    "GoalIntent",
    "GoalReading",
    "GoogleSearchDraft",
    "GuardrailVerdict",
    "Half",
    "InterestProposal",
    "InterestSection",
    "Landing",
    "LaunchDraft",
    "LaunchDraftDeepForm",
    "LaunchDraftWithoutForm",
    "LibraryImage",
    "Narrowing",
    "NarrowingStep",
    "ObjectState",
    "Policy",
    "ProviderAdvice",
    "QuestionKind",
    "QuestionOptions",
    "ReadingState",
    "Repair",
    "SuggestionKind",
    "TranslatedTerm",
    "TranslatedTerms",
    "Verdict",
    "Widening",
    "WideningStep",
    "assess",
    "broaden",
    "cap",
    "check_ad_pause",
    "check_budget_change",
    "check_creative_swap",
    "check_limit_change",
    "check_status_change",
    "check_targeting_change",
    "ctr_bp",
    "find",
    "holds",
    "judgeable",
    "named_audiences",
    "narrow",
    "per_ten_thousand",
    "read_goal",
    "read_goal_choice",
    "repair",
    "resets_learning",
    "scan",
    "troubled",
    "widen",
]
