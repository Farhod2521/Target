"""Who sees which board, without a database."""

import importlib.util
from pathlib import Path

from app.modules.backoffice.constants import Role
from app.modules.boards.access import access_of
from app.modules.boards.constants import (
    LEAD_ONLY_COLUMNS,
    SEED_COLUMNS,
    Board,
    SalesColumn,
)


def _roles(*roles: Role) -> frozenset[str]:
    return frozenset(str(role) for role in roles)


def test_a_sales_manager_sees_only_sales_and_leads_nothing() -> None:
    access = access_of(roles=_roles(Role.SALES), is_superuser=False)

    assert access.boards == (Board.SALES,)
    assert not access.leads and not access.full


def test_the_sales_lead_leads_sales_and_renewal_and_still_not_support() -> None:
    access = access_of(roles=_roles(Role.SALES_LEAD), is_superuser=False)

    assert access.boards == (Board.SALES, Board.RENEWAL)
    assert access.leads == {Board.SALES, Board.RENEWAL}


def test_a_renewal_manager_sees_only_the_renewal_board() -> None:
    access = access_of(roles=_roles(Role.RENEWAL), is_superuser=False)

    assert access.boards == (Board.RENEWAL,)
    assert not access.leads and not access.full


def test_support_sees_only_support() -> None:
    access = access_of(roles=_roles(Role.SUPPORT), is_superuser=False)

    assert access.boards == (Board.SUPPORT,)
    assert not access.leads


def test_the_owner_role_and_the_superuser_see_and_lead_every_board() -> None:
    for access in (
        access_of(roles=_roles(Role.OWNER), is_superuser=False),
        access_of(roles=frozenset(), is_superuser=True),
    ):
        assert access.boards == (Board.SALES, Board.SUPPORT, Board.RENEWAL)
        assert access.leads == {Board.SALES, Board.SUPPORT, Board.RENEWAL}
        assert access.full


def test_finance_and_engineers_have_no_board() -> None:
    access = access_of(roles=_roles(Role.FINANCE, Role.ENGINEER), is_superuser=False)

    assert access.boards == ()


def test_the_lead_only_columns_are_sales_columns() -> None:
    seeded = {(seed.board, seed.code) for seed in SEED_COLUMNS}

    assert seeded >= LEAD_ONLY_COLUMNS
    assert {board for board, _code in LEAD_ONLY_COLUMNS} == {Board.SALES}
    assert (Board.SALES, str(SalesColumn.UNWORKED)) in LEAD_ONLY_COLUMNS


def test_the_migration_seeds_the_same_columns_as_the_code() -> None:
    path = next(Path("migrations/versions").glob("*_0038_office_boards.py"))
    spec = importlib.util.spec_from_file_location("m0038", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    # 0042 shows the offer columns the first seed kept hidden.
    later = next(Path("migrations/versions").glob("*_0042_sales_offer.py"))
    spec = importlib.util.spec_from_file_location("m0042", later)
    assert spec is not None and spec.loader is not None
    offer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(offer)
    seeded = [
        (board, code, name, kind, final, shown or code in offer.OFFER_COLUMNS)
        for board, code, name, kind, final, shown in module.COLUMNS
    ]
    # 0045 puts three more columns in, each right after a neighbour.
    newest = next(Path("migrations/versions").glob("*_0045_board_deadlines.py"))
    spec = importlib.util.spec_from_file_location("m0045", newest)
    assert spec is not None and spec.loader is not None
    deadlines = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(deadlines)
    for board, code, name, kind, after in deadlines.NEW_COLUMNS:
        at = next(
            i for i, row in enumerate(seeded) if row[0] == board and row[1] == after
        )
        seeded.insert(at + 1, (board, code, name, kind, False, True))
    # 0052 puts three more on Support, and Hal qilindi becomes automatic.
    last = next(Path("migrations/versions").glob("*_0052_support_columns.py"))
    spec = importlib.util.spec_from_file_location("m0052", last)
    assert spec is not None and spec.loader is not None
    support = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(support)
    for code, name, kind, final, after, _back in support.NEW_COLUMNS:
        at = next(
            i
            for i, row in enumerate(seeded)
            if row[0] == support.BOARD and row[1] == after
        )
        seeded.insert(at + 1, (support.BOARD, code, name, kind, final, True))
    seeded = [
        (
            board,
            code,
            name,
            "auto" if (board, code) == ("support", "resolved") else kind,
            final,
            # 0053 hides «Chegirmasiz»: a card whose discount ran out closes.
            shown and (board, code) != ("sales", "no_discount"),
        )
        for board, code, name, kind, final, shown in seeded
    ]
    assert seeded == [
        (str(s.board), s.code, s.name, str(s.kind), s.is_final, s.is_visible)
        for s in SEED_COLUMNS
        # The renewal board's columns are seeded by its first read.
        if s.board != Board.RENEWAL
    ]


def test_the_migration_numbers_columns_from_one_within_each_board() -> None:
    path = next(Path("migrations/versions").glob("*_0038_office_boards.py"))
    spec = importlib.util.spec_from_file_location("m0038", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    numbered = [
        (seed.compile().params["board"], seed.compile().params["position"])
        for seed in module._seeds()
    ]
    for board in ("sales", "support"):
        own = [position for name, position in numbered if name == board]
        assert own == list(range(1, len(own) + 1))
