"""Google's places as :meth:`adskit.AudiencePort.find_locations`.

The one audience question Google answers the way Meta does: a word in, the
places it may mean out, ranked. ``geoTargetConstants:suggest`` is not under
a customer - Google's geography is the same for everybody - so it needs a
token and nothing else.

Names come back in English. The owner types "Toshkent", which Google
matches against its Latin names; Uzbek is not one of Google's locales.

Everything else on the audience port is Meta's shape (interests, traits,
a reach estimate, a spec replaced whole) and refuses by name here: a Search
campaign is aimed with keywords and places, and both are written when the
campaign is created.
"""

from typing import Any, Final

import httpx
from adskit import PortNotAvailable
from adskit.dto import ActionResult, InterestDTO, LocationDTO, ReachDTO
from adskit.refs import ExternalRef, GeoKind, ProviderName, TraitKind

from googleadskit.campaigns import google_calls
from googleadskit.client import AdsClient

PROVIDER: Final = ProviderName("google")

# The locale Google names places in. Latin, which is what an Uzbek owner
# types; Google has no Uzbek.
_LOCALE: Final = "en"

# Google's target types in the domain's four words. A city-sized place takes
# a radius; nothing larger does.
_KINDS: Final[dict[str, GeoKind]] = {
    "City": "city",
    "Municipality": "city",
    "District": "city",
    "Neighborhood": "city",
    "Region": "region",
    "Province": "region",
    "State": "region",
    "Governorate": "region",
    "Country": "country",
}


class GoogleAudiences:
    """Places are real; the rest of the port is Meta's and refuses."""

    def __init__(self, *, http: httpx.Client | None = None) -> None:
        self._http = http

    def find_locations(
        self, *, query: str, country_code: str, token: str
    ) -> list[LocationDTO]:
        body: dict[str, Any] = {
            "locale": _LOCALE,
            "locationNames": {"names": [query]},
        }
        if country_code:
            body["countryCode"] = country_code.upper()
        with google_calls(), AdsClient(token=token, http=self._http) as client:
            answer = client.post("geoTargetConstants:suggest", body)
        return [
            _location(row.get("geoTargetConstant") or {})
            for row in answer.get("geoTargetConstantSuggestions") or []
            if (row.get("geoTargetConstant") or {}).get("status", "ENABLED")
            == "ENABLED"
        ]

    # --- Meta's half of the port ----------------------------------------

    def find_interests(self, *, names: list[str], token: str) -> list[InterestDTO]:
        raise PortNotAvailable(provider=PROVIDER, port="audiences.find_interests")

    def find_traits(
        self, *, kind: TraitKind, names: list[str], token: str
    ) -> list[InterestDTO]:
        raise PortNotAvailable(provider=PROVIDER, port="audiences.find_traits")

    def estimate_reach(
        self,
        *,
        account: ExternalRef,
        targeting: dict[str, Any],
        optimization_goal: str,
        token: str,
    ) -> ReachDTO:
        raise PortNotAvailable(provider=PROVIDER, port="audiences.estimate_reach")

    def apply(
        self,
        *,
        ref: ExternalRef,
        targeting: dict[str, Any],
        token: str,
        dry_run: bool = True,
    ) -> ActionResult:
        raise PortNotAvailable(provider=PROVIDER, port="audiences.apply")


def country_target(client: AdsClient, customer_id: str, country_code: str) -> str:
    """The geo target for a whole country, by its ISO code - or empty.

    A GAQL read rather than a name search: the code is exact and a name
    is not, and every account can read Google's geography.
    """
    code = country_code.upper()
    if len(code) != 2 or not code.isalpha():
        return ""
    query = (
        "SELECT geo_target_constant.resource_name FROM geo_target_constant "
        f"WHERE geo_target_constant.country_code = '{code}' "
        "AND geo_target_constant.target_type = 'Country' "
        "AND geo_target_constant.status = 'ENABLED'"
    )
    for row in client.search(customer_id, query):
        name = str((row.get("geoTargetConstant") or {}).get("resourceName") or "")
        if name:
            return name
    return ""


def _location(node: dict[str, Any]) -> LocationDTO:
    canonical = str(node.get("canonicalName") or "")
    name = str(node.get("name") or "")
    # "Tashkent,Tashkent,Uzbekistan": everything after the place itself is
    # what contains it.
    context = ", ".join(part for part in canonical.split(",")[1:] if part)
    kind = _KINDS.get(str(node.get("targetType") or ""), "other")
    return LocationDTO(
        ref=ExternalRef(
            provider=PROVIDER,
            level="location",
            id=str(node.get("resourceName") or ""),
        ),
        name=name,
        kind=kind,
        country_code=str(node.get("countryCode") or ""),
        context=context,
        supports_radius=kind == "city",
    )


__all__ = ["GoogleAudiences", "country_target"]
