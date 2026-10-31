"""What one line of the center offers: the agent's word, the network, leaving it."""

from adskit import ExternalRef

from core.inbox import InboxItem, Subject, advised, leavable, left_key


def _item(kind: str = "figures", level: str = "news", **rest: object) -> InboxItem:
    return InboxItem(key="k", kind=kind, level=level, title="t", body="b", **rest)  # type: ignore[arg-type]


def test_a_kind_with_a_known_answer_is_given_the_agents_word() -> None:
    found = advised(_item(kind="connection", level="urgent"))

    assert "qayta ulang" in found.advice


def test_a_line_that_already_has_a_word_keeps_it() -> None:
    assert advised(_item(advice="O'zi")).advice == "O'zi"


def test_a_line_names_the_network_of_what_it_is_about() -> None:
    subject = Subject(ref=ExternalRef(provider="google", level="campaign", id="1"))

    assert advised(_item(subject=subject)).network == "google"
    assert advised(_item(kind="meta_hold", level="urgent")).network == "meta"
    assert advised(_item(kind="setup", level="decision")).network == ""


def test_only_a_line_that_can_wait_can_be_left() -> None:
    assert leavable(_item(level="news")) is True
    assert leavable(_item(level="decision")) is True
    assert leavable(_item(level="urgent")) is False
    assert leavable(_item(kind="suggestion", level="decision")) is False


def test_a_left_key_fits_the_seen_table_whatever_the_line_is_called() -> None:
    assert len(left_key("x" * 500)) <= 128
    assert left_key("a") != left_key("b")
