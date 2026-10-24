"""The order the list is read in, and what counts as new.

No database, no fixtures and no login: the whole point of the ordering
living in ``core`` is that these questions can be answered without any of
them. Everything here is about *arrangement* - which of two things a reader
meets first, which of them the bell counts, which of them the navigation
counts - because that is the part four surfaces must not disagree about.
"""

from datetime import UTC, datetime

from core.inbox import InboxItem, answerable, keys, ordered, unseen

MORNING = datetime(2026, 9, 1, 8, 0, tzinfo=UTC)
NOON = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
EVENING = datetime(2026, 9, 1, 20, 0, tzinfo=UTC)


def item(
    key: str,
    level: str = "decision",
    since: datetime | None = None,
) -> InboxItem:
    """One item, named by its key. Everything else here is scenery."""
    return InboxItem(
        key=key,
        kind="suggestion",
        level=level,  # type: ignore[arg-type]
        title=key,
        body="",
        since=since,
    )


def test_the_urgent_ones_come_before_the_questions() -> None:
    ranked = ordered(
        [
            item("news", level="news", since=MORNING),
            item("decision", level="decision", since=MORNING),
            item("urgent", level="urgent", since=MORNING),
        ]
    )

    assert [row.key for row in ranked] == ["urgent", "decision", "news"]


def test_inside_a_level_the_one_that_has_waited_longest_is_first() -> None:
    """A proposal expires. The oldest is the one that stops being answerable."""
    ranked = ordered(
        [
            item("newest", since=EVENING),
            item("oldest", since=MORNING),
            item("middle", since=NOON),
        ]
    )

    assert [row.key for row in ranked] == ["oldest", "middle", "newest"]


def test_an_item_with_no_date_sorts_last_in_its_level() -> None:
    """A provider's verdict arrives undated. It must not be sorted as ancient."""
    ranked = ordered([item("undated"), item("dated", since=EVENING)])

    assert [row.key for row in ranked] == ["dated", "undated"]


def test_a_level_still_beats_a_missing_date() -> None:
    """Undated does not mean unimportant: the level decides first."""
    ranked = ordered(
        [
            item("dated-question", level="decision", since=MORNING),
            item("undated-emergency", level="urgent"),
        ]
    )

    assert [row.key for row in ranked] == ["undated-emergency", "dated-question"]


def test_seen_is_by_key_so_a_rewritten_row_is_not_new_again() -> None:
    """The refusal whose sentence has not changed keeps its key and stays read."""
    already = item("refusal:abc123")
    fresh = item("refusal:def456")

    left = unseen([already, fresh], seen=frozenset({already.key}))

    assert [row.key for row in left] == [fresh.key]


def test_nothing_seen_means_everything_is_new() -> None:
    rows = [item("one", since=MORNING), item("two", since=NOON)]

    assert unseen(rows, seen=frozenset()) == ordered(rows)


def test_the_bell_keeps_the_screen_order() -> None:
    """One arrangement, two readers. A different order would be a second design."""
    rows = [
        item("quiet", level="news", since=MORNING),
        item("loud", level="urgent", since=EVENING),
    ]

    assert [row.key for row in unseen(rows, seen=frozenset())] == ["loud", "quiet"]


def test_only_the_questions_are_counted_by_the_navigation() -> None:
    """News is worth knowing and is not an unanswered question."""
    rows = [
        item("urgent", level="urgent"),
        item("decision", level="decision"),
        item("news", level="news"),
    ]

    assert [row.key for row in answerable(rows)] == ["urgent", "decision"]


def test_the_two_counts_answer_different_questions() -> None:
    """Read does not mean answered - the bell empties and the badge does not."""
    rows = [item("waiting", level="decision", since=MORNING)]
    seen = keys(rows)

    assert unseen(rows, seen=seen) == ()
    assert len(answerable(rows)) == 1


def test_keys_are_what_a_reader_has_seen() -> None:
    rows = [item("one"), item("two")]

    assert keys(rows) == frozenset({"one", "two"})


def test_an_empty_cabinet_is_an_empty_list() -> None:
    assert ordered([]) == ()
    assert unseen([], seen=frozenset()) == ()
    assert answerable([]) == ()
    assert keys([]) == frozenset()
