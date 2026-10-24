"""Meta's consent handshake as ``ConnectPort``."""

from typing import Any

import pytest
from adskit import AuthFailed, ConnectPort, GrantDTO, PortNotAvailable, Unavailable
from metaads import adapter
from metaads.adapter import MetaConnect, bundle
from metaads.connection_rows import AccessTokenDTO, TokenInfoDTO
from metaads.errors import MetaAuthError


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    """The three Graph calls, answered and recorded in order."""
    seen: list[tuple[str, dict[str, Any]]] = []

    def exchange_code(**kwargs: Any) -> AccessTokenDTO:
        seen.append(("exchange", kwargs))
        return AccessTokenDTO(access_token="short", expires_in=3600)

    def exchange_for_long_lived(**kwargs: Any) -> AccessTokenDTO:
        seen.append(("extend", kwargs))
        return AccessTokenDTO(access_token="long", expires_in=5_184_000)

    def inspect_token(**kwargs: Any) -> TokenInfoDTO:
        seen.append(("inspect", kwargs))
        return TokenInfoDTO(user_id="u1", is_valid=True, scopes=("ads_management",))

    monkeypatch.setattr(adapter, "exchange_code", exchange_code)
    monkeypatch.setattr(adapter, "exchange_for_long_lived", exchange_for_long_lived)
    monkeypatch.setattr(adapter, "inspect_token", inspect_token)
    return seen


def test_the_bundle_carries_a_real_connect_port() -> None:
    port = bundle(app_id="1", app_secret="s").connect

    assert isinstance(port, ConnectPort)
    assert isinstance(port, MetaConnect)


def test_the_dialog_url_carries_the_app_id_from_the_constructor() -> None:
    url = MetaConnect(app_id="4242", app_secret="s").authorize_url(
        redirect_uri="https://e.com/cb/", state="st"
    )

    assert "client_id=4242" in url
    assert "state=st" in url


def test_complete_stretches_the_token_and_names_who_approved(
    calls: list[tuple[str, dict[str, Any]]],
) -> None:
    grant = MetaConnect(app_id="1", app_secret="s").complete(
        redirect_uri="https://e.com/cb/", code="c"
    )

    assert grant == GrantDTO(
        token="long",
        expires_in=5_184_000,
        scopes=("ads_management",),
        external_user_id="u1",
    )
    # Skipping the second call gives a connection that dies overnight, and
    # the third must ask about the long token, not the short one.
    assert [name for name, _ in calls] == ["exchange", "extend", "inspect"]
    assert calls[1][1]["token"] == "short"
    assert calls[2][1]["token"] == "long"
    assert calls[0][1]["redirect_uri"] == "https://e.com/cb/"


def test_a_meta_refusal_leaves_as_the_domains_own(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refuse(**_: Any) -> AccessTokenDTO:
        raise MetaAuthError("expired code", code=100)

    monkeypatch.setattr(adapter, "exchange_code", refuse)

    with pytest.raises(AuthFailed):
        MetaConnect(app_id="1", app_secret="s").complete(
            redirect_uri="https://e.com/cb/", code="c"
        )


def test_the_token_stays_out_of_the_grants_repr() -> None:
    grant = GrantDTO(token="secret-token", external_user_id="u1")

    assert "secret-token" not in repr(grant)


def test_a_half_built_provider_refuses_to_connect_by_name() -> None:
    port = Unavailable(provider="google", port="connect")

    assert isinstance(port, ConnectPort)
    with pytest.raises(PortNotAvailable, match="connect"):
        port.complete(redirect_uri="https://e.com/cb/", code="c")
