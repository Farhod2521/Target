"""What the agent may put right without asking, and what it may never.

**The line is not "is it small".** Almost every fault Meta reports touches
money or touches who an advert is shown to, and neither of those is small
whatever the fix looks like from here. The line is somewhere else: between
*changing* something and *restoring* something.

Three conditions, and all three have to hold:

* **It does not spend.** Nothing that alters a budget, a bid, or whether an
  advert is delivering. A paused campaign costs nothing and a resumed one
  costs whatever it costs; both are the owner's decision.
* **It can be undone.** Not as a promise - as a named inverse. A fix that
  cannot say what would reverse it has not been shown to be reversible, it
  has been assumed to be.
* **It is not a new decision.** The owner already asked for this: they
  connected the page, they paid for those enquiries. Putting a thing back
  the way they set it up is not the product deciding anything.

**The model does not apply these conditions.** It is not asked "is this
small?" and never will be - the answer would be a judgement that drifts,
and one day it drifts on a live account. The decision comes out of the
table below, which is written by hand, and a trigger that is not in it is
never fixed automatically however obvious the fix looks. Meta rewrites its
messages and adds codes; a table that guessed at a code it had never seen
would be a confident wrong answer with somebody's advertising behind it.

What that leaves is a short list, and shortness is the design working
rather than the design being unfinished. Removing a broken audience does
not pass - who sees the advert changes. Raising a spend cap does not pass -
money. Restarting a stopped advert does not pass - money again. All of
those keep their button.

Django-free, like everything in ``core``: a table and three predicates.
"""

from dataclasses import dataclass
from typing import Final

# What was detected. Ids rather than sentences, and a closed set: a trigger
# with no entry below has no fix, no label and no route.
#
# Neither of these is a provider code, and that is worth saying out loud.
# Meta does not report either of these faults - it reports faults about
# *adverts*, and every one of those is about money or about who is being
# shown something. What can be put right without asking turns out to be
# the two things this product knows about its own plumbing: whether the
# page is still wired up to send enquiries, and whether enquiries it has
# already been paid for were never collected. The shape is kept general so
# a provider code can join the table the day one qualifies.
PAGE_UNSUBSCRIBED: Final = "page_unsubscribed"
LEADS_RECOVERABLE: Final = "leads_recoverable"


@dataclass(frozen=True, slots=True)
class Fix:
    """One repair, with the three conditions declared rather than assumed.

    ``undo`` is the named inverse, and an empty one is a statement rather
    than an omission: this repair adds something back and nothing sensibly
    takes it away again. Both entries in the table below are in that
    position today, which is not a coincidence - a repair that neither
    spends nor decides anything is almost always additive, and "undo" for
    an addition of the owner's own data would mean deleting it.
    """

    trigger: str
    # What would be done. A verb, matched to a service by the layer above -
    # this package knows no services.
    action: str
    spends: bool
    decides: bool
    undo: str = ""


def allowed(fix: Fix) -> bool:
    """The gate. All three, or the answer is no.

    Written as one expression on purpose. Three conditions checked in three
    places is three chances for one of them to be relaxed by somebody
    fixing something else.
    """
    return not fix.spends and not fix.decides and reversible(fix)


def reversible(fix: Fix) -> bool:
    """Whether this repair can be put back.

    An additive repair counts as reversible: what it puts back is a state
    the owner had, so the thing that would be "undone" is a broken state
    nobody chose. A repair that *changed* something and named no inverse
    does not count, which is the case this predicate exists to refuse.
    """
    return bool(fix.undo) or not fix.decides


# The hand-written list. Everything not here is left to a button.
_ALLOWED: Final[dict[str, Fix]] = {
    # The page stopped sending enquiries. Somebody removed the subscription
    # from the page's own settings, or a token was renewed and the app was
    # dropped along with it - neither is visible from inside this product
    # except as silence, which is the worst way to learn about it.
    #
    # Subscribing again spends nothing, decides nothing, and is idempotent
    # at the provider. The owner connected this page and asked for its
    # enquiries; this is that request, honoured again.
    PAGE_UNSUBSCRIBED: Fix(
        trigger=PAGE_UNSUBSCRIBED,
        action="relink_page",
        spends=False,
        decides=False,
    ),
    # Enquiries that were paid for and never stored. The provider keeps
    # them for ninety days and then they are gone at the source, so the
    # window in which this is fixable at all is the window in which nobody
    # is looking.
    #
    # Nothing is bought and nothing is decided: the money was spent when
    # the advert ran. What it adds is the customer's own data, which is
    # also why ``undo`` is empty - deleting somebody's enquiries is not a
    # thing this product should have a button for.
    LEADS_RECOVERABLE: Fix(
        trigger=LEADS_RECOVERABLE,
        action="recover_leads",
        spends=False,
        decides=False,
    ),
}


def fix_for(trigger: str) -> Fix | None:
    """The repair for one trigger, if it is one the agent may make.

    ``None`` for everything else, which is most things and always will be.
    An unknown trigger is never fixed automatically - that is the whole of
    the second condition, and it is why this returns rather than guesses.
    """
    found = _ALLOWED.get(trigger.strip()) if trigger else None
    if found is None or not allowed(found):
        return None
    return found


def triggers() -> tuple[str, ...]:
    """Every trigger the agent may act on, sorted. For the layer above."""
    return tuple(sorted(_ALLOWED))


__all__ = [
    "LEADS_RECOVERABLE",
    "PAGE_UNSUBSCRIBED",
    "Fix",
    "allowed",
    "fix_for",
    "reversible",
    "triggers",
]
