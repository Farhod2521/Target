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


def test_the_sales_lead_leads_sales_and_still_not_support() -> None:
    access = access_of(roles=_roles(Role.SALES_LEAD), is_superuser=False)

    assert access.boards == (Board.SALES,)
    assert access.leads == {Board.SALES}


def test_support_sees_only_support() -> None:
    access = access_of(roles=_roles(Role.SUPPORT), is_superuser=False)

    assert access.boards == (Board.SUPPORT,)
    assert not access.leads


def test_the_owner_role_and_the_superuser_see_and_lead_both() -> None:
    for access in (
        access_of(roles=_roles(Role.OWNER), is_superuser=False),
        access_of(roles=frozenset(), is_superuser=True),
    ):
        assert access.boards == (Board.SALES, Board.SUPPORT)
        assert access.leads == {Board.SALES, Board.SUPPORT}
        assert access.full


def test_finance_and_engineers_have_no_board() -> None:
    access = access_of(roles=_roles(Role.FINANCE, Role.ENGINEER), is_superuser=False)

    assert access.boards == ()


def test_the_lead_only_columns_are_sales_columns() -> None:
    sales = {seed.code for seed in SEED_COLUMNS if seed.board == Board.SALES}

    assert sales >= LEAD_ONLY_COLUMNS
    assert str(SalesColumn.UNWORKED) in LEAD_ONLY_COLUMNS


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
    assert seeded == [
        (str(s.board), s.code, s.name, str(s.kind), s.is_final, s.is_visible)
        for s in SEED_COLUMNS
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
