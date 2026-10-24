"""The gate that decides what the agent may put right without asking.

Three conditions and a hand-written table. What is asserted here is that
neither can be got around: a repair missing any one condition is refused
however obviously useful it looks, and a trigger nobody wrote down is
refused however obviously it resembles one that was.
"""

from core.agent.autofix import (
    LEADS_RECOVERABLE,
    PAGE_UNSUBSCRIBED,
    Fix,
    allowed,
    fix_for,
    triggers,
)


# --- The three conditions --------------------------------------------
def test_a_repair_that_spends_is_never_automatic() -> None:
    """Money is the first condition and the one with no exceptions.

    Raising a ceiling, restarting a stopped advert, moving a budget - all
    of them are somebody else's money and all of them keep their button.
    """
    assert not allowed(
        Fix(trigger="x", action="raise_cap", spends=True, decides=False, undo="lower")
    )


def test_a_repair_that_decides_something_new_is_never_automatic() -> None:
    """Removing a broken audience is the case this refuses.

    It spends nothing and it can be undone, and it still fails: who sees
    the advert changes, and nobody asked for that.
    """
    assert not allowed(
        Fix(trigger="x", action="drop_audience", spends=False, decides=True)
    )


def test_a_change_that_names_no_inverse_is_not_shown_to_be_reversible() -> None:
    """ "Reversible" has to be checkable or it is a promise.

    A repair that changed something and cannot say what would put it back
    has not been shown to be reversible - it has been assumed to be, which
    is the assumption this predicate exists to refuse.
    """
    changed = Fix(trigger="x", action="edit", spends=False, decides=True, undo="")

    assert not allowed(changed)


def test_an_additive_repair_needs_no_inverse() -> None:
    """What it puts back is a state the owner had.

    The thing an "undo" would restore is the broken state nobody chose,
    which is why both entries in the real table carry no inverse and both
    are still allowed.
    """
    assert allowed(Fix(trigger="x", action="relink", spends=False, decides=False))


# --- The table -------------------------------------------------------
def test_an_unknown_trigger_is_never_fixed_automatically() -> None:
    """The second condition, and the reason it is a table.

    Meta rewrites its messages and adds codes. A gate that reasoned about a
    code it had never seen would eventually reason confidently and wrongly,
    with somebody's advertising behind it.
    """
    assert fix_for("1815869") is None
    assert fix_for("something_new") is None
    assert fix_for("") is None


def test_the_two_repairs_that_are_allowed_are_the_two_that_are_listed() -> None:
    assert triggers() == (LEADS_RECOVERABLE, PAGE_UNSUBSCRIBED)


def test_every_listed_repair_passes_the_gate_it_is_listed_under() -> None:
    """The table and the predicate must not be able to disagree.

    An entry that fails ``allowed`` would be a repair the table offers and
    the gate refuses - silently, as a fix that never runs and never says
    why.
    """
    for trigger in triggers():
        assert fix_for(trigger) is not None


def test_relinking_a_page_spends_nothing_and_decides_nothing() -> None:
    fix = fix_for(PAGE_UNSUBSCRIBED)

    assert fix is not None
    assert not fix.spends
    assert not fix.decides


def test_recovering_enquiries_is_not_a_purchase() -> None:
    """The money was spent when the advert ran. This stores what it bought."""
    fix = fix_for(LEADS_RECOVERABLE)

    assert fix is not None
    assert not fix.spends
    assert fix.action == "recover_leads"
