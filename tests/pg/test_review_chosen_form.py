"""The form chosen on the plan stays the proposal's form on a page with many forms."""

from fastapi.testclient import TestClient
from metaads import PROVIDER
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.ads.summaries import form_summary
from app.modules.integrations.models import PageAccount
from app.modules.leads.constants import PICKER_FORMS
from app.modules.leads.models import LeadForm
from app.modules.leads.selectors.reads import usable_forms
from tests.pg.test_launch_api import _ready


def test_a_chosen_form_past_the_fold_is_still_among_the_review_options(
    client: TestClient, db: Session
) -> None:
    _, user = _ready(client, db)
    page = db.scalar(select(PageAccount).where(PageAccount.owner_id == user.id))
    assert page is not None
    for number in range(PICKER_FORMS + 5):
        db.add(
            LeadForm(
                owner_id=user.id,
                provider=PROVIDER,
                external_id=f"f_{number}",
                page_id=page.id,
                name=f"Forma {number}",
                questions_raw=[{"key": "phone", "type": "PHONE"}],
            )
        )
    db.commit()
    folded = usable_forms(db, owner=user, page=page)
    shown = {option.external_id for option in folded.options}
    assert len(shown) == PICKER_FORMS
    chosen = next(
        f"f_{number}"
        for number in range(PICKER_FORMS + 5)
        if f"f_{number}" not in shown
    )

    kept = usable_forms(db, owner=user, page=page, keep=chosen)

    assert chosen in {option.external_id for option in kept.options}
    assert kept.hidden + len(kept.options) == folded.hidden + len(folded.options)
    card = form_summary(
        options=kept.options, chosen_form=chosen, questions=[], chosen_kinds=[]
    )
    assert not card.is_new
    assert card.name == f"Forma {chosen.removeprefix('f_')}"


def test_the_newest_form_comes_first(client: TestClient, db: Session) -> None:
    from datetime import UTC, datetime, timedelta

    _, user = _ready(client, db)
    page = db.scalar(select(PageAccount).where(PageAccount.owner_id == user.id))
    assert page is not None
    start = datetime(2026, 1, 1, tzinfo=UTC)
    for number, days in (("old", 0), ("newest", 30), ("middle", 10), ("unknown", None)):
        db.add(
            LeadForm(
                owner_id=user.id,
                provider=PROVIDER,
                external_id=f"f_{number}",
                page_id=page.id,
                name=f"Forma {number}",
                questions_raw=[{"key": "phone", "type": "PHONE"}],
                created_time=None if days is None else start + timedelta(days=days),
            )
        )
    db.commit()

    offered = usable_forms(db, owner=user, page=page, limit=None)

    assert [option.external_id for option in offered.options] == [
        "f_newest",
        "f_middle",
        "f_old",
        "f_unknown",
    ]
