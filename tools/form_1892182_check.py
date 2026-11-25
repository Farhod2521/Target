"""Why did Meta refuse the lead form (100/1892182)? Read-only, changes nothing.

    docker compose exec -T api python - < tools/form_1892182_check.py
    docker compose exec -T api python - 7 < tools/form_1892182_check.py

The argument is how many days back to look (default 3). For each refused
launch it prints what we sent and what Meta says about the same form, page,
ad account and token today - side by side, so the mismatch is visible.
Only SELECTs and Graph GETs.
"""

import glob
import json
import os
import sys
from datetime import timedelta

import httpx
from sqlalchemy import or_, select

from app import models as _models  # noqa: F401
from app.common.crypto import decrypt
from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.ads.models import CampaignLaunch, LaunchCreative
from app.modules.integrations.models import AdAccount, PageAccount
from app.modules.leads.models import LeadForm
from app.worker import task_session

DAYS = int(sys.argv[1]) if len(sys.argv) > 1 else 3
GRAPH = "https://graph.facebook.com/v26.0"
CODE = "1892182"


def get(path: str, token: str, **params) -> dict:
    try:
        reply = httpx.get(
            f"{GRAPH}/{path}", params={**params, "access_token": token}, timeout=20
        )
        return reply.json()
    except Exception as exc:
        return {"error": str(exc)}


def show(label: str, value) -> None:
    text = json.dumps(value, ensure_ascii=False, default=str)
    print(f"  {label}: {text[:1500]}")


def token_of(encrypted: str) -> str:
    try:
        return decrypt(encrypted)
    except Exception:
        return ""


with task_session() as db:
    since = utcnow() - timedelta(days=DAYS)
    launches = list(
        db.scalars(
            select(CampaignLaunch)
            .where(
                CampaignLaunch.created_at >= since,
                or_(
                    CampaignLaunch.error_message.ilike(f"%{CODE}%"),
                    CampaignLaunch.error_code.ilike(f"%{CODE}%"),
                ),
            )
            .order_by(CampaignLaunch.created_at.desc())
        )
    )
    # error_detail is JSON; a refusal may sit only there
    for row in db.scalars(
        select(CampaignLaunch).where(CampaignLaunch.updated_at >= since)
    ):
        if CODE in json.dumps(row.error_detail or {}) and row not in launches:
            launches.append(row)
    print(f"{len(launches)} launch {CODE} bilan, oxirgi {DAYS} kun\n")

    for launch in launches:
        owner = db.get(User, launch.owner_id)
        page = db.get(PageAccount, launch.page_id) if launch.page_id else None
        account = (
            db.get(AdAccount, launch.ad_account_id) if launch.ad_account_id else None
        )
        print("=" * 80)
        print(f"launch {launch.id}  {launch.created_at:%Y-%m-%d %H:%M} UTC")
        print(f"  owner: {owner.email if owner else launch.owner_id}")
        print(f"  status={launch.status} step={launch.step} error={launch.error_message}")
        show("error_detail", launch.error_detail)
        show("preset", launch.preset_key)

        # -- what was chosen
        draft = launch.draft or {}
        targeting = launch.targeting or {}
        show("placement_mode (draft)", draft.get("placement_mode") or targeting.get("placement_mode"))
        show("publisher_platforms", targeting.get("publisher_platforms"))
        show("lead_form_external_id (tanlangan)", launch.lead_form_external_id)
        show("draft sources", draft.get("sources") or draft.get("_sources"))
        refs = launch.created_refs or {}
        show("created_refs", refs)

        # -- the media: a promoted Instagram post, or a new upload?
        for creative in db.scalars(
            select(LaunchCreative).where(LaunchCreative.launch_id == launch.id)
        ):
            asset = creative.media_asset
            print(
                f"  creative #{creative.position}: media_upload={creative.media_upload!r} "
                f"library={creative.library_upload!r} "
                f"asset={(asset.provider, asset.kind, asset.product, asset.external_id, asset.instagram_user_id) if asset else None}"
            )

        # -- page and ad account as we hold them
        if page:
            print(
                f"  page: {page.external_id} {page.name!r} ig={page.instagram_user_id} "
                f"biz={page.business_external_id} biz_ids={page.business_ids} state={page.business_state}"
            )
        if account:
            print(
                f"  account: {account.external_id} {account.name!r} "
                f"biz={account.business_external_id} biz_ids={account.business_ids}"
            )

        # -- every form this launch could have meant
        form_ids = {launch.lead_form_external_id} if launch.lead_form_external_id else set()
        kept = refs.get("form") or refs.get("FORM")
        if isinstance(kept, list):
            form_ids |= {str(x.get("id") if isinstance(x, dict) else x) for x in kept}
        elif isinstance(kept, dict) and kept.get("id"):
            form_ids.add(str(kept["id"]))
        elif kept:
            form_ids.add(str(kept))

        page_token = token_of(page.token_encrypted) if page else ""
        user_token = (
            token_of(account.connection.token_encrypted) if account else ""
        )
        for form_id in sorted(f for f in form_ids if f):
            row = db.scalar(
                select(LeadForm).where(
                    LeadForm.owner_id == launch.owner_id, LeadForm.external_id == form_id
                )
            )
            print(f"  -- forma {form_id}")
            if row:
                same_page = page is not None and row.page_id == page.id
                print(
                    f"     bizda: status={row.status} raw={row.status_raw} locale={row.locale} "
                    f"shu sahifami={same_page} synced={row.synced_at} created={row.created_time}"
                )
            else:
                print("     bizda: YO'Q")
            if page_token:
                show(
                    "     Meta (sahifa tokeni)",
                    get(
                        form_id,
                        page_token,
                        fields="id,name,status,locale,created_time,page,"
                        "is_optimized_for_quality,block_display_for_non_targeted_viewer,"
                        "context_card,thank_you_page,question_page_custom_headline,"
                        "questions,privacy_policy_url,follow_up_action_url",
                    ),
                )
            if user_token:
                show(
                    "     Meta (foydalanuvchi tokeni)",
                    get(form_id, user_token, fields="id,status,page"),
                )

        # -- does the token that made the creative reach the page and its forms?
        if user_token and page:
            show(
                "Meta sahifa (foydalanuvchi tokeni)",
                get(page.external_id, user_token, fields="id,name,business,tasks,instagram_business_account"),
            )
            show(
                "Meta sahifa formalari (foydalanuvchi tokeni)",
                get(f"{page.external_id}/leadgen_forms", user_token, fields="id,status", limit=3),
            )
            show(
                "Meta ToS (sahifa)",
                get(page.external_id, page_token or user_token, fields="leadgen_tos_accepted"),
            )
        if user_token and account:
            show(
                "Meta akkaunt",
                get(account.external_id if account.external_id.startswith("act_") else f"act_{account.external_id}",
                    user_token, fields="id,name,business,account_status,user_tasks"),
            )
            show("token ruxsatlari", get("me/permissions", user_token))

        # -- the trace, if tracing was on
        for path in sorted(glob.glob(os.path.join("logs/launches", f"*{launch.id}*"))):
            print(f"  trace: {path}")
        print()
