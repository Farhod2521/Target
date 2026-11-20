"""Every step a card takes across the board is written as it is taken, and
the steps of older cards are put together from their history."""

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.modules.crm.models import CrmCard, CrmStageMove
from app.modules.crm.moves import rebuild
from tests.pg.test_crm_http import CRM, _auth, _owner, _running


def _steps(db: Session, card_id: str) -> list[tuple[str, str]]:
    db.expire_all()
    return [
        (row.from_kind, row.to_kind)
        for row in db.scalars(
            select(CrmStageMove)
            .where(CrmStageMove.card_id == card_id)
            .order_by(CrmStageMove.at, CrmStageMove.created_at)
        )
    ]


def _stage(board: dict[str, Any], kind: str) -> str:
    return next(
        c["stage"]["id"] for c in board["columns"] if c["stage"]["kind"] == kind
    )


def _post(client: TestClient, head: dict[str, str], path: str, **body: Any) -> None:
    answer = client.post(f"{CRM}{path}", headers=head, json=body)
    assert answer.is_success, answer.text


def test_a_card_laid_on_the_board_has_its_arriving_step(
    client: TestClient, db: Session
) -> None:
    head = _auth(_owner(db))
    board = _running(client, head)

    cards = [c["id"] for c in board["columns"][0]["cards"]]

    assert len(cards) == 3
    assert [_steps(db, card) for card in cards] == [[("", "new")]] * 3


def test_each_way_of_changing_column_writes_one_step(
    client: TestClient, db: Session
) -> None:
    head = _auth(_owner(db))
    board = _running(client, head)
    taken, sold, refused = (c["id"] for c in board["columns"][0]["cards"])
    reason = client.get(f"{CRM}/cards/{refused}", headers=head).json()["reasons"][0]

    _post(client, head, f"/cards/{taken}/take")
    _post(client, head, f"/cards/{taken}/note", text="gaplashdik")
    _post(client, head, f"/cards/{sold}/move", to=_stage(board, "open"))
    _post(client, head, f"/cards/{sold}/win", amount="100")
    _post(client, head, f"/cards/{refused}/lose", reason=reason["id"])
    _post(client, head, f"/cards/{refused}/move", to=_stage(board, "junk"))
    _post(client, head, f"/cards/{refused}/move", to=_stage(board, "open"))

    # A note changes no column and writes no step.
    assert _steps(db, taken) == [("", "new"), ("new", "open")]
    assert _steps(db, sold) == [("", "new"), ("new", "open"), ("open", "won")]
    assert _steps(db, refused) == [
        ("", "new"),
        ("new", "lost"),
        ("lost", "junk"),
        ("junk", "open"),
    ]
    assert not db.scalar(select(CrmStageMove).where(CrmStageMove.rebuilt))


def test_a_deleted_column_writes_the_step_of_every_card_it_held(
    client: TestClient, db: Session
) -> None:
    head = _auth(_owner(db))
    board = _running(client, head)
    added = client.post(
        f"{CRM}/settings/stages", headers=head, json={"name": "Uchrashuv", "color": ""}
    )
    assert added.is_success, added.text
    extra = added.json()["id"]
    one, two, stays = (c["id"] for c in board["columns"][0]["cards"])
    _post(client, head, f"/cards/{one}/move", to=extra)
    _post(client, head, f"/cards/{two}/move", to=extra)

    gone = client.delete(f"{CRM}/settings/stages/{extra}", headers=head)

    assert gone.is_success, gone.text
    assert _steps(db, one) == [("", "new"), ("new", "open"), ("open", "new")]
    assert _steps(db, two) == [("", "new"), ("new", "open"), ("open", "new")]
    assert _steps(db, stays) == [("", "new")]
    # The column is gone; the step still says which one the cards left.
    left = db.scalar(
        select(CrmStageMove.from_stage_id).where(
            CrmStageMove.card_id == one,
            CrmStageMove.to_kind == "new",
            CrmStageMove.from_kind == "open",
        )
    )
    assert str(left) == extra


def test_older_cards_get_their_steps_from_their_history(
    client: TestClient, db: Session
) -> None:
    head = _auth(_owner(db))
    board = _running(client, head)
    taken, sold, refused = (c["id"] for c in board["columns"][0]["cards"])
    reason = client.get(f"{CRM}/cards/{refused}", headers=head).json()["reasons"][0]
    _post(client, head, f"/cards/{taken}/take")
    _post(client, head, f"/cards/{sold}/move", to=_stage(board, "open"))
    _post(client, head, f"/cards/{sold}/win", amount="100")
    _post(client, head, f"/cards/{refused}/lose", reason=reason["id"])
    _post(client, head, f"/cards/{refused}/move", to=_stage(board, "junk"))
    _post(client, head, f"/cards/{refused}/move", to=_stage(board, "open"))
    measured = {card: _steps(db, card) for card in (taken, sold, refused)}
    db.execute(delete(CrmStageMove))
    db.commit()

    assert rebuild(db, apply=False) == (3, 9)
    assert db.scalar(select(CrmStageMove)) is None
    assert rebuild(db, apply=True) == (3, 9)

    assert {card: _steps(db, card) for card in measured} == measured
    assert all(db.scalars(select(CrmStageMove.rebuilt)))
    # A card that has its steps is never given them twice.
    assert rebuild(db, apply=True) == (0, 0)


def test_a_history_that_does_not_lead_to_the_cards_column_is_closed_by_one_step(
    client: TestClient, db: Session
) -> None:
    head = _auth(_owner(db))
    board = _running(client, head)
    card_id = board["columns"][0]["cards"][0]["id"]
    _post(client, head, f"/cards/{card_id}/move", to=_stage(board, "open"))
    # The column is renamed after the move: the history line names one the
    # board no longer has.
    renamed = client.put(
        f"{CRM}/settings/stages/{_stage(board, 'open')}",
        headers=head,
        json={"name": "Boshqa nom", "color": ""},
    )
    assert renamed.is_success, renamed.text
    db.execute(delete(CrmStageMove))
    db.commit()

    rebuild(db, apply=True)

    assert _steps(db, card_id) == [("", "new"), ("new", "open")]
    card = db.get(CrmCard, card_id)
    last = db.scalars(
        select(CrmStageMove)
        .where(CrmStageMove.card_id == card_id)
        .order_by(CrmStageMove.at.desc())
    ).first()
    assert card is not None and last is not None
    assert last.to_stage_id == card.stage_id
