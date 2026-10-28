"""Keeping the waiting list to one answer about one group."""

from core.inbox import InboxItem


def quiet_waits(items: list[InboxItem]) -> list[InboxItem]:
    """The list without two answers about one group.

    "Too early" yields to a group burning money today and to a new group's
    watch; a burn line yields to the watch.
    """
    burning = _about(items, kind="burn")
    watched = _about(items, kind="watch")
    return [
        item
        for item in items
        if not (
            item.subject is not None
            and (
                (item.kind == "wait" and item.subject.ref.id in burning | watched)
                or (item.kind == "burn" and item.subject.ref.id in watched)
            )
        )
    ]


def _about(items: list[InboxItem], *, kind: str) -> set[str]:
    return {
        item.subject.ref.id
        for item in items
        if item.kind == kind and item.subject is not None
    }


__all__ = ["quiet_waits"]
