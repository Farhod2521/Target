"""The reader's language reaches the endpoint, sync or async."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.modules.businesses.models import BusinessCategory
from tests.pg.conftest import sign_up


def _labels(client: TestClient, auth: dict[str, str]) -> list[str]:
    body = client.get("/api/v1/business/choices", headers=auth).json()
    return [row["label"] for row in body["categories"]]


def test_each_reader_reads_their_own_language(client: TestClient, db: Session) -> None:
    db.add(
        BusinessCategory(
            key="shop",
            label_uz="Do'kon",
            label_ru="Магазин",
            label_en="Shop",
            preset_key="restaurant",
        )
    )
    db.commit()
    auth = sign_up(client)

    for language, label in (("uz", "Do'kon"), ("en", "Shop"), ("ru", "Магазин")):
        changed = client.put(
            "/api/v1/account/language", json={"language": language}, headers=auth
        )
        assert changed.status_code == 200, changed.text
        assert _labels(client, auth) == [label]
