"""The first line of a conversation the ad is about to open.

A chat ad buys one thing: somebody tapping it lands in a message thread
with the business. What is already written in that thread when they arrive
is the whole of what this module is about, and the provider hosts all of
it - there is no object to create, no id to keep and nothing to roll back.

**Two texts, and they are not the same text.**

``greeting``   the business speaking first. Shown in the thread above the
               input box, and the only thing in this flow written in the
               owner's own voice about their own business.
``autofill``   the customer's opening line, pre-typed into their box for
               them to send or replace. It follows from the *goal* rather
               than from the business - "tell me more about this offer" is
               the same sentence for a clinic and for a car dealer - which
               is why it lives in the catalogue and is never asked for.

The greeting is **optional**, and that is a provider fact rather than a
kindness: with none sent the provider writes its own ("Hello! Can I get
more info on this?"). So an unanswered greeting is a working ad in a
language the customer did not choose, never a refused launch - the
opposite of the website goal's address, where empty has to stop the
launch because the alternative is spending somebody's budget in the wrong
place.
"""

from collections.abc import Iterable
from typing import Final

from core.targeting.contracts import BusinessProfile
from core.targeting.exceptions import TargetingError
from core.targeting.presets import Preset
from core.targeting.render import render

# The provider's own ceilings, in characters. Meta refuses the creative
# past them - "Message text must not be more than 300 characters" - which
# is late enough to have created a campaign, an ad set and an image upload
# first, so the form that collects the text enforces them instead.
MAX_GREETING_CHARS: Final = 300
MAX_AUTOFILL_CHARS: Final = 300
# The questions a customer taps under the greeting. Meta caps a question at
# 80 characters and does not document a count; four is what Meta's own
# page-level questions allow, and the most this product offers.
MAX_CHAT_QUESTIONS: Final = 4
MAX_QUESTION_CHARS: Final = 80


def clean_questions(raw: Iterable[object]) -> tuple[str, ...]:
    """The owner's questions as they will be sent: trimmed, blank and
    repeated ones dropped, in the order written.

    Not cut to length or count - a question too long is refused by the form
    that collected it, where it can still be shortened.
    """
    seen: set[str] = set()
    kept: list[str] = []
    for item in raw:
        question = " ".join(str(item).split())
        key = question.casefold()
        if question and key not in seen:
            seen.add(key)
            kept.append(question)
    return tuple(kept)


def suggested_greeting(*, preset: Preset, business: BusinessProfile) -> str:
    """The catalogue's greeting with this business's own name in it.

    A **suggestion**, which is why this is the one place in the package
    that swallows a failure instead of raising. Everything else here builds
    a spec, and a half-filled spec spends money on the wrong thing; this
    fills a text box somebody is about to read and edit. A profile with no
    name yet leaves the box empty, and an empty box is a legal answer with
    a defined meaning - the provider greets them instead.

    Empty for every goal that opens no conversation, so the caller can ask
    without checking first.
    """
    if not preset.opens_chat or not preset.welcome_message:
        return ""
    try:
        greeting = render(
            preset.welcome_message,
            sources={"business": business},
            defaults=preset.defaults,
        )
    except TargetingError:
        return ""
    return str(greeting)[:MAX_GREETING_CHARS]
