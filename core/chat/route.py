"""Which parts of an account a question actually needs.

A question carrying the whole digest - the business, the window's totals,
ten campaigns, ten audiences and five proposals - is about seven hundred
and sixty tokens, measured, on top of a prompt of twelve hundred, and most
of it answers nothing. "Nega murojaat qimmatlashdi?" needs the totals and
the campaigns under them; it does not need the names of ten audiences, and
paying for them on every question, every day, for every account is what
this avoids.

**Rules, not a model.** The obvious alternative is to ask Claude what the
question is about - and that is a second call, with its own latency and its
own bill, to save part of one. A table of stems in three languages decides
it in microseconds and is readable by somebody who does not trust it. The
table is :mod:`core.chat.stems`, where every entry names why it is the
length it is.

**A question inherits the last one's subject.** "Nega bu qimmat?" is about
whatever was being discussed a moment ago, and a context that quietly
dropped the campaigns half way through a conversation would make the
assistant contradict what it had just said. So the previous question is
matched too, and only the previous one: a subject nobody has mentioned for
two turns has been left behind.

Django-free, like everything in ``core``: this is a decision about words,
and it is tested by handing it words.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final

from core.chat.stems import SECTIONS, WORDS, Section

# The apostrophe, in the four shapes a keyboard and a copy-paste produce.
# Uzbek carries one in a great many words - "o'zgartirish", "so'rov" - and a
# stem written with the wrong one matches nothing at all.
# Written as escapes rather than as the characters themselves: four
# glyphs that differ by a hair are four glyphs nobody can tell apart in
# a diff, and a reviewer has to be able to see which is which.
APOSTROPHES: Final = str.maketrans(dict.fromkeys("\u2018\u2019\u02bb\u02bc", "'"))


@dataclass(frozen=True, slots=True)
class Route:
    """What this question is about, and what it is therefore not sent.

    Both halves matter. ``wants`` decides what is assembled; ``omitted`` is
    written into the context itself, because a model that is handed no
    campaigns and is not told why will conclude the account has none - and
    "sizda hech qanday reklama yo'q" is a worse answer than a long one.
    """

    wants: frozenset[Section]
    omitted: tuple[Section, ...]


def route(*, question: str, previous: Iterable[str] = ()) -> Route:
    """What one question needs, given the one before it.

    ``previous`` is the reader's own earlier questions, newest last; only
    the last is read. Anything the model said is deliberately not matched -
    an answer that happened to mention audiences would pull the audiences
    into every following question, which is the drift this is meant to
    stop.

    Nothing matched is the ordinary case for "salom" and for "nima
    qilay?", and it produces the base: who is asking and what the account
    did over the window. The prompt's own rule covers the rest - name the
    screen, do not guess.
    """
    text = _fold(question)
    last = list(previous)[-1:]
    wants = _matched(text) | _matched(_fold(last[0]) if last else "")
    return Route(
        wants=frozenset(wants),
        omitted=tuple(name for name in SECTIONS if name not in wants),
    )


def _matched(text: str) -> set[Section]:
    if not text:
        return set()
    return {
        name for name, stems in WORDS.items() if any(stem in text for stem in stems)
    }


def _fold(text: str) -> str:
    """One casing, one apostrophe. Everything else is left as it arrived."""
    return text.casefold().translate(APOSTROPHES)


__all__ = ["SECTIONS", "WORDS", "Route", "Section", "route"]
