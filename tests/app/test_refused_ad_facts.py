"""New words for a refused advert may keep a fact from any of its own fields.

The prompt lets the model copy a figure from the advert as it runs - its
text, headline or description - and the check after it has to accept the
same three, or a repair that kept the headline's price is thrown away.
"""

from types import SimpleNamespace

import pytest

from app.modules.ads.models import Ad, AdCreative, AdSet, Campaign
from app.modules.agent.services import write_ad_copy


def test_the_facts_hold_the_advert_s_headline_and_description(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ad = Ad(adset=AdSet(external_id="s1", campaign=Campaign(external_id="c1")))
    creative = AdCreative(
        story_raw={"a": 1},
        message="Implant bilan tabassum.",
        headline="Implant 450 USD",
        description="Chilonzor filiali",
    )
    monkeypatch.setattr(write_ad_copy, "managed_target", lambda *_, **__: ad)
    monkeypatch.setattr(write_ad_copy, "creative_of", lambda *_, **__: creative)
    monkeypatch.setattr(write_ad_copy, "adset_launch", lambda *_, **__: None)
    monkeypatch.setattr(write_ad_copy, "campaign_launch", lambda *_, **__: None)
    finding = SimpleNamespace(ref=SimpleNamespace(id="ad1"))
    business = SimpleNamespace(offer_text="Stomatologiya")

    sources = write_ad_copy._sources(
        None,  # type: ignore[arg-type]
        user=None,  # type: ignore[arg-type]
        business=business,  # type: ignore[arg-type]
        finding=finding,  # type: ignore[arg-type]
    )

    assert "450 USD" in sources.facts
    assert "Chilonzor filiali" in sources.facts
