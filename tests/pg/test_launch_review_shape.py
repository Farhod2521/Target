"""The review answers keep the shape the API reference (and the frontend's types) promise."""

import re

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.modules.ads import draft as draft_field
from app.modules.ads.constants import DraftSection, MediaKind
from app.modules.ads.launch_schemas import (
    FormChosenOut,
    FormDepthOut,
    FormPickerOut,
    ReviewOut,
    ReviewPollOut,
)
from app.modules.ads.models import CampaignLaunch, MediaAsset
from tests.pg.test_launch_api import _ready


def test_a_lead_proposal_with_every_section_drawn_keeps_its_documented_shape(
    client: TestClient, db: Session, queued: list
) -> None:
    auth, user = _ready(client, db)
    launch_id = client.post("/api/v1/launch", headers=auth).json()["id"]
    goals = [
        g["goal"]
        for g in client.get(f"/api/v1/launch/{launch_id}/plan", headers=auth).json()[
            "goals"
        ]
    ]
    assert "leads" in goals, goals
    goal = "leads"
    plan = client.get(
        f"/api/v1/launch/{launch_id}/plan?goal={goal}", headers=auth
    ).json()
    saved = client.post(
        f"/api/v1/launch/{launch_id}/plan",
        json={
            "goal": goal,
            "daily_budget": plan["initial"]["daily_budget"] or "10",
            "link_url": "bahor.example",
            "phone_number": "+998901234567",
            "start_day": "today",
        },
        headers=auth,
    )
    assert saved.status_code == 200, saved.text
    launch = db.get(CampaignLaunch, launch_id)
    assert launch is not None
    asset = MediaAsset(
        owner_id=user.id,
        ad_account_id=launch.ad_account_id,
        provider=launch.provider,
        kind=MediaKind.IMAGE,
        external_id="hash_shape",
        name="banner.jpg",
        width=1080,
        height=1080,
    )
    db.add(asset)
    db.commit()
    went = client.post(
        f"/api/v1/launch/{launch_id}/media",
        json={
            "asset_ids": [str(asset.id)],
            "text": {"mode": "shared", "shared": "Kurs"},
        },
        headers=auth,
    )
    assert went.status_code == 200, went.text

    db.refresh(launch)
    draft = draft_field.empty_draft()
    draft_field.choose(
        draft,
        DraftSection.AUDIENCE,
        {"age_min": 18, "age_max": 35, "genders": [1], "targeting_mode": "interests"},
    )
    draft_field.propose(
        draft, DraftSection.INTERESTS, [{"query": "IELTS", "name": "IELTS"}]
    )
    draft_field.choose(
        draft,
        DraftSection.INTERESTS,
        [{"query": "IELTS", "name": "IELTS", "external_id": "6003"}],
    )
    draft_field.propose(
        draft, DraftSection.TRAITS, [{"query": "Talabalar", "name": "Talabalar"}]
    )
    draft_field.choose(draft, DraftSection.TRAITS, [{"query": "Talabalar"}])
    draft_field.propose(
        draft, DraftSection.FORM, [{"kind": "phone_number", "label": "Telefon"}]
    )
    draft_field.choose(
        draft, DraftSection.FORM, [{"kind": "phone_number", "label": "Telefon"}]
    )
    launch.draft = draft
    launch.status = "ready"
    launch.targeting = {"geo_locations": {"countries": ["UZ"]}}
    db.commit()

    ready = client.get(f"/api/v1/launch/{launch_id}/review", headers=auth)
    assert ready.status_code == 200, ready.text
    shaped = ReviewOut.model_validate(ready.json())
    assert shaped.proposal is not None
    assert shaped.proposal.interests.chosen_queries == ["IELTS"]
    assert len(shaped.proposal.variants) == 1
    assert shaped.proposal.lead_form is not None
    # The policy Meta will get, so the owner is not asked to type one.
    assert re.search(r"/privacy/[0-9a-f-]{36}/$", shaped.proposal.lead_form.privacy_url)

    polled = client.get(f"/api/v1/launch/{launch_id}/review/state", headers=auth)
    ReviewPollOut.model_validate(polled.json())


def test_the_form_step_keeps_its_documented_shape(
    client: TestClient, db: Session, queued: list
) -> None:
    auth, _user = _ready(client, db)
    launch_id = client.post("/api/v1/launch", headers=auth).json()["id"]
    form = f"/api/v1/launch/{launch_id}/form"

    # Asked for the goal tapped on the plan, before the plan is saved.
    picker = client.get(f"{form}?goal=leads", headers=auth)
    assert picker.status_code == 200, picker.text
    shaped = FormPickerOut.model_validate(picker.json())
    assert {"full_name", "phone"} <= {
        q.kind for q in shaped.standard_questions if q.checked
    }

    picked = client.post(
        form,
        json={
            "goal": "leads",
            "kinds": ["full_name", "phone"],
            "typed": [{"label": "Darajangiz?", "options": ["A1", "B1"]}],
            "ending": {"kind": "none"},
        },
        headers=auth,
    )
    assert picked.status_code == 200, picked.text
    FormChosenOut.model_validate(picked.json())

    auto = client.post(
        f"{form}/auto", json={"goal": "leads", "depth": "deep"}, headers=auth
    )
    assert auto.status_code == 200, auto.text
    assert FormChosenOut.model_validate(auto.json()).choice.depth == "deep"

    depth = client.get(f"/api/v1/launch/{launch_id}/form-depth/deep", headers=auth)
    assert depth.status_code == 200, depth.text
    FormDepthOut.model_validate(depth.json())
