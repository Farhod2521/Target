"""Everything one cabinet is waiting on, in one shape and one order.

Without one list, each screen knows one thing that needs answering and none
of them knows the whole: a proposal counted in the navigation, a broken
connection drawn as a banner, a refused advert only on the campaign's own
page, an unfinished preparation only on the dashboard - and an owner who
never opens those screens is never told. The order they matter in is
written down once, here, and every surface reads it from the same place.

**No sentences, only ids, levels and moments.** What an item is called, and
in which language, belongs to the layer that has ``gettext`` - the same rule
:mod:`core.onboarding` follows. What lives here is the part that must not
differ between the bell, the screen, the phone and the assistant: which of
two things is more urgent, and which of them somebody has already seen.

**Seen is a key, never a clock.** The obvious design is "newer than the last
look", and it is wrong for half of these: a refused advert is a row the
provider rewrites on every sync, so a timestamp would make the same refusal
new again four times an hour. A key is stable for exactly as long as the
thing it describes is - which is what :class:`~apps.notifications.models.TelegramNotice`
already proved for the phone, applied to the cabinet.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from adskit import ExternalRef

# What kind of thing is waiting. Ids rather than sentences, and a closed
# set: a kind that is not in this list has no place to be drawn, no label
# and no route, so adding one is a decision rather than a string.
ItemKind = Literal[
    "suggestion",
    "connection",
    # An advert the provider turned down against a policy it names. Its own
    # kind because the phone has a better message for it than a generic
    # one: it quotes the policy about one named advert and links to that
    # campaign.
    "refusal",
    # Delivery the provider has broken off - a deleted audience, a blocked
    # setting. Its own kind rather than the refusal above: the two arrive
    # from the same column and read the same on a screen, but only one of
    # them has an announcer of its own.
    "trouble",
    "subscription",
    "setup",
    "launch",
    "figures",
    "leads",
    # Four facts about the figures. Drawn nowhere else: the dashboard
    # carries no warnings at all, and its one sentence is an empty state
    # rather than a fault.
    "cap",
    "unpriced",
    "attribution",
    "ranking",
    # What the provider suggests could be better, as opposed to what it
    # says is broken. It is stored on two tables and otherwise drawn on one
    # campaign's own page, where advice a platform gives away for free
    # reaches almost nobody.
    "advice",
    # Something the agent already mended by itself. The only kind on this
    # list that is not waiting for anything: it is here because automation
    # that says nothing afterwards is a product doing things behind
    # somebody's back, and the list of what a cabinet should know is
    # exactly where "this was put right" belongs. Always ``news``.
    "repair",
    # Two things last night's diagnosis found that no proposal answers. A
    # group too young to judge, which is best left alone and is here so
    # nobody changes it on its second day; and a form or a page standing
    # between the clicks and the leads, which is fixed outside the advert.
    "wait",
    "landing",
    # The advert itself, which needs a new picture or video; and the
    # audience, too dear to reach or too small for the provider to learn on.
    "creative",
    "audience",
    # Leads the provider counted last week that never reached this product,
    # and the nightly re-read that recovers them failing for days in a row.
    # The first is a gap in the figures; the second is the repair not
    # running. Two kinds because the fix for each is a different screen.
    "lead_gap",
    "sweep",
    # One of the owner's pages whose form adverts collect leads while
    # nothing here is subscribed to it: the provider counts them, none
    # arrive. A button, because which pages to collect is the owner's call.
    "unheard_page",
    # A group spending today with nothing of its own kind to show, while
    # there is still day left to save. The one kind here built from today's
    # figures rather than from a finished day.
    "burn",
    # A group this product switched on in the last week that has spent
    # nothing, or spent with nothing back, for long enough to be worth a
    # word - see ``core.agent.launch_watch``. The one kind with several
    # buttons, one of them the advised.
    "watch",
    # Two things only Meta's own screens can fix, each with a button that
    # opens the screen: Meta holding the person until they confirm who they
    # are, and an ad account that cannot advertise.
    "meta_hold",
    "account_blocked",
    # A reply from the office in a support thread the reader has not opened
    # since. Always ``news``: it is somebody answering them, not something
    # going wrong.
    "support",
    # The office answering a piece of feedback the reader sent: approved
    # and paid, or turned down with a reason. Always ``news``.
    "feedback",
    # The night check itself not finishing, for long enough that its
    # silence has stopped meaning "nothing to change". The only kind here
    # about this product rather than about the advertising - and it earns
    # its place because every other kind is quieter when it is true: a
    # check that did not run proposes nothing, diagnoses nothing and
    # repairs nothing, so the waiting list gets shorter as the thing
    # feeding it dies.
    "checkup",
]

# How much it costs to ignore it. Three, and the difference between the
# first two is not severity but who is spending: ``urgent`` is money
# leaving or leads being lost *now*, ``decision`` is a question with a
# deadline, ``news`` is worth knowing and worth nobody's evening.
Level = Literal["urgent", "decision", "news"]

# Worst first. The order of this tuple *is* the order of the screen, so a
# level added in the middle changes what somebody reads first - which is a
# thing to decide, not a thing to sort alphabetically.
LEVELS: tuple[Level, ...] = ("urgent", "decision", "news")

# Which levels are a question rather than a statement. This is what the
# navigation counts: a number that shrinks only when somebody answers
# something, unlike the bell, which empties the moment it is opened.
ANSWERABLE: frozenset[str] = frozenset({"urgent", "decision"})


@dataclass(frozen=True, slots=True)
class Subject:
    """The advertising object one waiting item is about.

    Without it an item is three strings - a heading, a sentence and a
    level - and four separate things go wanting. The chat can be told
    *which line* somebody is asking about but not what the line is about,
    so it answers in generalities. The phone cannot carry the provider's
    own verdicts, because a message quoting a policy at somebody without
    naming the advert is a worse message than none. No button can be
    offered, because there is nothing to act on. And the agent, which sees
    objects rather than sentences, cannot be handed one of these at all.

    ``ref`` is the object itself, in the shape every other layer already
    uses. ``name`` is what the owner calls it - the provider's own name,
    printed rather than a level word, because "guruh" is not a word a shop
    owner has ever used. ``code`` is the provider's number for the trouble
    where there is one, which is what lets a known fault be translated
    into a sentence this product wrote instead of the provider's English.

    ``None`` on an item is not a missing field. A lapsed subscription and
    an unfinished setup are about the cabinet, not about an advert, and
    inventing a ref for them would put a nonexistent object in front of
    the agent.
    """

    ref: ExternalRef
    name: str = ""
    code: str = ""


@dataclass(frozen=True, slots=True)
class ItemAction:
    """One of several buttons under an item, for the kind that offers a choice.

    ``advised`` marks the one the product recommends, which is drawn apart
    from the rest. ``href`` is a form's address, always followed with a
    post - every one of these is a change to somebody's account. Empty for
    advice that is not a press: "wait" changes nothing, so it is said rather
    than offered. ``confirm`` is the question asked before the press, for
    the one change that cannot be taken back.
    """

    label: str
    href: str = ""
    advised: bool = False
    confirm: str = ""


@dataclass(frozen=True, slots=True)
class InboxItem:
    """One thing waiting for this cabinet's owner.

    ``key`` is what makes "already seen" possible and it has to be stable
    across a sync, a page reload and a worker restart - ``kind:subject``,
    where the subject is whatever identifies the thing itself. A key that
    changed while the underlying trouble did not would make the bell red
    forever; a key shared by two different troubles would hide the second.

    ``since`` is when the product believes this started, and it is
    ``None`` when the product does not know. That is not laziness: a
    provider's verdict on an advert arrives with no date on it, and
    stamping "now" on it would be inventing a fact to fill a column. It
    orders the list and nothing else - what is new is decided by the key.

    ``action`` and ``href`` are empty for an item answered where it is
    drawn. Today that is the agent's proposal, which carries its own two
    buttons; everything else is a link to the screen that fixes it.

    ``href`` is an address rather than a route name and its arguments.
    Half of these point at a screen that takes an id, and a template
    cannot expand a variable-length argument list into ``{% url %}`` - so
    the layer that has ``reverse`` resolves it, and every surface gets a
    string it can put in an anchor.
    """

    key: str
    kind: ItemKind
    level: Level
    title: str
    body: str
    since: datetime | None = None
    action: str = ""
    href: str = ""
    # What this is about, where it is about an advertising object at all.
    # See :class:`Subject` - the chat, the phone and the agent all need
    # the thing, not only the sentence.
    subject: Subject | None = None
    # How ``href`` is followed. A link almost always; ``post`` for the one
    # line whose action is a change to somebody's account - a stop - which
    # a link must never be able to make.
    method: Literal["get", "post"] = "get"
    # The choice, for the one kind that offers several - see
    # :class:`ItemAction`. Drawn instead of ``action`` when present.
    actions: tuple[ItemAction, ...] = ()


def ordered(items: Iterable[InboxItem]) -> tuple[InboxItem, ...]:
    """Worst first, and within a level the one that has waited longest.

    Oldest first inside a level rather than newest, which is the opposite
    of what a feed does and deliberately so: this is a list of work, and
    the proposal closest to expiring is the one that stops being
    answerable tomorrow. An item with no date sorts last in its level -
    it is the one the product cannot say anything about.
    """
    return tuple(
        sorted(items, key=lambda item: (LEVELS.index(item.level), _rank(item.since)))
    )


def unseen(
    items: Iterable[InboxItem], *, seen: frozenset[str]
) -> tuple[InboxItem, ...]:
    """What this reader has not been shown yet, in the same order.

    The bell's list. ``seen`` holds keys rather than a moment, so an item
    that has been read stays read however many times the sync rewrites the
    row underneath it - and an item that comes back after being fixed
    (a connection that broke twice) is new again, because its key was
    dropped when it went away.
    """
    return tuple(item for item in ordered(items) if item.key not in seen)


def answerable(items: Iterable[InboxItem]) -> tuple[InboxItem, ...]:
    """The ones that are a question. What the navigation counts.

    Apart from :func:`unseen` because they answer different questions.
    "What is new" empties when somebody looks; "what have I not answered"
    empties when somebody answers. One number doing both would be a badge
    that disappears while the work is still there.
    """
    return tuple(item for item in ordered(items) if item.level in ANSWERABLE)


def of_level(items: Iterable[InboxItem], *, level: Level) -> tuple[InboxItem, ...]:
    """One band of the list, still in order.

    The screen draws the three bands apart rather than as one run, because
    they are three different requests of a reader: fix this now, answer
    this, know this. A template that sliced the list itself would be
    deciding that, and a second screen would slice it differently.
    """
    return tuple(item for item in ordered(items) if item.level == level)


def without_kind(
    items: Iterable[InboxItem], *, kind: ItemKind
) -> tuple[InboxItem, ...]:
    """Everything except one kind, for a surface that draws that kind itself.

    The proposals are the only such kind today: they carry their own card,
    their own two buttons and their own swapped region, so the plain list
    must not draw a second, mute copy of them.
    """
    return tuple(item for item in ordered(items) if item.kind != kind)


def keys(items: Iterable[InboxItem]) -> frozenset[str]:
    """Every key in this list - what a reader's "seen" set is written from."""
    return frozenset(item.key for item in items)


def _rank(since: datetime | None) -> tuple[int, float]:
    """Sortable position for a moment that may not exist.

    A tuple rather than a sentinel date. Comparing against a fixed far
    future would work until somebody scheduled something past it, and this
    cannot be wrong: the first element decides known before unknown, the
    second orders the known ones among themselves.
    """
    if since is None:
        return (1, 0.0)
    return (0, since.timestamp())


__all__ = [
    "ANSWERABLE",
    "LEVELS",
    "InboxItem",
    "ItemKind",
    "Level",
    "Subject",
    "answerable",
    "keys",
    "of_level",
    "ordered",
    "unseen",
    "without_kind",
]
