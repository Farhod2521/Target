"""One line per key when the same list is gathered page by page.

A screen draws the page its reader is on; a phone has no header, so
everything it sends is gathered once per page of the subscription. That
turns two questions into one place: which lines are the same line seen
twice, and which of them may be labelled with a page at all.
"""

from collections.abc import Iterable

from core.inbox.items import InboxItem, ordered


def by_page(rows: Iterable[tuple[InboxItem, str]]) -> list[tuple[InboxItem, str]]:
    """The same lines once each, worst first, and no page guessed at.

    What a reader walking the pages one at a time gathers - the phone does,
    because it has no header saying which page it is looking at. Two things
    go wrong without this. A line that is true on several pages arrives
    several times, and only the first of them is ever sent, because the
    journal claims a subject once; and that one carries whichever page's
    name happened to come last.

    So a key that turned up under more than one page is **said once, under
    no name**. An account's own fact is true on every page paying from it,
    and a group nothing could place belongs to all of them and to none -
    naming one would send somebody to the wrong page to look for it.

    A key that turned up under one page keeps that page's name. Which is
    why a line about one page's own figures needs a key of its own: two
    pages with the same count would otherwise read as one line about
    neither.
    """
    pages: dict[str, str] = {}
    items: dict[str, InboxItem] = {}
    for item, page in rows:
        if item.key in items:
            if pages[item.key] != page:
                pages[item.key] = ""
            continue
        items[item.key] = item
        pages[item.key] = page
    return [(item, pages[item.key]) for item in ordered(items.values())]


__all__ = ["by_page"]
