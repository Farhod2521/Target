"""One line per key when the same list is gathered page by page."""

from collections.abc import Iterable

from core.inbox.items import InboxItem, ordered


def by_page(rows: Iterable[tuple[InboxItem, str]]) -> list[tuple[InboxItem, str]]:
    """The same lines once each, worst first, and no page guessed at."""
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
