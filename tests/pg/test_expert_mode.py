"""Expert mode is the owner's own choice, kept on the account."""

from fastapi.testclient import TestClient

from tests.pg.conftest import sign_up


def test_expert_mode_is_off_until_switched_on_and_stays(client: TestClient) -> None:
    auth = sign_up(client)

    assert client.get("/api/v1/account", headers=auth).json()["expert_mode"] is False

    on = client.put("/api/v1/account/expert-mode", json={"on": True}, headers=auth)
    assert on.status_code == 200, on.text
    assert on.json()["expert_mode"] is True
    assert client.get("/api/v1/account", headers=auth).json()["expert_mode"] is True

    off = client.put("/api/v1/account/expert-mode", json={"on": False}, headers=auth)
    assert off.json()["expert_mode"] is False


def test_expert_mode_wants_a_yes_or_no(client: TestClient) -> None:
    auth = sign_up(client)

    refused = client.put("/api/v1/account/expert-mode", json={}, headers=auth)

    assert refused.status_code == 422
