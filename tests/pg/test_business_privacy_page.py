"""The policy a lead form links to answers for a real business."""

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.businesses.models import Business
from tests.pg.conftest import sign_up


def _business(client: TestClient, db: Session, **fields: str) -> Business:
    sign_up(client)
    user = db.scalars(select(User)).one()
    business = Business(
        user_id=user.id,
        name="Lebem Mebel",
        timezone="Asia/Tashkent",
        country_code="UZ",
        **fields,
    )
    db.add(business)
    db.commit()
    return business


def test_the_page_names_the_business_and_how_to_reach_it(
    client: TestClient, db: Session
) -> None:
    business = _business(
        client,
        db,
        city="Toshkent",
        contact_phone="+998901234567",
        website="https://lebem.uz",
    )

    page = client.get(f"/api/v1/public/privacy/{business.id}")

    assert page.status_code == 200, page.text
    assert page.json()["business"] == {
        "id": str(business.id),
        "name": "Lebem Mebel",
        "city": "Toshkent",
        "contact_phone": "+998901234567",
        "website": "https://lebem.uz",
    }


def test_what_is_not_a_web_address_is_not_given_as_a_link(
    client: TestClient, db: Session
) -> None:
    business = _business(client, db, website="javascript:alert(1)")

    page = client.get(f"/api/v1/public/privacy/{business.id}")

    assert page.json()["business"]["website"] == ""
    assert page.json()["business"]["city"] == ""


def test_an_unknown_business_is_not_a_page(client: TestClient) -> None:
    assert client.get(f"/api/v1/public/privacy/{uuid.uuid4()}").status_code == 404


def test_the_business_page_says_who_it_is_and_where_to_find_it(
    client: TestClient, db: Session
) -> None:
    from app.modules.businesses.selectors import business_for
    from tests.pg.test_launch_api import _ready

    _auth, user = _ready(client, db)
    business = business_for(db, user)
    assert business is not None and business.page is not None
    business.city = "Toshkent"
    business.page.instagram_username = "@lebem.mebel"
    db.commit()

    answer = client.get(f"/api/v1/public/business/{business.id}")

    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert (body["name"], body["city"]) == (business.name, "Toshkent")
    assert body["website"] == business.website.strip()
    assert body["instagram_url"] == "https://www.instagram.com/lebem.mebel"
    assert body["facebook_url"] == (
        f"https://www.facebook.com/{business.page.external_id}"
    )


def test_a_business_with_no_page_still_has_its_own(
    client: TestClient, db: Session
) -> None:
    business = _business(client, db)

    answer = client.get(f"/api/v1/public/business/{business.id}")

    assert answer.json()["instagram_url"] == ""
    assert answer.json()["facebook_url"] == ""
    assert client.get(f"/api/v1/public/business/{uuid.uuid4()}").status_code == 404
