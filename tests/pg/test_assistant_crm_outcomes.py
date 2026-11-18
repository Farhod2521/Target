"""The assistant reads what the CRM did with each campaign's leads: sold,
refused, Sifatsiz - so «sales are low» gets numbers, not «the platform
cannot see sales»."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.assistant.selectors.crm_outcomes import crm_outcomes
from app.modules.chat.selectors.scope import asked_scopes
from tests.pg.test_crm_quality_counts import _board


def test_each_campaign_says_what_its_leads_became(
    client: TestClient, db: Session
) -> None:
    owner = _board(client, db)
    scope, _counted = asked_scopes(db, owner=owner)
    text = crm_outcomes(db, owner=owner, scope=scope, days=7, now=utcnow())
    assert "## CRM outcomes of leads that arrived" in text
    line = next(row for row in text.splitlines() if row.startswith("- «"))
    assert "leads 3" in line
    assert "Sotildi 1" in line and "Sifatsiz lid 1" in line and "Jarayonda 1" in line
    assert "150" in line


def test_no_crm_leads_says_sales_are_not_known_here(
    client: TestClient, db: Session
) -> None:
    from tests.pg.test_crm_http import _owner

    owner = _owner(db)
    scope, _counted = asked_scopes(db, owner=owner)
    text = crm_outcomes(db, owner=owner, scope=scope, days=7, now=utcnow())
    assert "no lead of this window is in the CRM" in text
